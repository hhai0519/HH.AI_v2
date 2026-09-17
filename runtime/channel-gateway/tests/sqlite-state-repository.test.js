/**
 * runtime/channel-gateway/tests/sqlite-state-repository.test.js
 *
 * Unit tests for Channel Gateway SQLite Authoritative State Repository (ADR-0023 / E-03 T6).
 * Uses synthetic os.tmpdir fixtures only; cleanup in try/finally blocks.
 * Zero external dependencies; zero skips on Windows and Linux.
 */

'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const { DatabaseSync } = require('node:sqlite');

const {
  SqliteStateRepository,
  SQLITE_STATE_SCHEMA_VERSION,
  SQLite_STATE_SCHEMA_VERSION,
  SQLITE_BUSY_TIMEOUT_MS,
  SQLITE_DATABASE_FILENAME,
} = require('../core/sqlite-state-repository');

function createTempHarness() {
  const baseDir = fs.mkdtempSync(path.join(os.tmpdir(), 'hhai-sqlite-test-'));
  const stateRoot = path.join(baseDir, 'state');
  fs.mkdirSync(stateRoot, { recursive: true });

  function cleanup() {
    try {
      fs.rmSync(baseDir, { recursive: true, force: true });
    } catch {
      // ignore cleanup errors
    }
  }

  return {
    baseDir,
    stateRoot,
    cleanup,
  };
}

// 1. constants contract: schema version 1, busy timeout 5000, fixed filename
test('SqliteStateRepository - 1. constants contract matches specification', () => {
  assert.strictEqual(SQLITE_STATE_SCHEMA_VERSION, 1);
  assert.strictEqual(SQLite_STATE_SCHEMA_VERSION, 1);
  assert.strictEqual(SQLITE_BUSY_TIMEOUT_MS, 5000);
  assert.strictEqual(SQLITE_DATABASE_FILENAME, 'channel-gateway-state.sqlite3');
});

// 2. non-string stateRoot rejected
test('SqliteStateRepository - 2. non-string stateRoot rejected', () => {
  assert.throws(() => new SqliteStateRepository(null), TypeError);
  assert.throws(() => new SqliteStateRepository(undefined), TypeError);
  assert.throws(() => new SqliteStateRepository(12345), TypeError);
  assert.throws(() => new SqliteStateRepository({}), TypeError);
  assert.throws(() => new SqliteStateRepository([]), TypeError);
  assert.throws(() => new SqliteStateRepository(true), TypeError);
});

// 3. empty stateRoot rejected
test('SqliteStateRepository - 3. empty stateRoot rejected', () => {
  assert.throws(() => new SqliteStateRepository(''), /non-empty/);
  assert.throws(() => new SqliteStateRepository('   '), /non-empty/);
  assert.throws(() => new SqliteStateRepository('\t\n'), /non-empty/);
});

// 4. relative stateRoot rejected
test('SqliteStateRepository - 4. relative stateRoot rejected', () => {
  assert.throws(() => new SqliteStateRepository('relative/state/dir'), /absolute path/);
  assert.throws(() => new SqliteStateRepository('./relative'), /absolute path/);
  assert.throws(() => new SqliteStateRepository('../relative'), /absolute path/);
});

// 5. missing stateRoot rejected; does not auto mkdir
test('SqliteStateRepository - 5. missing stateRoot rejected and does not auto mkdir', () => {
  const harness = createTempHarness();
  try {
    const missingDir = path.join(harness.baseDir, 'nonexistent-state-root');
    assert.strictEqual(fs.existsSync(missingDir), false);

    assert.throws(
      () => new SqliteStateRepository(missingDir),
      /does not exist or cannot be accessed/
    );

    assert.strictEqual(fs.existsSync(missingDir), false, 'Must not auto-create directory');
  } finally {
    harness.cleanup();
  }
});

// 6. stateRoot regular-file rejected
test('SqliteStateRepository - 6. stateRoot pointing to regular file rejected', () => {
  const harness = createTempHarness();
  try {
    const regularFile = path.join(harness.baseDir, 'state-file.txt');
    fs.writeFileSync(regularFile, 'not a directory', 'utf8');

    assert.throws(
      () => new SqliteStateRepository(regularFile),
      /must be a directory/
    );
  } finally {
    harness.cleanup();
  }
});

// 7. new repository creates: channel-gateway-state.sqlite3
test('SqliteStateRepository - 7. new repository creates channel-gateway-state.sqlite3', () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    const expectedDbPath = path.join(fs.realpathSync(harness.stateRoot), SQLITE_DATABASE_FILENAME);

    assert.strictEqual(repo.databasePath, expectedDbPath);
    assert.strictEqual(fs.existsSync(expectedDbPath), true);
    assert.strictEqual(repo.isOpen, true);
    repo.close();
  } finally {
    harness.cleanup();
  }
});

// 8. new repository PRAGMA readback: wal / 2 / 1 / 5000
test('SqliteStateRepository - 8. new repository PRAGMA readback matches wal / 2 / 1 / 5000', () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    const dbPath = repo.databasePath;
    repo.close();

    // Verify raw DB settings directly with DatabaseSync
    const rawDb = new DatabaseSync(dbPath);
    try {
      const jRow = rawDb.prepare('PRAGMA journal_mode;').get();
      const sRow = rawDb.prepare('PRAGMA synchronous;').get();
      const fkRow = rawDb.prepare('PRAGMA foreign_keys;').get();

      const journalMode = jRow.journal_mode ?? Object.values(jRow)[0];
      const synchronous = sRow.synchronous ?? Object.values(sRow)[0];
      const foreignKeys = fkRow.foreign_keys ?? Object.values(fkRow)[0];

      assert.strictEqual(journalMode, 'wal');
      assert.strictEqual(synchronous, 2);
      assert.strictEqual(foreignKeys, 1);
    } finally {
      rawDb.close();
    }
  } finally {
    harness.cleanup();
  }
});

// 9. new repository schema_migrations exists and exactly contains [1]
test('SqliteStateRepository - 9. new repository schema_migrations exists and contains [1]', () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    assert.strictEqual(repo.schemaVersion, 1);
    const dbPath = repo.databasePath;
    repo.close();

    const rawDb = new DatabaseSync(dbPath);
    try {
      const tableRow = rawDb.prepare(
        "SELECT name FROM sqlite_schema WHERE type = 'table' AND name = 'schema_migrations';"
      ).get();
      assert.ok(tableRow, 'schema_migrations table must exist');

      const rows = rawDb.prepare('SELECT version FROM schema_migrations ORDER BY version ASC;').all();
      assert.strictEqual(rows.length, 1);
      assert.strictEqual(rows[0].version, 1);
    } finally {
      rawDb.close();
    }
  } finally {
    harness.cleanup();
  }
});

// 10. close works
test('SqliteStateRepository - 10. close works and transitions isOpen to false', () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    assert.strictEqual(repo.isOpen, true);

    repo.close();
    assert.strictEqual(repo.isOpen, false);

    assert.throws(() => repo.schemaVersion, /closed/);
  } finally {
    harness.cleanup();
  }
});

// 11. idempotent close
test('SqliteStateRepository - 11. idempotent close safe on repeated calls', () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    repo.close();
    assert.strictEqual(repo.isOpen, false);

    // Repeated close calls must not throw
    assert.doesNotThrow(() => repo.close());
    assert.doesNotThrow(() => repo.close());
    assert.strictEqual(repo.isOpen, false);
  } finally {
    harness.cleanup();
  }
});

// 12. reopen existing valid DB succeeds
test('SqliteStateRepository - 12. reopen existing valid DB succeeds', () => {
  const harness = createTempHarness();
  try {
    const repo1 = new SqliteStateRepository(harness.stateRoot);
    assert.strictEqual(repo1.isOpen, true);
    repo1.close();

    const repo2 = new SqliteStateRepository(harness.stateRoot);
    assert.strictEqual(repo2.isOpen, true);
    repo2.close();
  } finally {
    harness.cleanup();
  }
});

// 13. reopen preserves schema version 1
test('SqliteStateRepository - 13. reopen preserves schema version 1', () => {
  const harness = createTempHarness();
  try {
    const repo1 = new SqliteStateRepository(harness.stateRoot);
    assert.strictEqual(repo1.schemaVersion, 1);
    repo1.close();

    const repo2 = SqliteStateRepository.open(harness.stateRoot);
    assert.strictEqual(repo2.schemaVersion, 1);
    repo2.close();
  } finally {
    harness.cleanup();
  }
});

// 14. existing SQLite DB without schema_migrations rejected fail-closed
test('SqliteStateRepository - 14. existing SQLite DB without schema_migrations rejected fail-closed', () => {
  const harness = createTempHarness();
  try {
    const dbPath = path.join(harness.stateRoot, SQLITE_DATABASE_FILENAME);
    const rawDb = new DatabaseSync(dbPath);
    rawDb.exec('CREATE TABLE some_random_table (id INTEGER PRIMARY KEY);');
    rawDb.close();

    assert.throws(
      () => new SqliteStateRepository(harness.stateRoot),
      /schema_migrations/
    );
  } finally {
    harness.cleanup();
  }
});

// 15. future schema version 2 rejected
test('SqliteStateRepository - 15. future schema version 2 rejected fail-closed', () => {
  const harness = createTempHarness();
  try {
    const dbPath = path.join(harness.stateRoot, SQLITE_DATABASE_FILENAME);
    const rawDb = new DatabaseSync(dbPath);
    rawDb.exec('CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY) STRICT;');
    rawDb.prepare('INSERT INTO schema_migrations (version) VALUES (1);').run();
    rawDb.prepare('INSERT INTO schema_migrations (version) VALUES (2);').run();
    rawDb.close();

    assert.throws(
      () => new SqliteStateRepository(harness.stateRoot),
      /Future schema version detected/
    );
  } finally {
    harness.cleanup();
  }
});

// 16. invalid/non-sequential migration state rejected
test('SqliteStateRepository - 16. invalid or non-sequential migration state rejected', () => {
  const harness = createTempHarness();
  try {
    const dbPath = path.join(harness.stateRoot, SQLITE_DATABASE_FILENAME);

    // Subtest A: empty schema_migrations table
    {
      const rawDb = new DatabaseSync(dbPath);
      rawDb.exec('CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY) STRICT;');
      rawDb.close();

      assert.throws(
        () => new SqliteStateRepository(harness.stateRoot),
        /empty/
      );
      fs.unlinkSync(dbPath);
    }

    // Subtest B: version is 0 or negative
    {
      const rawDb = new DatabaseSync(dbPath);
      rawDb.exec('CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY) STRICT;');
      rawDb.prepare('INSERT INTO schema_migrations (version) VALUES (-1);').run();
      rawDb.close();

      assert.throws(
        () => new SqliteStateRepository(harness.stateRoot),
        /Invalid schema version/
      );
      fs.unlinkSync(dbPath);
    }

    // Subtest C: gap in version (e.g. starts at 3)
    {
      const rawDb = new DatabaseSync(dbPath);
      rawDb.exec('CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY) STRICT;');
      rawDb.prepare('INSERT INTO schema_migrations (version) VALUES (3);').run();
      rawDb.close();

      assert.throws(
        () => new SqliteStateRepository(harness.stateRoot),
        /Future schema version|Invalid migration sequence/
      );
      fs.unlinkSync(dbPath);
    }
  } finally {
    harness.cleanup();
  }
});

// 17. repository exposes no raw DB escape hatch
test('SqliteStateRepository - 17. repository exposes no raw DB escape hatch', () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);

    assert.strictEqual(repo.db, undefined);
    assert.strictEqual(repo._db, undefined);
    assert.strictEqual(repo.rawDb, undefined);
    assert.strictEqual(repo.exec, undefined);
    assert.strictEqual(repo.query, undefined);
    assert.strictEqual(repo.prepare, undefined);
    assert.strictEqual(repo.statement, undefined);
    assert.strictEqual(repo.connection, undefined);

    const ownProps = Object.getOwnPropertyNames(repo);
    assert.ok(!ownProps.includes('db'));
    assert.ok(!ownProps.includes('_db'));
    assert.ok(!ownProps.includes('rawDb'));

    repo.close();
  } finally {
    harness.cleanup();
  }
});

// 18. extension loading not enabled
test('SqliteStateRepository - 18. extension loading not enabled', () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);

    assert.strictEqual(repo.loadExtension, undefined);
    assert.strictEqual(repo.enableLoadExtension, undefined);

    // Verify underlying Node DatabaseSync prevents extension loading
    const rawDb = new DatabaseSync(':memory:');
    try {
      assert.throws(() => rawDb.loadExtension('dummy'), /extension loading is not allowed/);
    } finally {
      rawDb.close();
    }

    repo.close();
  } finally {
    harness.cleanup();
  }
});

// 19. database remains usable across: open -> close -> reopen
test('SqliteStateRepository - 19. database remains usable across open -> close -> reopen', () => {
  const harness = createTempHarness();
  try {
    const repo1 = new SqliteStateRepository(harness.stateRoot);
    assert.strictEqual(repo1.isOpen, true);
    assert.strictEqual(repo1.schemaVersion, 1);
    repo1.close();
    assert.strictEqual(repo1.isOpen, false);

    const repo2 = new SqliteStateRepository(harness.stateRoot);
    assert.strictEqual(repo2.isOpen, true);
    assert.strictEqual(repo2.schemaVersion, 1);
    repo2.close();
    assert.strictEqual(repo2.isOpen, false);

    const repo3 = SqliteStateRepository.open(harness.stateRoot);
    assert.strictEqual(repo3.isOpen, true);
    assert.strictEqual(repo3.schemaVersion, 1);
    repo3.close();
    assert.strictEqual(repo3.isOpen, false);
  } finally {
    harness.cleanup();
  }
});

// 20. no domain tables created
test('SqliteStateRepository - 20. no domain tables created in database', () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    const dbPath = repo.databasePath;
    repo.close();

    const rawDb = new DatabaseSync(dbPath);
    try {
      const tables = rawDb.prepare(
        "SELECT name FROM sqlite_schema WHERE type = 'table' AND name NOT LIKE 'sqlite_%';"
      ).all();

      assert.strictEqual(tables.length, 1);
      assert.strictEqual(tables[0].name, 'schema_migrations');

      // Explicit check that domain tables do not exist
      const forbiddenTables = ['messages', 'channels', 'accounts', 'cursors', 'outbox', 'inbox', 'payload'];
      for (const tName of forbiddenTables) {
        const found = rawDb.prepare(
          "SELECT name FROM sqlite_schema WHERE type = 'table' AND name = ?;"
        ).get(tName);
        assert.strictEqual(found, undefined, `Forbidden table '${tName}' must not exist`);
      }
    } finally {
      rawDb.close();
    }
  } finally {
    harness.cleanup();
  }
});

// 21. failed open/init does not return usable repository
test('SqliteStateRepository - 21. failed open/init does not return usable repository', () => {
  const harness = createTempHarness();
  try {
    let repoInstance = null;
    assert.throws(() => {
      repoInstance = new SqliteStateRepository(path.join(harness.baseDir, 'nonexistent'));
    });
    assert.strictEqual(repoInstance, null);

    // Also verify when DB file is an invalid existing file
    const dbPath = path.join(harness.stateRoot, SQLITE_DATABASE_FILENAME);
    fs.writeFileSync(dbPath, 'CORRUPT_NON_SQLITE_DATA');
    assert.throws(() => {
      repoInstance = new SqliteStateRepository(harness.stateRoot);
    });
    assert.strictEqual(repoInstance, null);
  } finally {
    harness.cleanup();
  }
});

// 22. all SQL value paths parameterized
test('SqliteStateRepository - 22. all SQL value paths parameterized and no dynamic concatenation', () => {
  const moduleSource = fs.readFileSync(
    path.join(__dirname, '../core/sqlite-state-repository.js'),
    'utf8'
  );

  // Check that no string interpolation occurs with caller values into SQL
  // Allow static PRAGMA busy_timeout = ${SQLITE_BUSY_TIMEOUT_MS} which is a constant integer
  const forbiddenPatterns = [
    /db\.exec\(\s*`[^`]*\$\{[^S][^Q][^L][^I][^T][^E]/,
    /db\.prepare\(\s*`[^`]*\$\{/,
    /["']\s*\+\s*[a-zA-Z0-9_.]+\s*\+\s*["']/,
  ];

  for (const pattern of forbiddenPatterns) {
    assert.strictEqual(
      pattern.test(moduleSource),
      false,
      `Source code must not contain dynamic string concatenation in SQL queries: pattern ${pattern}`
    );
  }

  // Ensure parameter placeholder (?) is used for value insertions
  assert.ok(
    moduleSource.includes('INSERT INTO schema_migrations (version) VALUES (?)'),
    'Must use parameterized placeholder for migration insertion'
  );
});

// 23. Path boundary: DB file as directory rejected
test('SqliteStateRepository - 23. DB file existing as directory is rejected', () => {
  const harness = createTempHarness();
  try {
    const dbDir = path.join(harness.stateRoot, SQLITE_DATABASE_FILENAME);
    fs.mkdirSync(dbDir);

    assert.throws(
      () => new SqliteStateRepository(harness.stateRoot),
      /must be a regular file/
    );
  } finally {
    harness.cleanup();
  }
});
