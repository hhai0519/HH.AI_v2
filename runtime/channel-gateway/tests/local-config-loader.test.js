/**
 * runtime/channel-gateway/tests/local-config-loader.test.js
 *
 * Unit tests for Repo-External Config Loader + Startup Path Validation (ADR-0022 D24).
 * Uses synthetic temp fixtures only; cleanups in try/finally blocks.
 */

'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');

const {
  loadDataLocationConfigFromFile,
  validateStartupDataLocations,
} = require('../core/local-config-loader');
const {
  validateResolvedDataLocationConfig,
} = require('../core/data-location-config');

/**
 * Creates an isolated temporary directory harness for testing.
 *
 * @returns {object}
 */
function createTempHarness() {
  const baseDir = fs.mkdtempSync(path.join(os.tmpdir(), 'hhai-loader-test-'));
  const repoRoot = path.join(baseDir, 'fake-repo');
  const externalDir = path.join(baseDir, 'external');
  fs.mkdirSync(repoRoot, { recursive: true });
  fs.mkdirSync(externalDir, { recursive: true });

  const dataDirs = {
    archiveRoot: path.join(externalDir, 'archive'),
    attachmentTempRoot: path.join(externalDir, 'attachments'),
    stateRoot: path.join(externalDir, 'state'),
    logsRoot: path.join(externalDir, 'logs'),
    protectedRoots: [
      path.join(externalDir, 'protected-1'),
      path.join(externalDir, 'protected-2'),
    ],
  };

  for (const p of [
    dataDirs.archiveRoot,
    dataDirs.attachmentTempRoot,
    dataDirs.stateRoot,
    dataDirs.logsRoot,
    ...dataDirs.protectedRoots,
  ]) {
    fs.mkdirSync(p, { recursive: true });
  }

  const validConfig = {
    schemaVersion: 1,
    dataLocations: dataDirs,
  };

  const validConfigFile = path.join(externalDir, 'config.json');
  fs.writeFileSync(validConfigFile, JSON.stringify(validConfig, null, 2), 'utf8');

  function cleanup() {
    try {
      fs.rmSync(baseDir, { recursive: true, force: true });
    } catch {
      // ignore cleanup errors
    }
  }

  return {
    baseDir,
    repoRoot,
    externalDir,
    dataDirs,
    validConfig,
    validConfigFile,
    cleanup,
  };
}

test('LocalConfigLoader - 1. valid repo-external config loads', () => {
  const harness = createTempHarness();
  try {
    const config = loadDataLocationConfigFromFile(harness.validConfigFile, {
      repoRoot: harness.repoRoot,
    });
    assert.ok(config);
    assert.equal(config.schemaVersion, 1);
    assert.equal(config.dataLocations.archiveRoot, harness.dataDirs.archiveRoot);
    assert.equal(config.dataLocations.attachmentTempRoot, harness.dataDirs.attachmentTempRoot);
    assert.equal(config.dataLocations.stateRoot, harness.dataDirs.stateRoot);
    assert.equal(config.dataLocations.logsRoot, harness.dataDirs.logsRoot);
    assert.equal(config.dataLocations.protectedRoots.length, 2);
  } finally {
    harness.cleanup();
  }
});

test('LocalConfigLoader - 2. valid loaded config passes Wave 2C schema', () => {
  const harness = createTempHarness();
  try {
    const config = loadDataLocationConfigFromFile(harness.validConfigFile, {
      repoRoot: harness.repoRoot,
    });
    const revalidated = validateResolvedDataLocationConfig(config);
    assert.deepEqual(revalidated, config);
  } finally {
    harness.cleanup();
  }
});

test('LocalConfigLoader - 3. relative configPath rejected', () => {
  const harness = createTempHarness();
  try {
    assert.throws(
      () => loadDataLocationConfigFromFile('relative/path/config.json', { repoRoot: harness.repoRoot }),
      /must be an absolute path/
    );
    assert.throws(
      () => loadDataLocationConfigFromFile('./config.json', { repoRoot: harness.repoRoot }),
      /must be an absolute path/
    );
    assert.throws(
      () => loadDataLocationConfigFromFile('../config.json', { repoRoot: harness.repoRoot }),
      /must be an absolute path/
    );
    assert.throws(
      () => loadDataLocationConfigFromFile('   ', { repoRoot: harness.repoRoot }),
      /must be a non-empty string/
    );
    assert.throws(
      () => loadDataLocationConfigFromFile(123, { repoRoot: harness.repoRoot }),
      /must be a string/
    );
  } finally {
    harness.cleanup();
  }
});

test('LocalConfigLoader - 4. missing config file rejected', () => {
  const harness = createTempHarness();
  try {
    const missing = path.join(harness.externalDir, 'nonexistent.json');
    assert.throws(
      () => loadDataLocationConfigFromFile(missing, { repoRoot: harness.repoRoot }),
      /does not exist or cannot be accessed/
    );
  } finally {
    harness.cleanup();
  }
});

test('LocalConfigLoader - 5. configPath directory而非 file rejected', () => {
  const harness = createTempHarness();
  try {
    assert.throws(
      () => loadDataLocationConfigFromFile(harness.externalDir, { repoRoot: harness.repoRoot }),
      /must be a regular file/
    );
  } finally {
    harness.cleanup();
  }
});

test('LocalConfigLoader - 6. malformed JSON rejected', () => {
  const harness = createTempHarness();
  try {
    const malformedFile = path.join(harness.externalDir, 'malformed.json');
    fs.writeFileSync(malformedFile, '{ schemaVersion: 1, unquotedKey: true, }', 'utf8');
    assert.throws(
      () => loadDataLocationConfigFromFile(malformedFile, { repoRoot: harness.repoRoot }),
      /Failed to parse configuration file as JSON/
    );
  } finally {
    harness.cleanup();
  }
});

test('LocalConfigLoader - 7. unknown config key rejected', () => {
  const harness = createTempHarness();
  try {
    const unknownTopKeyFile = path.join(harness.externalDir, 'unknown-top.json');
    const cfg1 = { ...harness.validConfig, unexpectedKey: 'forbidden' };
    fs.writeFileSync(unknownTopKeyFile, JSON.stringify(cfg1), 'utf8');
    assert.throws(
      () => loadDataLocationConfigFromFile(unknownTopKeyFile, { repoRoot: harness.repoRoot }),
      /Unknown top-level configuration key: 'unexpectedKey'/
    );

    const unknownLocationKeyFile = path.join(harness.externalDir, 'unknown-loc.json');
    const cfg2 = {
      ...harness.validConfig,
      dataLocations: { ...harness.validConfig.dataLocations, secretLocation: 'C:\\Secrets' },
    };
    fs.writeFileSync(unknownLocationKeyFile, JSON.stringify(cfg2), 'utf8');
    assert.throws(
      () => loadDataLocationConfigFromFile(unknownLocationKeyFile, { repoRoot: harness.repoRoot }),
      /Unknown dataLocations key: 'secretLocation'/
    );
  } finally {
    harness.cleanup();
  }
});

test('LocalConfigLoader - 8. config file physically inside repoRoot rejected', () => {
  const harness = createTempHarness();
  try {
    const internalConfigFile = path.join(harness.repoRoot, 'internal-config.json');
    fs.writeFileSync(internalConfigFile, JSON.stringify(harness.validConfig), 'utf8');
    assert.throws(
      () => loadDataLocationConfigFromFile(internalConfigFile, { repoRoot: harness.repoRoot }),
      /Configuration file must be repo-external/
    );

    const subDir = path.join(harness.repoRoot, 'nested', 'deep');
    fs.mkdirSync(subDir, { recursive: true });
    const nestedConfigFile = path.join(subDir, 'nested-config.json');
    fs.writeFileSync(nestedConfigFile, JSON.stringify(harness.validConfig), 'utf8');
    assert.throws(
      () => loadDataLocationConfigFromFile(nestedConfigFile, { repoRoot: harness.repoRoot }),
      /Configuration file must be repo-external/
    );
  } finally {
    harness.cleanup();
  }
});

test('LocalConfigLoader - 9. repo-external symlink resolving into repo rejected 或 capability-aware skip', (t) => {
  const harness = createTempHarness();
  try {
    const fileInsideRepo = path.join(harness.repoRoot, 'real-config-inside-repo.json');
    fs.writeFileSync(fileInsideRepo, JSON.stringify(harness.validConfig), 'utf8');

    const externalSymlink = path.join(harness.externalDir, 'symlink-pointing-to-repo.json');
    try {
      fs.symlinkSync(fileInsideRepo, externalSymlink, 'file');
    } catch (symlinkErr) {
      t.skip(`Symlink creation not permitted in this environment (${symlinkErr.code || symlinkErr.message})`);
      return;
    }

    assert.throws(
      () => loadDataLocationConfigFromFile(externalSymlink, { repoRoot: harness.repoRoot }),
      /Configuration file must be repo-external/
    );
  } finally {
    harness.cleanup();
  }
});

test('LocalConfigLoader - 10. missing archiveRoot directory fails startup validation', () => {
  const harness = createTempHarness();
  try {
    const badConfig = JSON.parse(JSON.stringify(harness.validConfig));
    badConfig.dataLocations.archiveRoot = path.join(harness.externalDir, 'missing-archive-dir');
    assert.throws(
      () => validateStartupDataLocations(badConfig),
      /Configured data location 'archiveRoot' does not exist or cannot be accessed/
    );
  } finally {
    harness.cleanup();
  }
});

test('LocalConfigLoader - 11. file used where directory expected fails', () => {
  const harness = createTempHarness();
  try {
    const regularFile = path.join(harness.externalDir, 'dummy-file.txt');
    fs.writeFileSync(regularFile, 'hello', 'utf8');

    const fields = ['archiveRoot', 'attachmentTempRoot', 'stateRoot', 'logsRoot'];
    for (const field of fields) {
      const badConfig = JSON.parse(JSON.stringify(harness.validConfig));
      badConfig.dataLocations[field] = regularFile;
      assert.throws(
        () => validateStartupDataLocations(badConfig),
        new RegExp(`Configured data location '${field}' must be a directory`)
      );
    }
  } finally {
    harness.cleanup();
  }
});

test('LocalConfigLoader - 12. non-readable path fail-closed 或 capability-aware skip', (t) => {
  const harness = createTempHarness();
  try {
    const unreadableDir = path.join(harness.externalDir, 'unreadable-dir');
    fs.mkdirSync(unreadableDir, { recursive: true });

    let supportsChmodRestriction = false;
    try {
      fs.chmodSync(unreadableDir, 0o000);
      fs.accessSync(unreadableDir, fs.constants.R_OK);
    } catch {
      supportsChmodRestriction = true;
    }

    if (!supportsChmodRestriction) {
      try {
        fs.chmodSync(unreadableDir, 0o777);
      } catch {}
      t.skip('Platform does not support unreadable directory semantics via chmod');
      return;
    }

    const badConfig = JSON.parse(JSON.stringify(harness.validConfig));
    badConfig.dataLocations.logsRoot = unreadableDir;
    try {
      assert.throws(
        () => validateStartupDataLocations(badConfig),
        /must be readable/
      );
    } finally {
      try {
        fs.chmodSync(unreadableDir, 0o777);
      } catch {}
    }
  } finally {
    harness.cleanup();
  }
});

test('LocalConfigLoader - 13. valid four writable roots accepted', () => {
  const harness = createTempHarness();
  try {
    const canonical = validateStartupDataLocations(harness.validConfig);
    assert.ok(canonical);
    assert.equal(canonical.schemaVersion, 1);
    assert.equal(canonical.dataLocations.archiveRoot, fs.realpathSync(harness.dataDirs.archiveRoot));
    assert.equal(canonical.dataLocations.attachmentTempRoot, fs.realpathSync(harness.dataDirs.attachmentTempRoot));
    assert.equal(canonical.dataLocations.stateRoot, fs.realpathSync(harness.dataDirs.stateRoot));
    assert.equal(canonical.dataLocations.logsRoot, fs.realpathSync(harness.dataDirs.logsRoot));
    assert.equal(canonical.dataLocations.protectedRoots.length, 2);
  } finally {
    harness.cleanup();
  }
});

test('LocalConfigLoader - 14. protectedRoots non-empty', () => {
  const harness = createTempHarness();
  try {
    const badConfig = JSON.parse(JSON.stringify(harness.validConfig));
    badConfig.dataLocations.protectedRoots = [];
    assert.throws(
      () => validateStartupDataLocations(badConfig),
      /protectedRoots must contain at least one directory path/
    );
  } finally {
    harness.cleanup();
  }
});

test('LocalConfigLoader - 15. missing protected root rejected', () => {
  const harness = createTempHarness();
  try {
    const badConfig = JSON.parse(JSON.stringify(harness.validConfig));
    badConfig.dataLocations.protectedRoots = [
      path.join(harness.externalDir, 'nonexistent-protected'),
    ];
    assert.throws(
      () => validateStartupDataLocations(badConfig),
      /Configured protected root \[0\] does not exist or cannot be accessed/
    );
  } finally {
    harness.cleanup();
  }
});

test('LocalConfigLoader - 16. protected root file instead of directory rejected', () => {
  const harness = createTempHarness();
  try {
    const regularFile = path.join(harness.externalDir, 'protected-file.txt');
    fs.writeFileSync(regularFile, 'hello', 'utf8');

    const badConfig = JSON.parse(JSON.stringify(harness.validConfig));
    badConfig.dataLocations.protectedRoots = [regularFile];
    assert.throws(
      () => validateStartupDataLocations(badConfig),
      /Configured protected root \[0\] must be a directory/
    );
  } finally {
    harness.cleanup();
  }
});

test('LocalConfigLoader - 17. returned canonical paths use realpath', () => {
  const harness = createTempHarness();
  try {
    const canonical = validateStartupDataLocations(harness.validConfig);
    assert.equal(canonical.dataLocations.archiveRoot, fs.realpathSync(harness.dataDirs.archiveRoot));
    assert.equal(canonical.dataLocations.stateRoot, fs.realpathSync(harness.dataDirs.stateRoot));
    assert.equal(canonical.dataLocations.logsRoot, fs.realpathSync(harness.dataDirs.logsRoot));
    assert.equal(canonical.dataLocations.attachmentTempRoot, fs.realpathSync(harness.dataDirs.attachmentTempRoot));
    for (let i = 0; i < harness.dataDirs.protectedRoots.length; i++) {
      assert.equal(
        canonical.dataLocations.protectedRoots[i],
        fs.realpathSync(harness.dataDirs.protectedRoots[i])
      );
    }
  } finally {
    harness.cleanup();
  }
});

test('LocalConfigLoader - 18. input config object not mutated', () => {
  const harness = createTempHarness();
  try {
    const input = JSON.parse(JSON.stringify(harness.validConfig));
    Object.freeze(input);
    Object.freeze(input.dataLocations);
    Object.freeze(input.dataLocations.protectedRoots);

    const canonical = validateStartupDataLocations(input);
    assert.notStrictEqual(canonical, input);
    assert.notStrictEqual(canonical.dataLocations, input.dataLocations);
    assert.notStrictEqual(canonical.dataLocations.protectedRoots, input.dataLocations.protectedRoots);
  } finally {
    harness.cleanup();
  }
});

test('LocalConfigLoader - 19. no directory is auto-created', () => {
  const harness = createTempHarness();
  try {
    const nonExistentPath = path.join(harness.externalDir, 'never-created-dir');
    assert.strictEqual(fs.existsSync(nonExistentPath), false);

    const badConfig = JSON.parse(JSON.stringify(harness.validConfig));
    badConfig.dataLocations.archiveRoot = nonExistentPath;

    assert.throws(
      () => validateStartupDataLocations(badConfig),
      /Configured data location 'archiveRoot' does not exist or cannot be accessed/
    );

    // Explicitly verify the directory was NOT created
    assert.strictEqual(fs.existsSync(nonExistentPath), false);
  } finally {
    harness.cleanup();
  }
});

test('LocalConfigLoader - 20. template config.example.json cannot be used as production config', () => {
  const harness = createTempHarness();
  try {
    const actualRepoRoot = path.resolve(__dirname, '..', '..', '..');
    const templateInRepo = path.resolve(__dirname, '..', 'config.example.json');
    assert.ok(fs.existsSync(templateInRepo), 'config.example.json must exist in repo');

    // 1. Attempting to load template from within actual repoRoot is rejected as inside repo
    assert.throws(
      () => loadDataLocationConfigFromFile(templateInRepo, { repoRoot: actualRepoRoot }),
      /Configuration file must be repo-external/
    );

    // 2. Even if copied outside repo, placeholder paths are not absolute and fail Wave 2C schema
    const externalCopy = path.join(harness.externalDir, 'config.example.copy.json');
    fs.copyFileSync(templateInRepo, externalCopy);

    assert.throws(
      () => loadDataLocationConfigFromFile(externalCopy, { repoRoot: actualRepoRoot }),
      /must be an absolute path: received '__ARCHIVE_ROOT__'/
    );
  } finally {
    harness.cleanup();
  }
});

test('LocalConfigLoader - 21. loadDataLocationConfigFromFile with validateStartupLocations=true returns canonical paths', () => {
  const harness = createTempHarness();
  try {
    const canonical = loadDataLocationConfigFromFile(harness.validConfigFile, {
      repoRoot: harness.repoRoot,
      validateStartupLocations: true,
    });
    assert.ok(canonical);
    assert.equal(canonical.dataLocations.archiveRoot, fs.realpathSync(harness.dataDirs.archiveRoot));
  } finally {
    harness.cleanup();
  }
});
