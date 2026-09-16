/**
 * runtime/channel-gateway/tests/durable-state-store.test.js
 *
 * Unit tests for Channel Gateway Atomic Durable State Store (ADR-0022 D10).
 * Uses synthetic os.tmpdir fixtures only; cleanup in try/finally blocks.
 */

'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');

const {
  DurableStateStore,
  STATE_FILENAME,
  STATE_SCHEMA_VERSION,
  validateJsonCompatiblePayload,
  validateEnvelope,
} = require('../core/durable-state-store');

function createTempHarness() {
  const baseDir = fs.mkdtempSync(path.join(os.tmpdir(), 'hhai-state-test-'));
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

test('DurableStateStore - 1. valid existing writable stateRoot accepted', () => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    assert.ok(store);
    assert.equal(store.canonicalStateRoot, fs.realpathSync(harness.stateRoot));
    assert.equal(
      store.stateFilePath,
      path.join(fs.realpathSync(harness.stateRoot), 'channel-gateway-state.json')
    );
  } finally {
    harness.cleanup();
  }
});

test('DurableStateStore - 2. relative stateRoot rejected', () => {
  assert.throws(
    () => new DurableStateStore('relative/state/dir'),
    /stateRoot must be an absolute path/
  );
  assert.throws(
    () => new DurableStateStore('./state/dir'),
    /stateRoot must be an absolute path/
  );
  assert.throws(
    () => new DurableStateStore('../state/dir'),
    /stateRoot must be an absolute path/
  );
  assert.throws(
    () => new DurableStateStore('   '),
    /stateRoot must be a non-empty string/
  );
  assert.throws(
    () => new DurableStateStore(12345),
    /stateRoot must be a string/
  );
});

test('DurableStateStore - 3. missing stateRoot rejected', () => {
  const harness = createTempHarness();
  try {
    const missing = path.join(harness.baseDir, 'nonexistent-root');
    assert.throws(
      () => new DurableStateStore(missing),
      /stateRoot does not exist or cannot be accessed/
    );
  } finally {
    harness.cleanup();
  }
});

test('DurableStateStore - 4. file-as-stateRoot rejected', () => {
  const harness = createTempHarness();
  try {
    const dummyFile = path.join(harness.baseDir, 'dummy.txt');
    fs.writeFileSync(dummyFile, 'hello', 'utf8');
    assert.throws(
      () => new DurableStateStore(dummyFile),
      /stateRoot must be a directory/
    );
  } finally {
    harness.cleanup();
  }
});

test('DurableStateStore - 5. missing state file -> load returns null', () => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    assert.equal(store.load(), null);
  } finally {
    harness.cleanup();
  }
});

test('DurableStateStore - 6. first save -> revision = 1', () => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    const result = store.save({ test: 'first-snapshot' });
    assert.equal(result.revision, 1);
    assert.equal(result.stateFilePath, store.stateFilePath);

    const loaded = store.load();
    assert.ok(loaded);
    assert.equal(loaded.schemaVersion, 1);
    assert.equal(loaded.revision, 1);
    assert.deepEqual(loaded.payload, { test: 'first-snapshot' });
  } finally {
    harness.cleanup();
  }
});

test('DurableStateStore - 7. second save -> revision = 2', () => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    store.save({ stage: 'initial' });
    const result2 = store.save({ stage: 'updated' });
    assert.equal(result2.revision, 2);

    const loaded = store.load();
    assert.equal(loaded.revision, 2);
    assert.deepEqual(loaded.payload, { stage: 'updated' });
  } finally {
    harness.cleanup();
  }
});

test('DurableStateStore - 8. save/load payload round-trip', () => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    const samplePayload = {
      str: 'sample string',
      num: 42.5,
      negNum: -100,
      boolTrue: true,
      boolFalse: false,
      nullVal: null,
      nestedObj: {
        innerKey: 'innerVal',
        nestedArray: ['a', 'b', 1, 2, false, null],
      },
      list: [
        { id: 1, name: 'first' },
        { id: 2, name: 'second' },
      ],
    };

    store.save(samplePayload);
    const loaded = store.load();
    assert.deepEqual(loaded.payload, samplePayload);
  } finally {
    harness.cleanup();
  }
});

test('DurableStateStore - 9. fixed filename = channel-gateway-state.json', () => {
  const harness = createTempHarness();
  try {
    assert.equal(STATE_FILENAME, 'channel-gateway-state.json');
    const store = new DurableStateStore(harness.stateRoot);
    assert.equal(path.basename(store.stateFilePath), 'channel-gateway-state.json');

    store.save({ ok: true });
    assert.ok(fs.existsSync(store.stateFilePath));
    assert.equal(path.basename(store.stateFilePath), 'channel-gateway-state.json');
  } finally {
    harness.cleanup();
  }
});

test('DurableStateStore - 10. no missing directory auto-created', () => {
  const harness = createTempHarness();
  try {
    const missingDir = path.join(harness.baseDir, 'never-created-state-dir');
    assert.equal(fs.existsSync(missingDir), false);

    assert.throws(
      () => new DurableStateStore(missingDir),
      /stateRoot does not exist or cannot be accessed/
    );

    assert.equal(fs.existsSync(missingDir), false);
  } finally {
    harness.cleanup();
  }
});

test('DurableStateStore - 11. malformed JSON state file rejected', () => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    fs.writeFileSync(store.stateFilePath, '{"schemaVersion": 1, invalid_json: ', 'utf8');

    assert.throws(
      () => store.load(),
      /Failed to parse state file as JSON/
    );
  } finally {
    harness.cleanup();
  }
});

test('DurableStateStore - 12. wrong schemaVersion rejected', () => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    fs.writeFileSync(
      store.stateFilePath,
      JSON.stringify({ schemaVersion: 2, revision: 1, payload: { ok: true } }),
      'utf8'
    );

    assert.throws(
      () => store.load(),
      /Unsupported schemaVersion: expected 1, received 2/
    );
  } finally {
    harness.cleanup();
  }
});

test('DurableStateStore - 13. negative revision rejected', () => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    fs.writeFileSync(
      store.stateFilePath,
      JSON.stringify({ schemaVersion: 1, revision: -1, payload: { ok: true } }),
      'utf8'
    );

    assert.throws(
      () => store.load(),
      /revision must be a non-negative safe integer/
    );
  } finally {
    harness.cleanup();
  }
});

test('DurableStateStore - 14. non-integer revision rejected', () => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    fs.writeFileSync(
      store.stateFilePath,
      JSON.stringify({ schemaVersion: 1, revision: 3.1415, payload: { ok: true } }),
      'utf8'
    );

    assert.throws(
      () => store.load(),
      /revision must be a non-negative safe integer/
    );

    fs.writeFileSync(
      store.stateFilePath,
      JSON.stringify({ schemaVersion: 1, revision: '1', payload: { ok: true } }),
      'utf8'
    );

    assert.throws(
      () => store.load(),
      /revision must be a non-negative safe integer/
    );
  } finally {
    harness.cleanup();
  }
});

test('DurableStateStore - 15. unknown envelope key rejected', () => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    fs.writeFileSync(
      store.stateFilePath,
      JSON.stringify({ schemaVersion: 1, revision: 1, payload: {}, unexpectedKey: 'bad' }),
      'utf8'
    );

    assert.throws(
      () => store.load(),
      /Unknown envelope key: 'unexpectedKey'/
    );
  } finally {
    harness.cleanup();
  }
});

test('DurableStateStore - 16. payload null rejected', () => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    assert.throws(
      () => store.save(null),
      /payload must be a non-null plain object/
    );
  } finally {
    harness.cleanup();
  }
});

test('DurableStateStore - 17. payload array rejected', () => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    assert.throws(
      () => store.save([1, 2, 3]),
      /payload must be a non-null plain object/
    );
  } finally {
    harness.cleanup();
  }
});

test('DurableStateStore - 18. nested undefined rejected', () => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    assert.throws(
      () => store.save({ field: undefined }),
      /undefined is not JSON-compatible/
    );
    assert.throws(
      () => store.save({ items: [1, 2, undefined] }),
      /undefined is not JSON-compatible/
    );
  } finally {
    harness.cleanup();
  }
});

test('DurableStateStore - 19. nested function rejected', () => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    assert.throws(
      () => store.save({ fn: () => {} }),
      /function is not JSON-compatible/
    );
    assert.throws(
      () => store.save({ arr: [() => {}] }),
      /function is not JSON-compatible/
    );
  } finally {
    harness.cleanup();
  }
});

test('DurableStateStore - 20. BigInt rejected', () => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    assert.throws(
      () => store.save({ big: 9007199254740991n }),
      /BigInt is not JSON-compatible/
    );
    assert.throws(
      () => store.save({ arr: [1n] }),
      /BigInt is not JSON-compatible/
    );
  } finally {
    harness.cleanup();
  }
});

test('DurableStateStore - 21. NaN / Infinity rejected', () => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    assert.throws(
      () => store.save({ num: NaN }),
      /number must be finite/
    );
    assert.throws(
      () => store.save({ num: Infinity }),
      /number must be finite/
    );
    assert.throws(
      () => store.save({ num: -Infinity }),
      /number must be finite/
    );
  } finally {
    harness.cleanup();
  }
});

test('DurableStateStore - 22. Date / Map / Set rejected', () => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    assert.throws(
      () => store.save({ date: new Date() }),
      /object must be a plain object/
    );
    assert.throws(
      () => store.save({ map: new Map() }),
      /object must be a plain object/
    );
    assert.throws(
      () => store.save({ set: new Set() }),
      /object must be a plain object/
    );
    assert.throws(
      () => store.save({ regex: /test/ }),
      /object must be a plain object/
    );
  } finally {
    harness.cleanup();
  }
});

test('DurableStateStore - 23. circular payload rejected', () => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    const circular = { name: 'circular' };
    circular.self = circular;

    assert.throws(
      () => store.save(circular),
      /circular reference detected/
    );

    const circularArray = [];
    circularArray.push(circularArray);
    assert.throws(
      () => store.save({ arr: circularArray }),
      /circular reference detected/
    );
  } finally {
    harness.cleanup();
  }
});

test('DurableStateStore - 24. valid nested arrays + plain objects accepted', () => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    const validData = {
      level1: {
        level2: {
          level3: {
            array: [
              { a: 1, b: 'two', c: [true, false, null] },
              { d: 4, e: { deep: 'value' } },
            ],
          },
        },
      },
    };

    assert.doesNotThrow(() => store.save(validData));
    const loaded = store.load();
    assert.deepEqual(loaded.payload, validData);
  } finally {
    harness.cleanup();
  }
});

test('DurableStateStore - 25. existing state-file symlink rejected 或 capability-aware skip', (t) => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    const targetFile = path.join(harness.baseDir, 'target-outside.json');
    fs.writeFileSync(
      targetFile,
      JSON.stringify({ schemaVersion: 1, revision: 1, payload: { external: true } }),
      'utf8'
    );

    try {
      fs.symlinkSync(targetFile, store.stateFilePath, 'file');
    } catch (symlinkErr) {
      t.skip(`Symlink creation not permitted in this environment (${symlinkErr.code || symlinkErr.message})`);
      return;
    }

    assert.throws(
      () => store.load(),
      /State file must not be a symbolic link/
    );

    assert.throws(
      () => store.save({ attempt: 'write-to-symlink' }),
      /existing state file is a symbolic link/
    );
  } finally {
    harness.cleanup();
  }
});

test('DurableStateStore - 26. state file after successful save is regular file inside canonical stateRoot', () => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    store.save({ status: 'active' });

    assert.ok(fs.existsSync(store.stateFilePath));
    const lstat = fs.lstatSync(store.stateFilePath);
    assert.ok(lstat.isFile());
    assert.ok(!lstat.isSymbolicLink());

    const canonicalFile = fs.realpathSync(store.stateFilePath);
    assert.equal(path.dirname(canonicalFile), store.canonicalStateRoot);
  } finally {
    harness.cleanup();
  }
});

test('DurableStateStore - 27. no leftover *.tmp after successful save', () => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    for (let i = 0; i < 5; i++) {
      store.save({ iteration: i });
    }

    const files = fs.readdirSync(store.canonicalStateRoot);
    const tmpFiles = files.filter((f) => f.endsWith('.tmp'));
    assert.equal(tmpFiles.length, 0, `Expected 0 .tmp files, found: ${tmpFiles.join(', ')}`);
  } finally {
    harness.cleanup();
  }
});

test('DurableStateStore - 28. production module uses shared atomic writer 而不是 duplicated implementation', () => {
  const storeModulePath = require.resolve('../core/durable-state-store');
  const source = fs.readFileSync(storeModulePath, 'utf8');

  // Must import shared/atomicFs
  assert.ok(
    source.includes("require('../../../shared/atomicFs')"),
    'Must require shared/atomicFs directly'
  );

  // Must use writeStateAtomic
  assert.ok(
    source.includes('writeStateAtomic('),
    'Must call writeStateAtomic to perform atomic save'
  );

  // Must NOT implement its own renameSync or writeFileSync for saving
  assert.ok(
    !source.includes('fs.renameSync('),
    'Must not implement a separate renameSync in durable-state-store'
  );
  assert.ok(
    !source.includes('fs.writeFileSync('),
    'Must not call fs.writeFileSync directly in durable-state-store'
  );
});

test('DurableStateStore - 29. plain object with Symbol-keyed own property -> rejected', () => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    const p = { visible: 1 };
    p[Symbol('hidden')] = 2;
    assert.throws(
      () => store.save(p),
      /Symbol-keyed properties are not allowed/
    );
  } finally {
    harness.cleanup();
  }
});

test('DurableStateStore - 30. nested object with Symbol-keyed property -> rejected', () => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    const nested = { child: {} };
    nested.child[Symbol('nestedHidden')] = 'secret';
    assert.throws(
      () => store.save(nested),
      /Symbol-keyed properties are not allowed/
    );
  } finally {
    harness.cleanup();
  }
});

test('DurableStateStore - 31. non-enumerable own property -> rejected', () => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    const p = { visible: 'hello' };
    Object.defineProperty(p, 'hidden', {
      value: 'secret',
      enumerable: false,
      configurable: true,
      writable: true,
    });
    assert.throws(
      () => store.save(p),
      /non-enumerable properties are not allowed/
    );
  } finally {
    harness.cleanup();
  }
});

test('DurableStateStore - 32. nested non-enumerable own property -> rejected', () => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    const p = { nested: { ok: true } };
    Object.defineProperty(p.nested, 'hidden', {
      value: 123,
      enumerable: false,
      configurable: true,
      writable: true,
    });
    assert.throws(
      () => store.save(p),
      /non-enumerable properties are not allowed/
    );
  } finally {
    harness.cleanup();
  }
});

test('DurableStateStore - 33. non-enumerable own toJSON function -> rejected', () => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    const p = { data: 42 };
    Object.defineProperty(p, 'toJSON', {
      value: () => ({ transformed: true }),
      enumerable: false,
      configurable: true,
      writable: true,
    });
    assert.throws(
      () => store.save(p),
      /non-enumerable properties are not allowed/
    );
  } finally {
    harness.cleanup();
  }
});

test('DurableStateStore - 34. enumerable accessor getter property -> rejected', () => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    const p = {};
    Object.defineProperty(p, 'computed', {
      get() {
        return 'dynamic';
      },
      enumerable: true,
      configurable: true,
    });
    assert.throws(
      () => store.save(p),
      /accessor properties \(getters\/setters\) are not allowed/
    );
  } finally {
    harness.cleanup();
  }
});

test('DurableStateStore - 35. array with Symbol-keyed extra property -> rejected', () => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    const arr = [1, 2, 3];
    arr[Symbol('extra')] = 'val';
    assert.throws(
      () => store.save({ list: arr }),
      /Symbol-keyed properties on arrays are not allowed/
    );
  } finally {
    harness.cleanup();
  }
});

test('DurableStateStore - 36. array with named extra property: arr.extra = value -> rejected', () => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    const arr = [1, 2];
    arr.extra = 3;
    assert.throws(
      () => store.save({ list: arr }),
      /extra own property 'extra' on array is not allowed/
    );
  } finally {
    harness.cleanup();
  }
});

test('DurableStateStore - 37. array accessor index -> rejected', () => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    const arr = [1, 2];
    Object.defineProperty(arr, '0', {
      get() {
        return 99;
      },
      enumerable: true,
      configurable: true,
    });
    assert.throws(
      () => store.save({ list: arr }),
      /accessor properties on array indices are not allowed/
    );
  } finally {
    harness.cleanup();
  }
});

test('DurableStateStore - 38. sparse array -> rejected', () => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    // eslint-disable-next-line no-sparse-arrays
    const sparse = [1, , 3];
    assert.throws(
      () => store.save({ list: sparse }),
      /sparse arrays with holes are not allowed/
    );

    const emptyHole = new Array(3);
    assert.throws(
      () => store.save({ list: emptyHole }),
      /sparse arrays with holes are not allowed/
    );
  } finally {
    harness.cleanup();
  }
});

test('DurableStateStore - 39. ordinary dense nested array 仍 accepted', () => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    const payload = {
      matrix: [
        [1, 2, 3],
        [4, 5, 6],
      ],
      empty: [],
      mixed: [true, 'text', null, 42.5, { inside: [10, 20] }],
    };

    const result = store.save(payload);
    assert.equal(result.revision, 1);

    const loaded = store.load();
    assert.deepStrictEqual(loaded.payload, payload);
  } finally {
    harness.cleanup();
  }
});

test('DurableStateStore - 40. ordinary plain nested objects round-trip 仍完全相等', () => {
  const harness = createTempHarness();
  try {
    const store = new DurableStateStore(harness.stateRoot);
    const payload = {
      user: 'alice',
      meta: {
        active: true,
        count: 100,
        nested: {
          flag: false,
          value: null,
          items: ['a', 'b', 'c'],
        },
      },
    };

    const saved1 = store.save(payload);
    assert.equal(saved1.revision, 1);

    const loaded1 = store.load();
    assert.deepStrictEqual(loaded1.payload, payload);

    // Save revision 2
    payload.meta.count = 101;
    const saved2 = store.save(payload);
    assert.equal(saved2.revision, 2);

    const loaded2 = store.load();
    assert.deepStrictEqual(loaded2.payload, payload);
  } finally {
    harness.cleanup();
  }
});

