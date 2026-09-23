/**
 * runtime/channel-gateway/tests/data-location-config.test.js
 *
 * Unit tests for Data Location & Gateway Config Contract (ADR-0022 D24 / ADR-0025).
 * Pure domain validation tests with synthetic data only.
 */

'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const {
  DATA_LOCATION_SCHEMA_VERSION,
  CANONICAL_GATEWAY_PORT,
  validateResolvedDataLocationConfig,
  isAbsolutePath,
} = require('../core/data-location-config');

const VALID_WINDOWS_CONFIG = {
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

const VALID_POSIX_CONFIG = {
  schemaVersion: 2,
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
};

test('DataLocationConfig - 1. valid Windows-style resolved config accepted', () => {
  const result = validateResolvedDataLocationConfig(VALID_WINDOWS_CONFIG);
  assert.equal(result.schemaVersion, 2);
  assert.equal(result.dataLocations.archiveRoot, 'C:\\Users\\Synthetic\\Desktop\\HH.AI_v2_Archive');
  assert.equal(result.dataLocations.attachmentTempRoot, 'C:\\Users\\Synthetic\\AppData\\Local\\Temp\\hh-ai-attachments');
  assert.equal(result.dataLocations.stateRoot, 'C:\\Users\\Synthetic\\AppData\\Local\\hh-ai-gateway\\state');
  assert.equal(result.dataLocations.logsRoot, 'C:\\Users\\Synthetic\\AppData\\Local\\hh-ai-gateway\\logs');
  assert.equal(result.dataLocations.protectedRoots.length, 3);
  assert.equal(result.dataLocations.protectedRoots[0], 'C:\\Users\\Synthetic\\Projects\\HH.AI_v2');
  assert.equal(result.gateway.localPort, 3003);
});

test('DataLocationConfig - 2. valid POSIX-style resolved config accepted', () => {
  const result = validateResolvedDataLocationConfig(VALID_POSIX_CONFIG);
  assert.equal(result.schemaVersion, 2);
  assert.equal(result.dataLocations.archiveRoot, '/var/data/hh-ai/archive');
  assert.equal(result.dataLocations.attachmentTempRoot, '/tmp/hh-ai-attachments');
  assert.equal(result.dataLocations.stateRoot, '/var/lib/hh-ai-gateway/state');
  assert.equal(result.dataLocations.logsRoot, '/var/log/hh-ai-gateway');
  assert.equal(result.dataLocations.protectedRoots.length, 3);
  assert.equal(result.dataLocations.protectedRoots[0], '/opt/hh-ai-v2');
  assert.equal(result.gateway.localPort, 3003);
});

test('DataLocationConfig - 3. schemaVersion 1 rejected fail-closed', () => {
  assert.throws(
    () => validateResolvedDataLocationConfig({ ...VALID_WINDOWS_CONFIG, schemaVersion: 1 }),
    /Unsupported schemaVersion: expected 2, received 1/
  );
});

test('DataLocationConfig - 4. wrong schemaVersion type or value rejected', () => {
  assert.throws(
    () => validateResolvedDataLocationConfig({ ...VALID_WINDOWS_CONFIG, schemaVersion: 3 }),
    /Unsupported schemaVersion/
  );
  assert.throws(
    () => validateResolvedDataLocationConfig({ ...VALID_WINDOWS_CONFIG, schemaVersion: '2' }),
    /Unsupported schemaVersion/
  );
  assert.throws(
    () => validateResolvedDataLocationConfig({ ...VALID_WINDOWS_CONFIG, schemaVersion: 2.5 }),
    /Unsupported schemaVersion/
  );
  assert.throws(
    () => validateResolvedDataLocationConfig({ ...VALID_WINDOWS_CONFIG, schemaVersion: undefined }),
    /Missing required field: schemaVersion/
  );
});

test('DataLocationConfig - 5. missing or invalid dataLocations rejected', () => {
  assert.throws(
    () => validateResolvedDataLocationConfig({ schemaVersion: 2, gateway: { localPort: 3003 } }),
    /dataLocations must be a non-null object/
  );
  assert.throws(
    () => validateResolvedDataLocationConfig({ schemaVersion: 2, dataLocations: null, gateway: { localPort: 3003 } }),
    /dataLocations must be a non-null object/
  );
  assert.throws(
    () => validateResolvedDataLocationConfig({ schemaVersion: 2, dataLocations: [], gateway: { localPort: 3003 } }),
    /dataLocations must be a non-null object/
  );
  assert.throws(
    () => validateResolvedDataLocationConfig({ schemaVersion: 2, dataLocations: 'invalid', gateway: { localPort: 3003 } }),
    /dataLocations must be a non-null object/
  );
});

test('DataLocationConfig - 6. missing required singleton path rejected', () => {
  const fields = ['archiveRoot', 'attachmentTempRoot', 'stateRoot', 'logsRoot'];
  for (const field of fields) {
    const copy = JSON.parse(JSON.stringify(VALID_WINDOWS_CONFIG));
    delete copy.dataLocations[field];
    assert.throws(
      () => validateResolvedDataLocationConfig(copy),
      new RegExp(`Missing required dataLocations field: '${field}'`)
    );
  }
});

test('DataLocationConfig - 7. blank singleton path rejected', () => {
  const fields = ['archiveRoot', 'attachmentTempRoot', 'stateRoot', 'logsRoot'];
  for (const field of fields) {
    const copy = JSON.parse(JSON.stringify(VALID_WINDOWS_CONFIG));
    copy.dataLocations[field] = '   ';
    assert.throws(
      () => validateResolvedDataLocationConfig(copy),
      new RegExp(`'${field}' must be a non-empty string`)
    );
  }
});

test('DataLocationConfig - 8. relative singleton path rejected', () => {
  const fields = ['archiveRoot', 'attachmentTempRoot', 'stateRoot', 'logsRoot'];
  const relativePaths = ['relative/path', './subfolder', '../parent', 'data', 'temp'];
  for (const field of fields) {
    for (const rel of relativePaths) {
      const copy = JSON.parse(JSON.stringify(VALID_WINDOWS_CONFIG));
      copy.dataLocations[field] = rel;
      assert.throws(
        () => validateResolvedDataLocationConfig(copy),
        new RegExp(`'${field}' must be an absolute path: received '${rel}'`)
      );
    }
  }
});

test('DataLocationConfig - 9. protectedRoots non-array rejected', () => {
  const copyMissing = JSON.parse(JSON.stringify(VALID_WINDOWS_CONFIG));
  delete copyMissing.dataLocations.protectedRoots;
  assert.throws(
    () => validateResolvedDataLocationConfig(copyMissing),
    /Missing required dataLocations field: 'protectedRoots'/
  );

  const copyString = JSON.parse(JSON.stringify(VALID_WINDOWS_CONFIG));
  copyString.dataLocations.protectedRoots = 'C:\\Some\\Path';
  assert.throws(
    () => validateResolvedDataLocationConfig(copyString),
    /protectedRoots must be an array of absolute paths/
  );

  const copyNull = JSON.parse(JSON.stringify(VALID_WINDOWS_CONFIG));
  copyNull.dataLocations.protectedRoots = null;
  assert.throws(
    () => validateResolvedDataLocationConfig(copyNull),
    /Missing required dataLocations field: 'protectedRoots'/
  );
});

test('DataLocationConfig - 10. blank protected root rejected', () => {
  const copy = JSON.parse(JSON.stringify(VALID_WINDOWS_CONFIG));
  copy.dataLocations.protectedRoots.push('   ');
  assert.throws(
    () => validateResolvedDataLocationConfig(copy),
    /protectedRoots\[3\] must be a non-empty string/
  );
});

test('DataLocationConfig - 11. relative protected root rejected', () => {
  const copy = JSON.parse(JSON.stringify(VALID_WINDOWS_CONFIG));
  copy.dataLocations.protectedRoots.push('relative/sub/dir');
  assert.throws(
    () => validateResolvedDataLocationConfig(copy),
    /protectedRoots\[3\] must be an absolute path: received 'relative\/sub\/dir'/
  );
});

test('DataLocationConfig - 12. unknown top-level key rejected', () => {
  const copy = JSON.parse(JSON.stringify(VALID_WINDOWS_CONFIG));
  copy.unknownKey = 'something';
  assert.throws(
    () => validateResolvedDataLocationConfig(copy),
    /Unknown top-level configuration key: 'unknownKey'/
  );
});

test('DataLocationConfig - 13. unknown dataLocations key rejected', () => {
  const copy = JSON.parse(JSON.stringify(VALID_WINDOWS_CONFIG));
  copy.dataLocations.unrecognizedDir = 'C:\\Unrecognized';
  assert.throws(
    () => validateResolvedDataLocationConfig(copy),
    /Unknown dataLocations key: 'unrecognizedDir'/
  );
});

test('DataLocationConfig - 14. missing gateway object rejected', () => {
  const copy = JSON.parse(JSON.stringify(VALID_WINDOWS_CONFIG));
  delete copy.gateway;
  assert.throws(
    () => validateResolvedDataLocationConfig(copy),
    /Missing required field: gateway/
  );
});

test('DataLocationConfig - 15. gateway non-object rejected', () => {
  const badGateways = [null, '3003', 3003, true, []];
  for (const bad of badGateways) {
    const copy = JSON.parse(JSON.stringify(VALID_WINDOWS_CONFIG));
    copy.gateway = bad;
    assert.throws(
      () => validateResolvedDataLocationConfig(copy),
      /(gateway must be a non-null object|Missing required field: gateway)/
    );
  }
});

test('DataLocationConfig - 16. unknown gateway key rejected', () => {
  const copy = JSON.parse(JSON.stringify(VALID_WINDOWS_CONFIG));
  copy.gateway.unknownSetting = true;
  assert.throws(
    () => validateResolvedDataLocationConfig(copy),
    /Unknown gateway configuration key: 'unknownSetting'/
  );
});

test('DataLocationConfig - 17. missing gateway.localPort rejected', () => {
  const copy = JSON.parse(JSON.stringify(VALID_WINDOWS_CONFIG));
  delete copy.gateway.localPort;
  assert.throws(
    () => validateResolvedDataLocationConfig(copy),
    /Missing required gateway field: 'localPort'/
  );
});

test('DataLocationConfig - 18. gateway.localPort non-integer rejected', () => {
  const nonIntegers = ['3003', 3003.5, NaN, Infinity, true, null];
  for (const val of nonIntegers) {
    const copy = JSON.parse(JSON.stringify(VALID_WINDOWS_CONFIG));
    copy.gateway.localPort = val;
    assert.throws(
      () => validateResolvedDataLocationConfig(copy),
      /('localPort' must be an integer|Missing required gateway field: 'localPort')/
    );
  }
});

test('DataLocationConfig - 19. gateway.localPort != 3003 rejected fail-closed', () => {
  const disallowedPorts = [3000, 3001, 3002, 3004, 8080, 443, 80];
  for (const port of disallowedPorts) {
    const copy = JSON.parse(JSON.stringify(VALID_WINDOWS_CONFIG));
    copy.gateway.localPort = port;
    assert.throws(
      () => validateResolvedDataLocationConfig(copy),
      new RegExp(`Invalid gateway localPort: expected 3003, received ${port}`)
    );
  }
});

test('DataLocationConfig - 20. gateway.localPort = 3003 accepted', () => {
  const copy = JSON.parse(JSON.stringify(VALID_WINDOWS_CONFIG));
  copy.gateway.localPort = 3003;
  const result = validateResolvedDataLocationConfig(copy);
  assert.equal(result.gateway.localPort, 3003);
});

test('DataLocationConfig - 21. input object not mutated', () => {
  const input = {
    schemaVersion: 2,
    dataLocations: {
      archiveRoot: '  C:\\Users\\Synthetic\\Desktop\\HH.AI_v2_Archive  ',
      attachmentTempRoot: '  C:\\Temp\\attachments  ',
      stateRoot: '  C:\\State  ',
      logsRoot: '  C:\\Logs  ',
      protectedRoots: ['  C:\\Project1  ', '  C:\\Project2  '],
    },
    gateway: {
      localPort: 3003,
    },
  };
  const inputArchiveBefore = input.dataLocations.archiveRoot;
  const inputProtectedBefore = input.dataLocations.protectedRoots[0];

  const result = validateResolvedDataLocationConfig(input);

  // Original input strings retain their surrounding whitespace
  assert.equal(input.dataLocations.archiveRoot, inputArchiveBefore);
  assert.equal(input.dataLocations.protectedRoots[0], inputProtectedBefore);

  // Result strings are trimmed
  assert.equal(result.dataLocations.archiveRoot, 'C:\\Users\\Synthetic\\Desktop\\HH.AI_v2_Archive');
  assert.equal(result.dataLocations.protectedRoots[0], 'C:\\Project1');
});

test('DataLocationConfig - 22. returned protectedRoots is copied, not same array reference', () => {
  const input = JSON.parse(JSON.stringify(VALID_WINDOWS_CONFIG));
  const result = validateResolvedDataLocationConfig(input);

  assert.notEqual(result.dataLocations.protectedRoots, input.dataLocations.protectedRoots);
  assert.deepEqual(result.dataLocations.protectedRoots, input.dataLocations.protectedRoots);

  // Mutating result does not affect input
  result.dataLocations.protectedRoots.push('C:\\Extra');
  assert.equal(input.dataLocations.protectedRoots.length, 3);
  assert.equal(result.dataLocations.protectedRoots.length, 4);
});

test('DataLocationConfig - 23. config containing credential-like unrelated top-level field rejected as unknown', () => {
  const credentialFields = [
    'token',
    'botToken',
    'accessToken',
    'secret',
    'password',
    'apiKey',
    'credentials',
    'accounts',
    'port',
  ];

  for (const field of credentialFields) {
    const copy = JSON.parse(JSON.stringify(VALID_WINDOWS_CONFIG));
    copy[field] = 'some_sensitive_value';
    assert.throws(
      () => validateResolvedDataLocationConfig(copy),
      new RegExp(`Unknown top-level configuration key: '${field}'`)
    );
  }
});

test('DataLocationConfig - 24. config.example.json validation', () => {
  const templatePath = path.resolve(__dirname, '..', 'config.example.json');
  assert.ok(fs.existsSync(templatePath), 'config.example.json must exist');

  const content = fs.readFileSync(templatePath, 'utf-8');
  const template = JSON.parse(content);

  // Check valid schema structure
  assert.equal(template.schemaVersion, 2);
  assert.ok(template.dataLocations, 'dataLocations must be present');
  assert.ok(template.gateway, 'gateway must be present');
  assert.equal(template.gateway.localPort, 3003);

  // Verify only allowlisted keys
  const topKeys = Object.keys(template);
  assert.deepEqual(topKeys.sort(), ['dataLocations', 'gateway', 'schemaVersion']);

  const locationKeys = Object.keys(template.dataLocations);
  assert.deepEqual(
    locationKeys.sort(),
    ['archiveRoot', 'attachmentTempRoot', 'logsRoot', 'protectedRoots', 'stateRoot']
  );

  const gatewayKeys = Object.keys(template.gateway);
  assert.deepEqual(gatewayKeys, ['localPort']);

  // Check that placeholders remain unresolved
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

  // Template placeholders should fail isAbsolutePath (deliberate check)
  assert.ok(!isAbsolutePath(template.dataLocations.archiveRoot));
  assert.throws(
    () => validateResolvedDataLocationConfig(template),
    /must be an absolute path/
  );
});
