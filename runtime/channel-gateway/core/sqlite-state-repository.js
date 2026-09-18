/**
 * runtime/channel-gateway/core/sqlite-state-repository.js
 *
 * ADR-0023 / E-03 T6/T7A: Channel Gateway SQLite Authoritative State Repository & Durable Channel State Schema.
 *
 * Invariants:
 * - Built-in node:sqlite (DatabaseSync) only; zero npm dependencies.
 * - Single input contract: constructor/open accepts only stateRoot.
 * - Strict stateRoot validation: non-empty string, absolute, existing directory, readable, writable.
 * - No auto-creation: NEVER calls fs.mkdirSync or creates stateRoot.
 * - Fixed DB filename: channel-gateway-state.sqlite3 (zero caller override).
 * - Entry existence classification via fs.lstatSync:
 *     - Only err.code === 'ENOENT' indicates new database.
 *     - If entry exists: must be a regular file, non-symlink (dangling or resolving), resolving inside canonical stateRoot.
 * - Extension loading strictly disabled (no allowExtension, no loadExtension).
 * - Mandatory PRAGMAs on every open:
 *     PRAGMA journal_mode = WAL; (readback 'wal')
 *     PRAGMA synchronous = FULL; (readback 2)
 *     PRAGMA foreign_keys = ON; (readback 1)
 *     PRAGMA busy_timeout = 5000; (readback 5000)
 *   Any readback mismatch triggers fail-closed error and immediate close.
 * - Unified forward-only transactional migration runner:
 *     - Single generic runPendingMigrations(db, currentVersion, targetVersion) path for both new and existing databases.
 *     - Pending migrations selected by: version > currentVersion && version <= targetVersion.
 *     - Migration 1 creates canonical table: schema_migrations (version INTEGER PRIMARY KEY) STRICT.
 *     - Runner records version in schema_migrations via prepared statement within immediate transaction.
 *     - Existing DB missing schema_migrations fails closed.
 *     - Canonical schema_migrations shape verified via PRAGMA table_list and PRAGMA table_info (STRICT, 1 column, PK).
 *     - Gap, non-integer, <=0, duplicate, or future version > SQLITE_STATE_SCHEMA_VERSION fails closed.
 * - Canonical domain tables (channel_control, inbox) in T7A with strict DDL, CHECK, FK, and AUTOINCREMENT validation.
 * - SQL safety: parameterized prepared statements for any valued queries; no dynamic SQL string concatenation.
 * - No raw DatabaseSync handle escape hatch (no rawDb, exec, query exports).
 * - True read-only introspection via ECMAScript private fields (#db, #databasePath, #schemaVersion, #isOpen, #canonicalStateRoot).
 * - Idempotent close() lifecycle; unusable after close.
 */

'use strict';

const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { DatabaseSync } = require('node:sqlite');
const { isAbsolutePath } = require('./data-location-config');

const SQLITE_STATE_SCHEMA_VERSION = 3;
const SQLITE_BUSY_TIMEOUT_MS = 5000;
const SQLITE_DATABASE_FILENAME = 'channel-gateway-state.sqlite3';

/**
 * Canonical DDL definitions for domain tables introduced in schema version 2.
 * Preserved for migration 2 runner and v2 backup validation.
 */
const CHANNEL_CONTROL_SCHEMA_SQL = `
CREATE TABLE channel_control (
  channel_id TEXT PRIMARY KEY
    CHECK(length(trim(channel_id)) > 0),
  current_holder TEXT
    CHECK(
      current_holder IS NULL OR
      length(trim(current_holder)) > 0
    ),
  fencing_token INTEGER NOT NULL DEFAULT 0
    CHECK(fencing_token >= 0),
  last_heartbeat_at INTEGER
) STRICT;
`;

const INBOX_V2_SCHEMA_SQL = `
CREATE TABLE inbox (
  sequence INTEGER PRIMARY KEY AUTOINCREMENT,
  channel_id TEXT NOT NULL,
  message_id TEXT NOT NULL
    CHECK(length(trim(message_id)) > 0),
  receiving_account_id TEXT NOT NULL
    CHECK(length(trim(receiving_account_id)) > 0),
  status TEXT NOT NULL
    CHECK(status IN (
      'queued',
      'claimed',
      'discarded',
      'replied'
    )),
  claimed_by TEXT,
  claimed_at_token INTEGER
    CHECK(
      claimed_at_token IS NULL OR
      claimed_at_token >= 0
    ),
  discard_reason TEXT,
  discarded_by_holder TEXT,
  discarded_at_token INTEGER
    CHECK(
      discarded_at_token IS NULL OR
      discarded_at_token >= 0
    ),
  UNIQUE(channel_id, message_id),
  FOREIGN KEY(channel_id)
    REFERENCES channel_control(channel_id)
    ON DELETE RESTRICT
) STRICT;
`;

/**
 * Canonical DDL definitions for domain tables in schema version 3.
 * Inbox identity is now (account_id, platform_msg_id) with content column.
 * Ingest cursor table tracks per-account fetch cursor.
 */
const INBOX_SCHEMA_SQL = `
CREATE TABLE inbox (
  sequence INTEGER PRIMARY KEY AUTOINCREMENT,
  channel_id TEXT NOT NULL,
  account_id TEXT NOT NULL
    CHECK(length(trim(account_id)) > 0),
  platform_msg_id TEXT NOT NULL
    CHECK(length(trim(platform_msg_id)) > 0),
  status TEXT NOT NULL
    CHECK(status IN (
      'queued',
      'claimed',
      'discarded',
      'replied'
    )),
  content TEXT,
  claimed_by TEXT,
  claimed_at_token INTEGER
    CHECK(
      claimed_at_token IS NULL OR
      claimed_at_token >= 0
    ),
  discard_reason TEXT,
  discarded_by_holder TEXT,
  discarded_at_token INTEGER
    CHECK(
      discarded_at_token IS NULL OR
      discarded_at_token >= 0
    ),
  UNIQUE(account_id, platform_msg_id),
  FOREIGN KEY(channel_id)
    REFERENCES channel_control(channel_id)
    ON DELETE RESTRICT
) STRICT;
`;

const INGEST_CURSOR_SCHEMA_SQL = `
CREATE TABLE ingest_cursor (
  account_id TEXT PRIMARY KEY
    CHECK(length(trim(account_id)) > 0),
  cursor_value TEXT NOT NULL
    CHECK(length(trim(cursor_value)) > 0)
) STRICT;
`;

/**
 * Normalizes CREATE TABLE DDL SQL deterministically for canonical schema comparison.
 * Collapses whitespace, trims, normalizes punctuation spacing, strips trailing semicolons,
 * and normalizes keyword case outside single-quoted string literals.
 *
 * @param {string} sql
 * @returns {string}
 */
function normalizeCanonicalSchemaSql(sql) {
  if (typeof sql !== 'string') return '';
  const parts = sql.split(/('(?:''|[^'])*')/g);
  for (let i = 0; i < parts.length; i++) {
    if (i % 2 === 0) {
      parts[i] = parts[i]
        .replace(/;/g, ' ')
        .replace(/\s+/g, ' ')
        .replace(/\s*\(\s*/g, ' ( ')
        .replace(/\s*\)\s*/g, ' ) ')
        .replace(/\s*,\s*/g, ' , ')
        .replace(/\s*>=+\s*/g, ' >= ')
        .replace(/\s*<=+\s*/g, ' <= ')
        .replace(/\s*(?<![<>=])>(?![=])\s*/g, ' > ')
        .replace(/\s*(?<![<>=])<(?![=])\s*/g, ' < ')
        .replace(/\s*(?<![<>=!])=(?![=])\s*/g, ' = ')
        .toUpperCase();
    }
  }
  return parts
  .join('')
  .replace(/\s+/g, ' ')
  .trim();
}

/**
 * Ordered, forward-only migration definitions.
 * Each migration must be continuous starting from 1 up to SQLITE_STATE_SCHEMA_VERSION.
 */
const MIGRATIONS = Object.freeze([
  Object.freeze({
    version: 1,
    apply(db) {
      db.exec('CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY) STRICT;');
    },
  }),
  Object.freeze({
    version: 2,
    apply(db) {
      db.exec(CHANNEL_CONTROL_SCHEMA_SQL);
      db.exec(INBOX_V2_SCHEMA_SQL);
    },
  }),
  Object.freeze({
    version: 3,
    apply(db) {
      db.exec('ALTER TABLE inbox RENAME TO inbox_v2_legacy;');
      db.exec(INBOX_SCHEMA_SQL);
      db.exec(`
INSERT INTO inbox (
  sequence,
  channel_id,
  account_id,
  platform_msg_id,
  status,
  content,
  claimed_by,
  claimed_at_token,
  discard_reason,
  discarded_by_holder,
  discarded_at_token
)
SELECT
  sequence,
  channel_id,
  receiving_account_id,
  message_id,
  status,
  NULL,
  claimed_by,
  claimed_at_token,
  discard_reason,
  discarded_by_holder,
  discarded_at_token
FROM inbox_v2_legacy;
`);
      db.exec('DROP TABLE inbox_v2_legacy;');
      db.exec(INGEST_CURSOR_SCHEMA_SQL);
    },
  }),
]);

/**
 * Validates the internal migration definitions.
 *
 * @param {ReadonlyArray<{version: number, apply: Function}>} migrations
 * @param {number} targetVersion
 */
function validateMigrationRegistry(migrations, targetVersion) {
  if (!Array.isArray(migrations) || migrations.length === 0) {
    throw new Error('Migration registry must be a non-empty array (fail-closed)');
  }
  for (let i = 0; i < migrations.length; i++) {
    const m = migrations[i];
    const expectedVer = i + 1;
    if (!m || typeof m !== 'object') {
      throw new Error(`Migration entry at index ${i} is invalid (fail-closed)`);
    }
    if (m.version !== expectedVer) {
      throw new Error(
        `Migration sequence must be continuous starting from 1: expected version ${expectedVer}, got ${m.version} (fail-closed)`
      );
    }
    if (typeof m.apply !== 'function') {
      throw new Error(`Migration version ${m.version} missing apply function (fail-closed)`);
    }
  }
  const maxVer = migrations[migrations.length - 1].version;
  if (maxVer !== targetVersion) {
    throw new Error(
      `Migration registry max version ${maxVer} does not match target schema version ${targetVersion} (fail-closed)`
    );
  }
}

/**
 * Verifies that the schema_migrations table has the exact canonical DDL shape:
 * - Type is 'table'
 * - STRICT mode is enabled
 * - Exactly 1 column named 'version' of declared type 'INTEGER' which is PRIMARY KEY
 *
 * @param {DatabaseSync} db
 */
function verifyCanonicalSchemaMigrationsShape(db) {
  const tableList = db.prepare("PRAGMA table_list('schema_migrations');").all();
  if (!tableList || tableList.length === 0) {
    throw new Error('schema_migrations table does not exist in schema (fail-closed)');
  }
  const tableEntry = tableList.find((entry) => entry.name === 'schema_migrations');
  if (!tableEntry) {
    throw new Error('schema_migrations entry not found in table_list (fail-closed)');
  }
  if (tableEntry.type !== 'table') {
    throw new Error(
      `schema_migrations must be a table, got type '${tableEntry.type}' (fail-closed)`
    );
  }
  if (!tableEntry.strict || Number(tableEntry.strict) !== 1) {
    throw new Error('schema_migrations must be created with STRICT mode (fail-closed)');
  }

  const columns = db.prepare("PRAGMA table_info('schema_migrations');").all();
  if (!columns || columns.length !== 1) {
    throw new Error(
      `schema_migrations must have exactly 1 column, found ${columns ? columns.length : 0} (fail-closed)`
    );
  }
  const col0 = columns[0];
  if (col0.name !== 'version') {
    throw new Error(
      `schema_migrations column 0 must be named 'version', found '${col0.name}' (fail-closed)`
    );
  }
  if (String(col0.type).toUpperCase() !== 'INTEGER') {
    throw new Error(
      `schema_migrations column 'version' declared type must be INTEGER, found '${col0.type}' (fail-closed)`
    );
  }
  if (!col0.pk || Number(col0.pk) <= 0) {
    throw new Error("schema_migrations column 'version' must be PRIMARY KEY (fail-closed)");
  }
}

/**
 * Reads and strictly validates applied schema_migrations records.
 *
 * @param {DatabaseSync} db
 * @returns {number[]} Array of applied versions in ascending order
 */
function readAppliedMigrationVersions(db) {
  const rows = db.prepare('SELECT version FROM schema_migrations ORDER BY version ASC;').all();
  if (!rows || rows.length === 0) {
    throw new Error('schema_migrations table is empty (fail-closed)');
  }

  const versions = [];
  const seen = new Set();
  for (const row of rows) {
    const v = row.version;
    if (typeof v !== 'number' || !Number.isInteger(v) || !Number.isSafeInteger(v) || v <= 0) {
      throw new Error(`Invalid schema version: ${v} (fail-closed)`);
    }
    if (seen.has(v)) {
      throw new Error(`Duplicate schema version: ${v} (fail-closed)`);
    }
    seen.add(v);
    versions.push(v);
  }

  // Must be continuous starting from 1 with no gaps
  for (let i = 0; i < versions.length; i++) {
    const expected = i + 1;
    if (versions[i] !== expected) {
      throw new Error(
        `Invalid migration sequence: expected version ${expected} at index ${i}, found ${versions[i]} (fail-closed)`
      );
    }
  }

  return versions;
}

/**
 * Generic forward migration runner.
 * Applies any migrations where version > currentVersion && version <= targetVersion.
 * Each migration is applied inside its own immediate transaction.
 *
 * @param {DatabaseSync} db
 * @param {number} currentVersion
 * @param {number} targetVersion
 */
function runPendingMigrations(db, currentVersion, targetVersion) {
  if (typeof currentVersion !== 'number' || !Number.isInteger(currentVersion) || currentVersion < 0) {
    throw new Error(`Invalid currentVersion: ${currentVersion} (fail-closed)`);
  }
  if (typeof targetVersion !== 'number' || !Number.isInteger(targetVersion) || targetVersion <= 0) {
    throw new Error(`Invalid targetVersion: ${targetVersion} (fail-closed)`);
  }

  const pending = MIGRATIONS.filter(
    (m) => m.version > currentVersion && m.version <= targetVersion
  );

  for (const migration of pending) {
    db.exec('BEGIN IMMEDIATE;');
    try {
      migration.apply(db);
      const insertStmt = db.prepare('INSERT INTO schema_migrations (version) VALUES (?);');
      insertStmt.run(migration.version);
      db.exec('COMMIT;');
    } catch (mErr) {
      try {
        db.exec('ROLLBACK;');
      } catch (_) {}
      throw new Error(`Failed to apply migration ${migration.version}: ${mErr.message}`);
    }
  }
}

/**
 * Reads all non-internal user table names in ascending alphabetical order.
 *
 * @param {DatabaseSync} db
 * @returns {string[]}
 */
function getCanonicalUserTableNames(db) {
  const rows = db.prepare(
    "SELECT name FROM sqlite_schema WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name ASC;"
  ).all();
  return rows ? rows.map((r) => r.name) : [];
}

/**
 * Reads SQLite PRAGMA data_version as a concurrent mutation drift indicator.
 *
 * @param {DatabaseSync} db
 * @returns {number|null}
 */
function getDataVersion(db) {
  const row = db.prepare('PRAGMA data_version;').get();
  if (!row) return null;
  const val = row.data_version ?? Object.values(row)[0];
  return typeof val === 'number' ? val : null;
}

/**
 * Verifies that the domain tables (channel_control, inbox) have the exact canonical DDL shape:
 * - Both tables exist with type 'table' and STRICT mode enabled
 * - channel_control has exactly 4 columns:
 *     channel_id (TEXT, PK, NOT NULL)
 *     current_holder (TEXT, nullable)
 *     fencing_token (INTEGER, NOT NULL, DEFAULT 0)
 *     last_heartbeat_at (INTEGER, nullable)
 * - inbox has exactly 10 columns:
 *     sequence (INTEGER, PK AUTOINCREMENT)
 *     channel_id (TEXT, NOT NULL)
 *     message_id (TEXT, NOT NULL)
 *     receiving_account_id (TEXT, NOT NULL)
 *     status (TEXT, NOT NULL)
 *     claimed_by (TEXT, nullable)
 *     claimed_at_token (INTEGER, nullable)
 *     discard_reason (TEXT, nullable)
 *     discarded_by_holder (TEXT, nullable)
 *     discarded_at_token (INTEGER, nullable)
 * - inbox has FOREIGN KEY (channel_id) REFERENCES channel_control(channel_id) ON DELETE RESTRICT
 * - inbox has UNIQUE(channel_id, message_id) constraint
 *
 * @param {DatabaseSync} db
 */
/**
 * Verifies that the domain tables have the exact canonical DDL shape.
 * Supports:
 * - Version 2 (pre-migration historical shape, used during pre-migration backup validation)
 * - Version 3 (canonical shape with account_id/platform_msg_id/content inbox and ingest_cursor)
 *
 * @param {DatabaseSync} db
 * @param {number} [version=SQLITE_STATE_SCHEMA_VERSION]
 */
function verifyCanonicalDomainSchemaShape(db, version = SQLITE_STATE_SCHEMA_VERSION) {
  if (version !== 2 && version !== 3) {
    throw new Error(`Unsupported schema version for domain shape verification: ${version} (fail-closed)`);
  }

  // 1. Verify channel_control (unchanged across v2 and v3)
  const ccList = db.prepare("PRAGMA table_list('channel_control');").all();
  const ccEntry = ccList ? ccList.find((e) => e.name === 'channel_control') : null;
  if (!ccEntry || ccEntry.type !== 'table' || Number(ccEntry.strict) !== 1) {
    throw new Error('channel_control must exist as a STRICT table (fail-closed)');
  }
  const ccCols = db.prepare("PRAGMA table_info('channel_control');").all();
  if (!ccCols || ccCols.length !== 4) {
    throw new Error(
      `channel_control must have exactly 4 columns, found ${ccCols ? ccCols.length : 0} (fail-closed)`
    );
  }
  const ccExpected = {
    channel_id: { type: 'TEXT', notnull: 1, pk: 1 },
    current_holder: { type: 'TEXT', notnull: 0, pk: 0 },
    fencing_token: { type: 'INTEGER', notnull: 1, pk: 0, dflt_value: '0' },
    last_heartbeat_at: { type: 'INTEGER', notnull: 0, pk: 0 },
  };
  for (const col of ccCols) {
    const exp = ccExpected[col.name];
    if (!exp) {
      throw new Error(`Unexpected column '${col.name}' in channel_control (fail-closed)`);
    }
    if (
      col.type.toUpperCase() !== exp.type ||
      Number(col.notnull) !== exp.notnull ||
      Number(col.pk) !== exp.pk
    ) {
      throw new Error(
        `Column '${col.name}' in channel_control mismatch: expected type=${exp.type}, notnull=${exp.notnull}, pk=${exp.pk}; got type=${col.type}, notnull=${col.notnull}, pk=${col.pk} (fail-closed)`
      );
    }
    if (exp.dflt_value !== undefined && String(col.dflt_value) !== exp.dflt_value) {
      throw new Error(
        `Column '${col.name}' in channel_control mismatch: expected dflt_value='${exp.dflt_value}', got '${col.dflt_value}' (fail-closed)`
      );
    }
  }

  const schemaStmt = db.prepare("SELECT sql FROM sqlite_schema WHERE type = 'table' AND name = ?;");

  const ccSqlRow = schemaStmt.get('channel_control');
  if (!ccSqlRow || typeof ccSqlRow.sql !== 'string') {
    throw new Error('channel_control table definition not found in sqlite_schema (fail-closed)');
  }
  const normCC = normalizeCanonicalSchemaSql(ccSqlRow.sql);
  const expCC = normalizeCanonicalSchemaSql(CHANNEL_CONTROL_SCHEMA_SQL);
  if (!normCC.includes('CHECK ( FENCING_TOKEN >= 0 )')) {
    throw new Error('channel_control missing fencing_token >= 0 CHECK constraint (fail-closed)');
  }
  if (!normCC.includes('CHECK ( LENGTH ( TRIM ( CHANNEL_ID ) ) > 0 )')) {
    throw new Error('channel_control missing channel_id nonblank CHECK constraint (fail-closed)');
  }
  if (!normCC.includes('CHECK ( CURRENT_HOLDER IS NULL OR LENGTH ( TRIM ( CURRENT_HOLDER ) ) > 0 )')) {
    throw new Error('channel_control missing current_holder CHECK constraint (fail-closed)');
  }
  if (normCC !== expCC) {
    throw new Error('channel_control schema definition does not match canonical DDL contract (fail-closed)');
  }

  // 2. Verify inbox
  const inboxList = db.prepare("PRAGMA table_list('inbox');").all();
  const inboxEntry = inboxList ? inboxList.find((e) => e.name === 'inbox') : null;
  if (!inboxEntry || inboxEntry.type !== 'table' || Number(inboxEntry.strict) !== 1) {
    throw new Error('inbox must exist as a STRICT table (fail-closed)');
  }

  // Foreign key to channel_control is required in both v2 and v3
  const fks = db.prepare("PRAGMA foreign_key_list('inbox');").all();
  const fk = fks
    ? fks.find(
        (k) =>
          k.table === 'channel_control' &&
          k.from === 'channel_id' &&
          k.to === 'channel_id'
      )
    : null;
  if (!fk || !fk.on_delete || fk.on_delete.toUpperCase() !== 'RESTRICT') {
    throw new Error(
      'inbox must define FOREIGN KEY (channel_id) REFERENCES channel_control(channel_id) ON DELETE RESTRICT (fail-closed)'
    );
  }

  const inboxSqlRow = schemaStmt.get('inbox');
  if (!inboxSqlRow || typeof inboxSqlRow.sql !== 'string') {
    throw new Error('inbox table definition not found in sqlite_schema (fail-closed)');
  }
  const normInbox = normalizeCanonicalSchemaSql(inboxSqlRow.sql);

  if (!normInbox.includes('AUTOINCREMENT')) {
    throw new Error('inbox sequence column missing AUTOINCREMENT (fail-closed)');
  }
  if (!normInbox.includes("CHECK ( STATUS IN ( 'queued' , 'claimed' , 'discarded' , 'replied' ) )")) {
    throw new Error('inbox missing status enum CHECK constraint (fail-closed)');
  }
  if (!normInbox.includes('CHECK ( CLAIMED_AT_TOKEN IS NULL OR CLAIMED_AT_TOKEN >= 0 )')) {
    throw new Error('inbox missing claimed_at_token >= 0 CHECK constraint (fail-closed)');
  }
  if (!normInbox.includes('CHECK ( DISCARDED_AT_TOKEN IS NULL OR DISCARDED_AT_TOKEN >= 0 )')) {
    throw new Error('inbox missing discarded_at_token >= 0 CHECK constraint (fail-closed)');
  }

  const idxList = db.prepare("PRAGMA index_list('inbox');").all();
  const indexInfoStmt = db.prepare('SELECT name FROM pragma_index_info(?);');

  if (version === 2) {
    const inboxCols = db.prepare("PRAGMA table_info('inbox');").all();
    if (!inboxCols || inboxCols.length !== 10) {
      throw new Error(
        `inbox must have exactly 10 columns in v2, found ${inboxCols ? inboxCols.length : 0} (fail-closed)`
      );
    }
    const inboxExpectedV2 = {
      sequence: { type: 'INTEGER', notnull: 0, pk: 1 },
      channel_id: { type: 'TEXT', notnull: 1, pk: 0 },
      message_id: { type: 'TEXT', notnull: 1, pk: 0 },
      receiving_account_id: { type: 'TEXT', notnull: 1, pk: 0 },
      status: { type: 'TEXT', notnull: 1, pk: 0 },
      claimed_by: { type: 'TEXT', notnull: 0, pk: 0 },
      claimed_at_token: { type: 'INTEGER', notnull: 0, pk: 0 },
      discard_reason: { type: 'TEXT', notnull: 0, pk: 0 },
      discarded_by_holder: { type: 'TEXT', notnull: 0, pk: 0 },
      discarded_at_token: { type: 'INTEGER', notnull: 0, pk: 0 },
    };
    for (const col of inboxCols) {
      const exp = inboxExpectedV2[col.name];
      if (!exp) {
        throw new Error(`Unexpected column '${col.name}' in inbox v2 (fail-closed)`);
      }
      if (
        col.type.toUpperCase() !== exp.type ||
        Number(col.notnull) !== exp.notnull ||
        Number(col.pk) !== exp.pk
      ) {
        throw new Error(
          `Column '${col.name}' in inbox mismatch: expected type=${exp.type}, notnull=${exp.notnull}, pk=${exp.pk}; got type=${col.type}, notnull=${col.notnull}, pk=${col.pk} (fail-closed)`
        );
      }
    }

    let hasUniqueCompound = false;
    if (idxList) {
      for (const idx of idxList) {
        if (Number(idx.unique) === 1) {
          const info = indexInfoStmt.all(idx.name);
          const cols = info ? info.map((c) => c.name) : [];
          if (cols.length === 2 && cols[0] === 'channel_id' && cols[1] === 'message_id') {
            hasUniqueCompound = true;
            break;
          }
        }
      }
    }
    if (!hasUniqueCompound) {
      throw new Error('inbox must define UNIQUE(channel_id, message_id) constraint (fail-closed)');
    }

    if (!normInbox.includes('CHECK ( LENGTH ( TRIM ( MESSAGE_ID ) ) > 0 )')) {
      throw new Error('inbox missing message_id nonblank CHECK constraint (fail-closed)');
    }
    if (!normInbox.includes('CHECK ( LENGTH ( TRIM ( RECEIVING_ACCOUNT_ID ) ) > 0 )')) {
      throw new Error('inbox missing receiving_account_id nonblank CHECK constraint (fail-closed)');
    }
    const expInboxV2 = normalizeCanonicalSchemaSql(INBOX_V2_SCHEMA_SQL);
    if (normInbox !== expInboxV2) {
      throw new Error('inbox schema definition does not match canonical DDL contract (fail-closed)');
    }
  } else {
    // version === 3
    const inboxCols = db.prepare("PRAGMA table_info('inbox');").all();
    if (!inboxCols || inboxCols.length !== 11) {
      throw new Error(
        `inbox must have exactly 11 columns in v3, found ${inboxCols ? inboxCols.length : 0} (fail-closed)`
      );
    }
    const inboxExpectedV3 = {
      sequence: { type: 'INTEGER', notnull: 0, pk: 1 },
      channel_id: { type: 'TEXT', notnull: 1, pk: 0 },
      account_id: { type: 'TEXT', notnull: 1, pk: 0 },
      platform_msg_id: { type: 'TEXT', notnull: 1, pk: 0 },
      status: { type: 'TEXT', notnull: 1, pk: 0 },
      content: { type: 'TEXT', notnull: 0, pk: 0 },
      claimed_by: { type: 'TEXT', notnull: 0, pk: 0 },
      claimed_at_token: { type: 'INTEGER', notnull: 0, pk: 0 },
      discard_reason: { type: 'TEXT', notnull: 0, pk: 0 },
      discarded_by_holder: { type: 'TEXT', notnull: 0, pk: 0 },
      discarded_at_token: { type: 'INTEGER', notnull: 0, pk: 0 },
    };
    for (const col of inboxCols) {
      const exp = inboxExpectedV3[col.name];
      if (!exp) {
        throw new Error(`Unexpected column '${col.name}' in inbox v3 (fail-closed)`);
      }
      if (
        col.type.toUpperCase() !== exp.type ||
        Number(col.notnull) !== exp.notnull ||
        Number(col.pk) !== exp.pk
      ) {
        throw new Error(
          `Column '${col.name}' in inbox mismatch: expected type=${exp.type}, notnull=${exp.notnull}, pk=${exp.pk}; got type=${col.type}, notnull=${col.notnull}, pk=${col.pk} (fail-closed)`
        );
      }
    }

    let hasUniqueCompound = false;
    if (idxList) {
      for (const idx of idxList) {
        if (Number(idx.unique) === 1) {
          const info = indexInfoStmt.all(idx.name);
          const cols = info ? info.map((c) => c.name) : [];
          if (cols.length === 2 && cols[0] === 'account_id' && cols[1] === 'platform_msg_id') {
            hasUniqueCompound = true;
            break;
          }
        }
      }
    }
    if (!hasUniqueCompound) {
      throw new Error('inbox must define UNIQUE(account_id, platform_msg_id) constraint (fail-closed)');
    }

    if (!normInbox.includes('CHECK ( LENGTH ( TRIM ( ACCOUNT_ID ) ) > 0 )')) {
      throw new Error('inbox missing account_id nonblank CHECK constraint (fail-closed)');
    }
    if (!normInbox.includes('CHECK ( LENGTH ( TRIM ( PLATFORM_MSG_ID ) ) > 0 )')) {
      throw new Error('inbox missing platform_msg_id nonblank CHECK constraint (fail-closed)');
    }
    const expInboxV3 = normalizeCanonicalSchemaSql(INBOX_SCHEMA_SQL);
    if (normInbox !== expInboxV3) {
      throw new Error('inbox schema definition does not match canonical DDL contract (fail-closed)');
    }

    // 3. Verify ingest_cursor for v3
    const curList = db.prepare("PRAGMA table_list('ingest_cursor');").all();
    const curEntry = curList ? curList.find((e) => e.name === 'ingest_cursor') : null;
    if (!curEntry || curEntry.type !== 'table' || Number(curEntry.strict) !== 1) {
      throw new Error('ingest_cursor must exist as a STRICT table (fail-closed)');
    }
    const curCols = db.prepare("PRAGMA table_info('ingest_cursor');").all();
    if (!curCols || curCols.length !== 2) {
      throw new Error(
        `ingest_cursor must have exactly 2 columns, found ${curCols ? curCols.length : 0} (fail-closed)`
      );
    }
    const curExpected = {
      account_id: { type: 'TEXT', notnull: 1, pk: 1 },
      cursor_value: { type: 'TEXT', notnull: 1, pk: 0 },
    };
    for (const col of curCols) {
      const exp = curExpected[col.name];
      if (!exp) {
        throw new Error(`Unexpected column '${col.name}' in ingest_cursor (fail-closed)`);
      }
      if (
        col.type.toUpperCase() !== exp.type ||
        Number(col.notnull) !== exp.notnull ||
        Number(col.pk) !== exp.pk
      ) {
        throw new Error(
          `Column '${col.name}' in ingest_cursor mismatch: expected type=${exp.type}, notnull=${exp.notnull}, pk=${exp.pk}; got type=${col.type}, notnull=${col.notnull}, pk=${col.pk} (fail-closed)`
        );
      }
    }

    const curSqlRow = schemaStmt.get('ingest_cursor');
    if (!curSqlRow || typeof curSqlRow.sql !== 'string') {
      throw new Error('ingest_cursor table definition not found in sqlite_schema (fail-closed)');
    }
    const normCur = normalizeCanonicalSchemaSql(curSqlRow.sql);
    const expCur = normalizeCanonicalSchemaSql(INGEST_CURSOR_SCHEMA_SQL);
    if (!normCur.includes('CHECK ( LENGTH ( TRIM ( ACCOUNT_ID ) ) > 0 )')) {
      throw new Error('ingest_cursor missing account_id nonblank CHECK constraint (fail-closed)');
    }
    if (!normCur.includes('CHECK ( LENGTH ( TRIM ( CURSOR_VALUE ) ) > 0 )')) {
      throw new Error('ingest_cursor missing cursor_value nonblank CHECK constraint (fail-closed)');
    }
    if (normCur !== expCur) {
      throw new Error('ingest_cursor schema definition does not match canonical DDL contract (fail-closed)');
    }
  }
}

/**
 * Internal verified backup runner.
 * Creates an online snapshot of db via parameterized VACUUM INTO,
 * validates integrity, schema migrations, domain tables, and source stability.
 *
 * @param {DatabaseSync} db
 * @param {string} canonicalStateRoot
 * @param {number} expectedSourceSchemaVersion
 * @returns {{ success: true, backupPath: string, sourceSchemaVersion: number, integrity: string }}
 */
function executeVerifiedBackup(db, canonicalStateRoot, expectedSourceSchemaVersion) {
  if (!db) {
    throw new Error('Database connection must be provided for backup (fail-closed)');
  }
  if (typeof expectedSourceSchemaVersion !== 'number' || expectedSourceSchemaVersion <= 0) {
    throw new Error(`Invalid expectedSourceSchemaVersion: ${expectedSourceSchemaVersion} (fail-closed)`);
  }

  // 1. Pre-backup source baseline capture
  verifyCanonicalSchemaMigrationsShape(db);
  if (expectedSourceSchemaVersion >= 2) {
    verifyCanonicalDomainSchemaShape(db, expectedSourceSchemaVersion);
  }

  const sourceVersionsBefore = Array.from(readAppliedMigrationVersions(db));
  if (sourceVersionsBefore.length === 0) {
    throw new Error('Source schema_migrations is empty (fail-closed)');
  }

  const latestSourceVersion = sourceVersionsBefore[sourceVersionsBefore.length - 1];
  if (latestSourceVersion !== expectedSourceSchemaVersion) {
    throw new Error(
      `Source schema version drift detected (fail-closed): database state has latest version ${latestSourceVersion} but expected version ${expectedSourceSchemaVersion}`
    );
  }

  const sourceTablesBefore = Array.from(getCanonicalUserTableNames(db));
  const sourceDataVersionBefore = getDataVersion(db);

  // 2. Generate safe internal backup filename
  const uniqueId = crypto.randomUUID();
  const backupFilename = `channel-gateway-state.backup-v${expectedSourceSchemaVersion}-${uniqueId}.sqlite3`;
  const backupDestination = path.join(canonicalStateRoot, backupFilename);

  // 3. Pre-execution path confinement check
  const nominalRel = path.relative(canonicalStateRoot, backupDestination);
  if (nominalRel === '..' || nominalRel.startsWith('..' + path.sep) || path.isAbsolute(nominalRel)) {
    throw new Error(
      `Backup destination path escapes canonical state root: '${backupDestination}' is outside '${canonicalStateRoot}'`
    );
  }

  // 4. Destination existence check: only ENOENT is accepted
  let destLstat = null;
  try {
    destLstat = fs.lstatSync(backupDestination);
  } catch (err) {
    if (!err || err.code !== 'ENOENT') {
      throw new Error(
        `Failed to inspect backup destination path '${backupDestination}': ${err.message}`
      );
    }
  }
  if (destLstat !== null) {
    throw new Error(
      `Backup destination already exists (refusing overwrite/reuse): '${backupDestination}'`
    );
  }

  // 5. Execute VACUUM INTO using parameterized prepared statement
  try {
    const vacuumStmt = db.prepare('VACUUM INTO ?;');
    vacuumStmt.run(backupDestination);
  } catch (err) {
    throw new Error(`VACUUM INTO failed for destination '${backupDestination}': ${err.message}`);
  }

  // 6. Post-execution destination verification
  let postStat;
  try {
    postStat = fs.lstatSync(backupDestination);
  } catch (err) {
    throw new Error(
      `Backup file not found after VACUUM INTO: '${backupDestination}' (${err.message})`
    );
  }

  if (postStat.isSymbolicLink()) {
    throw new Error(`Backup file must not be a symbolic link: '${backupDestination}'`);
  }
  if (!postStat.isFile()) {
    throw new Error(`Backup file must be a regular file: '${backupDestination}'`);
  }

  let canonicalBackup;
  try {
    canonicalBackup = fs.realpathSync(backupDestination);
  } catch (err) {
    throw new Error(
      `Failed to resolve canonical path for backup file: '${backupDestination}' (${err.message})`
    );
  }

  const realRel = path.relative(canonicalStateRoot, canonicalBackup);
  if (realRel === '..' || realRel.startsWith('..' + path.sep) || path.isAbsolute(realRel)) {
    throw new Error(
      `Backup file resolves outside canonical state root: '${canonicalBackup}' is not within '${canonicalStateRoot}'`
    );
  }

  // 7. Read-only reopening and integrity verification
  let backupDb = null;
  try {
    backupDb = new DatabaseSync(backupDestination, {
      readOnly: true,
      enableForeignKeyConstraints: true,
    });

    // A. PRAGMA integrity_check
    const integrityRows = backupDb.prepare('PRAGMA integrity_check;').all();
    if (!integrityRows || integrityRows.length !== 1) {
      throw new Error(
        `PRAGMA integrity_check failed: expected 1 row, got ${integrityRows ? integrityRows.length : 0}`
      );
    }
    const integrityVal = integrityRows[0].integrity_check ?? Object.values(integrityRows[0])[0];
    if (integrityVal !== 'ok') {
      throw new Error(`PRAGMA integrity_check reported error: ${integrityVal}`);
    }

    // B. Canonical schema_migrations shape on backup
    verifyCanonicalSchemaMigrationsShape(backupDb);
    if (expectedSourceSchemaVersion >= 2) {
      verifyCanonicalDomainSchemaShape(backupDb, expectedSourceSchemaVersion);
    }

    // C. Applied migration history must match sourceVersionsBefore
    const backupVersions = readAppliedMigrationVersions(backupDb);
    if (backupVersions.length !== sourceVersionsBefore.length) {
      throw new Error(
        `Backup migration history count mismatch: backup has ${backupVersions.length}, source baseline had ${sourceVersionsBefore.length}`
      );
    }
    for (let i = 0; i < backupVersions.length; i++) {
      if (backupVersions[i] !== sourceVersionsBefore[i]) {
        throw new Error(
          `Backup migration history mismatch at index ${i}: backup=${backupVersions[i]}, source baseline=${sourceVersionsBefore[i]}`
        );
      }
    }

    // D. User table list must match sourceTablesBefore
    const backupTables = getCanonicalUserTableNames(backupDb);
    if (backupTables.length !== sourceTablesBefore.length) {
      throw new Error(
        `Backup tables count mismatch: backup has [${backupTables.join(', ')}], source baseline had [${sourceTablesBefore.join(', ')}]`
      );
    }
    for (let i = 0; i < backupTables.length; i++) {
      if (backupTables[i] !== sourceTablesBefore[i]) {
        throw new Error(
          `Backup table mismatch at index ${i}: backup has '${backupTables[i]}', source baseline has '${sourceTablesBefore[i]}'`
        );
      }
    }

    // E. Re-verify source database stability (post-backup verification)
    const sourceVersionsAfter = readAppliedMigrationVersions(db);
    if (sourceVersionsAfter.length !== sourceVersionsBefore.length) {
      throw new Error(
        `Source migration history count changed during backup: was ${sourceVersionsBefore.length}, now ${sourceVersionsAfter.length} (fail-closed)`
      );
    }
    for (let i = 0; i < sourceVersionsAfter.length; i++) {
      if (sourceVersionsAfter[i] !== sourceVersionsBefore[i]) {
        throw new Error(
          `Source migration version changed during backup at index ${i}: was ${sourceVersionsBefore[i]}, now ${sourceVersionsAfter[i]} (fail-closed)`
        );
      }
    }

    const sourceTablesAfter = getCanonicalUserTableNames(db);
    if (sourceTablesAfter.length !== sourceTablesBefore.length) {
      throw new Error(
        `Source table count changed during backup: was [${sourceTablesBefore.join(', ')}], now [${sourceTablesAfter.join(', ')}] (fail-closed)`
      );
    }
    for (let i = 0; i < sourceTablesAfter.length; i++) {
      if (sourceTablesAfter[i] !== sourceTablesBefore[i]) {
        throw new Error(
          `Source table changed during backup at index ${i}: was '${sourceTablesBefore[i]}', now '${sourceTablesAfter[i]}' (fail-closed)`
        );
      }
    }

    if (sourceDataVersionBefore !== null) {
      const sourceDataVersionAfter = getDataVersion(db);
      if (sourceDataVersionAfter !== sourceDataVersionBefore) {
        throw new Error(
          `Source data_version changed during backup: was ${sourceDataVersionBefore}, now ${sourceDataVersionAfter} (concurrent mutation detected, fail-closed)`
        );
      }
    }
  } catch (verifErr) {
    // Best-effort cleanup of destination ONLY IF confirmed regular file inside stateRoot
    try {
      const stat = fs.lstatSync(backupDestination);
      if (stat.isFile() && !stat.isSymbolicLink()) {
        const real = fs.realpathSync(backupDestination);
        const rel = path.relative(canonicalStateRoot, real);
        if (rel !== '..' && !rel.startsWith('..' + path.sep) && !path.isAbsolute(rel)) {
          fs.unlinkSync(backupDestination);
        }
      }
    } catch (_) {
      // Best effort: do not sacrifice path safety
    }
    throw new Error(`Backup verification failed: ${verifErr.message}`);
  } finally {
    if (backupDb) {
      try {
        backupDb.close();
      } catch (_) {}
    }
  }

  return {
    success: true,
    backupPath: backupDestination,
    sourceSchemaVersion: expectedSourceSchemaVersion,
    integrity: 'ok',
  };
}

/**
 * Bounded internal input validators for channel state operations (ADR-0023 / T7B).
 */
function validateChannelId(channelId) {
  if (typeof channelId !== 'string') {
    throw new TypeError('channelId must be a string');
  }
  const trimmed = channelId.trim();
  if (trimmed.length === 0) {
    throw new Error('channelId must be a non-empty string (fail-closed)');
  }
  return trimmed;
}

function validateHolderId(holderId) {
  if (typeof holderId !== 'string') {
    throw new TypeError('holderId must be a string');
  }
  const trimmed = holderId.trim();
  if (trimmed.length === 0) {
    throw new Error('holderId must be a non-empty string (fail-closed)');
  }
  return trimmed;
}

function validateFencingToken(token) {
  if (typeof token !== 'number' || !Number.isSafeInteger(token) || token < 0) {
    throw new Error('fencingToken must be a non-negative safe integer (fail-closed)');
  }
  return token;
}

function validateMessageId(messageId) {
  if (messageId === null || messageId === undefined) {
    throw new Error('messageId is required (fail-closed)');
  }
  const str = String(messageId).trim();
  if (str.length === 0) {
    throw new Error('messageId must not be empty (fail-closed)');
  }
  return str;
}

function validateReplyingAccountId(accountId) {
  if (typeof accountId !== 'string') {
    throw new TypeError('replyingAccountId must be a string');
  }
  const trimmed = accountId.trim();
  if (trimmed.length === 0) {
    throw new Error('replyingAccountId must be a non-empty string (fail-closed)');
  }
  return trimmed;
}

function validateOptionalTimestamp(ts) {
  if (ts === undefined || ts === null) {
    return null;
  }
  if (typeof ts !== 'number' || !Number.isSafeInteger(ts) || ts < 0) {
    throw new Error('timestamp must be a non-negative safe integer or null (fail-closed)');
  }
  return ts;
}

function validateClaimLimit(limit) {
  if (typeof limit !== 'number' || !Number.isSafeInteger(limit) || limit <= 0) {
    throw new Error('limit must be a positive safe integer (fail-closed)');
  }
  return limit;
}

function validateAccountId(accountId) {
  if (typeof accountId !== 'string') {
    throw new TypeError('accountId must be a string (fail-closed)');
  }
  const trimmed = accountId.trim();
  if (trimmed.length === 0) {
    throw new Error('accountId must be a non-empty string (fail-closed)');
  }
  return trimmed;
}

function validatePlatformMsgId(platformMsgId) {
  if (platformMsgId === null || platformMsgId === undefined) {
    throw new Error('platformMsgId is required (fail-closed)');
  }
  const str = String(platformMsgId).trim();
  if (str.length === 0) {
    throw new Error('platformMsgId must not be empty (fail-closed)');
  }
  return str;
}

function validateCursorValue(cursorValue) {
  if (cursorValue === null || cursorValue === undefined) {
    throw new Error('cursorValue is required (fail-closed)');
  }
  const str = String(cursorValue).trim();
  if (str.length === 0) {
    throw new Error('cursorValue must not be empty (fail-closed)');
  }
  return str;
}

function validateMessageContent(content) {
  if (typeof content !== 'string') {
    throw new TypeError('content must be a string (fail-closed)');
  }
  return content;
}

class SqliteStateRepository {
  /** @type {DatabaseSync|null} */
  #db = null;

  /** @type {string} */
  #canonicalStateRoot;

  /** @type {string} */
  #databasePath;

  /** @type {number|null} */
  #schemaVersion = null;

  /** @type {boolean} */
  #isOpen = false;

  /**
   * @param {string} stateRoot - Absolute path to an existing, writable stateRoot directory.
   */
  constructor(stateRoot) {
    if (typeof stateRoot !== 'string') {
      throw new TypeError('stateRoot must be a string');
    }

    const trimmed = stateRoot.trim();
    if (!trimmed) {
      throw new Error('stateRoot must be a non-empty string');
    }

    if (!isAbsolutePath(trimmed)) {
      throw new Error(`stateRoot must be an absolute path: received '${stateRoot}'`);
    }

    const nominal = path.resolve(trimmed);
    let stat;
    try {
      stat = fs.statSync(nominal);
    } catch (err) {
      throw new Error(
        `stateRoot does not exist or cannot be accessed: '${nominal}' (${err.message})`
      );
    }

    if (!stat.isDirectory()) {
      throw new Error(`stateRoot must be a directory: '${nominal}'`);
    }

    try {
      fs.accessSync(nominal, fs.constants.R_OK | fs.constants.W_OK);
    } catch (err) {
      throw new Error(
        `stateRoot must be readable and writable: '${nominal}' (${err.message})`
      );
    }

    this.#canonicalStateRoot = fs.realpathSync(nominal);
    this.#databasePath = path.join(this.#canonicalStateRoot, SQLITE_DATABASE_FILENAME);

    // F1 / T6 repair: Directory-entry existence classification via lstatSync only.
    // Never use fs.existsSync(databasePath), which treats dangling symlinks as absent.
    let isNew = false;
    let dbLstat = null;
    try {
      dbLstat = fs.lstatSync(this.#databasePath);
    } catch (err) {
      if (err && err.code === 'ENOENT') {
        isNew = true;
      } else {
        throw new Error(
          `Failed to inspect database path '${this.#databasePath}': ${err.message}`
        );
      }
    }

    if (!isNew) {
      if (dbLstat.isSymbolicLink()) {
        throw new Error(
          `Database file must not be a symbolic link: '${this.#databasePath}'`
        );
      }

      if (!dbLstat.isFile()) {
        throw new Error(
          `Database file must be a regular file: '${this.#databasePath}'`
        );
      }

      let canonicalDb;
      try {
        canonicalDb = fs.realpathSync(this.#databasePath);
      } catch (err) {
        throw new Error(
          `Failed to resolve canonical path for database file: '${this.#databasePath}' (${err.message})`
        );
      }

      const rel = path.relative(this.#canonicalStateRoot, canonicalDb);
      if (rel === '..' || rel.startsWith('..' + path.sep) || path.isAbsolute(rel)) {
        throw new Error(
          `Database file resolves outside canonical state root: '${canonicalDb}' is not within '${this.#canonicalStateRoot}'`
        );
      }
    }

    let db;
    try {
      db = new DatabaseSync(this.#databasePath, {
        timeout: SQLITE_BUSY_TIMEOUT_MS,
        enableForeignKeyConstraints: true,
      });
    } catch (err) {
      throw new Error(`Failed to open SQLite database at '${this.#databasePath}': ${err.message}`);
    }

    try {
      // 1. Mandatory PRAGMA setup
      db.exec('PRAGMA journal_mode = WAL;');
      db.exec('PRAGMA synchronous = FULL;');
      db.exec('PRAGMA foreign_keys = ON;');
      db.exec(`PRAGMA busy_timeout = ${SQLITE_BUSY_TIMEOUT_MS};`);

      // 2. Readback verification
      const jRow = db.prepare('PRAGMA journal_mode;').get();
      const sRow = db.prepare('PRAGMA synchronous;').get();
      const fkRow = db.prepare('PRAGMA foreign_keys;').get();
      const btRow = db.prepare('PRAGMA busy_timeout;').get();

      const journalMode = jRow ? (jRow.journal_mode ?? Object.values(jRow)[0]) : null;
      const synchronous = sRow ? (sRow.synchronous ?? Object.values(sRow)[0]) : null;
      const foreignKeys = fkRow ? (fkRow.foreign_keys ?? Object.values(fkRow)[0]) : null;
      const busyTimeout = btRow ? (btRow.timeout ?? btRow.busy_timeout ?? Object.values(btRow)[0]) : null;

      if (
        journalMode !== 'wal' ||
        synchronous !== 2 ||
        foreignKeys !== 1 ||
        busyTimeout !== SQLITE_BUSY_TIMEOUT_MS
      ) {
        throw new Error(
          `PRAGMA readback mismatch (fail-closed): journal_mode=${journalMode} (expected 'wal'), synchronous=${synchronous} (expected 2), foreign_keys=${foreignKeys} (expected 1), busy_timeout=${busyTimeout} (expected ${SQLITE_BUSY_TIMEOUT_MS})`
        );
      }

      // 3. Forward-only transactional migration runner / verification
      validateMigrationRegistry(MIGRATIONS, SQLITE_STATE_SCHEMA_VERSION);

      let currentVersion = 0;

      if (isNew) {
        // New DB: starts at version 0; schema_migrations table does not exist yet
        currentVersion = 0;
      } else {
        // Existing DB:
        // A. Must already have schema_migrations table
        const tableList = db.prepare("PRAGMA table_list('schema_migrations');").all();
        const hasTable = tableList && tableList.some((e) => e.name === 'schema_migrations');
        if (!hasTable) {
          throw new Error('Existing database is missing schema_migrations table (fail-closed)');
        }

        // B. Verify canonical table shape before reading history
        verifyCanonicalSchemaMigrationsShape(db);

        // C & D. Read migration history and verify valid sequential structure
        const appliedVersions = readAppliedMigrationVersions(db);

        // Fail-closed on future schema versions
        if (appliedVersions.some((v) => v > SQLITE_STATE_SCHEMA_VERSION)) {
          throw new Error(
            `Future schema version detected: [${appliedVersions.join(', ')}] exceeds supported version ${SQLITE_STATE_SCHEMA_VERSION} (fail-closed)`
          );
        }

        // E. Current version is the latest applied migration version
        currentVersion = appliedVersions[appliedVersions.length - 1];
      }

      // Pre-migration backup wiring:
      // If existing DB has pending migrations (currentVersion > 0 && currentVersion < SQLITE_STATE_SCHEMA_VERSION),
      // create verified pre-migration backup BEFORE running pending migrations.
      if (currentVersion > 0 && currentVersion < SQLITE_STATE_SCHEMA_VERSION) {
        executeVerifiedBackup(db, this.#canonicalStateRoot, currentVersion);
      }

      // Unified runner path: applies pending migrations (currentVersion < v <= targetVersion)
      // for both new and existing databases through the same forward runner.
      runPendingMigrations(db, currentVersion, SQLITE_STATE_SCHEMA_VERSION);

      // 4. Verify canonical schema_migrations shape (STRICT, single integer PK column)
      verifyCanonicalSchemaMigrationsShape(db);

      // 5. Verify canonical domain schema shape for v3
      verifyCanonicalDomainSchemaShape(db, SQLITE_STATE_SCHEMA_VERSION);

      // 6. Verify exact user table set
      const userTables = getCanonicalUserTableNames(db);
      const expectedTables = ['channel_control', 'inbox', 'ingest_cursor', 'schema_migrations'];
      if (
        userTables.length !== expectedTables.length ||
        !userTables.every((t, i) => t === expectedTables[i])
      ) {
        throw new Error(
          `User tables mismatch: expected [${expectedTables.join(', ')}], found [${userTables.join(', ')}] (fail-closed)`
        );
      }

      // 7. Verify final applied version state matches target schema version
      const finalVersions = readAppliedMigrationVersions(db);
      if (finalVersions[finalVersions.length - 1] !== SQLITE_STATE_SCHEMA_VERSION) {
        throw new Error(
          `Schema version mismatch: expected ${SQLITE_STATE_SCHEMA_VERSION}, got ${finalVersions[finalVersions.length - 1]} (fail-closed)`
        );
      }

      this.#schemaVersion = finalVersions[finalVersions.length - 1];
      this.#db = db;
      this.#isOpen = true;
    } catch (err) {
      try {
        db.close();
      } catch (_) {}
      throw err;
    }
  }

  /**
   * Static factory method for opening a repository.
   *
   * @param {string} stateRoot
   * @returns {SqliteStateRepository}
   */
  static open(stateRoot) {
    return new SqliteStateRepository(stateRoot);
  }

  /**
   * Canonical database file path.
   *
   * @returns {string}
   */
  get databasePath() {
    return this.#databasePath;
  }

  /**
   * Validated schema version read from database state.
   *
   * @returns {number}
   */
  get schemaVersion() {
    if (!this.#isOpen) {
      throw new Error('Repository is closed');
    }
    return this.#schemaVersion;
  }

  /**
   * Whether the repository connection is currently open.
   *
   * @returns {boolean}
   */
  get isOpen() {
    return Boolean(this.#isOpen);
  }

  /**
   * Creates a verified online backup of the SQLite database via VACUUM INTO.
   *
   * Invariants:
   * - Repository must be currently open; fails closed if closed.
   * - Pre-backup source baseline capture:
   *     1. Validates canonical schema_migrations shape on source DB.
   *     2. Captures sourceVersionsBefore (plain copied array of applied migration versions).
   *     3. Enforces sourceVersionsBefore[last] === this.#schemaVersion; fails closed on version drift.
   *     4. Captures sourceTablesBefore (plain copied array of user table names).
   *     5. Captures sourceDataVersionBefore (PRAGMA data_version) for concurrency drift detection.
   * - Source database remains open, usable, and unmodified.
   * - No caller path override: destination filename is generated internally using
   *   a safe naming pattern confined strictly to canonicalStateRoot.
   * - Destination existence is inspected with lstatSync: only ENOENT is accepted.
   *   Any existing regular file, symlink, or directory fails closed (no overwrite).
   * - SQL safety: uses parameterized prepared statement `VACUUM INTO ?;` with parameter binding.
   * - Backup file post-verification: must be a regular file, non-symlink, resolving inside canonicalStateRoot.
   * - Read-only integrity verification: opened with DatabaseSync({ readOnly: true, enableForeignKeyConstraints: true }).
   *   Verifies:
   *     1. PRAGMA integrity_check === 'ok'
   *     2. schema_migrations table canonical STRICT shape
   *     3. Applied migration history strictly matches sourceVersionsBefore
   *     4. User table list strictly matches sourceTablesBefore
   * - Post-backup source stability verification:
   *     1. sourceVersionsAfter strictly equals sourceVersionsBefore
   *     2. sourceTablesAfter strictly equals sourceTablesBefore
   *     3. sourceDataVersionAfter strictly equals sourceDataVersionBefore
   * - Returns clean success metadata ({ success: true, backupPath, sourceSchemaVersion, integrity: 'ok' }).
   *   Exposes no raw database handles or prepared statements.
   * - If verification fails, best-effort cleanup of destination is performed only if verified
   *   to be a regular non-symlink file within canonicalStateRoot.
   *
   * @returns {{ success: true, backupPath: string, sourceSchemaVersion: number, integrity: string }}
   */
  createVerifiedBackup() {
    if (!this.#isOpen || !this.#db) {
      throw new Error('Repository is closed (cannot create backup from closed repository)');
    }

    return executeVerifiedBackup(this.#db, this.#canonicalStateRoot, this.#schemaVersion);
  }

  /**
   * Private transaction execution runner.
   * Executes op inside an immediate transaction.
   * Ensures COMMIT succeeds before any successful mutation result is returned to caller.
   * In case of any error during operation or commit, performs best-effort rollback and rethrows.
   *
   * @param {function(DatabaseSync): any} op
   * @returns {any}
   */
  #runTransaction(op) {
    if (!this.#isOpen || !this.#db) {
      throw new Error('Repository is closed (cannot perform transaction on closed repository)');
    }
    const db = this.#db;
    db.exec('BEGIN IMMEDIATE;');
    let result;
    try {
      result = op(db);
      db.exec('COMMIT;');
    } catch (err) {
      try {
        db.exec('ROLLBACK;');
      } catch (_) {}
      throw err;
    }
    return result;
  }

  /**
   * Explicit channel takeover operation.
   * Updates or establishes channel holder and increments fencing token.
   * Discards any claimed unreplied messages for this channel with discard_reason = 'TAKEOVER'.
   * Preserves queued backlog messages.
   *
   * Invariants (D5, D6, D9):
   * - Executes atomically inside BEGIN IMMEDIATE.
   * - First takeover initializes fencing_token = 1, previousHolder = null.
   * - Existing row increments fencing_token by 1; fails closed if old token >= Number.MAX_SAFE_INTEGER.
   * - Discards all claimed messages for channel_id with discard_reason = 'TAKEOVER',
   *   recording discarded_by_holder = newHolder and discarded_at_token = newFencingToken.
   * - Does not alter queued, discarded, or replied messages.
   * - Returns success result strictly after COMMIT succeeds.
   *
   * @param {string} channelId
   * @param {string} holderId
   * @param {{ timestamp?: number|null }} [metadata={}]
   * @returns {{
   *   success: true,
   *   channelId: string,
   *   holder: string,
   *   fencingToken: number,
   *   previousHolder: string|null,
   *   discardedMessages: Array<{
   *     sequence: number,
   *     messageId: string,
   *     receivingAccountId: string,
   *     status: 'discarded',
   *     discardReason: 'TAKEOVER',
   *     claimedBy: string|null,
   *     claimedAtToken: number|null,
   *   }>,
   *   backlogCount: number
   * }}
   */
  takeoverChannel(channelId, holderId, metadata = {}) {
    const cId = validateChannelId(channelId);
    const hId = validateHolderId(holderId);
    const ts = validateOptionalTimestamp(
      metadata && typeof metadata === 'object' ? metadata.timestamp : undefined
    );

    return this.#runTransaction((db) => {
      const selectStmt = db.prepare(
        'SELECT channel_id, current_holder, fencing_token FROM channel_control WHERE channel_id = ?;'
      );
      const existing = selectStmt.get(cId);

      let newFencingToken;
      let previousHolder = null;

      if (!existing) {
        newFencingToken = 1;
        const insertStmt = db.prepare(
          'INSERT INTO channel_control (channel_id, current_holder, fencing_token, last_heartbeat_at) VALUES (?, ?, ?, ?);'
        );
        insertStmt.run(cId, hId, newFencingToken, ts);
      } else {
        previousHolder = existing.current_holder;
        const prevToken = existing.fencing_token;
        if (
          typeof prevToken !== 'number' ||
          !Number.isSafeInteger(prevToken) ||
          prevToken < 0 ||
          prevToken >= Number.MAX_SAFE_INTEGER
        ) {
          throw new Error(
            `fencing_token invalid or exceeded MAX_SAFE_INTEGER: ${prevToken} (fail-closed)`
          );
        }
        newFencingToken = prevToken + 1;
        const updateStmt = db.prepare(
          'UPDATE channel_control SET current_holder = ?, fencing_token = ?, last_heartbeat_at = ? WHERE channel_id = ?;'
        );
        updateStmt.run(hId, newFencingToken, ts, cId);
      }

      // Discard claimed messages for this channel
      const selectClaimed = db.prepare(
        "SELECT sequence, platform_msg_id, account_id, status, claimed_by, claimed_at_token FROM inbox WHERE channel_id = ? AND status = 'claimed' ORDER BY sequence ASC;"
      );
      const claimedRows = selectClaimed.all(cId);

      if (claimedRows.length > 0) {
        const updateClaimed = db.prepare(
          "UPDATE inbox SET status = 'discarded', discard_reason = 'TAKEOVER', discarded_by_holder = ?, discarded_at_token = ? WHERE channel_id = ? AND status = 'claimed';"
        );
        updateClaimed.run(hId, newFencingToken, cId);
      }

      const discardedMessages = claimedRows.map((r) => ({
        sequence: r.sequence,
        messageId: r.platform_msg_id,
        receivingAccountId: r.account_id,
        status: 'discarded',
        discardReason: 'TAKEOVER',
        claimedBy: r.claimed_by,
        claimedAtToken: r.claimed_at_token,
      }));

      const countQueued = db.prepare(
        "SELECT count(*) AS cnt FROM inbox WHERE channel_id = ? AND status = 'queued';"
      );
      const queuedRow = countQueued.get(cId);
      const backlogCount = queuedRow ? queuedRow.cnt : 0;

      return {
        success: true,
        channelId: cId,
        holder: hId,
        fencingToken: newFencingToken,
        previousHolder,
        discardedMessages,
        backlogCount,
      };
    });
  }

  /**
   * Channel heartbeat renewal operation.
   * Updates last_heartbeat_at timestamp if caller is current holder with matching fencing token.
   *
   * Invariants (D6, D8):
   * - Cannot implicitly acquire holder or create channel row.
   * - Rejects with HOLDER_MISMATCH if no channel row, holder is null, or holder differs.
   * - Rejects with STALE_FENCING_TOKEN if holder matches but token differs.
   * - Zero mutations on mismatch.
   * - Result returned only after transaction completion.
   *
   * @param {string} channelId
   * @param {string} holderId
   * @param {number} fencingToken
   * @param {{ timestamp?: number|null }} [metadata={}]
   * @returns {{
   *   success: boolean,
   *   reason?: string,
   *   currentHolder?: string|null,
   *   expectedToken?: number,
   *   receivedToken?: number,
   *   channelId?: string,
   *   holder?: string,
   *   fencingToken?: number,
   *   lastHeartbeatAt?: number|null
   * }}
   */
  heartbeatChannel(channelId, holderId, fencingToken, metadata = {}) {
    const cId = validateChannelId(channelId);
    const hId = validateHolderId(holderId);
    const fToken = validateFencingToken(fencingToken);
    const ts = validateOptionalTimestamp(
      metadata && typeof metadata === 'object' ? metadata.timestamp : undefined
    );

    return this.#runTransaction((db) => {
      const selectStmt = db.prepare(
        'SELECT channel_id, current_holder, fencing_token FROM channel_control WHERE channel_id = ?;'
      );
      const row = selectStmt.get(cId);

      if (!row || row.current_holder === null || row.current_holder !== hId) {
        return {
          success: false,
          reason: 'HOLDER_MISMATCH',
          currentHolder: row ? row.current_holder : null,
        };
      }

      if (row.fencing_token !== fToken) {
        return {
          success: false,
          reason: 'STALE_FENCING_TOKEN',
          expectedToken: row.fencing_token,
          receivedToken: fToken,
        };
      }

      const updateStmt = db.prepare(
        'UPDATE channel_control SET last_heartbeat_at = ? WHERE channel_id = ?;'
      );
      updateStmt.run(ts, cId);

      return {
        success: true,
        channelId: cId,
        holder: hId,
        fencingToken: fToken,
        lastHeartbeatAt: ts,
      };
    });
  }

  /**
   * Heartbeat expiry operation for a channel.
   * Clears current holder and heartbeat, discards claimed unreplied messages with discard_reason = 'HEARTBEAT_EXPIRY'.
   *
   * Invariants (D6, D9):
   * - If no active holder, returns NO_ACTIVE_HOLDER with zero mutation.
   * - Discards all claimed messages for channel_id with discard_reason = 'HEARTBEAT_EXPIRY',
   *   recording discarded_by_holder = expiredHolder and discarded_at_token = currentToken.
   * - Preserves queued messages.
   * - Resets current_holder to NULL and last_heartbeat_at to NULL.
   * - Fencing token is NOT incremented.
   * - Result returned only after COMMIT succeeds.
   *
   * @param {string} channelId
   * @returns {{
   *   success: boolean,
   *   reason?: string,
   *   channelId?: string,
   *   expiredHolder?: string,
   *   fencingToken?: number,
   *   discardedMessages?: Array<object>,
   *   backlogCount?: number
   * }}
   */
  expireChannelHolder(channelId) {
    const cId = validateChannelId(channelId);

    return this.#runTransaction((db) => {
      const selectStmt = db.prepare(
        'SELECT channel_id, current_holder, fencing_token FROM channel_control WHERE channel_id = ?;'
      );
      const row = selectStmt.get(cId);

      if (!row || row.current_holder === null) {
        return {
          success: false,
          reason: 'NO_ACTIVE_HOLDER',
        };
      }

      const expiredHolder = row.current_holder;
      const currentToken = row.fencing_token;

      // Discard claimed rows
      const selectClaimed = db.prepare(
        "SELECT sequence, platform_msg_id, account_id, status, claimed_by, claimed_at_token FROM inbox WHERE channel_id = ? AND status = 'claimed' ORDER BY sequence ASC;"
      );
      const claimedRows = selectClaimed.all(cId);

      if (claimedRows.length > 0) {
        const updateClaimed = db.prepare(
          "UPDATE inbox SET status = 'discarded', discard_reason = 'HEARTBEAT_EXPIRY', discarded_by_holder = ?, discarded_at_token = ? WHERE channel_id = ? AND status = 'claimed';"
        );
        updateClaimed.run(expiredHolder, currentToken, cId);
      }

      const discardedMessages = claimedRows.map((r) => ({
        sequence: r.sequence,
        messageId: r.platform_msg_id,
        receivingAccountId: r.account_id,
        status: 'discarded',
        discardReason: 'HEARTBEAT_EXPIRY',
        claimedBy: r.claimed_by,
        claimedAtToken: r.claimed_at_token,
      }));

      const updateCtrl = db.prepare(
        'UPDATE channel_control SET current_holder = NULL, last_heartbeat_at = NULL WHERE channel_id = ?;'
      );
      updateCtrl.run(cId);

      const countQueued = db.prepare(
        "SELECT count(*) AS cnt FROM inbox WHERE channel_id = ? AND status = 'queued';"
      );
      const queuedRow = countQueued.get(cId);
      const backlogCount = queuedRow ? queuedRow.cnt : 0;

      return {
        success: true,
        channelId: cId,
        expiredHolder,
        fencingToken: currentToken,
        discardedMessages,
        backlogCount,
      };
    });
  }

  /**
   * Alias for expireChannelHolder(channelId).
   *
   * @param {string} channelId
   */
  expireHolder(channelId) {
    return this.expireChannelHolder(channelId);
  }

  /**
   * Claims queued messages in FIFO order (by sequence ASC) up to limit.
   *
   * Invariants (D6, D8, T18):
   * - Requires active holder and exact fencing token match.
   * - Cannot implicitly takeover or acquire holder.
   * - Rejects with NOT_CURRENT_HOLDER or STALE_FENCING_TOKEN without mutation.
   * - limit must be a positive safe integer (fails closed if non-integer, <= 0, NaN, Infinity).
   * - Atomically transitions queued messages to claimed with claimed_by and claimed_at_token.
   * - Returns claimedMessages strictly in sequence ASC order.
   * - Returns remainingBacklogCount.
   * - Returns result only after COMMIT succeeds.
   *
   * @param {string} channelId
   * @param {string} holderId
   * @param {number} fencingToken
   * @param {number} limit
   * @returns {{
   *   success: boolean,
   *   reason?: string,
   *   claimedMessages: Array<object>,
   *   channelId?: string,
   *   holder?: string,
   *   fencingToken?: number,
   *   remainingBacklogCount?: number
   * }}
   */
  claimMessages(channelId, holderId, fencingToken, limit) {
    const cId = validateChannelId(channelId);
    const hId = validateHolderId(holderId);
    const fToken = validateFencingToken(fencingToken);
    const lim = validateClaimLimit(limit);

    return this.#runTransaction((db) => {
      const selectStmt = db.prepare(
        'SELECT channel_id, current_holder, fencing_token FROM channel_control WHERE channel_id = ?;'
      );
      const row = selectStmt.get(cId);

      if (!row || row.current_holder === null || row.current_holder !== hId) {
        return {
          success: false,
          reason: 'NOT_CURRENT_HOLDER',
          claimedMessages: [],
        };
      }

      if (row.fencing_token !== fToken) {
        return {
          success: false,
          reason: 'STALE_FENCING_TOKEN',
          claimedMessages: [],
        };
      }

      const selectQueued = db.prepare(
        "SELECT sequence, channel_id, platform_msg_id, account_id, status FROM inbox WHERE channel_id = ? AND status = 'queued' ORDER BY sequence ASC LIMIT ?;"
      );
      const queuedRows = selectQueued.all(cId, lim);

      if (queuedRows.length > 0) {
        const updateClaim = db.prepare(
          "UPDATE inbox SET status = 'claimed', claimed_by = ?, claimed_at_token = ? WHERE sequence = ?;"
        );
        for (const q of queuedRows) {
          updateClaim.run(hId, fToken, q.sequence);
        }
      }

      const claimedMessages = queuedRows.map((r) => ({
        sequence: r.sequence,
        channelId: r.channel_id,
        messageId: r.platform_msg_id,
        receivingAccountId: r.account_id,
        status: 'claimed',
        claimedBy: hId,
        claimedAtToken: fToken,
      }));

      const countQueued = db.prepare(
        "SELECT count(*) AS cnt FROM inbox WHERE channel_id = ? AND status = 'queued';"
      );
      const queuedRow = countQueued.get(cId);
      const remainingBacklogCount = queuedRow ? queuedRow.cnt : 0;

      return {
        success: true,
        channelId: cId,
        holder: hId,
        fencingToken: fToken,
        claimedMessages,
        remainingBacklogCount,
      };
    });
  }

  /**
   * Strictly READ-ONLY validation of reply authorization (ADR-0023, ADR-0024 F1).
   *
   * Invariants (D8, D26, R2, F1):
   * - ZERO side effects: does NOT update inbox, does NOT mark replied, does NOT create outbox.
   * - Validates:
   *     1. channel current_holder === holderId (NOT_CURRENT_HOLDER)
   *     2. fencing_token === fencingToken (STALE_FENCING_TOKEN)
   *     3. canonical message identity (account_id, platform_msg_id) exists in channel (MESSAGE_NOT_FOUND)
   *     4. cross-account collision existence probe in same channel (ACCOUNT_MISMATCH)
   *     5. message status === 'claimed' (MESSAGE_NOT_CLAIMED)
   *     6. message claimed_by === holderId and claimed_at_token === fencingToken (CLAIM_MISMATCH)
   * - If all pass, returns { authorized: true, messageId, channelId, receivingAccountId, replyingAccountId }.
   * - Message status remains 'claimed' in SQLite store.
   *
   * @param {string} channelId
   * @param {string} holderId
   * @param {number} fencingToken
   * @param {string|number} messageId
   * @param {string} replyingAccountId
   * @returns {{
   *   authorized: boolean,
   *   reason?: string,
   *   status?: string,
   *   messageId?: string,
   *   channelId?: string,
   *   receivingAccountId?: string,
   *   replyingAccountId?: string
   * }}
   */
  validateReplyAuthorization(channelId, holderId, fencingToken, messageId, replyingAccountId) {
    if (!this.#isOpen || !this.#db) {
      throw new Error(
        'Repository is closed (cannot validate reply authorization on closed repository)'
      );
    }

    const cId = validateChannelId(channelId);
    const hId = validateHolderId(holderId);
    const fToken = validateFencingToken(fencingToken);
    const mId = validateMessageId(messageId);
    const rAcc = validateReplyingAccountId(replyingAccountId);

    const selectCtrl = this.#db.prepare(
      'SELECT channel_id, current_holder, fencing_token FROM channel_control WHERE channel_id = ?;'
    );
    const ctrlRow = selectCtrl.get(cId);

    if (!ctrlRow || ctrlRow.current_holder !== hId) {
      return { authorized: false, reason: 'NOT_CURRENT_HOLDER' };
    }

    if (ctrlRow.fencing_token !== fToken) {
      return { authorized: false, reason: 'STALE_FENCING_TOKEN' };
    }

    const selectMsg = this.#db.prepare(
      'SELECT sequence, channel_id, platform_msg_id, account_id, status, claimed_by, claimed_at_token FROM inbox WHERE account_id = ? AND platform_msg_id = ? AND channel_id = ?;'
    );
    const msgRow = selectMsg.get(rAcc, mId, cId);

    if (!msgRow) {
      // Secondary probe in same channel to distinguish cross-account mismatch from message not found
      const probeMsg = this.#db.prepare(
        'SELECT 1 FROM inbox WHERE channel_id = ? AND platform_msg_id = ? LIMIT 1;'
      );
      const probeRow = probeMsg.get(cId, mId);
      if (probeRow) {
        return { authorized: false, reason: 'ACCOUNT_MISMATCH' };
      }
      return { authorized: false, reason: 'MESSAGE_NOT_FOUND' };
    }

    if (msgRow.status !== 'claimed') {
      return { authorized: false, reason: 'MESSAGE_NOT_CLAIMED', status: msgRow.status };
    }

    if (msgRow.claimed_by !== hId || msgRow.claimed_at_token !== fToken) {
      return { authorized: false, reason: 'CLAIM_MISMATCH' };
    }

    return {
      authorized: true,
      messageId: mId,
      channelId: cId,
      receivingAccountId: msgRow.account_id,
      replyingAccountId: rAcc,
    };
  }

  /**
   * Minimal read-only inspection of channel state.
   *
   * @param {string} channelId
   * @returns {{
   *   channelId: string,
   *   currentHolder: string|null,
   *   fencingToken: number,
   *   lastHeartbeatAt: number|null,
   *   backlogCount: number
   * }|null}
   */
  getChannelState(channelId) {
    if (!this.#isOpen || !this.#db) {
      throw new Error('Repository is closed (cannot inspect state on closed repository)');
    }

    const cId = validateChannelId(channelId);
    const selectCtrl = this.#db.prepare(
      'SELECT channel_id, current_holder, fencing_token, last_heartbeat_at FROM channel_control WHERE channel_id = ?;'
    );
    const ctrlRow = selectCtrl.get(cId);
    if (!ctrlRow) {
      return null;
    }

    const countQueued = this.#db.prepare(
      "SELECT count(*) AS cnt FROM inbox WHERE channel_id = ? AND status = 'queued';"
    );
    const queuedRow = countQueued.get(cId);
    const backlogCount = queuedRow ? queuedRow.cnt : 0;

    return {
      channelId: ctrlRow.channel_id,
      currentHolder: ctrlRow.current_holder,
      fencingToken: ctrlRow.fencing_token,
      lastHeartbeatAt: ctrlRow.last_heartbeat_at,
      backlogCount,
    };
  }

  /**
   * Ingests an inbound message atomically with per-account cursor tracking (T8B).
   *
   * Invariants (D10, D30, T8B):
   * - Atomically persists inbound message and advances cursor in a SINGLE immediate transaction.
   * - Ensures channel existence in channel_control without taking over holder (holder=NULL, token=0).
   * - Preserves existing holder, fencing_token, and heartbeat if channel already exists.
   * - Idempotent deduplication based on canonical identity (account_id, platform_msg_id):
   *     - If (account_id, platform_msg_id) already exists:
   *         - Returns { success: true, duplicate: true, sequence, channelId, accountId, platformMsgId }.
   *         - Zero mutation: does NOT insert duplicate, does NOT update content/status/channel.
   *         - CRITICAL: DUPLICATE MUST NOT UPDATE CURSOR.
   *     - If new identity:
   *         - Inserts inbox row with status='queued', exact content (untrimmed).
   *         - Upserts ingest_cursor(account_id, cursor_value) in SAME transaction.
   *         - Returns { success: true, duplicate: false, sequence, channelId, accountId, platformMsgId, cursorValue }.
   * - Rejects invalid inputs before any transaction mutation.
   * - Result returned only after COMMIT succeeds.
   *
   * @param {{
   *   accountId: string,
   *   platformMsgId: string|number,
   *   channelId: string,
   *   content: string,
   *   cursorValue: string|number
   * }} input
   * @returns {{
   *   success: true,
   *   duplicate: boolean,
   *   sequence: number,
   *   channelId: string,
   *   accountId: string,
   *   platformMsgId: string,
   *   cursorValue?: string
   * }}
   */
  ingestMessage(input) {
    if (!input || typeof input !== 'object' || Array.isArray(input)) {
      throw new TypeError('ingestMessage input must be a non-null object (fail-closed)');
    }

    const accId = validateAccountId(input.accountId);
    const pMsgId = validatePlatformMsgId(input.platformMsgId);
    const chId = validateChannelId(input.channelId);
    const content = validateMessageContent(input.content);
    const curVal = validateCursorValue(input.cursorValue);

    return this.#runTransaction((db) => {
      // 1. Check canonical duplicate identity: UNIQUE(account_id, platform_msg_id) FIRST
      // Duplicates must be strictly zero-mutation: no channel ensure, no inbox insert, no cursor change.
      const selectExisting = db.prepare(
        'SELECT sequence, channel_id, account_id, platform_msg_id FROM inbox WHERE account_id = ? AND platform_msg_id = ?;'
      );
      const existing = selectExisting.get(accId, pMsgId);

      if (existing) {
        // Duplicate identity: idempotent zero-mutation no-op, cursor MUST NOT be updated
        return {
          success: true,
          duplicate: true,
          sequence: existing.sequence,
          channelId: existing.channel_id,
          accountId: accId,
          platformMsgId: pMsgId,
        };
      }

      // 2. Ensure channel existence (unattended message persistence under D10)
      // Executed ONLY for non-duplicate messages to prevent orphan channel_control rows
      const selectChan = db.prepare(
        'SELECT channel_id, current_holder, fencing_token FROM channel_control WHERE channel_id = ?;'
      );
      const chanRow = selectChan.get(chId);
      if (!chanRow) {
        const insertChan = db.prepare(
          'INSERT INTO channel_control (channel_id, current_holder, fencing_token, last_heartbeat_at) VALUES (?, NULL, 0, NULL);'
        );
        insertChan.run(chId);
      }

      // 3. Insert new queued message
      const insertMsg = db.prepare(
        "INSERT INTO inbox (channel_id, account_id, platform_msg_id, content, status) VALUES (?, ?, ?, ?, 'queued');"
      );
      const msgResult = insertMsg.run(chId, accId, pMsgId, content);
      const sequence = Number(msgResult.lastInsertRowid);

      // 4. Update/insert ingest cursor in SAME transaction
      const upsertCursor = db.prepare(
        'INSERT INTO ingest_cursor (account_id, cursor_value) VALUES (?, ?) ON CONFLICT(account_id) DO UPDATE SET cursor_value = excluded.cursor_value;'
      );
      upsertCursor.run(accId, curVal);

      return {
        success: true,
        duplicate: false,
        sequence,
        channelId: chId,
        accountId: accId,
        platformMsgId: pMsgId,
        cursorValue: curVal,
      };
    });
  }

  /**
   * Minimal strictly READ-ONLY lookup of per-account ingest cursor.
   *
   * @param {string} accountId
   * @returns {string|null} Cursor string if exists, or null
   */
  getIngestCursor(accountId) {
    if (!this.#isOpen || !this.#db) {
      throw new Error('Repository is closed (cannot read cursor on closed repository)');
    }
    const accId = validateAccountId(accountId);
    const stmt = this.#db.prepare('SELECT cursor_value FROM ingest_cursor WHERE account_id = ?;');
    const row = stmt.get(accId);
    return row ? row.cursor_value : null;
  }

  /**
   * Closes the repository and underlying database connection.
   * Idempotent: safe to call multiple times.
   */
  close() {
    if (!this.#isOpen) {
      return;
    }
    this.#isOpen = false;
    if (this.#db) {
      try {
        this.#db.close();
      } finally {
        this.#db = null;
      }
    }
  }
}

module.exports = {
  SQLITE_STATE_SCHEMA_VERSION,
  SQLite_STATE_SCHEMA_VERSION: SQLITE_STATE_SCHEMA_VERSION,
  SQLITE_BUSY_TIMEOUT_MS,
  SQLITE_DATABASE_FILENAME,
  SqliteStateRepository,
  CHANNEL_CONTROL_SCHEMA_SQL,
  INBOX_SCHEMA_SQL,
  INBOX_V2_SCHEMA_SQL,
  INGEST_CURSOR_SCHEMA_SQL,
  normalizeCanonicalSchemaSql,
};
