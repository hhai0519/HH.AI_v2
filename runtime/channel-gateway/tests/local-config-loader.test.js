/**
 * runtime/channel-gateway/tests/local-config-loader.test.js
 *
 * Unit tests for Repo-External Config Loader + Startup Path Validation (ADR-0022 D24 / ADR-0025).
 * Uses synthetic temp fixtures only; cleanups in try/finally blocks.
 */

'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');

const {
  KNOWN_FOLDER_RESOLVE_TIMEOUT_MS,
  resolveWindowsKnownFolders,
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
    schemaVersion: 2,
    dataLocations: dataDirs,
    gateway: {
      localPort: 3003,
    },
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

// ==========================================
// Existing Wave 2C / 2D Regression Invariants
// ==========================================

test('LocalConfigLoader - 1. valid repo-external config loads', () => {
  const harness = createTempHarness();
  try {
    const config = loadDataLocationConfigFromFile(harness.validConfigFile, {
      repoRoot: harness.repoRoot,
    });
    assert.ok(config);
    assert.equal(config.schemaVersion, 4);
    assert.equal(config.dataLocations.archiveRoot, harness.dataDirs.archiveRoot);
    assert.equal(config.dataLocations.attachmentTempRoot, harness.dataDirs.attachmentTempRoot);
    assert.equal(config.dataLocations.stateRoot, harness.dataDirs.stateRoot);
    assert.equal(config.dataLocations.logsRoot, harness.dataDirs.logsRoot);
    assert.equal(config.dataLocations.protectedRoots.length, 2);
    assert.equal(config.gateway.localPort, 3003);
    assert.deepEqual(config.backup, {
      maxTotalBytes: 1_000_000_000,
      minKeepCount: 3,
    });
    assert.deepEqual(config.accounts, {
      telegram: [],
    });
  } finally {
    harness.cleanup();
  }
});

test('LocalConfigLoader - 2. valid loaded config passes schema v2', () => {
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

test('LocalConfigLoader - 5. configPath directory rejected', () => {
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
    fs.writeFileSync(malformedFile, '{ schemaVersion: 2, unquotedKey: true, }', 'utf8');
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

test('LocalConfigLoader - 11. file used where directory expected fails startup validation', () => {
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
    assert.equal(canonical.schemaVersion, 4);
    assert.equal(canonical.dataLocations.archiveRoot, fs.realpathSync(harness.dataDirs.archiveRoot));
    assert.equal(canonical.dataLocations.attachmentTempRoot, fs.realpathSync(harness.dataDirs.attachmentTempRoot));
    assert.equal(canonical.dataLocations.stateRoot, fs.realpathSync(harness.dataDirs.stateRoot));
    assert.equal(canonical.dataLocations.logsRoot, fs.realpathSync(harness.dataDirs.logsRoot));
    assert.equal(canonical.dataLocations.protectedRoots.length, 2);
    assert.equal(canonical.gateway.localPort, 3003);
    assert.deepEqual(canonical.backup, {
      maxTotalBytes: 1_000_000_000,
      minKeepCount: 3,
    });
    assert.deepEqual(canonical.accounts, {
      telegram: [],
    });
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
    assert.equal(canonical.gateway.localPort, 3003);
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
    Object.freeze(input.gateway);

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

    // 2. Even if copied outside repo, placeholder paths are not absolute and fail schema
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
    assert.equal(canonical.gateway.localPort, 3003);
  } finally {
    harness.cleanup();
  }
});

// ==========================================
// C. Known-Folder Resolver (Synthetic / Injected)
// ==========================================

test('LocalConfigLoader - 22. Known-Folder resolver: valid payload accepted', () => {
  let capturedOptions = null;
  let capturedArgs = null;
  const mockSpawnSync = (cmd, args, opts) => {
    capturedArgs = args;
    capturedOptions = opts;
    return {
      status: 0,
      stdout: Buffer.from(
        JSON.stringify({
          DesktopDirectory: 'C:\\Synthetic\\Desktop',
          LocalApplicationData: 'C:\\Synthetic\\AppData\\Local',
        })
      ),
    };
  };

  const result = resolveWindowsKnownFolders({
    platform: 'win32',
    powershellPath: process.execPath,
    spawnSync: mockSpawnSync,
  });

  assert.equal(result.desktopDirectory, 'C:\\Synthetic\\Desktop');
  assert.equal(result.localApplicationData, 'C:\\Synthetic\\AppData\\Local');

  // Verify invariants on execution parameters
  assert.equal(KNOWN_FOLDER_RESOLVE_TIMEOUT_MS, 60000);
  assert.equal(capturedOptions.shell, false);
  assert.equal(capturedOptions.windowsHide, true);
  assert.equal(capturedOptions.timeout, 60000);
  assert.ok(Array.isArray(capturedArgs));
  assert.ok(capturedArgs.includes('-NoProfile'));
  assert.ok(capturedArgs.includes('-File'));

  // Verify minimal non-secret child environment (no USERPROFILE or LOCALAPPDATA as authority)
  assert.strictEqual(capturedOptions.env.USERPROFILE, undefined);
  assert.strictEqual(capturedOptions.env.LOCALAPPDATA, undefined);
  assert.ok(capturedOptions.env.SystemRoot);
});

test('LocalConfigLoader - 23. Known-Folder resolver: empty DesktopDirectory fails closed', () => {
  const mockSpawnSync = () => ({
    status: 0,
    stdout: Buffer.from(
      JSON.stringify({
        DesktopDirectory: '   ',
        LocalApplicationData: 'C:\\Synthetic\\AppData\\Local',
      })
    ),
  });

  assert.throws(
    () =>
      resolveWindowsKnownFolders({
        platform: 'win32',
        powershellPath: process.execPath,
        spawnSync: mockSpawnSync,
      }),
    /Windows Known-Folder bridge returned empty or invalid DesktopDirectory/
  );
});

test('LocalConfigLoader - 24. Known-Folder resolver: empty LocalApplicationData fails closed', () => {
  const mockSpawnSync = () => ({
    status: 0,
    stdout: Buffer.from(
      JSON.stringify({
        DesktopDirectory: 'C:\\Synthetic\\Desktop',
        LocalApplicationData: '',
      })
    ),
  });

  assert.throws(
    () =>
      resolveWindowsKnownFolders({
        platform: 'win32',
        powershellPath: process.execPath,
        spawnSync: mockSpawnSync,
      }),
    /Windows Known-Folder bridge returned empty or invalid LocalApplicationData/
  );
});

test('LocalConfigLoader - 25. Known-Folder resolver: malformed JSON fails closed', () => {
  const mockSpawnSync = () => ({
    status: 0,
    stdout: Buffer.from('{ not-valid-json }'),
  });

  assert.throws(
    () =>
      resolveWindowsKnownFolders({
        platform: 'win32',
        powershellPath: process.execPath,
        spawnSync: mockSpawnSync,
      }),
    /Failed to parse Windows Known-Folder bridge output as JSON/
  );
});

test('LocalConfigLoader - 26. Known-Folder resolver: non-zero exit status fails closed', () => {
  const mockSpawnSync = () => ({
    status: 1,
    stdout: Buffer.from(''),
  });

  assert.throws(
    () =>
      resolveWindowsKnownFolders({
        platform: 'win32',
        powershellPath: process.execPath,
        spawnSync: mockSpawnSync,
      }),
    /Windows Known-Folder resolution bridge exited with non-zero status \(1\)/
  );
});

test('LocalConfigLoader - 27. Known-Folder resolver: spawn error fails closed', () => {
  const mockSpawnSync = () => ({
    error: new Error('Command failed'),
  });

  assert.throws(
    () =>
      resolveWindowsKnownFolders({
        platform: 'win32',
        powershellPath: process.execPath,
        spawnSync: mockSpawnSync,
      }),
    /Error executing Windows Known-Folder resolution bridge/
  );
});

test('LocalConfigLoader - 28. Known-Folder resolver: timeout / ETIMEDOUT fails closed', () => {
  const mockSpawnSync = () => ({
    error: Object.assign(new Error('Timed out'), { code: 'ETIMEDOUT' }),
  });

  assert.throws(
    () =>
      resolveWindowsKnownFolders({
        platform: 'win32',
        powershellPath: process.execPath,
        spawnSync: mockSpawnSync,
      }),
    /Windows Known-Folder resolution bridge timed out/
  );
});

test('LocalConfigLoader - 29. Known-Folder resolver: non-absolute returned path fails closed', () => {
  const mockSpawn1 = () => ({
    status: 0,
    stdout: Buffer.from(
      JSON.stringify({
        DesktopDirectory: 'relative\\desktop',
        LocalApplicationData: 'C:\\Synthetic\\AppData\\Local',
      })
    ),
  });
  assert.throws(
    () =>
      resolveWindowsKnownFolders({
        platform: 'win32',
        powershellPath: process.execPath,
        spawnSync: mockSpawn1,
      }),
    /Windows Known-Folder bridge returned non-absolute DesktopDirectory/
  );

  const mockSpawn2 = () => ({
    status: 0,
    stdout: Buffer.from(
      JSON.stringify({
        DesktopDirectory: 'C:\\Synthetic\\Desktop',
        LocalApplicationData: 'relative\\appdata',
      })
    ),
  });
  assert.throws(
    () =>
      resolveWindowsKnownFolders({
        platform: 'win32',
        powershellPath: process.execPath,
        spawnSync: mockSpawn2,
      }),
    /Windows Known-Folder bridge returned non-absolute LocalApplicationData/
  );
});

test('LocalConfigLoader - 30. Known-Folder resolver: raw stdout/stderr not reflected in thrown error', () => {
  const SENSITIVE_TOKEN = 'DO_NOT_LEAK_IN_EXCEPTION_MESSAGE';
  const mockSpawnSync = () => ({
    status: 1,
    stdout: Buffer.from(SENSITIVE_TOKEN),
    stderr: Buffer.from(SENSITIVE_TOKEN),
  });

  try {
    resolveWindowsKnownFolders({
      platform: 'win32',
      powershellPath: process.execPath,
      spawnSync: mockSpawnSync,
    });
    assert.fail('Should have thrown an error');
  } catch (err) {
    assert.ok(!err.message.includes(SENSITIVE_TOKEN), 'Exception message must not reflect raw stdout/stderr');
  }
});

test('LocalConfigLoader - Known-Folder resolver: nonexistent powershellPath fails closed before spawn', () => {
  let spawnInvoked = false;
  const mockSpawnSync = () => {
    spawnInvoked = true;
    return {
      status: 0,
      stdout: Buffer.from(
        JSON.stringify({
          DesktopDirectory: 'C:\\Synthetic\\Desktop',
          LocalApplicationData: 'C:\\Synthetic\\AppData\\Local',
        })
      ),
    };
  };

  const deterministicNonexistentPath = path.join(
    os.tmpdir(),
    'hhai-synthetic-nonexistent-powershell',
    'powershell.exe'
  );
  assert.strictEqual(fs.existsSync(deterministicNonexistentPath), false);

  assert.throws(
    () =>
      resolveWindowsKnownFolders({
        platform: 'win32',
        powershellPath: deterministicNonexistentPath,
        spawnSync: mockSpawnSync,
      }),
    /PowerShell executable does not exist/
  );

  assert.strictEqual(spawnInvoked, false, 'spawnSync must not be called when executable does not exist');
});

// ==========================================
// D. Default Fill Behavior
// ==========================================

test('LocalConfigLoader - 31. Windows missing singletons defaulted from Known Folders', () => {
  const harness = createTempHarness();
  try {
    const partialConfig = {
      schemaVersion: 2,
      dataLocations: {
        protectedRoots: ['C:\\Synthetic\\Protected'],
      },
      gateway: {
        localPort: 3003,
      },
    };
    const configFile = path.join(harness.externalDir, 'partial-config.json');
    fs.writeFileSync(configFile, JSON.stringify(partialConfig, null, 2), 'utf8');

    const mockSpawnSync = () => ({
      status: 0,
      stdout: Buffer.from(
        JSON.stringify({
          DesktopDirectory: 'C:\\Synthetic\\Desktop',
          LocalApplicationData: 'C:\\Synthetic\\AppData\\Local',
        })
      ),
    });

    const loaded = loadDataLocationConfigFromFile(configFile, {
      repoRoot: harness.repoRoot,
      platform: 'win32',
      powershellPath: process.execPath,
      spawnSync: mockSpawnSync,
    });

    assert.equal(loaded.dataLocations.archiveRoot, 'C:\\Synthetic\\Desktop\\HH.AI_v2_對話紀錄');
    assert.equal(
      loaded.dataLocations.attachmentTempRoot,
      'C:\\Synthetic\\AppData\\Local\\HH.AI_v2\\channel-gateway\\attachments'
    );
    assert.equal(
      loaded.dataLocations.stateRoot,
      'C:\\Synthetic\\AppData\\Local\\HH.AI_v2\\channel-gateway\\state'
    );
    assert.equal(
      loaded.dataLocations.logsRoot,
      'C:\\Synthetic\\AppData\\Local\\HH.AI_v2\\channel-gateway\\logs'
    );
    assert.equal(loaded.dataLocations.protectedRoots[0], 'C:\\Synthetic\\Protected');
    assert.equal(loaded.gateway.localPort, 3003);
  } finally {
    harness.cleanup();
  }
});

test('LocalConfigLoader - 32. explicit configured path takes precedence over default', () => {
  const harness = createTempHarness();
  try {
    const partialConfig = {
      schemaVersion: 2,
      dataLocations: {
        archiveRoot: 'C:\\Custom\\Archive',
        protectedRoots: ['C:\\Synthetic\\Protected'],
      },
      gateway: {
        localPort: 3003,
      },
    };
    const configFile = path.join(harness.externalDir, 'precedence-config.json');
    fs.writeFileSync(configFile, JSON.stringify(partialConfig, null, 2), 'utf8');

    const mockSpawnSync = () => ({
      status: 0,
      stdout: Buffer.from(
        JSON.stringify({
          DesktopDirectory: 'C:\\Synthetic\\Desktop',
          LocalApplicationData: 'C:\\Synthetic\\AppData\\Local',
        })
      ),
    });

    const loaded = loadDataLocationConfigFromFile(configFile, {
      repoRoot: harness.repoRoot,
      platform: 'win32',
      powershellPath: process.execPath,
      spawnSync: mockSpawnSync,
    });

    // Explicit path must NOT be overwritten
    assert.equal(loaded.dataLocations.archiveRoot, 'C:\\Custom\\Archive');
    // Missing singletons are filled
    assert.equal(
      loaded.dataLocations.stateRoot,
      'C:\\Synthetic\\AppData\\Local\\HH.AI_v2\\channel-gateway\\state'
    );
  } finally {
    harness.cleanup();
  }
});

test('LocalConfigLoader - 33. all explicit fields present -> resolver not invoked', () => {
  const harness = createTempHarness();
  try {
    let resolverInvoked = false;
    const mockSpawnSync = () => {
      resolverInvoked = true;
      throw new Error('Resolver should not be invoked when all fields are present');
    };

    const loaded = loadDataLocationConfigFromFile(harness.validConfigFile, {
      repoRoot: harness.repoRoot,
      platform: 'win32',
      spawnSync: mockSpawnSync,
    });

    assert.equal(resolverInvoked, false);
    assert.equal(loaded.dataLocations.archiveRoot, harness.dataDirs.archiveRoot);
  } finally {
    harness.cleanup();
  }
});

test('LocalConfigLoader - 34. protectedRoots has no default (fails closed if missing)', () => {
  const harness = createTempHarness();
  try {
    const configWithoutProtected = {
      schemaVersion: 2,
      dataLocations: {},
      gateway: {
        localPort: 3003,
      },
    };
    const configFile = path.join(harness.externalDir, 'missing-protected.json');
    fs.writeFileSync(configFile, JSON.stringify(configWithoutProtected, null, 2), 'utf8');

    const mockSpawnSync = () => ({
      status: 0,
      stdout: Buffer.from(
        JSON.stringify({
          DesktopDirectory: 'C:\\Synthetic\\Desktop',
          LocalApplicationData: 'C:\\Synthetic\\AppData\\Local',
        })
      ),
    });

    assert.throws(
      () =>
        loadDataLocationConfigFromFile(configFile, {
          repoRoot: harness.repoRoot,
          platform: 'win32',
          powershellPath: process.execPath,
          spawnSync: mockSpawnSync,
        }),
      /Missing required dataLocations field: 'protectedRoots'/
    );
  } finally {
    harness.cleanup();
  }
});

test('LocalConfigLoader - 35. gateway.localPort has no default (fails closed if missing)', () => {
  const harness = createTempHarness();
  try {
    const configWithoutGateway = {
      schemaVersion: 2,
      dataLocations: {
        protectedRoots: ['C:\\Synthetic\\Protected'],
      },
    };
    const configFile = path.join(harness.externalDir, 'missing-gateway.json');
    fs.writeFileSync(configFile, JSON.stringify(configWithoutGateway, null, 2), 'utf8');

    const mockSpawnSync = () => ({
      status: 0,
      stdout: Buffer.from(
        JSON.stringify({
          DesktopDirectory: 'C:\\Synthetic\\Desktop',
          LocalApplicationData: 'C:\\Synthetic\\AppData\\Local',
        })
      ),
    });

    assert.throws(
      () =>
        loadDataLocationConfigFromFile(configFile, {
          repoRoot: harness.repoRoot,
          platform: 'win32',
          powershellPath: process.execPath,
          spawnSync: mockSpawnSync,
        }),
      /Missing required field: gateway/
    );
  } finally {
    harness.cleanup();
  }
});

test('LocalConfigLoader - 36. non-win32 platform: missing singleton fails closed without default', () => {
  const harness = createTempHarness();
  try {
    const partialConfig = {
      schemaVersion: 2,
      dataLocations: {
        protectedRoots: ['/opt/protected'],
      },
      gateway: {
        localPort: 3003,
      },
    };
    const configFile = path.join(harness.externalDir, 'posix-partial.json');
    fs.writeFileSync(configFile, JSON.stringify(partialConfig, null, 2), 'utf8');

    assert.throws(
      () =>
        loadDataLocationConfigFromFile(configFile, {
          repoRoot: harness.repoRoot,
          platform: 'linux',
        }),
      /Missing required dataLocations field: 'archiveRoot'/
    );
  } finally {
    harness.cleanup();
  }
});

test('LocalConfigLoader - 37. default resolution does not auto-create directory and fails startup validation if missing', () => {
  const harness = createTempHarness();
  try {
    const nonExistentDesktop = path.join(harness.externalDir, 'synthetic-desktop-uncreated');
    assert.strictEqual(fs.existsSync(nonExistentDesktop), false);

    const partialConfig = {
      schemaVersion: 2,
      dataLocations: {
        protectedRoots: [harness.dataDirs.protectedRoots[0]],
      },
      gateway: {
        localPort: 3003,
      },
    };
    const configFile = path.join(harness.externalDir, 'uncreated-default.json');
    fs.writeFileSync(configFile, JSON.stringify(partialConfig, null, 2), 'utf8');

    const mockSpawnSync = () => ({
      status: 0,
      stdout: Buffer.from(
        JSON.stringify({
          DesktopDirectory: nonExistentDesktop,
          LocalApplicationData: harness.dataDirs.attachmentTempRoot,
        })
      ),
    });

    // Default resolution alone produces the path without creating directory
    const resolved = loadDataLocationConfigFromFile(configFile, {
      repoRoot: harness.repoRoot,
      platform: 'win32',
      powershellPath: process.execPath,
      spawnSync: mockSpawnSync,
      validateStartupLocations: false,
    });
    assert.ok(resolved.dataLocations.archiveRoot.includes('synthetic-desktop-uncreated'));
    // Directory was NOT auto-created
    assert.strictEqual(fs.existsSync(nonExistentDesktop), false);

    // Startup validation fails closed because directory does not exist
    assert.throws(
      () =>
        loadDataLocationConfigFromFile(configFile, {
          repoRoot: harness.repoRoot,
          platform: 'win32',
          powershellPath: process.execPath,
          spawnSync: mockSpawnSync,
          validateStartupLocations: true,
        }),
      /Configured data location 'archiveRoot' does not exist or cannot be accessed/
    );

    // Still NOT created
    assert.strictEqual(fs.existsSync(nonExistentDesktop), false);
  } finally {
    harness.cleanup();
  }
});

// ==========================================
// E. Live Bridge Integration
// ==========================================

test('LocalConfigLoader - 38. Live Windows bridge integration', () => {
  if (process.platform === 'win32') {
    const result = resolveWindowsKnownFolders();
    assert.ok(result, 'Result should be returned');
    assert.ok(typeof result.desktopDirectory === 'string', 'DesktopDirectory should be string');
    assert.ok(result.desktopDirectory.length > 0, 'DesktopDirectory should not be empty');
    assert.ok(path.win32.isAbsolute(result.desktopDirectory), 'DesktopDirectory should be absolute');
    assert.ok(typeof result.localApplicationData === 'string', 'LocalApplicationData should be string');
    assert.ok(result.localApplicationData.length > 0, 'LocalApplicationData should not be empty');
    assert.ok(path.win32.isAbsolute(result.localApplicationData), 'LocalApplicationData should be absolute');
  } else {
    // On non-win32 platforms, verify platform guard without calling PowerShell and without test skip
    assert.throws(
      () => resolveWindowsKnownFolders({ platform: 'linux' }),
      /Known-Folder resolution is only supported on win32/
    );
  }
});

// ==========================================
// F. TG-MVP-09A: Schema v3 & Location Guard Invariants
// ==========================================

test('LocalConfigLoader - 39. v3 config with explicit backup loads and preserves overrides', () => {
  const harness = createTempHarness();
  try {
    const configV3 = {
      schemaVersion: 3,
      dataLocations: harness.validConfig.dataLocations,
      gateway: harness.validConfig.gateway,
      backup: {
        maxTotalBytes: 500_000_000,
        minKeepCount: 5,
      },
    };
    const configFile = path.join(harness.externalDir, 'config-v3.json');
    fs.writeFileSync(configFile, JSON.stringify(configV3, null, 2), 'utf8');

    const loaded = loadDataLocationConfigFromFile(configFile, {
      repoRoot: harness.repoRoot,
    });
    assert.equal(loaded.schemaVersion, 4);
    assert.deepEqual(loaded.backup, {
      maxTotalBytes: 500_000_000,
      minKeepCount: 5,
    });
    assert.deepEqual(loaded.accounts, {
      telegram: [],
    });
  } finally {
    harness.cleanup();
  }
});

test('LocalConfigLoader - 40. v2 config declaring top-level backup is rejected fail-closed', () => {
  const harness = createTempHarness();
  try {
    const badV2 = {
      schemaVersion: 2,
      dataLocations: harness.validConfig.dataLocations,
      gateway: harness.validConfig.gateway,
      backup: {
        maxTotalBytes: 1_000_000_000,
      },
    };
    const configFile = path.join(harness.externalDir, 'bad-v2.json');
    fs.writeFileSync(configFile, JSON.stringify(badV2, null, 2), 'utf8');

    assert.throws(
      () =>
        loadDataLocationConfigFromFile(configFile, {
          repoRoot: harness.repoRoot,
        }),
      /Unknown top-level configuration key: 'backup'/
    );
  } finally {
    harness.cleanup();
  }
});

test('LocalConfigLoader - 41. stateRoot location guard: stateRoot inside OneDrive rejected during startup validation', () => {
  const harness = createTempHarness();
  try {
    const oneDriveStateDir = path.join(harness.externalDir, 'OneDrive', 'GatewayState');
    fs.mkdirSync(oneDriveStateDir, { recursive: true });

    const badConfig = {
      ...harness.validConfig,
      dataLocations: {
        ...harness.validConfig.dataLocations,
        stateRoot: oneDriveStateDir,
      },
    };

    assert.throws(
      () => validateStartupDataLocations(badConfig),
      /stateRoot must not reside within a synchronized folder \('OneDrive'\)/
    );
  } finally {
    harness.cleanup();
  }
});

test('LocalConfigLoader - 42. stateRoot location guard: stateRoot inside Dropbox / GoogleDrive rejected', () => {
  const harness = createTempHarness();
  try {
    const dropboxStateDir = path.join(harness.externalDir, 'Dropbox', 'GatewayState');
    fs.mkdirSync(dropboxStateDir, { recursive: true });

    const badConfig = {
      ...harness.validConfig,
      dataLocations: {
        ...harness.validConfig.dataLocations,
        stateRoot: dropboxStateDir,
      },
    };

    assert.throws(
      () => validateStartupDataLocations(badConfig),
      /stateRoot must not reside within a synchronized folder \('Dropbox'\)/
    );
  } finally {
    harness.cleanup();
  }
});

test('LocalConfigLoader - 43. stateRoot location guard: stateRoot UNC path rejected during startup validation', () => {
  const harness = createTempHarness();
  try {
    const badConfig = {
      ...harness.validConfig,
      dataLocations: {
        ...harness.validConfig.dataLocations,
        stateRoot: '\\\\fileserver\\share\\gateway\\state',
      },
    };

    assert.throws(
      () => validateStartupDataLocations(badConfig),
      /stateRoot must not be a UNC network path/
    );
  } finally {
    harness.cleanup();
  }
});

test('LocalConfigLoader - 44. stateRoot location guard: archiveRoot inside OneDrive redirected Desktop is ACCEPTED', () => {
  const harness = createTempHarness();
  try {
    // archiveRoot in OneDrive/Desktop is allowed; stateRoot is in safe local directory
    const oneDriveDesktopArchiveDir = path.join(harness.externalDir, 'OneDrive', 'Desktop', 'HH.AI_v2_Archive');
    fs.mkdirSync(oneDriveDesktopArchiveDir, { recursive: true });

    const validArchiveOneDriveConfig = {
      ...harness.validConfig,
      dataLocations: {
        ...harness.validConfig.dataLocations,
        archiveRoot: oneDriveDesktopArchiveDir,
      },
    };

    const canonical = validateStartupDataLocations(validArchiveOneDriveConfig);
    assert.ok(canonical);
    assert.equal(canonical.dataLocations.archiveRoot, fs.realpathSync(oneDriveDesktopArchiveDir));
    assert.equal(canonical.dataLocations.stateRoot, fs.realpathSync(harness.dataDirs.stateRoot));
  } finally {
    harness.cleanup();
  }
});

test('LocalConfigLoader - 45. stateRoot canonical realpath sync-root canary (M10): nominal safe link resolving to OneDrive target is rejected', () => {
  const harness = createTempHarness();
  try {
    const oneDriveStateTarget = path.join(harness.externalDir, 'OneDrive', 'StateTarget');
    fs.mkdirSync(oneDriveStateTarget, { recursive: true });

    const safeStateLink = path.join(harness.externalDir, 'safe-state-link');
    fs.symlinkSync(
      oneDriveStateTarget,
      safeStateLink,
      process.platform === 'win32' ? 'junction' : 'dir'
    );

    // 1. Nominal check passes: path string itself contains no OneDrive or sync segment
    const { assertSafeStateRootLocation } = require('../core/data-location-config');
    assert.doesNotThrow(() => {
      assertSafeStateRootLocation(safeStateLink);
    });

    // 2. Realpath resolves into OneDrive
    const canonicalTarget = fs.realpathSync(safeStateLink);
    assert.ok(
      canonicalTarget.includes('OneDrive'),
      `Canonical target must resolve to OneDrive, got: ${canonicalTarget}`
    );

    const badConfig = {
      ...harness.validConfig,
      dataLocations: {
        ...harness.validConfig.dataLocations,
        stateRoot: safeStateLink,
      },
    };

    // 3. Startup validation fails after realpathSync
    assert.throws(
      () => validateStartupDataLocations(badConfig),
      /stateRoot must not reside within a synchronized folder \('OneDrive'\)/
    );
  } finally {
    harness.cleanup();
  }
});

test('LocalConfigLoader - 46. v4 config with accounts loads and preserves metadata', () => {
  const harness = createTempHarness();
  try {
    const configV4 = {
      schemaVersion: 4,
      dataLocations: harness.validConfig.dataLocations,
      gateway: { localPort: 3003 },
      backup: { maxTotalBytes: 500_000_000, minKeepCount: 5 },
      accounts: {
        telegram: [
          {
            id: 'test-bot-01',
            label: 'Test Bot',
            description: 'Synthetic test bot',
            enabled: true,
          },
        ],
      },
    };
    const configFile = path.join(harness.externalDir, 'config-v4.json');
    fs.writeFileSync(configFile, JSON.stringify(configV4, null, 2), 'utf8');

    const loaded = loadDataLocationConfigFromFile(configFile, {
      repoRoot: harness.repoRoot,
    });
    assert.equal(loaded.schemaVersion, 4);
    assert.deepEqual(loaded.accounts, {
      telegram: [
        {
          id: 'test-bot-01',
          label: 'Test Bot',
          description: 'Synthetic test bot',
          enabled: true,
        },
      ],
    });
  } finally {
    harness.cleanup();
  }
});

