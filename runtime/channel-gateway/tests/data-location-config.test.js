/**
 * runtime/channel-gateway/tests/data-location-config.test.js
 *
 * Unit tests for Data Location Config Contract (ADR-0022 D24).
 * Pure domain validation tests with synthetic data only.
 */

'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const {
  DATA_LOCATION_SCHEMA_VERSION,
  validateResolvedDataLocationConfig,
  isAbsolutePath,
} = require('../core/data-location-config');

const VALID_WINDOWS_CONFIG = {
  schemaVersion: 1,
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
};

const VALID_POSIX_CONFIG = {
  schemaVersion: 1,
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
};

test('DataLocationConfig - 1. valid Windows-style resolved config accepted', () => {
  const result = validateResolvedDataLocationConfig(VALID_WINDOWS_CONFIG);
  assert.equal(result.schemaVersion, 1);
  assert.equal(result.dataLocations.archiveRoot, 'C:\\Users\\Synthetic\\Desktop\\HH.AI_v2_Archive');
  assert.equal(result.dataLocations.attachmentTempRoot, 'C:\\Users\\Synthetic\\AppData\\Local\\Temp\\hh-ai-attachments');
  assert.equal(result.dataLocations.stateRoot, 'C:\\Users\\Synthetic\\AppData\\Local\\hh-ai-gateway\\state');
  assert.equal(result.dataLocations.logsRoot, 'C:\\Users\\Synthetic\\AppData\\Local\\hh-ai-gateway\\logs');
  assert.equal(result.dataLocations.protectedRoots.length, 3);
  assert.equal(result.dataLocations.protectedRoots[0], 'C:\\Users\\Synthetic\\Projects\\HH.AI_v2');
});

test('DataLocationConfig - 2. valid POSIX-style resolved config accepted', () => {
  const result = validateResolvedDataLocationConfig(VALID_POSIX_CONFIG);
  assert.equal(result.schemaVersion, 1);
  assert.equal(result.dataLocations.archiveRoot, '/var/data/hh-ai/archive');
  assert.equal(result.dataLocations.attachmentTempRoot, '/tmp/hh-ai-attachments');
  assert.equal(result.dataLocations.stateRoot, '/var/lib/hh-ai-gateway/state');
  assert.equal(result.dataLocations.logsRoot, '/var/log/hh-ai-gateway');
  assert.equal(result.dataLocations.protectedRoots.length, 3);
  assert.equal(result.dataLocations.protectedRoots[0], '/opt/hh-ai-v2');
});

test('DataLocationConfig - 3. wrong schemaVersion rejected', () => {
  assert.throws(
    () => validateResolvedDataLocationConfig({ ...VALID_WINDOWS_CONFIG, schemaVersion: 2 }),
    /Unsupported schemaVersion/
  );
  assert.throws(
    () => validateResolvedDataLocationConfig({ ...VALID_WINDOWS_CONFIG, schemaVersion: '1' }),
    /Unsupported schemaVersion/
  );
  assert.throws(
    () => validateResolvedDataLocationConfig({ ...VALID_WINDOWS_CONFIG, schemaVersion: undefined }),
    /Missing required field: schemaVersion/
  );
});

test('DataLocationConfig - 4. missing or invalid dataLocations rejected', () => {
  assert.throws(
    () => validateResolvedDataLocationConfig({ schemaVersion: 1 }),
    /dataLocations must be a non-null object/
  );
  assert.throws(
    () => validateResolvedDataLocationConfig({ schemaVersion: 1, dataLocations: null }),
    /dataLocations must be a non-null object/
  );
  assert.throws(
    () => validateResolvedDataLocationConfig({ schemaVersion: 1, dataLocations: [] }),
    /dataLocations must be a non-null object/
  );
  assert.throws(
    () => validateResolvedDataLocationConfig({ schemaVersion: 1, dataLocations: 'invalid' }),
    /dataLocations must be a non-null object/
  );
});

test('DataLocationConfig - 5. missing required singleton path rejected', () => {
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

test('DataLocationConfig - 6. blank singleton path rejected', () => {
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

test('DataLocationConfig - 7. relative singleton path rejected', () => {
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

test('DataLocationConfig - 8. protectedRoots non-array rejected', () => {
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

test('DataLocationConfig - 9. blank protected root rejected', () => {
  const copy = JSON.parse(JSON.stringify(VALID_WINDOWS_CONFIG));
  copy.dataLocations.protectedRoots.push('   ');
  assert.throws(
    () => validateResolvedDataLocationConfig(copy),
    /protectedRoots\[3\] must be a non-empty string/
  );
});

test('DataLocationConfig - 10. relative protected root rejected', () => {
  const copy = JSON.parse(JSON.stringify(VALID_WINDOWS_CONFIG));
  copy.dataLocations.protectedRoots.push('relative/sub/dir');
  assert.throws(
    () => validateResolvedDataLocationConfig(copy),
    /protectedRoots\[3\] must be an absolute path: received 'relative\/sub\/dir'/
  );
});

test('DataLocationConfig - 11. unknown top-level key rejected', () => {
  const copy = JSON.parse(JSON.stringify(VALID_WINDOWS_CONFIG));
  copy.unknownKey = 'something';
  assert.throws(
    () => validateResolvedDataLocationConfig(copy),
    /Unknown top-level configuration key: 'unknownKey'/
  );
});

test('DataLocationConfig - 12. unknown dataLocations key rejected', () => {
  const copy = JSON.parse(JSON.stringify(VALID_WINDOWS_CONFIG));
  copy.dataLocations.unrecognizedDir = 'C:\\Unrecognized';
  assert.throws(
    () => validateResolvedDataLocationConfig(copy),
    /Unknown dataLocations key: 'unrecognizedDir'/
  );
});

test('DataLocationConfig - 13. input object not mutated', () => {
  const input = {
    schemaVersion: 1,
    dataLocations: {
      archiveRoot: '  C:\\Users\\Synthetic\\Desktop\\HH.AI_v2_Archive  ',
      attachmentTempRoot: '  C:\\Temp\\attachments  ',
      stateRoot: '  C:\\State  ',
      logsRoot: '  C:\\Logs  ',
      protectedRoots: ['  C:\\Project1  ', '  C:\\Project2  '],
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

test('DataLocationConfig - 14. returned protectedRoots is copied, not same array reference', () => {
  const input = JSON.parse(JSON.stringify(VALID_WINDOWS_CONFIG));
  const result = validateResolvedDataLocationConfig(input);

  assert.notEqual(result.dataLocations.protectedRoots, input.dataLocations.protectedRoots);
  assert.deepEqual(result.dataLocations.protectedRoots, input.dataLocations.protectedRoots);

  // Mutating result does not affect input
  result.dataLocations.protectedRoots.push('C:\\Extra');
  assert.equal(input.dataLocations.protectedRoots.length, 3);
  assert.equal(result.dataLocations.protectedRoots.length, 4);
});

test('DataLocationConfig - 15. config containing credential-like unrelated top-level field rejected as unknown', () => {
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

test('DataLocationConfig - 16. config.example.json validation', () => {
  const templatePath = path.resolve(__dirname, '..', 'config.example.json');
  assert.ok(fs.existsSync(templatePath), 'config.example.json must exist');

  const content = fs.readFileSync(templatePath, 'utf-8');
  const template = JSON.parse(content);

  // Check valid schema structure
  assert.equal(template.schemaVersion, 1);
  assert.ok(template.dataLocations, 'dataLocations must be present');

  // Verify only allowlisted keys
  const topKeys = Object.keys(template);
  assert.deepEqual(topKeys.sort(), ['dataLocations', 'schemaVersion']);

  const locationKeys = Object.keys(template.dataLocations);
  assert.deepEqual(
    locationKeys.sort(),
    ['archiveRoot', 'attachmentTempRoot', 'logsRoot', 'protectedRoots', 'stateRoot']
  );

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
