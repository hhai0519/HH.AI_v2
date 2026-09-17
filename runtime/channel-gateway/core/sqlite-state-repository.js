/**
 * runtime/channel-gateway/core/sqlite-state-repository.js
 *
 * ADR-0023 / E-03 T6: Channel Gateway SQLite Authoritative State Repository & Schema Foundation.
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
 *     - Gap, non-integer, <=0, duplicate, or future version > 1 fails closed.
 * - No domain tables or columns in T6 foundation.
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

const SQLITE_STATE_SCHEMA_VERSION = 1;
const SQLITE_BUSY_TIMEOUT_MS = 5000;
const SQLITE_DATABASE_FILENAME = 'channel-gateway-state.sqlite3';

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

      // Unified runner path: applies pending migrations (currentVersion < v <= targetVersion)
      // for both new and existing databases through the same forward runner.
      runPendingMigrations(db, currentVersion, SQLITE_STATE_SCHEMA_VERSION);

      // 4. Verify canonical table shape (STRICT, single integer PK column)
      verifyCanonicalSchemaMigrationsShape(db);

      // 5. Verify no domain tables exist (T6 foundation boundary)
      const nonInternalTables = db.prepare(
        "SELECT name FROM sqlite_schema WHERE type = 'table' AND name NOT LIKE 'sqlite_%';"
      ).all();
      for (const t of nonInternalTables) {
        if (t.name !== 'schema_migrations') {
          throw new Error(`Unexpected table in schema: '${t.name}' (no domain tables allowed in T6)`);
        }
      }

      // 6. Verify final applied version state matches target schema version
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

    // 1. Pre-backup source baseline capture
    verifyCanonicalSchemaMigrationsShape(this.#db);

    const sourceVersionsBefore = Array.from(readAppliedMigrationVersions(this.#db));
    if (sourceVersionsBefore.length === 0) {
      throw new Error('Source schema_migrations is empty (fail-closed)');
    }

    const latestSourceVersion = sourceVersionsBefore[sourceVersionsBefore.length - 1];
    if (latestSourceVersion !== this.#schemaVersion) {
      throw new Error(
        `Source schema version drift detected (fail-closed): database state has latest version ${latestSourceVersion} but repository was opened at version ${this.#schemaVersion}`
      );
    }

    const sourceTablesBefore = Array.from(getCanonicalUserTableNames(this.#db));
    const sourceDataVersionBefore = getDataVersion(this.#db);

    // 2. Generate safe internal backup filename
    const uniqueId = crypto.randomUUID();
    const backupFilename = `channel-gateway-state.backup-v${this.#schemaVersion}-${uniqueId}.sqlite3`;
    const backupDestination = path.join(this.#canonicalStateRoot, backupFilename);

    // 3. Pre-execution path confinement check
    const nominalRel = path.relative(this.#canonicalStateRoot, backupDestination);
    if (nominalRel === '..' || nominalRel.startsWith('..' + path.sep) || path.isAbsolute(nominalRel)) {
      throw new Error(
        `Backup destination path escapes canonical state root: '${backupDestination}' is outside '${this.#canonicalStateRoot}'`
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
      const vacuumStmt = this.#db.prepare('VACUUM INTO ?;');
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

    const realRel = path.relative(this.#canonicalStateRoot, canonicalBackup);
    if (realRel === '..' || realRel.startsWith('..' + path.sep) || path.isAbsolute(realRel)) {
      throw new Error(
        `Backup file resolves outside canonical state root: '${canonicalBackup}' is not within '${this.#canonicalStateRoot}'`
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
      const sourceVersionsAfter = readAppliedMigrationVersions(this.#db);
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

      const sourceTablesAfter = getCanonicalUserTableNames(this.#db);
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
        const sourceDataVersionAfter = getDataVersion(this.#db);
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
          const rel = path.relative(this.#canonicalStateRoot, real);
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
      sourceSchemaVersion: this.#schemaVersion,
      integrity: 'ok',
    };
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
};
