/**
 * runtime/channel-gateway/tests/channel-state-persistence.test.js
 *
 * ADR-0022 D5, D9, D10: Multi-Channel Durable State Persistence Bridge unit tests.
 * Uses synthetic os.tmpdir fixtures only; cleanup in try/finally blocks.
 */

'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');

const { ChannelControl, MESSAGE_STATUS } = require('../core/channel-control');
const {
  buildChannelControlSnapshot,
  recoverChannelControlFromSnapshot,
} = require('../core/channel-state-recovery');
const { DurableStateStore } = require('../core/durable-state-store');
const {
  CHANNEL_STATE_PAYLOAD_SCHEMA_VERSION,
  validateChannelStatePayload,
  DurableChannelStateRepository,
} = require('../core/channel-state-persistence');

function createTempHarness() {
  const baseDir = fs.mkdtempSync(path.join(os.tmpdir(), 'hhai-bridge-test-'));
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

// ============================================================================
// Test 1: payload schemaVersion = 1
// ============================================================================
test('ChannelStatePersistence - 1. payload schemaVersion = 1', () => {
  assert.equal(CHANNEL_STATE_PAYLOAD_SCHEMA_VERSION, 1);

  // Valid schemaVersion 1
  assert.doesNotThrow(() => {
    validateChannelStatePayload({
      schemaVersion: 1,
      channels: [],
    });
  });

  // Unsupported schemaVersion
  assert.throws(
    () => {
      validateChannelStatePayload({
        schemaVersion: 2,
        channels: [],
      });
    },
    { message: /unsupported schemaVersion/ }
  );

  // Missing schemaVersion
  assert.throws(
    () => {
      validateChannelStatePayload({
        channels: [],
      });
    },
    { message: /missing required field: schemaVersion/ }
  );
});

// ============================================================================
// Test 2: empty channels accepted
// ============================================================================
test('ChannelStatePersistence - 2. empty channels accepted', () => {
  assert.doesNotThrow(() => {
    validateChannelStatePayload({
      schemaVersion: 1,
      channels: [],
    });
  });
});

// ============================================================================
// Test 3: unknown payload key rejected
// ============================================================================
test('ChannelStatePersistence - 3. unknown payload key rejected', () => {
  assert.throws(
    () => {
      validateChannelStatePayload({
        schemaVersion: 1,
        channels: [],
        unknownField: 'unexpected',
      });
    },
    { message: /unknown payload key: 'unknownField'/ }
  );
});

// ============================================================================
// Test 4: duplicate channelId rejected
// ============================================================================
test('ChannelStatePersistence - 4. duplicate channelId rejected', () => {
  const c1 = new ChannelControl('telegram');
  const snap1 = buildChannelControlSnapshot(c1);
  const snap2 = buildChannelControlSnapshot(c1);

  assert.throws(
    () => {
      validateChannelStatePayload({
        schemaVersion: 1,
        channels: [snap1, snap2],
      });
    },
    { message: /duplicate channelId in payload: 'telegram'/ }
  );
});

// ============================================================================
// Test 5: invalid nested channel snapshot rejected
// ============================================================================
test('ChannelStatePersistence - 5. invalid nested channel snapshot rejected', () => {
  assert.throws(
    () => {
      validateChannelStatePayload({
        schemaVersion: 1,
        channels: [{ invalid: 'snapshot' }],
      });
    },
    { message: /Unknown top-level snapshot key: 'invalid'/ }
  );
});

// ============================================================================
// Test 6: no state file -> loadOrCreate telegram returns firstStart
// ============================================================================
test('ChannelStatePersistence - 6. no state file -> loadOrCreate telegram returns firstStart', () => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    const repo = new DurableChannelStateRepository(store);

    const result = repo.loadOrCreateChannel('telegram');
    assert.equal(result.firstStart, true);
    assert.ok(result.control instanceof ChannelControl);
    assert.equal(result.control.channelId, 'telegram');
    assert.deepEqual(result.discardedOnRecovery, []);
    assert.equal(result.recoveryPersisted, false);
    assert.equal(result.revision, null);
  } finally {
    harness.cleanup();
  }
});

// ============================================================================
// Test 7: first-start load不得建立 state file
// ============================================================================
test('ChannelStatePersistence - 7. first-start load does not create state file', () => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    const repo = new DurableChannelStateRepository(store);

    assert.equal(fs.existsSync(store.stateFilePath), false);
    repo.loadOrCreateChannel('telegram');
    assert.equal(fs.existsSync(store.stateFilePath), false);
  } finally {
    harness.cleanup();
  }
});

// ============================================================================
// Test 8: save telegram -> revision 1
// ============================================================================
test('ChannelStatePersistence - 8. save telegram -> revision 1', () => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    const repo = new DurableChannelStateRepository(store);

    const control = new ChannelControl('telegram');
    control.enqueueMessage({ id: 'msg-1', receivingAccountId: 'bot-1' });

    const result = repo.saveChannel(control);
    assert.equal(result.channelId, 'telegram');
    assert.equal(result.revision, 1);
    assert.equal(result.channelCount, 1);
    assert.equal(result.stateFilePath, store.stateFilePath);
    assert.equal(fs.existsSync(store.stateFilePath), true);

    const envelope = store.load();
    assert.equal(envelope.revision, 1);
    assert.equal(envelope.payload.channels.length, 1);
    assert.equal(envelope.payload.channels[0].channelId, 'telegram');
  } finally {
    harness.cleanup();
  }
});

// ============================================================================
// Test 9: saved telegram reload成功
// ============================================================================
test('ChannelStatePersistence - 9. saved telegram reload succeeds', () => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    const repo = new DurableChannelStateRepository(store);

    const control = new ChannelControl('telegram');
    control.enqueueMessage({
      id: 'msg-1',
      receivingAccountId: 'bot-1',
      metadata: { text: 'hello' },
    });
    repo.saveChannel(control);

    const loadResult = repo.loadOrCreateChannel('telegram');
    assert.equal(loadResult.firstStart, false);
    assert.equal(loadResult.recoveryPersisted, false);
    assert.equal(loadResult.revision, 1);
    assert.equal(loadResult.control.channelId, 'telegram');
    assert.equal(loadResult.control.messages.length, 1);
    assert.equal(loadResult.control.messages[0].id, 'msg-1');
    assert.equal(loadResult.control.messages[0].status, MESSAGE_STATUS.QUEUED);
    assert.deepEqual(loadResult.control.messages[0].metadata, { text: 'hello' });
  } finally {
    harness.cleanup();
  }
});

// ============================================================================
// Test 10: save line after telegram -> both preserved
// ============================================================================
test('ChannelStatePersistence - 10. save line after telegram -> both preserved', () => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    const repo = new DurableChannelStateRepository(store);

    const tg = new ChannelControl('telegram');
    tg.enqueueMessage({ id: 'tg-1', receivingAccountId: 'tg-bot' });
    repo.saveChannel(tg);

    const line = new ChannelControl('line');
    line.enqueueMessage({ id: 'line-1', receivingAccountId: 'line-bot' });
    const lineSave = repo.saveChannel(line);

    assert.equal(lineSave.revision, 2);
    assert.equal(lineSave.channelCount, 2);

    const envelope = store.load();
    assert.equal(envelope.payload.channels.length, 2);
    const ids = envelope.payload.channels.map((c) => c.channelId);
    assert.ok(ids.includes('telegram'));
    assert.ok(ids.includes('line'));
  } finally {
    harness.cleanup();
  }
});

// ============================================================================
// Test 11: update telegram -> line preserved
// ============================================================================
test('ChannelStatePersistence - 11. update telegram -> line preserved', () => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    const repo = new DurableChannelStateRepository(store);

    const tg = new ChannelControl('telegram');
    tg.enqueueMessage({ id: 'tg-1', receivingAccountId: 'tg-bot' });
    repo.saveChannel(tg);

    const line = new ChannelControl('line');
    line.enqueueMessage({ id: 'line-1', receivingAccountId: 'line-bot' });
    repo.saveChannel(line);

    // Update telegram with new message
    tg.enqueueMessage({ id: 'tg-2', receivingAccountId: 'tg-bot' });
    const tgSave2 = repo.saveChannel(tg);

    assert.equal(tgSave2.revision, 3);
    assert.equal(tgSave2.channelCount, 2);

    const envelope = store.load();
    assert.equal(envelope.payload.channels.length, 2);

    const lineSnapshot = envelope.payload.channels.find((c) => c.channelId === 'line');
    assert.ok(lineSnapshot);
    assert.equal(lineSnapshot.messages.length, 1);
    assert.equal(lineSnapshot.messages[0].id, 'line-1');

    const tgSnapshot = envelope.payload.channels.find((c) => c.channelId === 'telegram');
    assert.ok(tgSnapshot);
    assert.equal(tgSnapshot.messages.length, 2);
    assert.equal(tgSnapshot.messages[1].id, 'tg-2');
  } finally {
    harness.cleanup();
  }
});

// ============================================================================
// Test 12: canonical channel ordering deterministic
// ============================================================================
test('ChannelStatePersistence - 12. canonical channel ordering deterministic', () => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    const repo = new DurableChannelStateRepository(store);

    const zebra = new ChannelControl('zebra');
    repo.saveChannel(zebra);

    const alpha = new ChannelControl('alpha');
    repo.saveChannel(alpha);

    const mid = new ChannelControl('mid');
    repo.saveChannel(mid);

    const envelope = store.load();
    const ids = envelope.payload.channels.map((c) => c.channelId);
    assert.deepEqual(ids, ['alpha', 'mid', 'zebra']);
  } finally {
    harness.cleanup();
  }
});

// ============================================================================
// Test 13: load missing channel from existing payload returns new control without deleting existing channels
// ============================================================================
test('ChannelStatePersistence - 13. load missing channel from existing payload returns new control without deleting existing channels', () => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    const repo = new DurableChannelStateRepository(store);

    const tg = new ChannelControl('telegram');
    tg.enqueueMessage({ id: 'tg-1', receivingAccountId: 'tg-bot' });
    repo.saveChannel(tg);

    const lineResult = repo.loadOrCreateChannel('line');
    assert.equal(lineResult.firstStart, true);
    assert.equal(lineResult.control.channelId, 'line');
    assert.deepEqual(lineResult.control.messages, []);
    assert.equal(lineResult.recoveryPersisted, false);

    // Existing payload must be intact
    const envelope = store.load();
    assert.equal(envelope.payload.channels.length, 1);
    assert.equal(envelope.payload.channels[0].channelId, 'telegram');
  } finally {
    harness.cleanup();
  }
});

// ============================================================================
// Test 14: missing channel load does not bump revision
// ============================================================================
test('ChannelStatePersistence - 14. missing channel load does not bump revision', () => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    const repo = new DurableChannelStateRepository(store);

    const tg = new ChannelControl('telegram');
    repo.saveChannel(tg);

    const envelopeBefore = store.load();
    assert.equal(envelopeBefore.revision, 1);

    repo.loadOrCreateChannel('line');

    const envelopeAfter = store.load();
    assert.equal(envelopeAfter.revision, 1);
  } finally {
    harness.cleanup();
  }
});

// ============================================================================
// Test 15: queued-only recovery does not bump revision
// ============================================================================
test('ChannelStatePersistence - 15. queued-only recovery does not bump revision', () => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    const repo = new DurableChannelStateRepository(store);

    const tg = new ChannelControl('telegram');
    tg.enqueueMessage({ id: 'tg-1', receivingAccountId: 'tg-bot' });
    repo.saveChannel(tg);

    const res = repo.loadOrCreateChannel('telegram');
    assert.equal(res.recoveryPersisted, false);
    assert.equal(res.revision, 1);
    assert.deepEqual(res.discardedOnRecovery, []);

    const envelope = store.load();
    assert.equal(envelope.revision, 1);
  } finally {
    harness.cleanup();
  }
});

// ============================================================================
// Test 16: claimed recovery -> CLAIMED becomes DISCARDED
// ============================================================================
test('ChannelStatePersistence - 16. claimed recovery -> CLAIMED becomes DISCARDED', () => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    const repo = new DurableChannelStateRepository(store);

    const tg = new ChannelControl('telegram');
    tg.takeover('agent-1');
    tg.enqueueMessage({ id: 'tg-1', receivingAccountId: 'tg-bot' });
    tg.pollMessages('agent-1', 1); // claims tg-1

    repo.saveChannel(tg);

    const res = repo.loadOrCreateChannel('telegram');
    assert.equal(res.control.messages.length, 1);
    assert.equal(res.control.messages[0].status, MESSAGE_STATUS.DISCARDED);
    assert.equal(res.control.messages[0].discardReason, 'GATEWAY_RESTART');
    assert.equal(res.discardedOnRecovery.length, 1);
    assert.equal(res.discardedOnRecovery[0].id, 'tg-1');
    assert.equal(res.discardedOnRecovery[0].discardReason, 'GATEWAY_RESTART');
  } finally {
    harness.cleanup();
  }
});

// ============================================================================
// Test 17: claimed recovery write-back -> revision increments exactly once
// ============================================================================
test('ChannelStatePersistence - 17. claimed recovery write-back -> revision increments exactly once', () => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    const repo = new DurableChannelStateRepository(store);

    const tg = new ChannelControl('telegram');
    tg.takeover('agent-1');
    tg.enqueueMessage({ id: 'tg-1', receivingAccountId: 'tg-bot' });
    tg.pollMessages('agent-1', 1);
    repo.saveChannel(tg); // revision 1

    const res = repo.loadOrCreateChannel('telegram');
    assert.equal(res.revision, 2);

    const envelope = store.load();
    assert.equal(envelope.revision, 2);
  } finally {
    harness.cleanup();
  }
});

// ============================================================================
// Test 18: claimed recovery returns recoveryPersisted=true
// ============================================================================
test('ChannelStatePersistence - 18. claimed recovery returns recoveryPersisted=true', () => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    const repo = new DurableChannelStateRepository(store);

    const tg = new ChannelControl('telegram');
    tg.takeover('agent-1');
    tg.enqueueMessage({ id: 'tg-1', receivingAccountId: 'tg-bot' });
    tg.pollMessages('agent-1', 1);
    repo.saveChannel(tg);

    const res = repo.loadOrCreateChannel('telegram');
    assert.equal(res.recoveryPersisted, true);
    assert.equal(res.revision, 2);
  } finally {
    harness.cleanup();
  }
});

// ============================================================================
// Test 19: second load after persisted recovery: discardedOnRecovery=[]
// ============================================================================
test('ChannelStatePersistence - 19. second load after persisted recovery: discardedOnRecovery=[]', () => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    const repo = new DurableChannelStateRepository(store);

    const tg = new ChannelControl('telegram');
    tg.takeover('agent-1');
    tg.enqueueMessage({ id: 'tg-1', receivingAccountId: 'tg-bot' });
    tg.pollMessages('agent-1', 1);
    repo.saveChannel(tg);

    // First load triggers restart conversion and persists it
    const res1 = repo.loadOrCreateChannel('telegram');
    assert.equal(res1.discardedOnRecovery.length, 1);
    assert.equal(res1.recoveryPersisted, true);

    // Second load from durable file
    const res2 = repo.loadOrCreateChannel('telegram');
    assert.deepEqual(res2.discardedOnRecovery, []);
    assert.equal(res2.recoveryPersisted, false);
    assert.equal(res2.control.messages[0].status, MESSAGE_STATUS.DISCARDED);
  } finally {
    harness.cleanup();
  }
});

// ============================================================================
// Test 20: second load does not bump revision again
// ============================================================================
test('ChannelStatePersistence - 20. second load does not bump revision again', () => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    const repo = new DurableChannelStateRepository(store);

    const tg = new ChannelControl('telegram');
    tg.takeover('agent-1');
    tg.enqueueMessage({ id: 'tg-1', receivingAccountId: 'tg-bot' });
    tg.pollMessages('agent-1', 1);
    repo.saveChannel(tg);

    repo.loadOrCreateChannel('telegram'); // bumps to 2
    const res2 = repo.loadOrCreateChannel('telegram');

    assert.equal(res2.revision, 2);
    const envelope = store.load();
    assert.equal(envelope.revision, 2);
  } finally {
    harness.cleanup();
  }
});

// ============================================================================
// Test 21: fencingToken survives through durable bridge
// ============================================================================
test('ChannelStatePersistence - 21. fencingToken survives through durable bridge', () => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    const repo = new DurableChannelStateRepository(store);

    const tg = new ChannelControl('telegram');
    tg.takeover('agent-1');
    tg.takeover('agent-2');
    tg.takeover('agent-3');
    assert.equal(tg.fencingToken, 3);

    repo.saveChannel(tg);

    const res = repo.loadOrCreateChannel('telegram');
    assert.equal(res.control.fencingToken, 3);
  } finally {
    harness.cleanup();
  }
});

// ============================================================================
// Test 22: currentHolder after recovery = null
// ============================================================================
test('ChannelStatePersistence - 22. currentHolder after recovery = null', () => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    const repo = new DurableChannelStateRepository(store);

    const tg = new ChannelControl('telegram');
    tg.takeover('agent-1');
    assert.equal(tg.currentHolder, 'agent-1');

    repo.saveChannel(tg);

    const res = repo.loadOrCreateChannel('telegram');
    assert.equal(res.control.currentHolder, null);
  } finally {
    harness.cleanup();
  }
});

// ============================================================================
// Test 23: lastHeartbeatAt = null after recovery
// ============================================================================
test('ChannelStatePersistence - 23. lastHeartbeatAt = null after recovery', () => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    const repo = new DurableChannelStateRepository(store);

    const tg = new ChannelControl('telegram');
    tg.takeover('agent-1', { timestamp: 999999 });
    assert.equal(tg.lastHeartbeatAt, 999999);

    repo.saveChannel(tg);

    const res = repo.loadOrCreateChannel('telegram');
    assert.equal(res.control.lastHeartbeatAt, null);
  } finally {
    harness.cleanup();
  }
});

// ============================================================================
// Test 24: telegram recovery write-back preserves line state
// ============================================================================
test('ChannelStatePersistence - 24. telegram recovery write-back preserves line state', () => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    const repo = new DurableChannelStateRepository(store);

    // Save line with queued message
    const line = new ChannelControl('line');
    line.enqueueMessage({ id: 'line-msg', receivingAccountId: 'line-bot' });
    repo.saveChannel(line);

    // Save telegram with claimed message
    const tg = new ChannelControl('telegram');
    tg.takeover('tg-agent');
    tg.enqueueMessage({ id: 'tg-msg', receivingAccountId: 'tg-bot' });
    tg.pollMessages('tg-agent', 1);
    repo.saveChannel(tg);

    // Recover telegram (triggers write-back)
    const tgLoad = repo.loadOrCreateChannel('telegram');
    assert.equal(tgLoad.recoveryPersisted, true);

    // Verify line is fully intact in durable state
    const lineLoad = repo.loadOrCreateChannel('line');
    assert.equal(lineLoad.firstStart, false);
    assert.equal(lineLoad.control.messages.length, 1);
    assert.equal(lineLoad.control.messages[0].id, 'line-msg');
    assert.equal(lineLoad.control.messages[0].status, MESSAGE_STATUS.QUEUED);
  } finally {
    harness.cleanup();
  }
});

// ============================================================================
// Test 25: line recovery write-back preserves telegram state
// ============================================================================
test('ChannelStatePersistence - 25. line recovery write-back preserves telegram state', () => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    const repo = new DurableChannelStateRepository(store);

    // Save telegram with queued message
    const tg = new ChannelControl('telegram');
    tg.enqueueMessage({ id: 'tg-msg', receivingAccountId: 'tg-bot' });
    repo.saveChannel(tg);

    // Save line with claimed message
    const line = new ChannelControl('line');
    line.takeover('line-agent');
    line.enqueueMessage({ id: 'line-msg', receivingAccountId: 'line-bot' });
    line.pollMessages('line-agent', 1);
    repo.saveChannel(line);

    // Recover line (triggers write-back)
    const lineLoad = repo.loadOrCreateChannel('line');
    assert.equal(lineLoad.recoveryPersisted, true);

    // Verify telegram is fully intact in durable state
    const tgLoad = repo.loadOrCreateChannel('telegram');
    assert.equal(tgLoad.firstStart, false);
    assert.equal(tgLoad.control.messages.length, 1);
    assert.equal(tgLoad.control.messages[0].id, 'tg-msg');
    assert.equal(tgLoad.control.messages[0].status, MESSAGE_STATUS.QUEUED);
  } finally {
    harness.cleanup();
  }
});

// ============================================================================
// Test 26: invalid live metadata save rejected before write
// ============================================================================
test('ChannelStatePersistence - 26. invalid live metadata save rejected before write', () => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    const repo = new DurableChannelStateRepository(store);

    const tg = new ChannelControl('telegram');
    const badMetadata = {};
    Object.defineProperty(badMetadata, 'badProp', {
      get() {
        return 'getter';
      },
      enumerable: true,
    });
    tg.messages.push({
      id: 'bad-msg',
      receivingAccountId: 'bot',
      status: MESSAGE_STATUS.QUEUED,
      claimedBy: null,
      claimedAtToken: null,
      discardReason: null,
      metadata: badMetadata,
    });

    assert.throws(
      () => {
        repo.saveChannel(tg);
      },
      { message: /accessor properties \(getters\/setters\) are not allowed/ }
    );
  } finally {
    harness.cleanup();
  }
});

// ============================================================================
// Test 27: invalid live metadata: revision unchanged
// ============================================================================
test('ChannelStatePersistence - 27. invalid live metadata: revision unchanged', () => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    const repo = new DurableChannelStateRepository(store);

    const goodTg = new ChannelControl('telegram');
    goodTg.enqueueMessage({ id: 'good', receivingAccountId: 'bot' });
    repo.saveChannel(goodTg);

    assert.equal(store.load().revision, 1);

    // Attempt to save channel with invalid live metadata
    const badTg = new ChannelControl('telegram');
    badTg.messages.push({
      id: 'bad',
      receivingAccountId: 'bot',
      status: MESSAGE_STATUS.QUEUED,
      claimedBy: null,
      claimedAtToken: null,
      discardReason: null,
      metadata: { [Symbol('sym')]: 'bad' },
    });

    assert.throws(() => {
      repo.saveChannel(badTg);
    });

    // Durable store revision must remain 1
    assert.equal(store.load().revision, 1);
  } finally {
    harness.cleanup();
  }
});

// ============================================================================
// Test 28: malformed existing payload fail-closed
// ============================================================================
test('ChannelStatePersistence - 28. malformed existing payload fail-closed', () => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    const repo = new DurableChannelStateRepository(store);

    // Tamper with state file to contain unknown top-level key in payload
    store.save({
      schemaVersion: 1,
      channels: [],
    });

    // Corrupt payload directly in store
    const rawContent = JSON.parse(fs.readFileSync(store.stateFilePath, 'utf8'));
    rawContent.payload.corruptKey = 'bad';
    fs.writeFileSync(store.stateFilePath, JSON.stringify(rawContent), 'utf8');

    assert.throws(
      () => {
        repo.loadOrCreateChannel('telegram');
      },
      { message: /unknown payload key/ }
    );

    const freshTg = new ChannelControl('telegram');
    assert.throws(
      () => {
        repo.saveChannel(freshTg);
      },
      { message: /unknown payload key/ }
    );
  } finally {
    harness.cleanup();
  }
});

// ============================================================================
// Test 29: no AccountRegistry data in canonical payload
// ============================================================================
test('ChannelStatePersistence - 29. no AccountRegistry data in canonical payload', () => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    const repo = new DurableChannelStateRepository(store);

    const tg = new ChannelControl('telegram');
    repo.saveChannel(tg);

    const envelope = store.load();
    assert.equal(envelope.payload.accounts, undefined);
    assert.equal(envelope.payload.activeAccountId, undefined);
    assert.equal(envelope.payload.accountRegistry, undefined);

    // Adding account registry keys to payload must fail validation
    assert.throws(
      () => {
        validateChannelStatePayload({
          schemaVersion: 1,
          channels: [],
          accounts: [],
        });
      },
      { message: /unknown payload key: 'accounts'/ }
    );
  } finally {
    harness.cleanup();
  }
});

// ============================================================================
// Test 30: no credentials / secrets fields introduced
// ============================================================================
test('ChannelStatePersistence - 30. no credentials / secrets fields introduced', () => {
  const forbiddenKeys = ['token', 'secret', 'password', 'apiKey', 'botToken', 'credentials', 'accounts'];

  for (const forbidden of forbiddenKeys) {
    assert.throws(
      () => {
        validateChannelStatePayload({
          schemaVersion: 1,
          channels: [],
          [forbidden]: 'forbidden_value',
        });
      },
      { message: new RegExp(`unknown payload key: '${forbidden}'`) }
    );
  }
});
