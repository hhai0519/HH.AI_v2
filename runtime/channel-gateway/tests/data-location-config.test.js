/**
 * runtime/channel-gateway/tests/data-location-config.test.js
 *
 * Unit tests for Data Location & Gateway Config Contract (ADR-0022 D24 / ADR-0023 / TG-MVP-09A).
 * Pure domain validation tests with synthetic data only.
 */

'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const {
  CURRENT_SCHEMA_VERSION,
  LEGACY_SUPPORTED_SCHEMA_VERSION,
  DATA_LOCATION_SCHEMA_VERSION,
  CANONICAL_GATEWAY_PORT,
  DEFAULT_MAX_TOTAL_BYTES,
  DEFAULT_MIN_KEEP_COUNT,
  validateResolvedDataLocationConfig,
  isAbsolutePath,
  assertSafeStateRootLocation,
} = require('../core/data-location-config');

const VALID_WINDOWS_CONFIG_V2 = {
  schemaVersion: 2,
  dataLocations: {
    archiveRoot: 'C:\\Users\\Synthetic\\Desktop\\HH.AI_v2_Archive',
    attachmentTempRoot: 'C:\\Users\\Synthetic\\AppData\\Local\\Temp\\hh-ai-attachments',
    stateRoot: 'C:\\Users\\Synthetic\\AppData\\Local\\hh-ai-gateway\\state',
    logsRoot: 'C:\\Users\\Synthetic\\AppData\\Local\\hh-ai-gateway\\logs',
    protectedRoots: [
      'C:\\Users\\Synthetic\\Projects\\HH.AI_v2',
      'C:\\Users\\Synthetic\\Projects\\HH.AI_Legacy',
      'C:\\Users\\Synthetic\\.gemini',
    ],
  },
  gateway: {
    localPort: 3003,
  },
};

const VALID_POSIX_CONFIG_V3 = {
  schemaVersion: 3,
  dataLocations: {
    archiveRoot: '/var/data/hh-ai/archive',
    attachmentTempRoot: '/tmp/hh-ai-attachments',
    stateRoot: '/var/lib/hh-ai-gateway/state',
    logsRoot: '/var/log/hh-ai-gateway',
    protectedRoots: [
      '/opt/hh-ai-v2',
      '/opt/legacy-repo',
      '/home/synthetic/.config/hh-ai',
    ],
  },
  gateway: {
    localPort: 3003,
  },
  backup: {
    maxTotalBytes: 500_000_000,
    minKeepCount: 5,
  },
};

test('DataLocationConfig - 1. valid Windows-style resolved v2 config accepted and normalized to v3', () => {
  const result = validateResolvedDataLocationConfig(VALID_WINDOWS_CONFIG_V2);
  assert.equal(result.schemaVersion, 3);
  assert.equal(result.dataLocations.archiveRoot, 'C:\\Users\\Synthetic\\Desktop\\HH.AI_v2_Archive');
  assert.equal(result.dataLocations.attachmentTempRoot, 'C:\\Users\\Synthetic\\AppData\\Local\\Temp\\hh-ai-attachments');
  assert.equal(result.dataLocations.stateRoot, 'C:\\Users\\Synthetic\\AppData\\Local\\hh-ai-gateway\\state');
  assert.equal(result.dataLocations.logsRoot, 'C:\\Users\\Synthetic\\AppData\\Local\\hh-ai-gateway\\logs');
  assert.equal(result.dataLocations.protectedRoots.length, 3);
  assert.equal(result.dataLocations.protectedRoots[0], 'C:\\Users\\Synthetic\\Projects\\HH.AI_v2');
  assert.equal(result.gateway.localPort, 3003);
  // v2 input automatically acquires v3 defaults
  assert.deepEqual(result.backup, {
    maxTotalBytes: 1_000_000_000,
    minKeepCount: 3,
  });
});

test('DataLocationConfig - 2. valid POSIX-style resolved v3 config accepted with backup overrides', () => {
  const result = validateResolvedDataLocationConfig(VALID_POSIX_CONFIG_V3);
  assert.equal(result.schemaVersion, 3);
  assert.equal(result.dataLocations.archiveRoot, '/var/data/hh-ai/archive');
  assert.equal(result.dataLocations.attachmentTempRoot, '/tmp/hh-ai-attachments');
  assert.equal(result.dataLocations.stateRoot, '/var/lib/hh-ai-gateway/state');
  assert.equal(result.dataLocations.logsRoot, '/var/log/hh-ai-gateway');
  assert.equal(result.dataLocations.protectedRoots.length, 3);
  assert.equal(result.dataLocations.protectedRoots[0], '/opt/hh-ai-v2');
  assert.equal(result.gateway.localPort, 3003);
  assert.deepEqual(result.backup, {
    maxTotalBytes: 500_000_000,
    minKeepCount: 5,
  });
});

test('DataLocationConfig - 3. schemaVersion 1 rejected fail-closed', () => {
  assert.throws(
    () => validateResolvedDataLocationConfig({ ...VALID_WINDOWS_CONFIG_V2, schemaVersion: 1 }),
    /Unsupported schemaVersion/
  );
});

test('DataLocationConfig - 4. wrong schemaVersion type or value rejected (v4 rejected)', () => {
  assert.throws(
    () => validateResolvedDataLocationConfig({ ...VALID_WINDOWS_CONFIG_V2, schemaVersion: 4 }),
    /Unsupported schemaVersion/
  );
  assert.throws(
    () => validateResolvedDataLocationConfig({ ...VALID_WINDOWS_CONFIG_V2, schemaVersion: '3' }),
    /Unsupported schemaVersion/
  );
  assert.throws(
    () => validateResolvedDataLocationConfig({ ...VALID_WINDOWS_CONFIG_V2, schemaVersion: 3.5 }),
    /Unsupported schemaVersion/
  );
  assert.throws(
    () => validateResolvedDataLocationConfig({ ...VALID_WINDOWS_CONFIG_V2, schemaVersion: undefined }),
    /Missing required field: schemaVersion/
  );
});

test('DataLocationConfig - 5. missing or invalid dataLocations rejected', () => {
  assert.throws(
    () => validateResolvedDataLocationConfig({ schemaVersion: 3, gateway: { localPort: 3003 } }),
    /dataLocations must be a non-null object/
  );
  assert.throws(
    () => validateResolvedDataLocationConfig({ schemaVersion: 3, dataLocations: null, gateway: { localPort: 3003 } }),
    /dataLocations must be a non-null object/
  );
  assert.throws(
    () => validateResolvedDataLocationConfig({ schemaVersion: 3, dataLocations: [], gateway: { localPort: 3003 } }),
    /dataLocations must be a non-null object/
  );
});

test('DataLocationConfig - 6. unknown top-level key rejected fail-closed', () => {
  assert.throws(
    () => validateResolvedDataLocationConfig({ ...VALID_WINDOWS_CONFIG_V2, unknownKey: 'value' }),
    /Unknown top-level configuration key/
  );
});

test('DataLocationConfig - 7. v2 config declaring top-level backup key is rejected fail-closed', () => {
  assert.throws(
    () =>
      validateResolvedDataLocationConfig({
        ...VALID_WINDOWS_CONFIG_V2,
        schemaVersion: 2,
        backup: { maxTotalBytes: 1_000_000_000 },
      }),
    /Unknown top-level configuration key: 'backup'/
  );
});

test('DataLocationConfig - 8. v3 config without backup block acquires default backup values', () => {
  const configV3NoBackup = {
    schemaVersion: 3,
    dataLocations: VALID_WINDOWS_CONFIG_V2.dataLocations,
    gateway: { localPort: 3003 },
  };
  const result = validateResolvedDataLocationConfig(configV3NoBackup);
  assert.equal(result.schemaVersion, 3);
  assert.deepEqual(result.backup, {
    maxTotalBytes: 1_000_000_000,
    minKeepCount: 3,
  });
});

test('DataLocationConfig - 9. v3 backup unknown key rejected fail-closed', () => {
  const invalid = {
    schemaVersion: 3,
    dataLocations: VALID_WINDOWS_CONFIG_V2.dataLocations,
    gateway: { localPort: 3003 },
    backup: {
      maxTotalBytes: 1_000_000_000,
      unknownOption: 123,
    },
  };
  assert.throws(
    () => validateResolvedDataLocationConfig(invalid),
    /Unknown backup configuration key: 'unknownOption'/
  );
});

test('DataLocationConfig - 10. v3 backup validation matrix: zero, negative, fractional, unsafe integer', () => {
  const base = {
    schemaVersion: 3,
    dataLocations: VALID_WINDOWS_CONFIG_V2.dataLocations,
    gateway: { localPort: 3003 },
  };

  // maxTotalBytes <= 0
  assert.throws(
    () => validateResolvedDataLocationConfig({ ...base, backup: { maxTotalBytes: 0 } }),
    /maxTotalBytes must be a positive safe integer/
  );
  assert.throws(
    () => validateResolvedDataLocationConfig({ ...base, backup: { maxTotalBytes: -100 } }),
    /maxTotalBytes must be a positive safe integer/
  );
  // fractional
  assert.throws(
    () => validateResolvedDataLocationConfig({ ...base, backup: { maxTotalBytes: 1000.5 } }),
    /maxTotalBytes must be a positive safe integer/
  );
  // unsafe integer
  assert.throws(
    () => validateResolvedDataLocationConfig({ ...base, backup: { maxTotalBytes: Number.MAX_SAFE_INTEGER + 10 } }),
    /maxTotalBytes must be a positive safe integer/
  );

  // minKeepCount < 1
  assert.throws(
    () => validateResolvedDataLocationConfig({ ...base, backup: { minKeepCount: 0 } }),
    /minKeepCount must be an integer >= 1/
  );
  assert.throws(
    () => validateResolvedDataLocationConfig({ ...base, backup: { minKeepCount: -1 } }),
    /minKeepCount must be an integer >= 1/
  );
  assert.throws(
    () => validateResolvedDataLocationConfig({ ...base, backup: { minKeepCount: 2.5 } }),
    /minKeepCount must be an integer >= 1/
  );
});

test('DataLocationConfig - 11. missing required singleton path rejected', () => {
  for (const field of ['archiveRoot', 'attachmentTempRoot', 'stateRoot', 'logsRoot']) {
    const copy = JSON.parse(JSON.stringify(VALID_WINDOWS_CONFIG_V2));
    delete copy.dataLocations[field];
    assert.throws(
      () => validateResolvedDataLocationConfig(copy),
      new RegExp(`Missing required dataLocations field: '${field}'`)
    );
  }
});

test('DataLocationConfig - 12. non-string singleton path rejected', () => {
  for (const field of ['archiveRoot', 'attachmentTempRoot', 'stateRoot', 'logsRoot']) {
    const copy = JSON.parse(JSON.stringify(VALID_WINDOWS_CONFIG_V2));
    copy.dataLocations[field] = 12345;
    assert.throws(
      () => validateResolvedDataLocationConfig(copy),
      new RegExp(`'${field}' must be a string`)
    );
  }
});

test('DataLocationConfig - 13. relative singleton path rejected', () => {
  for (const field of ['archiveRoot', 'attachmentTempRoot', 'stateRoot', 'logsRoot']) {
    const copy = JSON.parse(JSON.stringify(VALID_WINDOWS_CONFIG_V2));
    copy.dataLocations[field] = 'relative/path';
    assert.throws(
      () => validateResolvedDataLocationConfig(copy),
      new RegExp(`'${field}' must be an absolute path`)
    );
  }
});

test('DataLocationConfig - 14. protectedRoots not array rejected', () => {
  const copy = JSON.parse(JSON.stringify(VALID_WINDOWS_CONFIG_V2));
  copy.dataLocations.protectedRoots = 'not_an_array';
  assert.throws(
    () => validateResolvedDataLocationConfig(copy),
    /protectedRoots must be an array of absolute paths/
  );
});

test('DataLocationConfig - 15. protectedRoots relative path rejected', () => {
  const copy = JSON.parse(JSON.stringify(VALID_WINDOWS_CONFIG_V2));
  copy.dataLocations.protectedRoots = ['relative/path/1'];
  assert.throws(
    () => validateResolvedDataLocationConfig(copy),
    /protectedRoots\[0\] must be an absolute path/
  );
});

test('DataLocationConfig - 16. missing gateway block rejected', () => {
  const copy = JSON.parse(JSON.stringify(VALID_WINDOWS_CONFIG_V2));
  delete copy.gateway;
  assert.throws(
    () => validateResolvedDataLocationConfig(copy),
    /Missing required field: gateway/
  );
});

test('DataLocationConfig - 17. non-3003 localPort rejected', () => {
  const copy = JSON.parse(JSON.stringify(VALID_WINDOWS_CONFIG_V2));
  copy.gateway.localPort = 8080;
  assert.throws(
    () => validateResolvedDataLocationConfig(copy),
    /Invalid 'localPort': Gateway v1 strictly requires port 3003/
  );
});

test('DataLocationConfig - 18. unknown dataLocations key rejected', () => {
  const copy = JSON.parse(JSON.stringify(VALID_WINDOWS_CONFIG_V2));
  copy.dataLocations.unknownField = '/tmp/unknown';
  assert.throws(
    () => validateResolvedDataLocationConfig(copy),
    /Unknown dataLocations key: 'unknownField'/
  );
});

test('DataLocationConfig - 19. unknown gateway key rejected', () => {
  const copy = JSON.parse(JSON.stringify(VALID_WINDOWS_CONFIG_V2));
  copy.gateway.unknownSetting = true;
  assert.throws(
    () => validateResolvedDataLocationConfig(copy),
    /Unknown gateway configuration key: 'unknownSetting'/
  );
});

test('DataLocationConfig - 20. stateRoot location guard: OneDrive rejected fail-closed', () => {
  assert.throws(
    () => assertSafeStateRootLocation('C:\\Users\\User\\OneDrive\\State'),
    /must not reside within a synchronized folder \('OneDrive'\)/
  );
  assert.throws(
    () => assertSafeStateRootLocation('C:\\Users\\User\\OneDrive - Commercial\\Gateway\\State'),
    /must not reside within a synchronized folder/
  );
});

test('DataLocationConfig - 21. stateRoot location guard: Dropbox, Google Drive, iCloudDrive rejected', () => {
  assert.throws(
    () => assertSafeStateRootLocation('C:\\Users\\User\\Dropbox\\State'),
    /must not reside within a synchronized folder \('Dropbox'\)/
  );
  assert.throws(
    () => assertSafeStateRootLocation('/home/user/Google Drive/State'),
    /must not reside within a synchronized folder \('Google Drive'\)/
  );
  assert.throws(
    () => assertSafeStateRootLocation('C:\\Users\\User\\GoogleDrive\\State'),
    /must not reside within a synchronized folder \('GoogleDrive'\)/
  );
  assert.throws(
    () => assertSafeStateRootLocation('C:\\Users\\User\\iCloudDrive\\State'),
    /must not reside within a synchronized folder \('iCloudDrive'\)/
  );
});

test('DataLocationConfig - 22. stateRoot location guard: UNC and extended UNC rejected', () => {
  assert.throws(
    () => assertSafeStateRootLocation('\\\\fileserver\\share\\state'),
    /must not be a UNC network path/
  );
  assert.throws(
    () => assertSafeStateRootLocation('//fileserver/share/state'),
    /must not be a UNC network path/
  );
  assert.throws(
    () => assertSafeStateRootLocation('\\\\?\\UNC\\server\\share\\state'),
    /must not be an extended UNC network path/
  );
});

test('DataLocationConfig - 23. stateRoot location guard: safe local path passes', () => {
  assert.doesNotThrow(() =>
    assertSafeStateRootLocation('C:\\Users\\User\\AppData\\Local\\hh-ai\\state')
  );
  assert.doesNotThrow(() =>
    assertSafeStateRootLocation('/var/lib/hh-ai/state')
  );
});

test('DataLocationConfig - 24. config.example.json validation adheres to schemaVersion 3', () => {
  const templatePath = path.resolve(__dirname, '..', 'config.example.json');
  assert.ok(fs.existsSync(templatePath), 'config.example.json must exist');

  const content = fs.readFileSync(templatePath, 'utf-8');
  const template = JSON.parse(content);

  // Check valid schema structure
  assert.equal(template.schemaVersion, 3);
  assert.ok(template.dataLocations, 'dataLocations must be present');
  assert.ok(template.gateway, 'gateway must be present');
  assert.equal(template.gateway.localPort, 3003);
  assert.ok(template.backup, 'backup must be present in example');
  assert.equal(template.backup.maxTotalBytes, 1_000_000_000);
  assert.equal(template.backup.minKeepCount, 3);

  // Verify only allowlisted keys
  const topKeys = Object.keys(template);
  assert.deepEqual(topKeys.sort(), ['backup', 'dataLocations', 'gateway', 'schemaVersion']);

  const locationKeys = Object.keys(template.dataLocations);
  assert.deepEqual(
    locationKeys.sort(),
    ['archiveRoot', 'attachmentTempRoot', 'logsRoot', 'protectedRoots', 'stateRoot']
  );

  const gatewayKeys = Object.keys(template.gateway);
  assert.deepEqual(gatewayKeys, ['localPort']);

  const backupKeys = Object.keys(template.backup);
  assert.deepEqual(backupKeys.sort(), ['maxTotalBytes', 'minKeepCount']);

  // Check placeholders remain unresolved
  assert.equal(template.dataLocations.archiveRoot, '__ARCHIVE_ROOT__');
  assert.equal(template.dataLocations.attachmentTempRoot, '__ATTACHMENT_TEMP_ROOT__');
  assert.equal(template.dataLocations.stateRoot, '__STATE_ROOT__');
  assert.equal(template.dataLocations.logsRoot, '__LOGS_ROOT__');
  assert.ok(Array.isArray(template.dataLocations.protectedRoots));
  assert.ok(template.dataLocations.protectedRoots.includes('__HH_AI_V2_ROOT__'));

  // Ensure NO secrets, tokens, passwords, api keys in file content
  const lowerContent = content.toLowerCase();
  const forbiddenPatterns = [
    'bot_token',
    'bottoken',
    'secret',
    'password',
    'apikey',
    'bearer',
    'c:\\users\\hh.ai_260806',
  ];
  for (const pattern of forbiddenPatterns) {
    assert.ok(
      !lowerContent.includes(pattern),
      `config.example.json must not contain secret/machine string: ${pattern}`
    );
  }

  // Template placeholders fail isAbsolutePath (deliberate check)
  assert.ok(!isAbsolutePath(template.dataLocations.archiveRoot));
  assert.throws(
    () => validateResolvedDataLocationConfig(template),
    /must be an absolute path/
  );
});
