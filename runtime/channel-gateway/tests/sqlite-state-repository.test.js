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
const crypto = require('node:crypto');
const { DatabaseSync } = require('node:sqlite');

const {
  SqliteStateRepository,
  SQLITE_STATE_SCHEMA_VERSION,
  SQLite_STATE_SCHEMA_VERSION,
  SQLITE_BUSY_TIMEOUT_MS,
  SQLITE_DATABASE_FILENAME,
  CHANNEL_CONTROL_SCHEMA_SQL,
  INBOX_SCHEMA_SQL,
  normalizeCanonicalSchemaSql,
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

// 1. constants contract: schema version 2, busy timeout 5000, fixed filename
test('SqliteStateRepository - 1. constants contract matches specification', () => {
  assert.strictEqual(SQLITE_STATE_SCHEMA_VERSION, 2);
  assert.strictEqual(SQLite_STATE_SCHEMA_VERSION, 2);
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

// 9. new repository schema_migrations exists and exactly contains [1, 2]
test('SqliteStateRepository - 9. new repository schema_migrations exists and contains [1, 2]', () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    assert.strictEqual(repo.schemaVersion, 2);
    const dbPath = repo.databasePath;
    repo.close();

    const rawDb = new DatabaseSync(dbPath);
    try {
      const tableRow = rawDb.prepare(
        "SELECT name FROM sqlite_schema WHERE type = 'table' AND name = 'schema_migrations';"
      ).get();
      assert.ok(tableRow, 'schema_migrations table must exist');

      const rows = rawDb.prepare('SELECT version FROM schema_migrations ORDER BY version ASC;').all();
      assert.strictEqual(rows.length, 2);
      assert.deepStrictEqual(rows.map((r) => r.version), [1, 2]);
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

// 13. reopen preserves schema version 2
test('SqliteStateRepository - 13. reopen preserves schema version 2', () => {
  const harness = createTempHarness();
  try {
    const repo1 = new SqliteStateRepository(harness.stateRoot);
    assert.strictEqual(repo1.schemaVersion, 2);
    repo1.close();

    const repo2 = SqliteStateRepository.open(harness.stateRoot);
    assert.strictEqual(repo2.schemaVersion, 2);
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

// 15. future schema version 3 rejected fail-closed
test('SqliteStateRepository - 15. future schema version 3 rejected fail-closed', () => {
  const harness = createTempHarness();
  try {
    const dbPath = path.join(harness.stateRoot, SQLITE_DATABASE_FILENAME);
    const rawDb = new DatabaseSync(dbPath);
    rawDb.exec('CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY) STRICT;');
    rawDb.prepare('INSERT INTO schema_migrations (version) VALUES (1);').run();
    rawDb.prepare('INSERT INTO schema_migrations (version) VALUES (2);').run();
    rawDb.prepare('INSERT INTO schema_migrations (version) VALUES (3);').run();
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
    assert.strictEqual(repo1.schemaVersion, 2);
    repo1.close();
    assert.strictEqual(repo1.isOpen, false);

    const repo2 = new SqliteStateRepository(harness.stateRoot);
    assert.strictEqual(repo2.isOpen, true);
    assert.strictEqual(repo2.schemaVersion, 2);
    repo2.close();
    assert.strictEqual(repo2.isOpen, false);

    const repo3 = SqliteStateRepository.open(harness.stateRoot);
    assert.strictEqual(repo3.isOpen, true);
    assert.strictEqual(repo3.schemaVersion, 2);
    repo3.close();
    assert.strictEqual(repo3.isOpen, false);
  } finally {
    harness.cleanup();
  }
});

// 20. domain tables created in v2 and forbidden tables absent
test('SqliteStateRepository - 20. domain tables channel_control and inbox created, forbidden tables absent', () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    const dbPath = repo.databasePath;
    repo.close();

    const rawDb = new DatabaseSync(dbPath);
    try {
      const tables = rawDb.prepare(
        "SELECT name FROM sqlite_schema WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name ASC;"
      ).all();

      assert.strictEqual(tables.length, 3);
      assert.deepStrictEqual(tables.map((t) => t.name), ['channel_control', 'inbox', 'schema_migrations']);

      // Explicit check that forbidden tables do not exist
      const forbiddenTables = ['messages', 'channels', 'accounts', 'cursors', 'outbox', 'payload', 'ingest_cursor'];
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

// 24. F1 Regression: Dangling DB symlink rejected and outside target not created
test('SqliteStateRepository - 24. F1: dangling DB symlink rejected without creating outside target', () => {
  const harness = createTempHarness();
  try {
    const linkPath = path.join(harness.stateRoot, SQLITE_DATABASE_FILENAME);
    const outsideTarget = path.join(harness.baseDir, 'outside-target.sqlite3');

    let symlinkCreated = false;
    try {
      fs.symlinkSync(outsideTarget, linkPath, 'file');
      symlinkCreated = true;
    } catch (symErr) {
      // Symlink creation not permitted on this host (e.g. unprivileged Windows)
      symlinkCreated = false;
    }

    if (symlinkCreated) {
      // Host supports symlink creation: run active behavioral regression
      assert.strictEqual(fs.existsSync(outsideTarget), false, 'Outside target must start absent');
      assert.throws(
        () => new SqliteStateRepository(harness.stateRoot),
        /symbolic link/i
      );
      assert.strictEqual(
        fs.existsSync(outsideTarget),
        false,
        'Outside target must remain absent after rejection'
      );
    } else {
      // Host lacks symlink privilege: run non-skip bounded source & semantic canary
      const moduleSource = fs.readFileSync(
        path.join(__dirname, '../core/sqlite-state-repository.js'),
        'utf8'
      );
      assert.strictEqual(
        /existsSync\s*\(\s*this\.\s*#?databasePath\s*\)/.test(moduleSource),
        false,
        'Production source must NOT use existsSync for databasePath classification'
      );
      assert.ok(
        /fs\.lstatSync\s*\(\s*this\.#databasePath\s*\)/.test(moduleSource),
        'Production source must use lstatSync on databasePath'
      );
      assert.ok(
        /code\s*===\s*['"]ENOENT['"]/.test(moduleSource),
        'Production source must check err.code === "ENOENT" for new database classification'
      );
    }
  } finally {
    harness.cleanup();
  }
});

// 25. F2 Regression: Canonical schema_migrations shape validation
test('SqliteStateRepository - 25. F2: non-STRICT schema_migrations rejected', () => {
  const harness = createTempHarness();
  try {
    const dbPath = path.join(harness.stateRoot, SQLITE_DATABASE_FILENAME);
    const rawDb = new DatabaseSync(dbPath);
    // Non-strict table
    rawDb.exec('CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY);');
    rawDb.prepare('INSERT INTO schema_migrations (version) VALUES (1);').run();
    rawDb.close();

    assert.throws(
      () => new SqliteStateRepository(harness.stateRoot),
      /STRICT/i
    );
  } finally {
    harness.cleanup();
  }
});

test('SqliteStateRepository - 26. F2: STRICT schema_migrations without PRIMARY KEY rejected', () => {
  const harness = createTempHarness();
  try {
    const dbPath = path.join(harness.stateRoot, SQLITE_DATABASE_FILENAME);
    const rawDb = new DatabaseSync(dbPath);
    // Strict table without PRIMARY KEY
    rawDb.exec('CREATE TABLE schema_migrations (version INTEGER) STRICT;');
    rawDb.prepare('INSERT INTO schema_migrations (version) VALUES (1);').run();
    rawDb.close();

    assert.throws(
      () => new SqliteStateRepository(harness.stateRoot),
      /PRIMARY KEY/i
    );
  } finally {
    harness.cleanup();
  }
});

test('SqliteStateRepository - 27. F2: STRICT schema_migrations with extra columns rejected', () => {
  const harness = createTempHarness();
  try {
    const dbPath = path.join(harness.stateRoot, SQLITE_DATABASE_FILENAME);
    const rawDb = new DatabaseSync(dbPath);
    // Strict table with extra column
    rawDb.exec('CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, extra TEXT) STRICT;');
    rawDb.prepare('INSERT INTO schema_migrations (version, extra) VALUES (?, ?);').run(1, 'unexpected');
    rawDb.close();

    assert.throws(
      () => new SqliteStateRepository(harness.stateRoot),
      /exactly 1 column/i
    );
  } finally {
    harness.cleanup();
  }
});

test('SqliteStateRepository - 28. F2: canonical STRICT schema_migrations with PK accepted and migrates v1 to v2', () => {
  const harness = createTempHarness();
  try {
    const dbPath = path.join(harness.stateRoot, SQLITE_DATABASE_FILENAME);
    const rawDb = new DatabaseSync(dbPath);
    rawDb.exec('CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY) STRICT;');
    rawDb.prepare('INSERT INTO schema_migrations (version) VALUES (1);').run();
    rawDb.close();

    const repo = new SqliteStateRepository(harness.stateRoot);
    assert.strictEqual(repo.isOpen, true);
    assert.strictEqual(repo.schemaVersion, 2);
    repo.close();

    // Verify pre-migration backup for v1 was created
    const files = fs.readdirSync(harness.stateRoot);
    const v1Backups = files.filter(
      (f) => f.startsWith('channel-gateway-state.backup-v1-') && f.endsWith('.sqlite3')
    );
    assert.strictEqual(v1Backups.length, 1);
  } finally {
    harness.cleanup();
  }
});

// 29. F3 Regression: Forward-only migration foundation
test('SqliteStateRepository - 29. F3: forward-only migration runner and registry invariants', () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    assert.strictEqual(repo.schemaVersion, SQLITE_STATE_SCHEMA_VERSION);

    // Verify repository does NOT expose down migration or reset APIs
    assert.strictEqual(repo.down, undefined);
    assert.strictEqual(repo.rollback, undefined);
    assert.strictEqual(repo.resetSchema, undefined);
    assert.strictEqual(repo.migrateDown, undefined);

    repo.close();
  } finally {
    harness.cleanup();
  }
});

// 30. F4 Regression: Read-only introspection & ECMAScript private fields
test('SqliteStateRepository - 30. F4: mutable lifecycle fields are private and not exposed as own properties', () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    const ownProps = Object.getOwnPropertyNames(repo);

    // Must NOT expose internal mutable properties
    assert.strictEqual(ownProps.includes('_databasePath'), false);
    assert.strictEqual(ownProps.includes('_schemaVersion'), false);
    assert.strictEqual(ownProps.includes('_isOpen'), false);
    assert.strictEqual(ownProps.includes('_canonicalStateRoot'), false);
    assert.strictEqual(ownProps.includes('_db'), false);
    assert.strictEqual(ownProps.length, 0, 'Instance should not have exposed own properties');

    // Assignment to getters must throw or fail without changing state
    assert.throws(
      () => {
        repo.isOpen = false;
      },
      TypeError
    );
    assert.throws(
      () => {
        repo.schemaVersion = 999;
      },
      TypeError
    );
    assert.throws(
      () => {
        repo.databasePath = '/tmp/hijack';
      },
      TypeError
    );

    // Setting expando _isOpen must not affect actual isOpen or close behavior
    repo._isOpen = false;
    assert.strictEqual(repo.isOpen, true, 'Internal isOpen must remain true');
    repo.close();
    assert.strictEqual(repo.isOpen, false, 'close() must successfully close');

    // Closed repository must reject schemaVersion access
    assert.throws(() => repo.schemaVersion, /closed/);
  } finally {
    harness.cleanup();
  }
});

// 31. PRAGMA busy_timeout fail-closed verification
test('SqliteStateRepository - 31. PRAGMA busy_timeout contract verified on open', () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    assert.strictEqual(SQLITE_BUSY_TIMEOUT_MS, 5000);
    assert.strictEqual(repo.isOpen, true);
    repo.close();

    const moduleSource = fs.readFileSync(
      path.join(__dirname, '../core/sqlite-state-repository.js'),
      'utf8'
    );
    assert.ok(
      moduleSource.includes('PRAGMA busy_timeout = 5000;') ||
      moduleSource.includes('PRAGMA busy_timeout = ${SQLITE_BUSY_TIMEOUT_MS};'),
      'Source must configure PRAGMA busy_timeout to 5000'
    );
    assert.ok(
      moduleSource.includes('busyTimeout !== SQLITE_BUSY_TIMEOUT_MS'),
      'Source must fail-closed on busyTimeout readback mismatch'
    );
  } finally {
    harness.cleanup();
  }
});

// 32. F3: Single generic pending migration runner across new and existing paths
test('SqliteStateRepository - 32. F3: unified pending migration runner architecture canary', () => {
  const moduleSource = fs.readFileSync(
    path.join(__dirname, '../core/sqlite-state-repository.js'),
    'utf8'
  );

  // 1. Generic runner function exists
  assert.ok(
    /function\s+runPendingMigrations\s*\(\s*db\s*,\s*currentVersion\s*,\s*targetVersion\s*\)/.test(moduleSource),
    'Production source must declare generic runPendingMigrations(db, currentVersion, targetVersion)'
  );

  // 2. Generic runner is NOT scoped inside if (isNew)
  // Check that runPendingMigrations is called outside of the if (isNew) block
  assert.ok(
    /runPendingMigrations\s*\(\s*db\s*,\s*currentVersion\s*,\s*SQLITE_STATE_SCHEMA_VERSION\s*\)/.test(moduleSource),
    'Production constructor must call runPendingMigrations with currentVersion and SQLITE_STATE_SCHEMA_VERSION'
  );

  // 3. Pending selection semantics: version > currentVersion && version <= targetVersion
  assert.ok(
    /version\s*>\s*currentVersion\s*&&\s*[^.]*version\s*<=\s*targetVersion/.test(moduleSource) ||
    /m\.version\s*>\s*currentVersion\s*&&\s*m\.version\s*<=\s*targetVersion/.test(moduleSource),
    'Pending migration selection must use: version > currentVersion && version <= targetVersion'
  );

  // 4. MIGRATIONS registry contains exactly version 1 and 2, and no version 3
  assert.ok(/version:\s*1\b/.test(moduleSource));
  assert.ok(/version:\s*2\b/.test(moduleSource));
  assert.strictEqual(
    /version:\s*3\b/.test(moduleSource),
    false,
    'Production source must NOT contain migration version 3'
  );
});

// 33. F3: Existing DB passes through generic runner with 0 pending migrations
test('SqliteStateRepository - 33. F3: existing valid DB [1, 2] executes 0 pending migrations and preserves schema', () => {
  const harness = createTempHarness();
  try {
    // First open: creates new DB and applies migration 1 and 2
    const repo1 = new SqliteStateRepository(harness.stateRoot);
    assert.strictEqual(repo1.isOpen, true);
    assert.strictEqual(repo1.schemaVersion, 2);
    repo1.close();

    // Second open: existing DB with currentVersion = 2 runs through runPendingMigrations(db, 2, 2)
    // Pending list is empty, zero migrations run, schema remains canonical and valid
    const repo2 = new SqliteStateRepository(harness.stateRoot);
    assert.strictEqual(repo2.isOpen, true);
    assert.strictEqual(repo2.schemaVersion, 2);
    repo2.close();

    // Verify raw DB has exactly version 1 and 2
    const rawDb = new DatabaseSync(path.join(harness.stateRoot, SQLITE_DATABASE_FILENAME));
    try {
      const rows = rawDb.prepare('SELECT version FROM schema_migrations ORDER BY version ASC;').all();
      assert.strictEqual(rows.length, 2);
      assert.deepStrictEqual(rows.map((r) => r.version), [1, 2]);
    } finally {
      rawDb.close();
    }
  } finally {
    harness.cleanup();
  }
});

// 34. T11A: createVerifiedBackup succeeds on open valid repository and returns canonical metadata
test('SqliteStateRepository - 34. T11A: createVerifiedBackup succeeds and returns canonical metadata', () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    const result = repo.createVerifiedBackup();

    assert.strictEqual(result.success, true);
    assert.strictEqual(typeof result.backupPath, 'string');
    assert.strictEqual(result.sourceSchemaVersion, 2);
    assert.strictEqual(result.integrity, 'ok');

    // Return metadata exposes no raw handles
    assert.strictEqual(result.db, undefined);
    assert.strictEqual(result.rawDb, undefined);
    assert.strictEqual(result._db, undefined);

    repo.close();
  } finally {
    harness.cleanup();
  }
});

// 35. T11A: backup path confinement, naming pattern, and filesystem attributes
test('SqliteStateRepository - 35. T11A: backup path confinement, safe naming, and regular file attributes', () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    const result = repo.createVerifiedBackup();

    // 1. Backup path is distinct from source path
    assert.notStrictEqual(result.backupPath, repo.databasePath);

    // 2. Confined within canonical stateRoot
    const canonicalRoot = fs.realpathSync(harness.stateRoot);
    const rel = path.relative(canonicalRoot, result.backupPath);
    assert.strictEqual(rel.startsWith('..'), false);
    assert.strictEqual(path.isAbsolute(rel), false);

    // 3. Filename matches safe pattern
    const basename = path.basename(result.backupPath);
    const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
    const match = basename.match(/^channel-gateway-state\.backup-v2-([0-9a-f-]+)\.sqlite3$/);
    assert.ok(match, `Backup filename '${basename}' must match pattern channel-gateway-state.backup-v2-<uuid>.sqlite3`);
    assert.ok(uuidPattern.test(match[1]), `UUID segment '${match[1]}' must be valid UUID`);

    // 4. File attributes: regular file, non-symlink
    const stat = fs.lstatSync(result.backupPath);
    assert.strictEqual(stat.isFile(), true);
    assert.strictEqual(stat.isSymbolicLink(), false);

    repo.close();
  } finally {
    harness.cleanup();
  }
});

// 36. T11A: source repository lifecycle unchanged after backup
test('SqliteStateRepository - 36. T11A: source repository remains open, schema version unchanged, usable after backup', () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    const backupResult = repo.createVerifiedBackup();
    assert.strictEqual(backupResult.success, true);

    // Source remains open
    assert.strictEqual(repo.isOpen, true);
    assert.strictEqual(repo.schemaVersion, 2);
    assert.strictEqual(repo.databasePath, path.join(fs.realpathSync(harness.stateRoot), SQLITE_DATABASE_FILENAME));

    // Source migration history unchanged [1, 2]
    const rawDb = new DatabaseSync(repo.databasePath, { readOnly: true });
    try {
      const rows = rawDb.prepare('SELECT version FROM schema_migrations ORDER BY version ASC;').all();
      assert.strictEqual(rows.length, 2);
      assert.deepStrictEqual(rows.map((r) => r.version), [1, 2]);
    } finally {
      rawDb.close();
    }

    repo.close();
    assert.strictEqual(repo.isOpen, false);
  } finally {
    harness.cleanup();
  }
});

// 37. T11A: backup database read-only verification: integrity_check, schema shape, migration history, user tables
test('SqliteStateRepository - 37. T11A: backup read-only verification passes integrity_check, canonical schema, history [1, 2]', () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    const backupResult = repo.createVerifiedBackup();
    repo.close();

    // Verify backup independently via DatabaseSync in readOnly mode
    const backupDb = new DatabaseSync(backupResult.backupPath, { readOnly: true });
    try {
      // 1. integrity_check exact 'ok'
      const integrityRows = backupDb.prepare('PRAGMA integrity_check;').all();
      assert.strictEqual(integrityRows.length, 1);
      const integrityVal = integrityRows[0].integrity_check ?? Object.values(integrityRows[0])[0];
      assert.strictEqual(integrityVal, 'ok');

      // 2. schema_migrations canonical STRICT shape
      const tableList = backupDb.prepare("PRAGMA table_list('schema_migrations');").all();
      const tableEntry = tableList.find((e) => e.name === 'schema_migrations');
      assert.ok(tableEntry, 'schema_migrations must exist in backup');
      assert.strictEqual(Number(tableEntry.strict), 1, 'backup schema_migrations must be STRICT');

      const colInfo = backupDb.prepare("PRAGMA table_info('schema_migrations');").all();
      assert.strictEqual(colInfo.length, 1);
      assert.strictEqual(colInfo[0].name, 'version');
      assert.strictEqual(colInfo[0].type.toUpperCase(), 'INTEGER');
      assert.ok(Number(colInfo[0].pk) > 0);

      // 3. migration history exact [1, 2]
      const rows = backupDb.prepare('SELECT version FROM schema_migrations ORDER BY version ASC;').all();
      assert.strictEqual(rows.length, 2);
      assert.deepStrictEqual(rows.map((r) => r.version), [1, 2]);

      // 4. user tables in v2 backup: channel_control, inbox, schema_migrations
      const tables = backupDb.prepare(
        "SELECT name FROM sqlite_schema WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name ASC;"
      ).all();
      assert.strictEqual(tables.length, 3);
      assert.deepStrictEqual(tables.map((t) => t.name), ['channel_control', 'inbox', 'schema_migrations']);
    } finally {
      backupDb.close();
    }
  } finally {
    harness.cleanup();
  }
});

// 38. T11A: sequential backups create distinct files
test('SqliteStateRepository - 38. T11A: sequential backups generate distinct backup files', () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    const backup1 = repo.createVerifiedBackup();
    const backup2 = repo.createVerifiedBackup();

    assert.notStrictEqual(backup1.backupPath, backup2.backupPath);
    assert.ok(fs.existsSync(backup1.backupPath));
    assert.ok(fs.existsSync(backup2.backupPath));

    repo.close();
  } finally {
    harness.cleanup();
  }
});

// 39. T11A: closed repository rejects createVerifiedBackup fail-closed
test('SqliteStateRepository - 39. T11A: closed repository rejects createVerifiedBackup fail-closed', () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    repo.close();

    assert.throws(
      () => repo.createVerifiedBackup(),
      /closed/i
    );
  } finally {
    harness.cleanup();
  }
});

// 40. T11A: caller arguments for destination path/filename are ignored
test('SqliteStateRepository - 40. T11A: caller arguments for destination/filename are ignored', () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    const maliciousDestination = path.join(os.tmpdir(), 'malicious-escaped-backup.sqlite3');

    const result = repo.createVerifiedBackup(maliciousDestination, { customPath: true });

    // Backup is NOT written to caller's provided path
    assert.notStrictEqual(result.backupPath, maliciousDestination);
    assert.strictEqual(fs.existsSync(maliciousDestination), false);

    // Backup is confined to stateRoot
    const canonicalRoot = fs.realpathSync(harness.stateRoot);
    const rel = path.relative(canonicalRoot, result.backupPath);
    assert.strictEqual(rel.startsWith('..'), false);

    repo.close();
  } finally {
    harness.cleanup();
  }
});

// 41. T11A: pre-existing destination entry fails closed (refuses overwrite)
test('SqliteStateRepository - 41. T11A: pre-existing destination entry fails closed without overwriting', () => {
  const harness = createTempHarness();
  const fixedUuid = '11111111-2222-3333-4444-555555555555';
  const origRandomUUID = crypto.randomUUID;
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    const canonicalRoot = fs.realpathSync(harness.stateRoot);
    const existingBackupPath = path.join(
      canonicalRoot,
      `channel-gateway-state.backup-v2-${fixedUuid}.sqlite3`
    );

    // Pre-create destination file with sentinel content
    fs.writeFileSync(existingBackupPath, 'SENTINEL_DO_NOT_OVERWRITE', 'utf8');

    // Mock randomUUID to hit the pre-created destination
    crypto.randomUUID = () => fixedUuid;

    assert.throws(
      () => repo.createVerifiedBackup(),
      /already exists/i
    );

    // Verify sentinel content was not overwritten or truncated
    const content = fs.readFileSync(existingBackupPath, 'utf8');
    assert.strictEqual(content, 'SENTINEL_DO_NOT_OVERWRITE');

    repo.close();
  } finally {
    crypto.randomUUID = origRandomUUID;
    harness.cleanup();
  }
});

// 42. T11A: Parameterized VACUUM INTO behavior canary
test('SqliteStateRepository - 42. T11A: parameterized VACUUM INTO behavior canary', () => {
  const harness = createTempHarness();
  try {
    // 1. Production code inspect: VACUUM INTO must use bound parameter '?'
    const moduleSource = fs.readFileSync(
      path.join(__dirname, '../core/sqlite-state-repository.js'),
      'utf8'
    );
    assert.ok(
      /db\.prepare\(\s*['"]VACUUM\s+INTO\s+\?;\s*['"]\s*\)/i.test(moduleSource),
      'Production source must use parameterized prepared statement VACUUM INTO ?;'
    );
    assert.strictEqual(
      /VACUUM\s+INTO\s+['"`]\$\{/.test(moduleSource),
      false,
      'Production source must NEVER concatenate destination into VACUUM INTO SQL'
    );

    // 2. Behavioral proof: node:sqlite DatabaseSync natively executes VACUUM INTO ? with bound parameter
    const testDbPath = path.join(harness.stateRoot, 'test_param_source.sqlite3');
    const testDestPath = path.join(harness.stateRoot, 'test_param_dest.sqlite3');
    const rawDb = new DatabaseSync(testDbPath);
    rawDb.exec('CREATE TABLE test_table (v INTEGER PRIMARY KEY) STRICT;');
    rawDb.prepare('INSERT INTO test_table (v) VALUES (?);').run(42);

    const vacuumStmt = rawDb.prepare('VACUUM INTO ?;');
    vacuumStmt.run(testDestPath);
    rawDb.close();

    const verifyDb = new DatabaseSync(testDestPath, { readOnly: true });
    const row = verifyDb.prepare('SELECT v FROM test_table;').get();
    assert.strictEqual(row.v, 42);
    verifyDb.close();
  } finally {
    harness.cleanup();
  }
});

// 43. T11A-F1 Regression: external schema_migrations mutation before backup fails closed
test('SqliteStateRepository - 43. T11A-F1 Regression: external schema_migrations mutation before backup fails closed', () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    assert.strictEqual(repo.schemaVersion, 2);

    // Keep repo open; simulate external connection inserting migration version 3
    const externalDb = new DatabaseSync(repo.databasePath);
    try {
      externalDb.prepare('INSERT INTO schema_migrations (version) VALUES (3);').run();
    } finally {
      externalDb.close();
    }

    // createVerifiedBackup must detect version drift (2 vs 3) and throw fail-closed
    assert.throws(
      () => repo.createVerifiedBackup(),
      /drift|schema version/i
    );

    repo.close();
  } finally {
    harness.cleanup();
  }
});

// 44. T11A-F1: pre-vacuum source baseline capture and post-backup stability verification canary
test('SqliteStateRepository - 44. T11A-F1: pre-vacuum source baseline capture and post-backup stability verification canary', () => {
  const moduleSource = fs.readFileSync(
    path.join(__dirname, '../core/sqlite-state-repository.js'),
    'utf8'
  );

  // 1. Source baseline captured before VACUUM INTO execution
  const vacuumStmtIndex = moduleSource.indexOf("prepare('VACUUM INTO ?;')");
  const sourceVersionsBeforeIndex = moduleSource.indexOf('const sourceVersionsBefore');
  const sourceTablesBeforeIndex = moduleSource.indexOf('const sourceTablesBefore');
  const sourceDataVersionBeforeIndex = moduleSource.indexOf('const sourceDataVersionBefore');

  assert.ok(vacuumStmtIndex > 0, 'Production source must contain prepare("VACUUM INTO ?;")');
  assert.ok(sourceVersionsBeforeIndex > 0, 'Production source must define sourceVersionsBefore');
  assert.ok(sourceTablesBeforeIndex > 0, 'Production source must define sourceTablesBefore');
  assert.ok(
    sourceVersionsBeforeIndex < vacuumStmtIndex,
    'sourceVersionsBefore must be captured before VACUUM INTO execution'
  );
  assert.ok(
    sourceTablesBeforeIndex < vacuumStmtIndex,
    'sourceTablesBefore must be captured before VACUUM INTO execution'
  );
  if (sourceDataVersionBeforeIndex > 0) {
    assert.ok(
      sourceDataVersionBeforeIndex < vacuumStmtIndex,
      'sourceDataVersionBefore must be captured before VACUUM INTO execution'
    );
  }

  // 2. Backup verification compares against sourceVersionsBefore and sourceTablesBefore
  assert.ok(
    moduleSource.includes('backupVersions.length !== sourceVersionsBefore.length') ||
    moduleSource.includes('backupVersions[i] !== sourceVersionsBefore[i]'),
    'backupVersions must be compared against sourceVersionsBefore'
  );
  assert.ok(
    moduleSource.includes('backupTables.length !== sourceTablesBefore.length') ||
    moduleSource.includes('backupTables[i] !== sourceTablesBefore[i]'),
    'backupTables must be compared against sourceTablesBefore'
  );

  // 3. Post-backup source stability check
  assert.ok(
    moduleSource.includes('sourceVersionsAfter'),
    'Production source must verify sourceVersionsAfter for stability'
  );
  assert.ok(
    moduleSource.includes('sourceTablesAfter'),
    'Production source must verify sourceTablesAfter for stability'
  );
});

// 45. T11A: normal v2 source produces consistent backup and verified metadata
test('SqliteStateRepository - 45. T11A: normal v2 source produces consistent backup and verified metadata', () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    assert.strictEqual(repo.schemaVersion, 2);

    const result = repo.createVerifiedBackup();
    assert.strictEqual(result.success, true);
    assert.strictEqual(result.sourceSchemaVersion, 2);
    assert.strictEqual(result.integrity, 'ok');

    const backupDb = new DatabaseSync(result.backupPath, { readOnly: true });
    try {
      const rows = backupDb.prepare('SELECT version FROM schema_migrations ORDER BY version ASC;').all();
      assert.deepStrictEqual(rows.map((r) => r.version), [1, 2]);
    } finally {
      backupDb.close();
    }

    repo.close();
  } finally {
    harness.cleanup();
  }
});

// ============================================================================
// T7A Test Matrix Additions (Items 1-25)
// ============================================================================

// 46. T7A Matrix Items 1-5: new database lifecycle, registry, history [1, 2], tables, and zero backup-v0
test('SqliteStateRepository - 46. T7A: new database lifecycle, user tables, and zero backup-v0 generation', () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    assert.strictEqual(repo.isOpen, true);
    assert.strictEqual(repo.schemaVersion, 2);
    repo.close();

    const rawDb = new DatabaseSync(path.join(harness.stateRoot, SQLITE_DATABASE_FILENAME), { readOnly: true });
    try {
      // 1. Exact registry & history [1, 2]
      const rows = rawDb.prepare('SELECT version FROM schema_migrations ORDER BY version ASC;').all();
      assert.deepStrictEqual(rows.map((r) => r.version), [1, 2]);

      // 2. Exact user tables
      const tables = rawDb.prepare(
        "SELECT name FROM sqlite_schema WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name ASC;"
      ).all();
      assert.deepStrictEqual(tables.map((t) => t.name), ['channel_control', 'inbox', 'schema_migrations']);
    } finally {
      rawDb.close();
    }

    // 3. New DB must NOT create any pre-migration backup (zero backup-v0 files)
    const files = fs.readdirSync(harness.stateRoot);
    const backupFiles = files.filter((f) => f.includes('backup'));
    assert.strictEqual(backupFiles.length, 0, 'New DB must not generate any backup files');
  } finally {
    harness.cleanup();
  }
});

// 47. T7A Matrix Items 6-12: manual canonical v1 fixture auto-migrates to v2 with verified v1 backup
test('SqliteStateRepository - 47. T7A: canonical v1 fixture automatically migrates to v2 with verified v1 backup', () => {
  const harness = createTempHarness();
  try {
    const dbPath = path.join(harness.stateRoot, SQLITE_DATABASE_FILENAME);
    // Create synthetic canonical v1 database
    const rawDb = new DatabaseSync(dbPath);
    rawDb.exec('CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY) STRICT;');
    rawDb.prepare('INSERT INTO schema_migrations (version) VALUES (1);').run();
    rawDb.close();

    // Open repository: must create verified v1 backup BEFORE running migration 2
    const repo = new SqliteStateRepository(harness.stateRoot);
    assert.strictEqual(repo.isOpen, true);
    assert.strictEqual(repo.schemaVersion, 2);
    repo.close();

    // Inspect files in stateRoot: exactly one backup-v1-* file
    const files = fs.readdirSync(harness.stateRoot);
    const v1Backups = files.filter(
      (f) => f.startsWith('channel-gateway-state.backup-v1-') && f.endsWith('.sqlite3')
    );
    assert.strictEqual(v1Backups.length, 1, 'Exactly one pre-migration v1 backup must exist');

    const backupPath = path.join(harness.stateRoot, v1Backups[0]);

    // Inspect pre-migration backup independently:
    const backupDb = new DatabaseSync(backupPath, { readOnly: true });
    try {
      // PRAGMA integrity_check === 'ok'
      const integrity = backupDb.prepare('PRAGMA integrity_check;').get();
      assert.strictEqual(integrity.integrity_check ?? Object.values(integrity)[0], 'ok');

      // History is strictly [1]
      const bRows = backupDb.prepare('SELECT version FROM schema_migrations ORDER BY version ASC;').all();
      assert.deepStrictEqual(bRows.map((r) => r.version), [1]);

      // User tables are strictly ['schema_migrations']
      const bTables = backupDb.prepare(
        "SELECT name FROM sqlite_schema WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name ASC;"
      ).all();
      assert.deepStrictEqual(bTables.map((t) => t.name), ['schema_migrations']);
    } finally {
      backupDb.close();
    }

    // Inspect live DB after migration: history is [1, 2]
    const liveDb = new DatabaseSync(dbPath, { readOnly: true });
    try {
      const lRows = liveDb.prepare('SELECT version FROM schema_migrations ORDER BY version ASC;').all();
      assert.deepStrictEqual(lRows.map((r) => r.version), [1, 2]);

      const lTables = liveDb.prepare(
        "SELECT name FROM sqlite_schema WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name ASC;"
      ).all();
      assert.deepStrictEqual(lTables.map((t) => t.name), ['channel_control', 'inbox', 'schema_migrations']);
    } finally {
      liveDb.close();
    }

    // Reopen already-v2 DB: no new migration backup created
    const repo2 = new SqliteStateRepository(harness.stateRoot);
    assert.strictEqual(repo2.isOpen, true);
    assert.strictEqual(repo2.schemaVersion, 2);
    repo2.close();

    const filesAfterReopen = fs.readdirSync(harness.stateRoot);
    const v1BackupsAfter = filesAfterReopen.filter(
      (f) => f.startsWith('channel-gateway-state.backup-v1-') && f.endsWith('.sqlite3')
    );
    assert.strictEqual(v1BackupsAfter.length, 1, 'Reopening v2 DB must not create new migration backup');
  } finally {
    harness.cleanup();
  }
});

// 48. T7A Matrix Items 13-14: deterministic migration 2 failure rolls back live DB, keeps valid v1 backup
test('SqliteStateRepository - 48. T7A: migration 2 deterministic failure rolls back live DB, live history remains [1]', () => {
  const harness = createTempHarness();
  try {
    const dbPath = path.join(harness.stateRoot, SQLITE_DATABASE_FILENAME);
    // Create synthetic v1 DB with conflicting table to guarantee migration 2 failure
    const rawDb = new DatabaseSync(dbPath);
    rawDb.exec('CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY) STRICT;');
    rawDb.prepare('INSERT INTO schema_migrations (version) VALUES (1);').run();
    // Conflicting table causes CREATE TABLE channel_control to fail deterministically
    rawDb.exec('CREATE TABLE channel_control (conflicting_col TEXT);');
    rawDb.close();

    // Opening repository must fail closed
    assert.throws(
      () => new SqliteStateRepository(harness.stateRoot),
      /Failed to apply migration 2|already exists/i
    );

    // 1. Live DB verification: migration history STILL [1] (2 was rolled back)
    const liveDb = new DatabaseSync(dbPath, { readOnly: true });
    try {
      const rows = liveDb.prepare('SELECT version FROM schema_migrations ORDER BY version ASC;').all();
      assert.deepStrictEqual(rows.map((r) => r.version), [1], 'Live DB history must remain [1] on rollback');

      // inbox table was never committed
      const inboxCheck = liveDb.prepare(
        "SELECT name FROM sqlite_schema WHERE type = 'table' AND name = 'inbox';"
      ).get();
      assert.strictEqual(inboxCheck, undefined, 'inbox table must not exist after rollback');
    } finally {
      liveDb.close();
    }

    // 2. Pre-migration backup exists and is valid snapshot before migration attempt
    const files = fs.readdirSync(harness.stateRoot);
    const v1Backups = files.filter(
      (f) => f.startsWith('channel-gateway-state.backup-v1-') && f.endsWith('.sqlite3')
    );
    assert.strictEqual(v1Backups.length, 1, 'Pre-migration v1 backup must be preserved');

    const backupDb = new DatabaseSync(path.join(harness.stateRoot, v1Backups[0]), { readOnly: true });
    try {
      const integrity = backupDb.prepare('PRAGMA integrity_check;').get();
      assert.strictEqual(integrity.integrity_check ?? Object.values(integrity)[0], 'ok');

      const bRows = backupDb.prepare('SELECT version FROM schema_migrations ORDER BY version ASC;').all();
      assert.deepStrictEqual(bRows.map((r) => r.version), [1]);
    } finally {
      backupDb.close();
    }
  } finally {
    harness.cleanup();
  }
});

// 49. T7A Matrix Items 15, 17: channel_control STRICT shape, PK, defaults, and CHECK constraints
test('SqliteStateRepository - 49. T7A: channel_control STRICT shape, PK, default 0, and negative fencing rejected', () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    const rawDb = new DatabaseSync(repo.databasePath);
    try {
      // 1. Valid insert with default fencing_token
      rawDb.prepare('INSERT INTO channel_control (channel_id) VALUES (?);').run('test_ch_1');
      const row = rawDb.prepare('SELECT * FROM channel_control WHERE channel_id = ?;').get('test_ch_1');
      assert.strictEqual(row.channel_id, 'test_ch_1');
      assert.strictEqual(row.current_holder, null);
      assert.strictEqual(row.fencing_token, 0);
      assert.strictEqual(row.last_heartbeat_at, null);

      // 2. Valid insert with explicit non-zero fencing token and holder
      rawDb.prepare(
        'INSERT INTO channel_control (channel_id, current_holder, fencing_token, last_heartbeat_at) VALUES (?, ?, ?, ?);'
      ).run('test_ch_2', 'holder_alpha', 42, 1700000000);
      const row2 = rawDb.prepare('SELECT * FROM channel_control WHERE channel_id = ?;').get('test_ch_2');
      assert.strictEqual(row2.current_holder, 'holder_alpha');
      assert.strictEqual(row2.fencing_token, 42);
      assert.strictEqual(row2.last_heartbeat_at, 1700000000);

      // 3. Negative fencing_token rejected by CHECK constraint
      assert.throws(
        () => rawDb.prepare('INSERT INTO channel_control (channel_id, fencing_token) VALUES (?, ?);').run('test_ch_3', -1),
        /CHECK constraint failed/i
      );

      // 4. Empty/whitespace channel_id rejected by CHECK constraint
      assert.throws(
        () => rawDb.prepare('INSERT INTO channel_control (channel_id) VALUES (?);').run('   '),
        /CHECK constraint failed/i
      );

      // 5. Empty/whitespace current_holder rejected by CHECK constraint
      assert.throws(
        () => rawDb.prepare('INSERT INTO channel_control (channel_id, current_holder) VALUES (?, ?);').run('test_ch_4', '   '),
        /CHECK constraint failed/i
      );

      // 6. Duplicate channel_id rejected (PK)
      assert.throws(
        () => rawDb.prepare('INSERT INTO channel_control (channel_id) VALUES (?);').run('test_ch_1'),
        /UNIQUE constraint failed|PRIMARY KEY/i
      );
    } finally {
      rawDb.close();
      repo.close();
    }
  } finally {
    harness.cleanup();
  }
});

// 50. T7A Matrix Items 16, 18-21: inbox STRICT shape, constraints, and foreign key enforcement
test('SqliteStateRepository - 50. T7A: inbox STRICT shape, constraints, FIFO sequence, and foreign key enforcement', () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    const rawDb = new DatabaseSync(repo.databasePath);
    try {
      rawDb.exec('PRAGMA foreign_keys = ON;');

      // 1. Missing parent channel_id in channel_control fails foreign key check
      assert.throws(
        () =>
          rawDb.prepare(
            'INSERT INTO inbox (channel_id, message_id, receiving_account_id, status) VALUES (?, ?, ?, ?);'
          ).run('nonexistent_channel', 'msg_001', 'acc_01', 'queued'),
        /FOREIGN KEY constraint failed/i
      );

      // Create valid parent channel
      rawDb.prepare('INSERT INTO channel_control (channel_id) VALUES (?);').run('ch_parent');

      // 2. Valid insertion into inbox
      rawDb.prepare(
        'INSERT INTO inbox (channel_id, message_id, receiving_account_id, status) VALUES (?, ?, ?, ?);'
      ).run('ch_parent', 'msg_001', 'acc_01', 'queued');

      // 3. FIFO sequence increments deterministically
      rawDb.prepare(
        'INSERT INTO inbox (channel_id, message_id, receiving_account_id, status) VALUES (?, ?, ?, ?);'
      ).run('ch_parent', 'msg_002', 'acc_01', 'queued');

      const rows = rawDb.prepare('SELECT sequence, message_id FROM inbox ORDER BY sequence ASC;').all();
      assert.strictEqual(rows.length, 2);
      assert.strictEqual(rows[0].sequence, 1);
      assert.strictEqual(rows[0].message_id, 'msg_001');
      assert.strictEqual(rows[1].sequence, 2);
      assert.strictEqual(rows[1].message_id, 'msg_002');

      // 4. Duplicate (channel_id, message_id) rejected
      assert.throws(
        () =>
          rawDb.prepare(
            'INSERT INTO inbox (channel_id, message_id, receiving_account_id, status) VALUES (?, ?, ?, ?);'
          ).run('ch_parent', 'msg_001', 'acc_02', 'queued'),
        /UNIQUE constraint failed/i
      );

      // 5. Invalid status rejected by CHECK constraint
      assert.throws(
        () =>
          rawDb.prepare(
            'INSERT INTO inbox (channel_id, message_id, receiving_account_id, status) VALUES (?, ?, ?, ?);'
          ).run('ch_parent', 'msg_003', 'acc_01', 'invalid_status'),
        /CHECK constraint failed/i
      );

      // 6. Negative claimed_at_token rejected by CHECK constraint
      assert.throws(
        () =>
          rawDb.prepare(
            'INSERT INTO inbox (channel_id, message_id, receiving_account_id, status, claimed_at_token) VALUES (?, ?, ?, ?, ?);'
          ).run('ch_parent', 'msg_004', 'acc_01', 'claimed', -1),
        /CHECK constraint failed/i
      );

      // 7. Negative discarded_at_token rejected by CHECK constraint
      assert.throws(
        () =>
          rawDb.prepare(
            'INSERT INTO inbox (channel_id, message_id, receiving_account_id, status, discarded_at_token) VALUES (?, ?, ?, ?, ?);'
          ).run('ch_parent', 'msg_005', 'acc_01', 'discarded', -1),
        /CHECK constraint failed/i
      );

      // 8. Valid statuses: 'queued', 'claimed', 'discarded', 'replied'
      for (const validStatus of ['claimed', 'discarded', 'replied']) {
        rawDb.prepare(
          'INSERT INTO inbox (channel_id, message_id, receiving_account_id, status) VALUES (?, ?, ?, ?);'
        ).run('ch_parent', `msg_${validStatus}`, 'acc_01', validStatus);
      }
    } finally {
      rawDb.close();
      repo.close();
    }
  } finally {
    harness.cleanup();
  }
});

// 51. T7A Matrix Items 22-24: architectural boundaries (no ingest_cursor, no composite account dedupe, no outbox, no domain transaction methods)
test('SqliteStateRepository - 51. T7A: architectural boundaries: no ingest_cursor, no composite dedupe, no outbox, no domain transaction methods', () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    const rawDb = new DatabaseSync(repo.databasePath, { readOnly: true });
    try {
      // 1. No forbidden tables exist
      const forbidden = ['ingest_cursor', 'outbox', 'messages', 'cursors', 'accounts', 'channels'];
      for (const tName of forbidden) {
        const found = rawDb.prepare("SELECT name FROM sqlite_schema WHERE type = 'table' AND name = ?;").get(tName);
        assert.strictEqual(found, undefined, `Forbidden table '${tName}' must not exist in T7A`);
      }

      // 2. No composite (account_id, platform_msg_id) index or constraint
      const indexes = rawDb.prepare("SELECT name, sql FROM sqlite_schema WHERE type = 'index';").all();
      for (const idx of indexes) {
        if (idx.sql) {
          assert.strictEqual(
            /platform_msg_id/i.test(idx.sql),
            false,
            'No index should reference platform_msg_id in T7A'
          );
        }
      }

      // 3. SqliteStateRepository exposes NO domain transaction methods yet (deferred to T7B)
      const forbiddenMethods = [
        'takeoverChannel',
        'heartbeatChannel',
        'expireHolder',
        'enqueueMessage',
        'claimMessages',
        'pollMessages',
        'authorizeReply',
        'discardQueuedForAccount',
      ];
      for (const m of forbiddenMethods) {
        assert.strictEqual(repo[m], undefined, `Domain transaction method '${m}' must not be exposed in T7A`);
        assert.strictEqual(
          SqliteStateRepository.prototype[m],
          undefined,
          `Domain transaction method '${m}' must not exist on prototype in T7A`
        );
      }
    } finally {
      rawDb.close();
      repo.close();
    }
  } finally {
    harness.cleanup();
  }
});

// 52. T7A Matrix Item 25: public createVerifiedBackup on v2 repository produces verified v2 snapshot
test('SqliteStateRepository - 52. T7A: public createVerifiedBackup on v2 repository: sourceSchemaVersion = 2, history [1, 2]', () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    assert.strictEqual(repo.schemaVersion, 2);

    const backupResult = repo.createVerifiedBackup();
    assert.strictEqual(backupResult.success, true);
    assert.strictEqual(backupResult.sourceSchemaVersion, 2);
    assert.strictEqual(backupResult.integrity, 'ok');

    const backupDb = new DatabaseSync(backupResult.backupPath, { readOnly: true });
    try {
      const integrity = backupDb.prepare('PRAGMA integrity_check;').get();
      assert.strictEqual(integrity.integrity_check ?? Object.values(integrity)[0], 'ok');

      const rows = backupDb.prepare('SELECT version FROM schema_migrations ORDER BY version ASC;').all();
      assert.deepStrictEqual(rows.map((r) => r.version), [1, 2]);

      const tables = backupDb.prepare(
        "SELECT name FROM sqlite_schema WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name ASC;"
      ).all();
      assert.deepStrictEqual(tables.map((t) => t.name), ['channel_control', 'inbox', 'schema_migrations']);
    } finally {
      backupDb.close();
      repo.close();
    }
  } finally {
    harness.cleanup();
  }
});

// 53. T7A-F1 Regression: Synthetic weakened-v2 database without CHECK constraints and without AUTOINCREMENT is rejected fail-closed
test('SqliteStateRepository - 53. T7A-F1: synthetic weakened-v2 DB without CHECKs and without AUTOINCREMENT rejected fail-closed', () => {
  const harness = createTempHarness();
  try {
    const dbPath = path.join(harness.stateRoot, SQLITE_DATABASE_FILENAME);
    const rawDb = new DatabaseSync(dbPath);
    try {
      rawDb.exec('PRAGMA journal_mode = WAL;');
      rawDb.exec('PRAGMA foreign_keys = ON;');
      rawDb.exec('CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY) STRICT;');
      rawDb.exec('INSERT INTO schema_migrations (version) VALUES (1), (2);');
      // Weakened channel_control: STRICT, same 4 columns, same PK/default, BUT NO CHECK constraints
      rawDb.exec(`
        CREATE TABLE channel_control (
          channel_id TEXT PRIMARY KEY,
          current_holder TEXT,
          fencing_token INTEGER NOT NULL DEFAULT 0,
          last_heartbeat_at INTEGER
        ) STRICT;
      `);
      // Weakened inbox: STRICT, same 10 columns, same FK, same UNIQUE, BUT sequence INTEGER PRIMARY KEY (no AUTOINCREMENT), NO CHECK constraints
      rawDb.exec(`
        CREATE TABLE inbox (
          sequence INTEGER PRIMARY KEY,
          channel_id TEXT NOT NULL,
          message_id TEXT NOT NULL,
          receiving_account_id TEXT NOT NULL,
          status TEXT NOT NULL,
          claimed_by TEXT,
          claimed_at_token INTEGER,
          discard_reason TEXT,
          discarded_by_holder TEXT,
          discarded_at_token INTEGER,
          UNIQUE(channel_id, message_id),
          FOREIGN KEY(channel_id) REFERENCES channel_control(channel_id) ON DELETE RESTRICT
        ) STRICT;
      `);
    } finally {
      rawDb.close();
    }

    assert.throws(
      () => new SqliteStateRepository(harness.stateRoot),
      /fail-closed/i,
      'Reopening weakened v2 database missing CHECKs and AUTOINCREMENT must fail closed'
    );
  } finally {
    harness.cleanup();
  }
});

// 54. T7A-F1 Targeted: channel_control missing fencing_token >= 0 CHECK constraint is rejected fail-closed
test('SqliteStateRepository - 54. T7A-F1: channel_control missing fencing_token CHECK constraint rejected fail-closed', () => {
  const harness = createTempHarness();
  try {
    const dbPath = path.join(harness.stateRoot, SQLITE_DATABASE_FILENAME);
    const rawDb = new DatabaseSync(dbPath);
    try {
      rawDb.exec('PRAGMA journal_mode = WAL;');
      rawDb.exec('PRAGMA foreign_keys = ON;');
      rawDb.exec('CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY) STRICT;');
      rawDb.exec('INSERT INTO schema_migrations (version) VALUES (1), (2);');
      rawDb.exec(`
        CREATE TABLE channel_control (
          channel_id TEXT PRIMARY KEY CHECK(length(trim(channel_id)) > 0),
          current_holder TEXT CHECK(current_holder IS NULL OR length(trim(current_holder)) > 0),
          fencing_token INTEGER NOT NULL DEFAULT 0,
          last_heartbeat_at INTEGER
        ) STRICT;
      `);
      rawDb.exec(INBOX_SCHEMA_SQL);
    } finally {
      rawDb.close();
    }

    assert.throws(
      () => new SqliteStateRepository(harness.stateRoot),
      /fencing_token.*CHECK|canonical DDL/i,
      'channel_control missing fencing_token CHECK constraint must fail closed'
    );
  } finally {
    harness.cleanup();
  }
});

// 55. T7A-F1 Targeted: inbox missing status enum CHECK constraint is rejected fail-closed
test('SqliteStateRepository - 55. T7A-F1: inbox missing status enum CHECK constraint rejected fail-closed', () => {
  const harness = createTempHarness();
  try {
    const dbPath = path.join(harness.stateRoot, SQLITE_DATABASE_FILENAME);
    const rawDb = new DatabaseSync(dbPath);
    try {
      rawDb.exec('PRAGMA journal_mode = WAL;');
      rawDb.exec('PRAGMA foreign_keys = ON;');
      rawDb.exec('CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY) STRICT;');
      rawDb.exec('INSERT INTO schema_migrations (version) VALUES (1), (2);');
      rawDb.exec(CHANNEL_CONTROL_SCHEMA_SQL);
      rawDb.exec(`
        CREATE TABLE inbox (
          sequence INTEGER PRIMARY KEY AUTOINCREMENT,
          channel_id TEXT NOT NULL,
          message_id TEXT NOT NULL CHECK(length(trim(message_id)) > 0),
          receiving_account_id TEXT NOT NULL CHECK(length(trim(receiving_account_id)) > 0),
          status TEXT NOT NULL,
          claimed_by TEXT,
          claimed_at_token INTEGER CHECK(claimed_at_token IS NULL OR claimed_at_token >= 0),
          discard_reason TEXT,
          discarded_by_holder TEXT,
          discarded_at_token INTEGER CHECK(discarded_at_token IS NULL OR discarded_at_token >= 0),
          UNIQUE(channel_id, message_id),
          FOREIGN KEY(channel_id) REFERENCES channel_control(channel_id) ON DELETE RESTRICT
        ) STRICT;
      `);
    } finally {
      rawDb.close();
    }

    assert.throws(
      () => new SqliteStateRepository(harness.stateRoot),
      /status enum.*CHECK|canonical DDL/i,
      'inbox missing status enum CHECK constraint must fail closed'
    );
  } finally {
    harness.cleanup();
  }
});

// 56. T7A-F1 Targeted: inbox missing AUTOINCREMENT on sequence column is rejected fail-closed
test('SqliteStateRepository - 56. T7A-F1: inbox missing AUTOINCREMENT on sequence column rejected fail-closed', () => {
  const harness = createTempHarness();
  try {
    const dbPath = path.join(harness.stateRoot, SQLITE_DATABASE_FILENAME);
    const rawDb = new DatabaseSync(dbPath);
    try {
      rawDb.exec('PRAGMA journal_mode = WAL;');
      rawDb.exec('PRAGMA foreign_keys = ON;');
      rawDb.exec('CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY) STRICT;');
      rawDb.exec('INSERT INTO schema_migrations (version) VALUES (1), (2);');
      rawDb.exec(CHANNEL_CONTROL_SCHEMA_SQL);
      rawDb.exec(`
        CREATE TABLE inbox (
          sequence INTEGER PRIMARY KEY,
          channel_id TEXT NOT NULL,
          message_id TEXT NOT NULL CHECK(length(trim(message_id)) > 0),
          receiving_account_id TEXT NOT NULL CHECK(length(trim(receiving_account_id)) > 0),
          status TEXT NOT NULL CHECK(status IN ('queued', 'claimed', 'discarded', 'replied')),
          claimed_by TEXT,
          claimed_at_token INTEGER CHECK(claimed_at_token IS NULL OR claimed_at_token >= 0),
          discard_reason TEXT,
          discarded_by_holder TEXT,
          discarded_at_token INTEGER CHECK(discarded_at_token IS NULL OR discarded_at_token >= 0),
          UNIQUE(channel_id, message_id),
          FOREIGN KEY(channel_id) REFERENCES channel_control(channel_id) ON DELETE RESTRICT
        ) STRICT;
      `);
    } finally {
      rawDb.close();
    }

    assert.throws(
      () => new SqliteStateRepository(harness.stateRoot),
      /AUTOINCREMENT|canonical DDL/i,
      'inbox missing AUTOINCREMENT must fail closed'
    );
  } finally {
    harness.cleanup();
  }
});

// 57. T7A-F1 Positive Reopen: canonical v2 database reopen succeeds and preserves schema contract
test('SqliteStateRepository - 57. T7A-F1: canonical v2 database reopen succeeds and preserves schema', () => {
  const harness = createTempHarness();
  try {
    const repo1 = new SqliteStateRepository(harness.stateRoot);
    assert.strictEqual(repo1.schemaVersion, 2);
    assert.strictEqual(repo1.isOpen, true);
    repo1.close();

    const repo2 = new SqliteStateRepository(harness.stateRoot);
    assert.strictEqual(repo2.schemaVersion, 2);
    assert.strictEqual(repo2.isOpen, true);
    repo2.close();
  } finally {
    harness.cleanup();
  }
});

// 58. T7A-F1 Backup Safety: weakened v2 database cannot be opened to produce verified backup
test('SqliteStateRepository - 58. T7A-F1: weakened v2 database cannot be opened to produce verified backup', () => {
  const harness = createTempHarness();
  try {
    const dbPath = path.join(harness.stateRoot, SQLITE_DATABASE_FILENAME);
    const rawDb = new DatabaseSync(dbPath);
    try {
      rawDb.exec('PRAGMA journal_mode = WAL;');
      rawDb.exec('PRAGMA foreign_keys = ON;');
      rawDb.exec('CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY) STRICT;');
      rawDb.exec('INSERT INTO schema_migrations (version) VALUES (1), (2);');
      rawDb.exec(`
        CREATE TABLE channel_control (
          channel_id TEXT PRIMARY KEY,
          current_holder TEXT,
          fencing_token INTEGER NOT NULL DEFAULT 0,
          last_heartbeat_at INTEGER
        ) STRICT;
      `);
      rawDb.exec(INBOX_SCHEMA_SQL);
    } finally {
      rawDb.close();
    }

    assert.throws(
      () => new SqliteStateRepository(harness.stateRoot),
      /fail-closed/i,
      'Weakened v2 repository open must fail closed, preventing verified backup generation'
    );
  } finally {
    harness.cleanup();
  }
});

// 59. T7A-F1 SQL Normalizer: normalizeCanonicalSchemaSql handles formatting, casing, and preserves literals
test('SqliteStateRepository - 59. T7A-F1: normalizeCanonicalSchemaSql handles formatting, casing, and preserves string literals', () => {
  assert.strictEqual(normalizeCanonicalSchemaSql(null), '');
  assert.strictEqual(normalizeCanonicalSchemaSql(''), '');

  const sql1 = `
    CREATE TABLE test (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      status TEXT CHECK ( status IN ( 'queued', 'claimed' ) )
    ) STRICT;
  `;
  const sql2 = "create table test(id integer primary key autoincrement, status text check(status in ('queued', 'claimed'))) strict";
  assert.strictEqual(normalizeCanonicalSchemaSql(sql1), normalizeCanonicalSchemaSql(sql2));

  // Case of string literal must be preserved (case-sensitive enum)
  const sqlBadEnum = "create table test(id integer primary key autoincrement, status text check(status in ('QUEUED', 'claimed'))) strict";
  assert.notStrictEqual(normalizeCanonicalSchemaSql(sql1), normalizeCanonicalSchemaSql(sqlBadEnum));
});
