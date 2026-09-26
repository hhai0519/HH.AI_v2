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
const { ensureBackupsDirectory } = require('./backup-hygiene');
const {
  computeCanonicalPayloadHash,
  evaluateStartupRecovery,
  LINE_RETRY_KEY_UUID_REGEX,
} = require('./outbox-delivery-policy');

const SQLITE_STATE_SCHEMA_VERSION = 7;
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

const INGEST_CURSOR_V3_SCHEMA_SQL = `
CREATE TABLE ingest_cursor (
  account_id TEXT PRIMARY KEY
    CHECK(length(trim(account_id)) > 0),
  cursor_value TEXT NOT NULL
    CHECK(length(trim(cursor_value)) > 0)
) STRICT;
`;

/**
 * Canonical DDL definitions for domain tables in schema version 5.
 * Ingest cursor table tracks per-account fetch cursor with observation timestamp.
 */
const INGEST_CURSOR_SCHEMA_SQL = `
CREATE TABLE ingest_cursor (
  account_id TEXT PRIMARY KEY
    CHECK(length(trim(account_id)) > 0),
  cursor_value TEXT NOT NULL
    CHECK(length(trim(cursor_value)) > 0),
  updated_at_ms INTEGER NOT NULL
    CHECK(updated_at_ms >= 0)
) STRICT;
`;

/**
 * Canonical DDL definitions for domain tables in schema version 4.
 * Inbound event ledger tracks per-event ingress with (account_id, platform_event_id) uniqueness.
 */
const INBOUND_EVENT_SCHEMA_SQL = `
CREATE TABLE inbound_event (
  event_sequence INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id TEXT NOT NULL
    CHECK(length(trim(account_id)) > 0),
  platform_event_id TEXT NOT NULL
    CHECK(length(trim(platform_event_id)) > 0),
  event_type TEXT NOT NULL
    CHECK(event_type IN ('MESSAGE', 'EDIT', 'UNSEND', 'IGNORED')),
  channel_id TEXT,
  platform_msg_id TEXT,
  CHECK(
    (event_type = 'IGNORED' AND channel_id IS NULL AND platform_msg_id IS NULL)
    OR
    (event_type IN ('MESSAGE', 'EDIT', 'UNSEND') AND channel_id IS NOT NULL AND length(trim(channel_id)) > 0 AND platform_msg_id IS NOT NULL AND length(trim(platform_msg_id)) > 0)
  ),
  UNIQUE(account_id, platform_event_id),
  FOREIGN KEY(channel_id)
    REFERENCES channel_control(channel_id)
    ON DELETE RESTRICT
) STRICT;
`;

/**
 * Canonical DDL definition for durable outbox table in schema version 6 (ADR-0025 R2).
 * Preserved for migration 6 runner and v6 backup validation.
 */
const OUTBOX_V6_SCHEMA_SQL = `
CREATE TABLE outbox (
  command_id TEXT PRIMARY KEY
    CHECK(length(trim(command_id)) > 0),
  client_request_id TEXT NOT NULL UNIQUE
    CHECK(length(trim(client_request_id)) > 0),
  payload_hash TEXT NOT NULL
    CHECK(length(payload_hash) = 64),
  platform TEXT NOT NULL
    CHECK(length(trim(platform)) > 0),
  account_id TEXT NOT NULL
    CHECK(length(trim(account_id)) > 0),
  endpoint_operation TEXT NOT NULL
    CHECK(length(trim(endpoint_operation)) > 0),
  recipient TEXT NOT NULL
    CHECK(length(trim(recipient)) > 0),
  logical_reply_target TEXT
    CHECK(
      logical_reply_target IS NULL OR
      length(trim(logical_reply_target)) > 0
    ),
  message_type TEXT NOT NULL
    CHECK(length(trim(message_type)) > 0),
  body TEXT NOT NULL
    CHECK(length(trim(body)) > 0),
  status TEXT NOT NULL
    CHECK(status IN (
      'QUEUED',
      'IN_FLIGHT',
      'ACCEPTED_BY_PLATFORM',
      'UNCERTAIN',
      'FAILED_TERMINAL'
    )),
  attempt_count INTEGER NOT NULL DEFAULT 0
    CHECK(attempt_count >= 0),
  next_attempt_at INTEGER
    CHECK(
      next_attempt_at IS NULL OR
      next_attempt_at >= 0
    ),
  external_retry_key TEXT
    CHECK(
      external_retry_key IS NULL OR
      length(trim(external_retry_key)) > 0
    ),
  external_retry_expires_at INTEGER
    CHECK(
      external_retry_expires_at IS NULL OR
      external_retry_expires_at >= 0
    ),
  created_at INTEGER NOT NULL
    CHECK(created_at >= 0),
  updated_at INTEGER NOT NULL
    CHECK(updated_at >= 0),
  CHECK(
    (external_retry_key IS NULL AND external_retry_expires_at IS NULL) OR
    (external_retry_key IS NOT NULL AND external_retry_expires_at IS NOT NULL)
  )
) STRICT;
`;

/**
 * Canonical DDL definition for durable outbox table in schema version 7 (TG-MVP-13 §18).
 * Adds terminal_reason_code TEXT column with uppercase/digits/underscore check.
 */
const OUTBOX_SCHEMA_SQL = `
CREATE TABLE outbox (
  command_id TEXT PRIMARY KEY
    CHECK(length(trim(command_id)) > 0),
  client_request_id TEXT NOT NULL UNIQUE
    CHECK(length(trim(client_request_id)) > 0),
  payload_hash TEXT NOT NULL
    CHECK(length(payload_hash) = 64),
  platform TEXT NOT NULL
    CHECK(length(trim(platform)) > 0),
  account_id TEXT NOT NULL
    CHECK(length(trim(account_id)) > 0),
  endpoint_operation TEXT NOT NULL
    CHECK(length(trim(endpoint_operation)) > 0),
  recipient TEXT NOT NULL
    CHECK(length(trim(recipient)) > 0),
  logical_reply_target TEXT
    CHECK(
      logical_reply_target IS NULL OR
      length(trim(logical_reply_target)) > 0
    ),
  message_type TEXT NOT NULL
    CHECK(length(trim(message_type)) > 0),
  body TEXT NOT NULL
    CHECK(length(trim(body)) > 0),
  status TEXT NOT NULL
    CHECK(status IN (
      'QUEUED',
      'IN_FLIGHT',
      'ACCEPTED_BY_PLATFORM',
      'UNCERTAIN',
      'FAILED_TERMINAL'
    )),
  attempt_count INTEGER NOT NULL DEFAULT 0
    CHECK(attempt_count >= 0),
  next_attempt_at INTEGER
    CHECK(
      next_attempt_at IS NULL OR
      next_attempt_at >= 0
    ),
  external_retry_key TEXT
    CHECK(
      external_retry_key IS NULL OR
      length(trim(external_retry_key)) > 0
    ),
  external_retry_expires_at INTEGER
    CHECK(
      external_retry_expires_at IS NULL OR
      external_retry_expires_at >= 0
    ),
  created_at INTEGER NOT NULL
    CHECK(created_at >= 0),
  updated_at INTEGER NOT NULL
    CHECK(updated_at >= 0),
  terminal_reason_code TEXT
    CHECK(
      terminal_reason_code IS NULL OR
      (
        length(terminal_reason_code) >= 1 AND
        length(terminal_reason_code) <= 96 AND
        terminal_reason_code NOT GLOB '*[^A-Z0-9_]*'
      )
    ),
  CHECK(
    (external_retry_key IS NULL AND external_retry_expires_at IS NULL) OR
    (external_retry_key IS NOT NULL AND external_retry_expires_at IS NOT NULL)
  )
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
      db.exec(INGEST_CURSOR_V3_SCHEMA_SQL);
    },
  }),
  Object.freeze({
    version: 4,
    apply(db) {
      db.exec(INBOUND_EVENT_SCHEMA_SQL);
    },
  }),
  Object.freeze({
    version: 5,
    apply(db) {
      db.exec('ALTER TABLE ingest_cursor RENAME TO ingest_cursor_v4_legacy;');
      db.exec(INGEST_CURSOR_SCHEMA_SQL);
      const nowMs = Date.now();
      const insertStmt = db.prepare(`
        INSERT INTO ingest_cursor (account_id, cursor_value, updated_at_ms)
        SELECT account_id, cursor_value, ? FROM ingest_cursor_v4_legacy;
      `);
      insertStmt.run(nowMs);
      db.exec('DROP TABLE ingest_cursor_v4_legacy;');
    },
  }),
  Object.freeze({
    version: 6,
    apply(db) {
      db.exec(OUTBOX_V6_SCHEMA_SQL);
    },
  }),
  Object.freeze({
    version: 7,
    apply(db) {
      db.exec('ALTER TABLE outbox RENAME TO outbox_v6_legacy;');
      db.exec(OUTBOX_SCHEMA_SQL);
      db.exec(`
INSERT INTO outbox (
  command_id,
  client_request_id,
  payload_hash,
  platform,
  account_id,
  endpoint_operation,
  recipient,
  logical_reply_target,
  message_type,
  body,
  status,
  attempt_count,
  next_attempt_at,
  external_retry_key,
  external_retry_expires_at,
  created_at,
  updated_at,
  terminal_reason_code
)
SELECT
  command_id,
  client_request_id,
  payload_hash,
  platform,
  account_id,
  endpoint_operation,
  recipient,
  logical_reply_target,
  message_type,
  body,
  status,
  attempt_count,
  next_attempt_at,
  external_retry_key,
  external_retry_expires_at,
  created_at,
  updated_at,
  NULL
FROM outbox_v6_legacy;
`);
      db.exec('DROP TABLE outbox_v6_legacy;');
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
 * - Version 4 (canonical shape with inbound_event ledger)
 *
 * @param {DatabaseSync} db
 * @param {number} [version=SQLITE_STATE_SCHEMA_VERSION]
 */
function verifyCanonicalDomainSchemaShape(db, version = SQLITE_STATE_SCHEMA_VERSION) {
  if (
    version !== 2 &&
    version !== 3 &&
    version !== 4 &&
    version !== 5 &&
    version !== 6 &&
    version !== 7
  ) {
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

    // 3. Verify ingest_cursor for v3, v4, v5
    const curList = db.prepare("PRAGMA table_list('ingest_cursor');").all();
    const curEntry = curList ? curList.find((e) => e.name === 'ingest_cursor') : null;
    if (!curEntry || curEntry.type !== 'table' || Number(curEntry.strict) !== 1) {
      throw new Error('ingest_cursor must exist as a STRICT table (fail-closed)');
    }
    const curCols = db.prepare("PRAGMA table_info('ingest_cursor');").all();
    if (version === 3 || version === 4) {
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
      const expCur = normalizeCanonicalSchemaSql(INGEST_CURSOR_V3_SCHEMA_SQL);
      if (!normCur.includes('CHECK ( LENGTH ( TRIM ( ACCOUNT_ID ) ) > 0 )')) {
        throw new Error('ingest_cursor missing account_id nonblank CHECK constraint (fail-closed)');
      }
      if (!normCur.includes('CHECK ( LENGTH ( TRIM ( CURSOR_VALUE ) ) > 0 )')) {
        throw new Error('ingest_cursor missing cursor_value nonblank CHECK constraint (fail-closed)');
      }
      if (normCur !== expCur) {
        throw new Error('ingest_cursor schema definition does not match canonical DDL contract (fail-closed)');
      }
    } else if (version === 5 || version === 6) {
      if (!curCols || curCols.length !== 3) {
        throw new Error(
          `ingest_cursor must have exactly 3 columns, found ${curCols ? curCols.length : 0} (fail-closed)`
        );
      }
      const curExpected = {
        account_id: { type: 'TEXT', notnull: 1, pk: 1 },
        cursor_value: { type: 'TEXT', notnull: 1, pk: 0 },
        updated_at_ms: { type: 'INTEGER', notnull: 1, pk: 0 },
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
      if (!normCur.includes('CHECK ( UPDATED_AT_MS >= 0 )')) {
        throw new Error('ingest_cursor missing updated_at_ms non-negative CHECK constraint (fail-closed)');
      }
      if (normCur !== expCur) {
        throw new Error('ingest_cursor schema definition does not match canonical DDL contract (fail-closed)');
      }
    }

    // 4. Verify inbound_event for v4, v5, and v6
    if (version === 4 || version === 5 || version === 6) {
      const eventList = db.prepare("PRAGMA table_list('inbound_event');").all();
      const eventEntry = eventList ? eventList.find((e) => e.name === 'inbound_event') : null;
      if (!eventEntry || eventEntry.type !== 'table' || Number(eventEntry.strict) !== 1) {
        throw new Error('inbound_event must exist as a STRICT table (fail-closed)');
      }
      const eventCols = db.prepare("PRAGMA table_info('inbound_event');").all();
      if (!eventCols || eventCols.length !== 6) {
        throw new Error(
          `inbound_event must have exactly 6 columns, found ${eventCols ? eventCols.length : 0} (fail-closed)`
        );
      }
      const eventExpected = {
        event_sequence: { type: 'INTEGER', notnull: 0, pk: 1 },
        account_id: { type: 'TEXT', notnull: 1, pk: 0 },
        platform_event_id: { type: 'TEXT', notnull: 1, pk: 0 },
        event_type: { type: 'TEXT', notnull: 1, pk: 0 },
        channel_id: { type: 'TEXT', notnull: 0, pk: 0 },
        platform_msg_id: { type: 'TEXT', notnull: 0, pk: 0 },
      };
      for (const col of eventCols) {
        const exp = eventExpected[col.name];
        if (!exp) {
          throw new Error(`Unexpected column '${col.name}' in inbound_event (fail-closed)`);
        }
        if (
          col.type.toUpperCase() !== exp.type ||
          Number(col.notnull) !== exp.notnull ||
          Number(col.pk) !== exp.pk
        ) {
          throw new Error(
            `Column '${col.name}' in inbound_event mismatch: expected type=${exp.type}, notnull=${exp.notnull}, pk=${exp.pk}; got type=${col.type}, notnull=${col.notnull}, pk=${col.pk} (fail-closed)`
          );
        }
      }

      // Foreign key to channel_control
      const eventFks = db.prepare("PRAGMA foreign_key_list('inbound_event');").all();
      const eventFk = eventFks
        ? eventFks.find(
            (k) =>
              k.table === 'channel_control' &&
              k.from === 'channel_id' &&
              k.to === 'channel_id'
          )
        : null;
      if (!eventFk || !eventFk.on_delete || eventFk.on_delete.toUpperCase() !== 'RESTRICT') {
        throw new Error(
          'inbound_event must define FOREIGN KEY (channel_id) REFERENCES channel_control(channel_id) ON DELETE RESTRICT (fail-closed)'
        );
      }

      // UNIQUE(account_id, platform_event_id)
      const eventIdxList = db.prepare("PRAGMA index_list('inbound_event');").all();
      let hasEventUniqueCompound = false;
      if (eventIdxList) {
        for (const idx of eventIdxList) {
          if (Number(idx.unique) === 1) {
            const info = indexInfoStmt.all(idx.name);
            const cols = info ? info.map((c) => c.name) : [];
            if (cols.length === 2 && cols[0] === 'account_id' && cols[1] === 'platform_event_id') {
              hasEventUniqueCompound = true;
              break;
            }
          }
        }
      }
      if (!hasEventUniqueCompound) {
        throw new Error('inbound_event must define UNIQUE(account_id, platform_event_id) constraint (fail-closed)');
      }

      const eventSqlRow = schemaStmt.get('inbound_event');
      if (!eventSqlRow || typeof eventSqlRow.sql !== 'string') {
        throw new Error('inbound_event table definition not found in sqlite_schema (fail-closed)');
      }
      const normEvent = normalizeCanonicalSchemaSql(eventSqlRow.sql);
      const expEvent = normalizeCanonicalSchemaSql(INBOUND_EVENT_SCHEMA_SQL);

      if (!normEvent.includes('AUTOINCREMENT')) {
        throw new Error('inbound_event event_sequence column missing AUTOINCREMENT (fail-closed)');
      }
      if (!normEvent.includes('CHECK ( LENGTH ( TRIM ( ACCOUNT_ID ) ) > 0 )')) {
        throw new Error('inbound_event missing account_id nonblank CHECK constraint (fail-closed)');
      }
      if (!normEvent.includes('CHECK ( LENGTH ( TRIM ( PLATFORM_EVENT_ID ) ) > 0 )')) {
        throw new Error('inbound_event missing platform_event_id nonblank CHECK constraint (fail-closed)');
      }
      if (!normEvent.includes("CHECK ( EVENT_TYPE IN ( 'MESSAGE' , 'EDIT' , 'UNSEND' , 'IGNORED' ) )")) {
        throw new Error('inbound_event missing event_type enum CHECK constraint (fail-closed)');
      }
      if (normEvent !== expEvent) {
        throw new Error('inbound_event schema definition does not match canonical DDL contract (fail-closed)');
      }
    }

    // 5. Verify outbox for v6 and v7
    if (version === 6 || version === 7) {
      const obList = db.prepare("PRAGMA table_list('outbox');").all();
      const obEntry = obList ? obList.find((e) => e.name === 'outbox') : null;
      if (!obEntry || obEntry.type !== 'table' || Number(obEntry.strict) !== 1) {
        throw new Error('outbox must exist as a STRICT table (fail-closed)');
      }
      const obCols = db.prepare("PRAGMA table_info('outbox');").all();
      const expectedColCount = version === 6 ? 17 : 18;
      if (!obCols || obCols.length !== expectedColCount) {
        throw new Error(
          `outbox must have exactly ${expectedColCount} columns, found ${obCols ? obCols.length : 0} (fail-closed)`
        );
      }
      const obExpected = {
        command_id: { type: 'TEXT', notnull: 1, pk: 1 },
        client_request_id: { type: 'TEXT', notnull: 1, pk: 0 },
        payload_hash: { type: 'TEXT', notnull: 1, pk: 0 },
        platform: { type: 'TEXT', notnull: 1, pk: 0 },
        account_id: { type: 'TEXT', notnull: 1, pk: 0 },
        endpoint_operation: { type: 'TEXT', notnull: 1, pk: 0 },
        recipient: { type: 'TEXT', notnull: 1, pk: 0 },
        logical_reply_target: { type: 'TEXT', notnull: 0, pk: 0 },
        message_type: { type: 'TEXT', notnull: 1, pk: 0 },
        body: { type: 'TEXT', notnull: 1, pk: 0 },
        status: { type: 'TEXT', notnull: 1, pk: 0 },
        attempt_count: { type: 'INTEGER', notnull: 1, pk: 0, dflt_value: '0' },
        next_attempt_at: { type: 'INTEGER', notnull: 0, pk: 0 },
        external_retry_key: { type: 'TEXT', notnull: 0, pk: 0 },
        external_retry_expires_at: { type: 'INTEGER', notnull: 0, pk: 0 },
        created_at: { type: 'INTEGER', notnull: 1, pk: 0 },
        updated_at: { type: 'INTEGER', notnull: 1, pk: 0 },
      };
      if (version === 7) {
        obExpected.terminal_reason_code = { type: 'TEXT', notnull: 0, pk: 0 };
      }
      for (const col of obCols) {
        const exp = obExpected[col.name];
        if (!exp) {
          throw new Error(`Unexpected column '${col.name}' in outbox (fail-closed)`);
        }
        if (
          col.type.toUpperCase() !== exp.type ||
          Number(col.pk) !== exp.pk
        ) {
          throw new Error(
            `Column '${col.name}' in outbox mismatch: expected type=${exp.type}, pk=${exp.pk}; got type=${col.type}, pk=${col.pk} (fail-closed)`
          );
        }
        if (exp.dflt_value !== undefined && String(col.dflt_value) !== exp.dflt_value) {
          throw new Error(
            `Column '${col.name}' in outbox mismatch: expected dflt_value='${exp.dflt_value}', got '${col.dflt_value}' (fail-closed)`
          );
        }
      }

      const obIdxList = db.prepare("PRAGMA index_list('outbox');").all();
      let hasClientReqUnique = false;
      if (obIdxList) {
        for (const idx of obIdxList) {
          if (Number(idx.unique) === 1) {
            const info = indexInfoStmt.all(idx.name);
            const cols = info ? info.map((c) => c.name) : [];
            if (cols.length === 1 && cols[0] === 'client_request_id') {
              hasClientReqUnique = true;
              break;
            }
          }
        }
      }
      if (!hasClientReqUnique) {
        throw new Error('outbox must define UNIQUE constraint on client_request_id (fail-closed)');
      }

      const obSqlRow = schemaStmt.get('outbox');
      if (!obSqlRow || typeof obSqlRow.sql !== 'string') {
        throw new Error('outbox table definition not found in sqlite_schema (fail-closed)');
      }
      const normOb = normalizeCanonicalSchemaSql(obSqlRow.sql);
      const expOb = normalizeCanonicalSchemaSql(
        version === 6 ? OUTBOX_V6_SCHEMA_SQL : OUTBOX_SCHEMA_SQL
      );
      if (!normOb.includes('CHECK ( LENGTH ( PAYLOAD_HASH ) = 64 )')) {
        throw new Error('outbox missing payload_hash length 64 CHECK constraint (fail-closed)');
      }
      if (!normOb.includes("CHECK ( STATUS IN ( 'QUEUED' , 'IN_FLIGHT' , 'ACCEPTED_BY_PLATFORM' , 'UNCERTAIN' , 'FAILED_TERMINAL' ) )")) {
        throw new Error('outbox missing status enum CHECK constraint (fail-closed)');
      }
      if (!normOb.includes('CHECK ( ATTEMPT_COUNT >= 0 )')) {
        throw new Error('outbox missing attempt_count non-negative CHECK constraint (fail-closed)');
      }
      if (!normOb.includes('CHECK ( ( EXTERNAL_RETRY_KEY IS NULL AND EXTERNAL_RETRY_EXPIRES_AT IS NULL ) OR ( EXTERNAL_RETRY_KEY IS NOT NULL AND EXTERNAL_RETRY_EXPIRES_AT IS NOT NULL ) )')) {
        throw new Error('outbox missing external_retry pair CHECK constraint (fail-closed)');
      }
      if (version === 7) {
        if (!normOb.includes("CHECK ( TERMINAL_REASON_CODE IS NULL OR ( LENGTH ( TERMINAL_REASON_CODE ) >= 1 AND LENGTH ( TERMINAL_REASON_CODE ) <= 96 AND TERMINAL_REASON_CODE NOT GLOB '*[^A-Z0-9_]*' ) )")) {
          throw new Error('outbox missing terminal_reason_code CHECK constraint (fail-closed)');
        }
      }
      if (normOb !== expOb) {
        throw new Error('outbox schema definition does not match canonical DDL contract (fail-closed)');
      }
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

  // 2. Generate safe internal backup filename inside stateRoot/backups/
  const backupRoot = ensureBackupsDirectory(canonicalStateRoot);
  const uniqueId = crypto.randomUUID();
  const backupFilename = `channel-gateway-state.backup-v${expectedSourceSchemaVersion}-${uniqueId}.sqlite3`;
  const backupDestination = path.join(backupRoot, backupFilename);

  // 3. Pre-execution path confinement check
  const nominalRel = path.relative(backupRoot, backupDestination);
  if (nominalRel === '..' || nominalRel.startsWith('..' + path.sep) || path.isAbsolute(nominalRel)) {
    throw new Error(
      `Backup destination path escapes backup root: '${backupDestination}' is outside '${backupRoot}'`
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

  const realRel = path.relative(backupRoot, canonicalBackup);
  if (realRel === '..' || realRel.startsWith('..' + path.sep) || path.isAbsolute(realRel)) {
    throw new Error(
      `Backup file resolves outside backup root: '${canonicalBackup}' is not within '${backupRoot}'`
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
    // Best-effort cleanup of destination ONLY IF confirmed regular file inside backupRoot
    try {
      const stat = fs.lstatSync(backupDestination);
      if (stat.isFile() && !stat.isSymbolicLink()) {
        const real = fs.realpathSync(backupDestination);
        const rel = path.relative(backupRoot, real);
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

function validatePlatformEventId(platformEventId) {
  if (platformEventId === null || platformEventId === undefined) {
    throw new Error('platformEventId is required (fail-closed)');
  }
  if (typeof platformEventId !== 'string' && typeof platformEventId !== 'number') {
    throw new TypeError('platformEventId must be a string or number (fail-closed)');
  }
  const str = String(platformEventId).trim();
  if (str.length === 0) {
    throw new Error('platformEventId must not be empty (fail-closed)');
  }
  return str;
}

function validateCursorValue(cursorValue) {
  if (cursorValue === undefined) {
    throw new Error('cursorValue must not be undefined (fail-closed)');
  }
  if (cursorValue === null) {
    return null;
  }
  if (typeof cursorValue === 'number') {
    if (!Number.isInteger(cursorValue) || cursorValue < 0 || !Number.isSafeInteger(cursorValue)) {
      throw new Error('Numeric cursorValue must be a non-negative safe integer (fail-closed)');
    }
    return String(cursorValue);
  }
  if (typeof cursorValue === 'string') {
    if (!/^(0|[1-9][0-9]*)$/.test(cursorValue)) {
      throw new Error(`cursorValue must be a canonical non-negative decimal string: received '${cursorValue}' (fail-closed)`);
    }
    return cursorValue;
  }
  throw new TypeError('cursorValue must be a string, number, or null (fail-closed)');
}

function compareCanonicalDecimals(a, b) {
  if (a === b) return 0;
  if (a.length > b.length) return 1;
  if (a.length < b.length) return -1;
  return a > b ? 1 : -1;
}

function validateMessageContent(content) {
  if (typeof content !== 'string') {
    throw new TypeError('content must be a string (fail-closed)');
  }
  return content;
}

function validateCursorObservedAtMs(val, cursorValue) {
  if (cursorValue === null) {
    if (val !== undefined && val !== null) {
      if (typeof val !== 'number' || !Number.isSafeInteger(val) || val < 0) {
        throw new TypeError('cursorObservedAtMs must be a safe integer >= 0 (fail-closed)');
      }
      return val;
    }
    return null;
  }
  if (val === undefined || val === null || typeof val !== 'number' || !Number.isSafeInteger(val) || val < 0) {
    throw new TypeError('cursorObservedAtMs must be a safe integer >= 0 (fail-closed)');
  }
  return val;
}

function validateClientRequestId(val) {
  if (typeof val !== 'string') {
    throw new TypeError('clientRequestId must be a string (fail-closed)');
  }
  const trimmed = val.trim();
  if (trimmed.length === 0) {
    throw new Error('clientRequestId must not be empty (fail-closed)');
  }
  return trimmed;
}

function validatePayloadHash(val) {
  if (typeof val !== 'string') {
    throw new TypeError('payloadHash must be a string (fail-closed)');
  }
  const trimmed = val.trim();
  if (!/^[0-9a-f]{64}$/.test(trimmed)) {
    throw new Error('payloadHash must be 64 lowercase hex characters (fail-closed)');
  }
  return trimmed;
}

const FIXED_TERMINAL_REASONS = Object.freeze(new Set([
  'TELEGRAM_RETRY_AFTER_INVALID',
  'TELEGRAM_DELIVERY_WINDOW_EXCEEDED',
  'OUTBOUND_ACCOUNT_SWITCH_DISCARDED',
  'TELEGRAM_REPLY_TARGET_INVALID',
  'TELEGRAM_SECRET_UNAVAILABLE',
  'INVALID_TELEGRAM_TOKEN_SYNTAX',
  'LINE_REPLY_RETRY_KEY_FORBIDDEN',
]));

const BOUNDED_CLIENT_ERROR_REGEX = /^(?:TELEGRAM_CLIENT_ERROR|LINE_CLIENT_ERROR|CLIENT_ERROR)_[4][0-9]{2}$/;
const TERMINAL_REASON_SYNTAX_REGEX = /^[A-Z0-9_]{1,96}$/;

function isValidTerminalReasonCode(code) {
  if (typeof code !== 'string') return false;
  if (!TERMINAL_REASON_SYNTAX_REGEX.test(code)) return false;
  if (FIXED_TERMINAL_REASONS.has(code)) return true;
  if (BOUNDED_CLIENT_ERROR_REGEX.test(code)) return true;
  return false;
}

function validateTerminalReasonCode(code) {
  if (!isValidTerminalReasonCode(code)) {
    throw new Error(`Invalid terminal_reason_code: '${code}' (fail-closed)`);
  }
  return code;
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

      // 5. Verify canonical domain schema shape for target schema version
      verifyCanonicalDomainSchemaShape(db, SQLITE_STATE_SCHEMA_VERSION);

      // 6. Verify exact user table set for schema v6
      const userTables = getCanonicalUserTableNames(db);
      const expectedTables = [
        'channel_control',
        'inbound_event',
        'inbox',
        'ingest_cursor',
        'outbox',
        'schema_migrations',
      ];
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
   * Authoritative canonical path to the primary SQLite database file.
   *
   * @returns {string} Absolute canonical file path to channel-gateway-state.sqlite3
   */
  get databasePath() {
    return this.#databasePath;
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
   * Strictly READ-ONLY query for claimed messages for the current channel holder and token (ADR-0023, D-TG11-2).
   *
   * Invariants (D-TG11-2):
   * - Validates channelId, holderId, fencingToken syntax.
   * - Fails closed on closed repository.
   * - Validates current holder in channel_control:
   *     current holder MUST equal holderId
   *     current fencing token MUST equal fencingToken
   *     no current holder => []
   *     wrong holder => []
   *     stale/wrong fencing token => []
   * - SELECT only rows where:
   *     status = 'claimed'
   *     claimed_by = holderId
   *     claimed_at_token = fencingToken
   * - Includes message content.
   * - ORDER BY sequence ASC.
   * - Hard repository LIMIT 50.
   * - ZERO schema mutation, zero INSERT, zero UPDATE, zero DELETE, zero transaction-state mutation.
   *
   * @param {string} channelId
   * @param {string} holderId
   * @param {number} fencingToken
   * @returns {Array<{
   *   sequence: number,
   *   channel_id: string,
   *   channelId: string,
   *   message_id: string,
   *   messageId: string,
   *   account_id: string,
   *   accountId: string,
   *   receivingAccountId: string,
   *   status: string,
   *   claimed_by: string,
   *   claimedBy: string,
   *   claimed_at_token: number,
   *   claimedAtToken: number,
   *   content: string
   * }>}
   */
  getClaimedMessages(channelId, holderId, fencingToken) {
    if (!this.#isOpen || !this.#db) {
      throw new Error('Repository is closed (cannot inspect claimed messages on closed repository)');
    }

    const cId = validateChannelId(channelId);
    const hId = validateHolderId(holderId);
    const fToken = validateFencingToken(fencingToken);

    const selectCtrl = this.#db.prepare(
      'SELECT channel_id, current_holder, fencing_token FROM channel_control WHERE channel_id = ?;'
    );
    const ctrlRow = selectCtrl.get(cId);
    if (!ctrlRow || ctrlRow.current_holder === null || ctrlRow.current_holder !== hId) {
      return [];
    }
    if (ctrlRow.fencing_token !== fToken) {
      return [];
    }

    const selectClaimed = this.#db.prepare(
      "SELECT sequence, channel_id, platform_msg_id, account_id, status, claimed_by, claimed_at_token, content FROM inbox WHERE channel_id = ? AND status = 'claimed' AND claimed_by = ? AND claimed_at_token = ? ORDER BY sequence ASC LIMIT 50;"
    );
    const rows = selectClaimed.all(cId, hId, fToken);

    return rows.map((r) => ({
      sequence: r.sequence,
      channel_id: r.channel_id,
      channelId: r.channel_id,
      message_id: r.platform_msg_id,
      messageId: r.platform_msg_id,
      account_id: r.account_id,
      accountId: r.account_id,
      receivingAccountId: r.account_id,
      status: 'claimed',
      claimed_by: r.claimed_by,
      claimedBy: r.claimed_by,
      claimed_at_token: r.claimed_at_token,
      claimedAtToken: r.claimed_at_token,
      content: r.content !== null && r.content !== undefined ? String(r.content) : '',
    }));
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
   * Ingests an inbound message atomically with per-event ledger and per-account cursor tracking (T8B v4).
   *
   * Invariants (ADR-0024):
   * - Atomically persists inbound event in inbound_event and advances cursor in a SINGLE immediate transaction.
   * - Event-level deduplication based on canonical key (account_id, platform_event_id):
   *     - If (account_id, platform_event_id) already exists in inbound_event:
   *         - If event_type !== 'MESSAGE' or channel_id !== input.channelId or platform_msg_id !== input.platformMsgId:
   *             - Throws EVENT_IDENTITY_CONFLICT (fail-closed).
   *         - True duplicate event: idempotent zero mutation (no channel ensure, no inbox insert, no cursor change).
   *         - Returns { success: true, duplicate: true, eventSequence, messageCreated: false, sequence, channelId, accountId, platformEventId, platformMsgId, cursorValue, cursorAction: 'NONE' }.
   * - For new event:
   *     - Evaluates cursor decision (NONE if cursorValue === null; ADVANCE / NOOP / fail-closed CURSOR_REGRESSION).
   *     - Stored cursor must be canonical decimal; if invalid, throws STORED_CURSOR_INVALID (fail-closed).
   *     - Checks logical message (account_id, platform_msg_id) in inbox:
   *         - If exists under a different channel: throws LOGICAL_MESSAGE_CHANNEL_MISMATCH (fail-closed).
   *     - Ensures channel existence in channel_control (unattended persistence).
   *     - Inserts inbound_event row with event_type='MESSAGE'.
   *     - If logical message does not exist in inbox: inserts inbox row with status='queued', messageCreated=true.
   *       If already exists in inbox (same channel): messageCreated=false, preserves existing inbox content/status/claims.
   *     - If cursorAction === 'ADVANCE': upserts ingest_cursor(account_id, cursor_value).
   *     - Returns { success: true, duplicate: false, eventSequence, messageCreated, sequence, channelId, accountId, platformEventId, platformMsgId, cursorValue, cursorAction }.
   * - Rejects invalid inputs before any transaction mutation.
   * - Result returned only after COMMIT succeeds.
   *
   * @param {{
   *   accountId: string,
   *   platformEventId: string|number,
   *   platformMsgId: string|number,
   *   channelId: string,
   *   content: string,
   *   cursorValue: string|number|null
   * }} input
   * @returns {{
   *   success: true,
   *   duplicate: boolean,
   *   eventSequence: number,
   *   messageCreated: boolean,
   *   sequence: number|null,
   *   channelId: string,
   *   accountId: string,
   *   platformEventId: string,
   *   platformMsgId: string,
   *   cursorValue: string|null,
   *   cursorAction: 'ADVANCE'|'NOOP'|'NONE'
   * }}
   */
  ingestMessage(input) {
    if (!input || typeof input !== 'object' || Array.isArray(input)) {
      throw new TypeError('ingestMessage input must be a non-null object (fail-closed)');
    }

    const accId = validateAccountId(input.accountId);
    const pEventId = validatePlatformEventId(input.platformEventId);
    const pMsgId = validatePlatformMsgId(input.platformMsgId);
    const chId = validateChannelId(input.channelId);
    const content = validateMessageContent(input.content);
    const curVal = validateCursorValue(input.cursorValue);
    const observedAtMs = validateCursorObservedAtMs(input.cursorObservedAtMs, curVal);

    return this.#runTransaction((db) => {
      // 1. Check canonical event duplicate identity: UNIQUE(account_id, platform_event_id)
      const selectExistingEvent = db.prepare(
        'SELECT event_sequence, account_id, platform_event_id, event_type, channel_id, platform_msg_id FROM inbound_event WHERE account_id = ? AND platform_event_id = ?;'
      );
      const existingEvent = selectExistingEvent.get(accId, pEventId);

      if (existingEvent) {
        if (
          existingEvent.event_type !== 'MESSAGE' ||
          existingEvent.channel_id !== chId ||
          existingEvent.platform_msg_id !== pMsgId
        ) {
          throw new Error('EVENT_IDENTITY_CONFLICT: Existing event in inbound_event has conflicting identity or target (fail-closed)');
        }

        // True duplicate event: idempotent zero-mutation no-op, cursor MUST NOT be updated
        const existingMsg = db.prepare(
          'SELECT sequence FROM inbox WHERE account_id = ? AND platform_msg_id = ?;'
        ).get(accId, pMsgId);

        return {
          success: true,
          duplicate: true,
          eventSequence: existingEvent.event_sequence,
          messageCreated: false,
          sequence: existingMsg ? existingMsg.sequence : null,
          channelId: chId,
          accountId: accId,
          platformEventId: pEventId,
          platformMsgId: pMsgId,
          cursorValue: curVal,
          cursorAction: curVal === null ? 'NONE' : 'NOOP',
          cursorObservedAtMs: curVal === null ? null : observedAtMs,
        };
      }

      // 2. Cursor decision for new event
      let cursorAction = 'NONE';
      if (curVal !== null) {
        const selectCursor = db.prepare('SELECT cursor_value FROM ingest_cursor WHERE account_id = ?;');
        const cursorRow = selectCursor.get(accId);
        const storedCursor = cursorRow ? cursorRow.cursor_value : null;

        if (storedCursor === null) {
          cursorAction = 'ADVANCE';
        } else {
          if (!/^(0|[1-9][0-9]*)$/.test(storedCursor)) {
            throw new Error(`STORED_CURSOR_INVALID: Stored cursor '${storedCursor}' is not a canonical decimal string (fail-closed)`);
          }
          const cmp = compareCanonicalDecimals(curVal, storedCursor);
          if (cmp > 0) {
            cursorAction = 'ADVANCE';
          } else if (cmp === 0) {
            cursorAction = 'NOOP';
          } else {
            throw new Error(`CURSOR_REGRESSION: candidate cursor '${curVal}' < stored cursor '${storedCursor}' (fail-closed)`);
          }
        }
      }

      // 3. Logical message check: (account_id, platform_msg_id)
      const selectExistingMsg = db.prepare(
        'SELECT sequence, channel_id, account_id, platform_msg_id FROM inbox WHERE account_id = ? AND platform_msg_id = ?;'
      );
      const existingMsg = selectExistingMsg.get(accId, pMsgId);
      if (existingMsg && existingMsg.channel_id !== chId) {
        throw new Error(
          `LOGICAL_MESSAGE_CHANNEL_MISMATCH: Logical message exists in channel '${existingMsg.channel_id}' but received for channel '${chId}' (fail-closed)`
        );
      }

      // 4. Ensure channel existence in channel_control (unattended persistence)
      const selectChan = db.prepare(
        'SELECT channel_id FROM channel_control WHERE channel_id = ?;'
      );
      const chanRow = selectChan.get(chId);
      if (!chanRow) {
        const insertChan = db.prepare(
          'INSERT INTO channel_control (channel_id, current_holder, fencing_token, last_heartbeat_at) VALUES (?, NULL, 0, NULL);'
        );
        insertChan.run(chId);
      }

      // 5. Insert inbound_event row (MESSAGE)
      const insertEvent = db.prepare(
        "INSERT INTO inbound_event (account_id, platform_event_id, event_type, channel_id, platform_msg_id) VALUES (?, ?, 'MESSAGE', ?, ?);"
      );
      const eventResult = insertEvent.run(accId, pEventId, chId, pMsgId);
      const eventSequence = Number(eventResult.lastInsertRowid);

      // 6. Handle logical inbox message
      let sequence;
      let messageCreated = false;
      if (!existingMsg) {
        const insertMsg = db.prepare(
          "INSERT INTO inbox (channel_id, account_id, platform_msg_id, content, status) VALUES (?, ?, ?, ?, 'queued');"
        );
        const msgResult = insertMsg.run(chId, accId, pMsgId, content);
        sequence = Number(msgResult.lastInsertRowid);
        messageCreated = true;
      } else {
        sequence = existingMsg.sequence;
        messageCreated = false;
      }

      // 7. Update cursor in SAME transaction if ADVANCE
      if (cursorAction === 'ADVANCE') {
        const upsertCursor = db.prepare(
          'INSERT INTO ingest_cursor (account_id, cursor_value, updated_at_ms) VALUES (?, ?, ?) ON CONFLICT(account_id) DO UPDATE SET cursor_value = excluded.cursor_value, updated_at_ms = excluded.updated_at_ms;'
        );
        upsertCursor.run(accId, curVal, observedAtMs);
      }

      return {
        success: true,
        duplicate: false,
        eventSequence,
        messageCreated,
        sequence,
        channelId: chId,
        accountId: accId,
        platformEventId: pEventId,
        platformMsgId: pMsgId,
        cursorValue: curVal,
        cursorAction,
        cursorObservedAtMs: curVal === null ? null : observedAtMs,
      };
    });
  }

  /**
   * Records a durable terminal record for an unsupported inbound event (T8B v4).
   * Prevents poison polling loops in adapters by durably advancing cursor and logging IGNORED event.
   *
   * @param {{
   *   accountId: string,
   *   platformEventId: string|number,
   *   cursorValue: string|number|null
   * }} input
   * @returns {{
   *   success: true,
   *   duplicate: boolean,
   *   eventSequence: number,
   *   accountId: string,
   *   platformEventId: string,
   *   cursorValue: string|null,
   *   cursorAction: 'ADVANCE'|'NOOP'|'NONE'
   * }}
   */
  recordIgnoredEvent(input) {
    if (!input || typeof input !== 'object' || Array.isArray(input)) {
      throw new TypeError('recordIgnoredEvent input must be a non-null object (fail-closed)');
    }

    const accId = validateAccountId(input.accountId);
    const pEventId = validatePlatformEventId(input.platformEventId);
    const curVal = validateCursorValue(input.cursorValue);
    const observedAtMs = validateCursorObservedAtMs(input.cursorObservedAtMs, curVal);

    return this.#runTransaction((db) => {
      // 1. Dedup lookup
      const selectEvent = db.prepare(
        'SELECT event_sequence, account_id, platform_event_id, event_type FROM inbound_event WHERE account_id = ? AND platform_event_id = ?;'
      );
      const existing = selectEvent.get(accId, pEventId);

      if (existing) {
        if (existing.event_type !== 'IGNORED') {
          throw new Error('EVENT_IDENTITY_CONFLICT: Existing event in inbound_event is not IGNORED (fail-closed)');
        }
        return {
          success: true,
          duplicate: true,
          eventSequence: existing.event_sequence,
          accountId: accId,
          platformEventId: pEventId,
          cursorValue: curVal,
          cursorAction: curVal === null ? 'NONE' : 'NOOP',
          cursorObservedAtMs: curVal === null ? null : observedAtMs,
        };
      }

      // 2. Cursor decision for new event
      let cursorAction = 'NONE';
      if (curVal !== null) {
        const selectCursor = db.prepare('SELECT cursor_value FROM ingest_cursor WHERE account_id = ?;');
        const cursorRow = selectCursor.get(accId);
        const storedCursor = cursorRow ? cursorRow.cursor_value : null;

        if (storedCursor === null) {
          cursorAction = 'ADVANCE';
        } else {
          if (!/^(0|[1-9][0-9]*)$/.test(storedCursor)) {
            throw new Error(`STORED_CURSOR_INVALID: Stored cursor '${storedCursor}' is not a canonical decimal string (fail-closed)`);
          }
          const cmp = compareCanonicalDecimals(curVal, storedCursor);
          if (cmp > 0) {
            cursorAction = 'ADVANCE';
          } else if (cmp === 0) {
            cursorAction = 'NOOP';
          } else {
            throw new Error(`CURSOR_REGRESSION: candidate cursor '${curVal}' < stored cursor '${storedCursor}' (fail-closed)`);
          }
        }
      }

      // 3. Insert inbound_event row (IGNORED: channel_id and platform_msg_id are NULL)
      const insertEvent = db.prepare(
        "INSERT INTO inbound_event (account_id, platform_event_id, event_type, channel_id, platform_msg_id) VALUES (?, ?, 'IGNORED', NULL, NULL);"
      );
      const res = insertEvent.run(accId, pEventId);
      const eventSequence = Number(res.lastInsertRowid);

      // 4. Update cursor in SAME transaction if ADVANCE
      if (cursorAction === 'ADVANCE') {
        const upsertCursor = db.prepare(
          'INSERT INTO ingest_cursor (account_id, cursor_value, updated_at_ms) VALUES (?, ?, ?) ON CONFLICT(account_id) DO UPDATE SET cursor_value = excluded.cursor_value, updated_at_ms = excluded.updated_at_ms;'
        );
        upsertCursor.run(accId, curVal, observedAtMs);
      }

      return {
        success: true,
        duplicate: false,
        eventSequence,
        accountId: accId,
        platformEventId: pEventId,
        cursorValue: curVal,
        cursorAction,
        cursorObservedAtMs: curVal === null ? null : observedAtMs,
      };
    });
  }

  /**
   * Ingests an edited inbound message event (M6 / ADR-0024 Canary B).
   *
   * @param {{
   *   accountId: string,
   *   platformEventId: string|number,
   *   platformMsgId: string|number,
   *   channelId: string,
   *   content: string,
   *   cursorValue: string|number|null,
   *   cursorObservedAtMs?: number|null
   * }} input
   * @returns {{
   *   success: true,
   *   duplicate: boolean,
   *   applied: boolean,
   *   inboxUpdated: boolean,
   *   sequence: number|null,
   *   reason?: string,
   *   eventSequence: number,
   *   channelId: string,
   *   accountId: string,
   *   platformEventId: string,
   *   platformMsgId: string,
   *   cursorValue: string|null,
   *   cursorAction: 'ADVANCE'|'NOOP'|'NONE',
   *   cursorObservedAtMs: number|null
   * }}
   */
  ingestEdit(input) {
    if (!input || typeof input !== 'object' || Array.isArray(input)) {
      throw new TypeError('ingestEdit input must be a non-null object (fail-closed)');
    }

    const accId = validateAccountId(input.accountId);
    const pEventId = validatePlatformEventId(input.platformEventId);
    const pMsgId = validatePlatformMsgId(input.platformMsgId);
    const chId = validateChannelId(input.channelId);
    const content = validateMessageContent(input.content);
    const curVal = validateCursorValue(input.cursorValue);
    const observedAtMs = validateCursorObservedAtMs(input.cursorObservedAtMs, curVal);

    return this.#runTransaction((db) => {
      // 1. Check canonical event duplicate identity: UNIQUE(account_id, platform_event_id)
      const selectExistingEvent = db.prepare(
        'SELECT event_sequence, account_id, platform_event_id, event_type, channel_id, platform_msg_id FROM inbound_event WHERE account_id = ? AND platform_event_id = ?;'
      );
      const existingEvent = selectExistingEvent.get(accId, pEventId);

      if (existingEvent) {
        if (
          existingEvent.event_type !== 'EDIT' ||
          existingEvent.channel_id !== chId ||
          existingEvent.platform_msg_id !== pMsgId
        ) {
          throw new Error('EVENT_IDENTITY_CONFLICT: Existing event in inbound_event has conflicting identity or target (fail-closed)');
        }

        // True duplicate event: idempotent zero-mutation no-op
        const existingMsg = db.prepare(
          'SELECT sequence FROM inbox WHERE account_id = ? AND platform_msg_id = ?;'
        ).get(accId, pMsgId);

        return {
          success: true,
          duplicate: true,
          applied: false,
          inboxUpdated: false,
          eventSequence: existingEvent.event_sequence,
          sequence: existingMsg ? existingMsg.sequence : null,
          channelId: chId,
          accountId: accId,
          platformEventId: pEventId,
          platformMsgId: pMsgId,
          cursorValue: curVal,
          cursorAction: curVal === null ? 'NONE' : 'NOOP',
          cursorObservedAtMs: curVal === null ? null : observedAtMs,
        };
      }

      // 2. Cursor decision for new event
      let cursorAction = 'NONE';
      if (curVal !== null) {
        const selectCursor = db.prepare('SELECT cursor_value FROM ingest_cursor WHERE account_id = ?;');
        const cursorRow = selectCursor.get(accId);
        const storedCursor = cursorRow ? cursorRow.cursor_value : null;

        if (storedCursor === null) {
          cursorAction = 'ADVANCE';
        } else {
          if (!/^(0|[1-9][0-9]*)$/.test(storedCursor)) {
            throw new Error(`STORED_CURSOR_INVALID: Stored cursor '${storedCursor}' is not a canonical decimal string (fail-closed)`);
          }
          const cmp = compareCanonicalDecimals(curVal, storedCursor);
          if (cmp > 0) {
            cursorAction = 'ADVANCE';
          } else if (cmp === 0) {
            cursorAction = 'NOOP';
          } else {
            throw new Error(`CURSOR_REGRESSION: candidate cursor '${curVal}' < stored cursor '${storedCursor}' (fail-closed)`);
          }
        }
      }

      // 3. Ensure channel existence in channel_control
      const selectChan = db.prepare('SELECT channel_id FROM channel_control WHERE channel_id = ?;');
      if (!selectChan.get(chId)) {
        db.prepare(
          'INSERT INTO channel_control (channel_id, current_holder, fencing_token, last_heartbeat_at) VALUES (?, NULL, 0, NULL);'
        ).run(chId);
      }

      // 4. Check if target message exists in inbox: (account_id, platform_msg_id)
      const selectExistingMsg = db.prepare(
        'SELECT sequence, channel_id, account_id, platform_msg_id, status FROM inbox WHERE account_id = ? AND platform_msg_id = ?;'
      );
      const existingMsg = selectExistingMsg.get(accId, pMsgId);
      if (existingMsg && existingMsg.channel_id !== chId) {
        throw new Error(
          `LOGICAL_MESSAGE_CHANNEL_MISMATCH: Logical message exists in channel '${existingMsg.channel_id}' but received for channel '${chId}' (fail-closed)`
        );
      }

      // 5. Insert inbound_event row (EDIT)
      const insertEvent = db.prepare(
        "INSERT INTO inbound_event (account_id, platform_event_id, event_type, channel_id, platform_msg_id) VALUES (?, ?, 'EDIT', ?, ?);"
      );
      const eventResult = insertEvent.run(accId, pEventId, chId, pMsgId);
      const eventSequence = Number(eventResult.lastInsertRowid);

      // 6. Handle target inbox row
      let applied = false;
      let inboxUpdated = false;
      let sequence = null;
      let reason = undefined;

      if (existingMsg) {
        db.prepare('UPDATE inbox SET content = ? WHERE sequence = ?;').run(content, existingMsg.sequence);
        applied = true;
        inboxUpdated = true;
        sequence = existingMsg.sequence;
      } else {
        applied = false;
        inboxUpdated = false;
        reason = 'EDIT_TARGET_NOT_FOUND';
      }

      // 7. Update cursor in SAME transaction if ADVANCE
      if (cursorAction === 'ADVANCE') {
        const upsertCursor = db.prepare(
          'INSERT INTO ingest_cursor (account_id, cursor_value, updated_at_ms) VALUES (?, ?, ?) ON CONFLICT(account_id) DO UPDATE SET cursor_value = excluded.cursor_value, updated_at_ms = excluded.updated_at_ms;'
        );
        upsertCursor.run(accId, curVal, observedAtMs);
      }

      return {
        success: true,
        duplicate: false,
        applied,
        inboxUpdated,
        sequence,
        reason,
        eventSequence,
        channelId: chId,
        accountId: accId,
        platformEventId: pEventId,
        platformMsgId: pMsgId,
        cursorValue: curVal,
        cursorAction,
        cursorObservedAtMs: curVal === null ? null : observedAtMs,
      };
    });
  }

  /**
   * Retrieves full cursor state (cursorValue, updatedAtMs) for an account (M8).
   *
   * @param {string} accountId
   * @returns {{ cursorValue: string, updatedAtMs: number }|null}
   */
  getIngestCursorState(accountId) {
    if (!this.#isOpen || !this.#db) {
      throw new Error('Repository is closed (cannot read cursor state on closed repository)');
    }
    const accId = validateAccountId(accountId);
    const stmt = this.#db.prepare('SELECT cursor_value, updated_at_ms FROM ingest_cursor WHERE account_id = ?;');
    const row = stmt.get(accId);
    if (!row) {
      return null;
    }
    return {
      cursorValue: row.cursor_value,
      updatedAtMs: Number(row.updated_at_ms),
    };
  }

  /**
   * Exact-state conditional deletion of an ingest cursor for transport week-rebase (M8).
   * Deletes the cursor row ONLY if both stored cursor_value and stored updated_at_ms match expected.
   *
   * @param {{ accountId: string, expectedCursorValue: string, expectedUpdatedAtMs: number }} input
   * @returns {{ success: true, accountId: string, deleted: true }}
   */
  resetIngestCursorForTransportRebase(input) {
    if (!input || typeof input !== 'object' || Array.isArray(input)) {
      throw new TypeError('resetIngestCursorForTransportRebase input must be a non-null object (fail-closed)');
    }
    const accId = validateAccountId(input.accountId);
    const expectedCur = validateCursorValue(input.expectedCursorValue);
    if (expectedCur === null) {
      throw new Error('expectedCursorValue must be a non-empty string (fail-closed)');
    }
    if (
      typeof input.expectedUpdatedAtMs !== 'number' ||
      !Number.isSafeInteger(input.expectedUpdatedAtMs) ||
      input.expectedUpdatedAtMs < 0
    ) {
      throw new TypeError('expectedUpdatedAtMs must be a safe integer >= 0 (fail-closed)');
    }
    const expectedTime = input.expectedUpdatedAtMs;

    return this.#runTransaction((db) => {
      const selectStmt = db.prepare('SELECT cursor_value, updated_at_ms FROM ingest_cursor WHERE account_id = ?;');
      const row = selectStmt.get(accId);
      if (!row) {
        throw new Error('CURSOR_REBASE_STATE_MISMATCH: No cursor row exists for account (fail-closed)');
      }
      if (row.cursor_value !== expectedCur || Number(row.updated_at_ms) !== expectedTime) {
        throw new Error(
          `CURSOR_REBASE_STATE_MISMATCH: Stored cursor (${row.cursor_value}, ${row.updated_at_ms}) does not match expected (${expectedCur}, ${expectedTime}) (fail-closed)`
        );
      }
      db.prepare('DELETE FROM ingest_cursor WHERE account_id = ? AND cursor_value = ? AND updated_at_ms = ?;').run(
        accId,
        expectedCur,
        expectedTime
      );
      return {
        success: true,
        accountId: accId,
        deleted: true,
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
   * Atomic authorized reply enqueue primitive (ADR-0025 R2, Section 10).
   *
   * Executes in a single BEGIN IMMEDIATE transaction:
   * A. If client_request_id exists:
   *    - same payload_hash -> idempotent replay, return existing command_id + status
   *    - diff payload_hash -> IDEMPOTENCY_CONFLICT, zero mutation
   * B. If client_request_id does not exist:
   *    - fresh authorization against channel_control and inbox
   *    - if authorized: INSERT outbox (QUEUED) + UPDATE inbox status ('replied')
   *    - COMMIT
   * Any failure rolls back completely: zero half-rows.
   *
   * @param {object} params
   * @returns {{
   *   success: boolean,
   *   reason?: string,
   *   commandId?: string,
   *   outboxStatus?: string,
   *   idempotentReplay?: boolean
   * }}
   */
  enqueueAuthorizedReply(params) {
    if (!this.#isOpen || !this.#db) {
      throw new Error('Repository is closed (fail-closed)');
    }
    if (!params || typeof params !== 'object') {
      throw new TypeError('enqueueAuthorizedReply params must be an object');
    }

    const clientRequestId = validateClientRequestId(params.clientRequestId);
    const channelId = validateChannelId(params.channelId);
    const holderId = validateHolderId(params.holderId);
    const fencingToken = validateFencingToken(params.fencingToken);
    const messageId = validateMessageId(params.messageId);
    const replyingAccountId = validateReplyingAccountId(params.replyingAccountId);
    const text = validateMessageContent(params.text);
    const platform = validateAccountId(params.platform);
    const endpointOperation = validateAccountId(params.endpointOperation);
    const recipient = validateMessageId(params.recipient);
    const logicalReplyTarget = params.logicalReplyTarget ? String(params.logicalReplyTarget).trim() : null;
    const messageType = params.messageType ? String(params.messageType).trim() : 'text';
    const payloadHash = validatePayloadHash(params.payloadHash);
    const nowSec =
      typeof params.nowSec === 'number' && Number.isSafeInteger(params.nowSec) && params.nowSec >= 0
        ? params.nowSec
        : Math.floor(Date.now() / 1000);

    let externalRetryKey = null;
    let externalRetryExpiresAt = null;

    const hasRetryKey = params.externalRetryKey !== undefined && params.externalRetryKey !== null;
    const hasRetryExpires = params.externalRetryExpiresAt !== undefined && params.externalRetryExpiresAt !== null;

    if (hasRetryKey !== hasRetryExpires) {
      throw new TypeError(
        'externalRetryKey and externalRetryExpiresAt must be provided together or both omitted (fail-closed)'
      );
    }

    if (hasRetryKey && hasRetryExpires) {
      if (typeof params.externalRetryKey !== 'string') {
        throw new TypeError('externalRetryKey must be a string');
      }
      const trimmedKey = params.externalRetryKey.trim();
      if (!LINE_RETRY_KEY_UUID_REGEX.test(trimmedKey)) {
        throw new TypeError(
          `externalRetryKey must be a valid 128-bit UUID (8-4-4-4-12 hex groups): received '${params.externalRetryKey}' (fail-closed)`
        );
      }
      const exp = params.externalRetryExpiresAt;
      if (typeof exp !== 'number' || !Number.isSafeInteger(exp)) {
        throw new TypeError(
          `externalRetryExpiresAt must be a safe integer: received ${exp} (fail-closed)`
        );
      }
      if (exp <= nowSec || exp > nowSec + 86400) {
        throw new RangeError(
          `externalRetryExpiresAt must be > nowSec (${nowSec}) and <= nowSec + 86400 (${nowSec + 86400}): received ${exp} (fail-closed)`
        );
      }
      externalRetryKey = trimmedKey;
      externalRetryExpiresAt = exp;
    }

    this.#db.exec('BEGIN IMMEDIATE;');
    try {
      // Step A: Idempotency probe by client_request_id
      const selectOutbox = this.#db.prepare(
        'SELECT command_id, payload_hash, status FROM outbox WHERE client_request_id = ?;'
      );
      const existing = selectOutbox.get(clientRequestId);

      if (existing) {
        if (existing.payload_hash === payloadHash) {
          // Idempotent Replay: return existing command + status without modifying anything
          this.#db.exec('COMMIT;');
          return {
            success: true,
            commandId: existing.command_id,
            outboxStatus: existing.status,
            idempotentReplay: true,
          };
        }
        // Conflict: same client_request_id, different payload hash
        this.#db.exec('ROLLBACK;');
        return {
          success: false,
          reason: 'IDEMPOTENCY_CONFLICT',
        };
      }

      // Step B: Fresh authorization against channel_control and inbox
      const selectCtrl = this.#db.prepare(
        'SELECT channel_id, current_holder, fencing_token FROM channel_control WHERE channel_id = ?;'
      );
      const ctrlRow = selectCtrl.get(channelId);

      if (!ctrlRow || ctrlRow.current_holder !== holderId) {
        this.#db.exec('ROLLBACK;');
        return { success: false, reason: 'NOT_CURRENT_HOLDER' };
      }

      if (ctrlRow.fencing_token !== fencingToken) {
        this.#db.exec('ROLLBACK;');
        return { success: false, reason: 'STALE_FENCING_TOKEN' };
      }

      const selectMsg = this.#db.prepare(
        'SELECT sequence, channel_id, platform_msg_id, account_id, status, claimed_by, claimed_at_token FROM inbox WHERE account_id = ? AND platform_msg_id = ? AND channel_id = ?;'
      );
      const msgRow = selectMsg.get(replyingAccountId, messageId, channelId);

      if (!msgRow) {
        const probeMsg = this.#db.prepare(
          'SELECT 1 FROM inbox WHERE channel_id = ? AND platform_msg_id = ? LIMIT 1;'
        );
        const probeRow = probeMsg.get(channelId, messageId);
        this.#db.exec('ROLLBACK;');
        if (probeRow) {
          return { success: false, reason: 'ACCOUNT_MISMATCH' };
        }
        return { success: false, reason: 'MESSAGE_NOT_FOUND' };
      }

      if (msgRow.status !== 'claimed') {
        this.#db.exec('ROLLBACK;');
        return { success: false, reason: 'MESSAGE_NOT_CLAIMED', status: msgRow.status };
      }

      if (msgRow.claimed_by !== holderId || msgRow.claimed_at_token !== fencingToken) {
        this.#db.exec('ROLLBACK;');
        return { success: false, reason: 'CLAIM_MISMATCH' };
      }

      // Step C: Authorized fresh insert into outbox and update inbox to replied
      const commandId = `cmd_${crypto.randomUUID()}`;
      const insertOutbox = this.#db.prepare(`
        INSERT INTO outbox (
          command_id,
          client_request_id,
          payload_hash,
          platform,
          account_id,
          endpoint_operation,
          recipient,
          logical_reply_target,
          message_type,
          body,
          status,
          attempt_count,
          next_attempt_at,
          external_retry_key,
          external_retry_expires_at,
          created_at,
          updated_at,
          terminal_reason_code
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'QUEUED', 0, NULL, ?, ?, ?, ?, NULL);
      `);

      insertOutbox.run(
        commandId,
        clientRequestId,
        payloadHash,
        platform,
        replyingAccountId,
        endpointOperation,
        recipient,
        logicalReplyTarget,
        messageType,
        text,
        externalRetryKey,
        externalRetryExpiresAt,
        nowSec,
        nowSec
      );

      const updateInbox = this.#db.prepare(`
        UPDATE inbox
        SET status = 'replied'
        WHERE account_id = ? AND platform_msg_id = ? AND channel_id = ? AND status = 'claimed' AND claimed_by = ? AND claimed_at_token = ?;
      `);
      const updateRes = updateInbox.run(
        replyingAccountId,
        messageId,
        channelId,
        holderId,
        fencingToken
      );

      if (updateRes.changes !== 1) {
        throw new Error(
          `Expected exactly 1 inbox row updated to 'replied', updated ${updateRes.changes} (fail-closed)`
        );
      }

      this.#db.exec('COMMIT;');
      return {
        success: true,
        commandId,
        outboxStatus: 'QUEUED',
        idempotentReplay: false,
      };
    } catch (err) {
      try {
        this.#db.exec('ROLLBACK;');
      } catch (_) {}
      throw err;
    }
  }

  /**
   * Reads bounded summaries of UNCERTAIN outbox commands (ADR-0025 R2-3 Option B).
   * Strictly excludes message body, text, secret, token, HMAC, or raw payloads.
   *
   * @param {number} [limit=50]
   * @returns {{ count: number, summaries: Array<{ command_id: string, platform: string, account_id: string, recipient: string, created_at: number }> }}
   */
  getUncertainSummaries(limit = 50) {
    if (!this.#isOpen || !this.#db) {
      throw new Error('Repository is closed (fail-closed)');
    }
    const safeLimit = Number.isSafeInteger(limit) && limit > 0 ? limit : 50;

    const countRow = this.#db
      .prepare("SELECT COUNT(*) AS total FROM outbox WHERE status = 'UNCERTAIN';")
      .get();
    const count = countRow ? Number(countRow.total) : 0;

    const rows = this.#db
      .prepare(`
        SELECT command_id, platform, account_id, recipient, created_at
        FROM outbox
        WHERE status = 'UNCERTAIN'
        ORDER BY created_at ASC
        LIMIT ?;
      `)
      .all(safeLimit);

    return {
      count,
      summaries: rows || [],
    };
  }

  /**
   * Reads bounded summaries of FAILED_TERMINAL outbox commands (TG-MVP-13 §21).
   * Ordered by updated_at DESC, command_id ASC.
   * Strictly excludes message body, text, secret, token, HMAC, or raw payloads.
   *
   * @param {number} [limit=50]
   * @returns {{ count: number, summaries: Array<{ command_id: string, platform: string, account_id: string, recipient: string, created_at: number, updated_at: number, terminal_reason_code: string|null }> }}
   */
  getFailedTerminalSummaries(limit = 50) {
    if (!this.#isOpen || !this.#db) {
      throw new Error('Repository is closed (fail-closed)');
    }
    const safeLimit = Number.isSafeInteger(limit) && limit > 0 ? Math.min(limit, 50) : 50;

    const countRow = this.#db
      .prepare("SELECT COUNT(*) AS total FROM outbox WHERE status = 'FAILED_TERMINAL';")
      .get();
    const count = countRow ? Number(countRow.total) : 0;

    const rows = this.#db
      .prepare(`
        SELECT command_id, platform, account_id, recipient, created_at, updated_at, terminal_reason_code
        FROM outbox
        WHERE status = 'FAILED_TERMINAL'
        ORDER BY updated_at DESC, command_id ASC
        LIMIT ?;
      `)
      .all(safeLimit);

    return {
      count,
      summaries: rows || [],
    };
  }

  /**
   * Retrieves single outbox command by command_id.
   *
   * @param {string} commandId
   * @returns {object|null}
   */
  getOutboxCommand(commandId) {
    if (!this.#isOpen || !this.#db) {
      throw new Error('Repository is closed (fail-closed)');
    }
    const cId = validateMessageId(commandId);
    const stmt = this.#db.prepare('SELECT * FROM outbox WHERE command_id = ?;');
    const row = stmt.get(cId);
    return row || null;
  }

  /**
   * Retrieves single outbox command by client_request_id.
   *
   * @param {string} clientRequestId
   * @returns {object|null}
   */
  getOutboxCommandByClientRequestId(clientRequestId) {
    if (!this.#isOpen || !this.#db) {
      throw new Error('Repository is closed (fail-closed)');
    }
    const cReqId = validateClientRequestId(clientRequestId);
    const stmt = this.#db.prepare('SELECT * FROM outbox WHERE client_request_id = ?;');
    const row = stmt.get(cReqId);
    return row || null;
  }

  /**
   * Atomically claims next due QUEUED command for worker delivery attempt.
   * Transitions QUEUED -> IN_FLIGHT, increments attempt_count.
   *
   * @param {number} [nowSec]
   * @returns {object|null}
   */
  claimNextQueuedOutboxCommand(nowSec = Math.floor(Date.now() / 1000)) {
    if (!this.#isOpen || !this.#db) {
      throw new Error('Repository is closed (fail-closed)');
    }
    this.#db.exec('BEGIN IMMEDIATE;');
    try {
      // Defense 2: Atomic pre-claim defense: expire stale Telegram QUEUED rows (D-R3-C1 / §20)
      const expireStmt = this.#db.prepare(`
        UPDATE outbox
        SET status = 'FAILED_TERMINAL',
            terminal_reason_code = 'TELEGRAM_DELIVERY_WINDOW_EXCEEDED',
            next_attempt_at = NULL,
            updated_at = ?
        WHERE lower(platform) = 'telegram'
          AND status = 'QUEUED'
          AND ? > created_at + 86400;
      `);
      expireStmt.run(nowSec, nowSec);

      const selectStmt = this.#db.prepare(`
        SELECT * FROM outbox
        WHERE status = 'QUEUED' AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
        ORDER BY created_at ASC
        LIMIT 1;
      `);
      const row = selectStmt.get(nowSec);
      if (!row) {
        this.#db.exec('COMMIT;');
        return null;
      }

      const nextAttemptCount = row.attempt_count + 1;
      const updateStmt = this.#db.prepare(`
        UPDATE outbox
        SET status = 'IN_FLIGHT', attempt_count = ?, updated_at = ?
        WHERE command_id = ? AND status = 'QUEUED';
      `);
      const updateRes = updateStmt.run(nextAttemptCount, nowSec, row.command_id);
      if (updateRes.changes !== 1) {
        this.#db.exec('ROLLBACK;');
        return null;
      }

      this.#db.exec('COMMIT;');
      return {
        ...row,
        status: 'IN_FLIGHT',
        attempt_count: nextAttemptCount,
        updated_at: nowSec,
      };
    } catch (err) {
      try {
        this.#db.exec('ROLLBACK;');
      } catch (_) {}
      throw err;
    }
  }

  /**
   * Updates outbox command status and retry schedule after delivery attempt.
   * Post-attempt updates never create, rotate, or update external retry credentials (ADR-0025 R2).
   *
   * @param {string} commandId
   * @param {object} updateData
   * @param {string} updateData.status
   * @param {number|null} [updateData.nextAttemptAt]
   * @param {number} [updateData.nowSec]
   */
  updateOutboxCommandResult(commandId, updateData) {
    if (!this.#isOpen || !this.#db) {
      throw new Error('Repository is closed (fail-closed)');
    }
    const cId = validateMessageId(commandId);
    const status = updateData.status;
    const nextAttemptAt = updateData.nextAttemptAt !== undefined ? updateData.nextAttemptAt : null;
    const nowSec = updateData.nowSec !== undefined ? updateData.nowSec : Math.floor(Date.now() / 1000);

    let terminalReasonCode = null;
    if (status === 'FAILED_TERMINAL') {
      terminalReasonCode = validateTerminalReasonCode(updateData.terminalReasonCode);
    } else {
      if (updateData.terminalReasonCode !== undefined && updateData.terminalReasonCode !== null) {
        throw new Error(
          `terminalReasonCode must be null for non-terminal status '${status}' (fail-closed)`
        );
      }
    }

    this.#db.exec('BEGIN IMMEDIATE;');
    try {
      const updateStmt = this.#db.prepare(`
        UPDATE outbox
        SET status = ?,
            next_attempt_at = ?,
            terminal_reason_code = ?,
            updated_at = ?
        WHERE command_id = ?;
      `);
      updateStmt.run(status, nextAttemptAt, terminalReasonCode, nowSec, cId);
      this.#db.exec('COMMIT;');
    } catch (err) {
      try {
        this.#db.exec('ROLLBACK;');
      } catch (_) {}
      throw err;
    }
  }

  /**
   * Recovers in-flight commands on startup (ADR-0025 Section 5, Section 18).
   * Never unconditional reset IN_FLIGHT -> QUEUED.
   * Telegram or un-idempotent endpoints become UNCERTAIN.
   *
   * @param {number} [nowSec]
   * @returns {{ requeuedCount: number, uncertainCount: number, total: number }}
   */
  recoverInFlightCommands(nowSec = Math.floor(Date.now() / 1000)) {
    if (!this.#isOpen || !this.#db) {
      throw new Error('Repository is closed (fail-closed)');
    }
    this.#db.exec('BEGIN IMMEDIATE;');
    try {
      const selectStmt = this.#db.prepare(`
        SELECT command_id, platform, endpoint_operation, external_retry_key, external_retry_expires_at
        FROM outbox
        WHERE status = 'IN_FLIGHT';
      `);
      const rows = selectStmt.all();
      let requeuedCount = 0;
      let uncertainCount = 0;

      for (const row of rows) {
        const recovery = evaluateStartupRecovery(
          {
            status: 'IN_FLIGHT',
            platform: row.platform,
            endpoint_operation: row.endpoint_operation,
            external_retry_key: row.external_retry_key,
            external_retry_expires_at: row.external_retry_expires_at,
          },
          { nowSec }
        );

        const updateStmt = this.#db.prepare(`
          UPDATE outbox SET status = ?, updated_at = ? WHERE command_id = ?;
        `);
        updateStmt.run(recovery.target_status, nowSec, row.command_id);

        if (recovery.target_status === 'QUEUED') {
          requeuedCount++;
        } else {
          uncertainCount++;
        }
      }

      this.#db.exec('COMMIT;');
      return { requeuedCount, uncertainCount, total: rows.length };
    } catch (err) {
      try {
        this.#db.exec('ROLLBACK;');
      } catch (_) {}
      throw err;
    }
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
  INGEST_CURSOR_V3_SCHEMA_SQL,
  INBOUND_EVENT_SCHEMA_SQL,
  OUTBOX_SCHEMA_SQL,
  OUTBOX_V6_SCHEMA_SQL,
  computeCanonicalPayloadHash,
  normalizeCanonicalSchemaSql,
  validatePlatformEventId,
  compareCanonicalDecimals,
  validateTerminalReasonCode,
  isValidTerminalReasonCode,
  FIXED_TERMINAL_REASONS,
};
