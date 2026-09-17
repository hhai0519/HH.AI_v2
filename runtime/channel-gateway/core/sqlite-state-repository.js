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
 * - Existing DB file validation: must be a regular file, non-symlink, resolving inside canonical stateRoot.
 * - Extension loading strictly disabled (no allowExtension, no loadExtension).
 * - Mandatory PRAGMAs on every open:
 *     PRAGMA journal_mode = WAL; (readback 'wal')
 *     PRAGMA synchronous = FULL; (readback 2)
 *     PRAGMA foreign_keys = ON; (readback 1)
 *     PRAGMA busy_timeout = 5000; (readback 5000)
 *   Any readback mismatch triggers fail-closed error and immediate close.
 * - Schema versioning: schema_migrations (version INTEGER PRIMARY KEY) STRICT.
 * - New DB initialization: transactional (BEGIN IMMEDIATE ... COMMIT), inserts version 1.
 * - Existing DB handling: missing schema_migrations, gap, non-integer, <=0, duplicate, or future version > 1 fails closed.
 * - No domain tables or columns in T6 foundation.
 * - SQL safety: parameterized prepared statements for any valued queries; no dynamic SQL string concatenation.
 * - No raw DatabaseSync handle escape hatch (no rawDb, exec, query exports).
 * - Idempotent close() lifecycle; unusable after close.
 */

'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { DatabaseSync } = require('node:sqlite');
const { isAbsolutePath } = require('./data-location-config');

const SQLITE_STATE_SCHEMA_VERSION = 1;
const SQLITE_BUSY_TIMEOUT_MS = 5000;
const SQLITE_DATABASE_FILENAME = 'channel-gateway-state.sqlite3';

class SqliteStateRepository {
  /** @type {DatabaseSync|null} */
  #db = null;

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

    this._canonicalStateRoot = fs.realpathSync(nominal);
    this._databasePath = path.join(this._canonicalStateRoot, SQLITE_DATABASE_FILENAME);

    const isNew = !fs.existsSync(this._databasePath);

    if (!isNew) {
      let lstat;
      try {
        lstat = fs.lstatSync(this._databasePath);
      } catch (err) {
        throw new Error(
          `Failed to stat database file: '${this._databasePath}' (${err.message})`
        );
      }

      if (lstat.isSymbolicLink()) {
        throw new Error(
          `Database file must not be a symbolic link: '${this._databasePath}'`
        );
      }

      if (!lstat.isFile()) {
        throw new Error(
          `Database file must be a regular file: '${this._databasePath}'`
        );
      }

      let canonicalDb;
      try {
        canonicalDb = fs.realpathSync(this._databasePath);
      } catch (err) {
        throw new Error(
          `Failed to resolve canonical path for database file: '${this._databasePath}' (${err.message})`
        );
      }

      const rel = path.relative(this._canonicalStateRoot, canonicalDb);
      if (rel === '..' || rel.startsWith('..' + path.sep) || path.isAbsolute(rel)) {
        throw new Error(
          `Database file resolves outside canonical state root: '${canonicalDb}' is not within '${this._canonicalStateRoot}'`
        );
      }
    }

    let db;
    try {
      db = new DatabaseSync(this._databasePath, {
        timeout: SQLITE_BUSY_TIMEOUT_MS,
        enableForeignKeyConstraints: true,
      });
    } catch (err) {
      throw new Error(`Failed to open SQLite database at '${this._databasePath}': ${err.message}`);
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

      // 3. Schema initialization or verification
      if (isNew) {
        db.exec('BEGIN IMMEDIATE;');
        try {
          db.exec('CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY) STRICT;');
          const insertStmt = db.prepare('INSERT INTO schema_migrations (version) VALUES (?);');
          insertStmt.run(SQLITE_STATE_SCHEMA_VERSION);
          db.exec('COMMIT;');
        } catch (initErr) {
          try {
            db.exec('ROLLBACK;');
          } catch (_) {}
          throw initErr;
        }
      } else {
        const tableCheck = db.prepare(
          "SELECT name FROM sqlite_schema WHERE type = 'table' AND name = 'schema_migrations';"
        ).get();
        if (!tableCheck) {
          throw new Error('Existing database is missing schema_migrations table (fail-closed)');
        }
      }

      // 4. Verify schema state and read back version
      this._schemaVersion = this._readAndVerifySchemaVersion(db);

      this.#db = db;
      this._isOpen = true;
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
   * Reads and strictly validates schema_migrations records.
   *
   * @private
   * @param {DatabaseSync} db
   * @returns {number} The current validated schema version
   */
  _readAndVerifySchemaVersion(db) {
    const tableCheck = db.prepare(
      "SELECT name FROM sqlite_schema WHERE type = 'table' AND name = 'schema_migrations';"
    ).get();
    if (!tableCheck) {
      throw new Error('Database is missing schema_migrations table (fail-closed)');
    }

    const nonInternalTables = db.prepare(
      "SELECT name FROM sqlite_schema WHERE type = 'table' AND name NOT LIKE 'sqlite_%';"
    ).all();
    for (const t of nonInternalTables) {
      if (t.name !== 'schema_migrations') {
        throw new Error(`Unexpected table in schema: '${t.name}' (no domain tables allowed in T6)`);
      }
    }

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

    if (versions.some((v) => v > SQLITE_STATE_SCHEMA_VERSION)) {
      throw new Error(
        `Future schema version detected: [${versions.join(', ')}] exceeds supported version ${SQLITE_STATE_SCHEMA_VERSION} (fail-closed)`
      );
    }

    if (versions.length !== 1 || versions[0] !== SQLITE_STATE_SCHEMA_VERSION) {
      throw new Error(
        `Invalid migration sequence: received [${versions.join(', ')}], expected [${SQLITE_STATE_SCHEMA_VERSION}] (fail-closed)`
      );
    }

    return versions[versions.length - 1];
  }

  /**
   * Canonical database file path.
   *
   * @returns {string}
   */
  get databasePath() {
    return this._databasePath;
  }

  /**
   * Validated schema version read from database state.
   *
   * @returns {number}
   */
  get schemaVersion() {
    if (!this._isOpen) {
      throw new Error('Repository is closed');
    }
    return this._schemaVersion;
  }

  /**
   * Whether the repository connection is currently open.
   *
   * @returns {boolean}
   */
  get isOpen() {
    return Boolean(this._isOpen);
  }

  /**
   * Closes the repository and underlying database connection.
   * Idempotent: safe to call multiple times.
   */
  close() {
    if (!this._isOpen) {
      return;
    }
    this._isOpen = false;
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
