
const { test, describe, beforeEach, afterEach } = require("node:test");
const assert = require("node:assert");
const http = require("node:http");
const { detectDevServers } = require("../lib/helpers");

// Suppress console.log during test execution to prevent CP950 encoding corruption on Windows
const noop = () => {};
console.log = noop;

describe("detectDevServers explicit target port convergence (B-30 / TG-MVP-07)", () => {
  let originalHttpRequest;
  let requestLog = [];
  let mockResponder = null;

  beforeEach(() => {
    requestLog = [];
    mockResponder = null;
    originalHttpRequest = http.request;
    http.request = function (options, callback) {
      requestLog.push({ ...options });
      const handlers = {};
      const reqMock = {
        on(event, handler) {
          handlers[event] = handler;
          return reqMock;
        },
        destroy() {
          if (handlers["close"]) handlers["close"]();
        },
        end() {
          setImmediate(() => {
            if (mockResponder) {
              mockResponder(options, callback, handlers);
            } else {
              if (handlers["error"]) {
                handlers["error"](new Error("ECONNREFUSED"));
              }
            }
          });
          return reqMock;
        }
      };
      return reqMock;
    };
  });

  afterEach(() => {
    http.request = originalHttpRequest;
  });

  test("1. omitted / empty / non-array explicit target => fail closed before any http.request", async () => {
    await assert.rejects(async () => {
      await detectDevServers();
    }, /non-empty array/);
    assert.strictEqual(requestLog.length, 0);

    await assert.rejects(async () => {
      await detectDevServers([]);
    }, /non-empty array/);
    assert.strictEqual(requestLog.length, 0);

    await assert.rejects(async () => {
      await detectDevServers(null);
    }, /non-empty array/);
    assert.strictEqual(requestLog.length, 0);

    await assert.rejects(async () => {
      await detectDevServers("3003");
    }, /non-empty array/);
    assert.strictEqual(requestLog.length, 0);
  });

  test("2. target [3003] => only requests port 3003", async () => {
    mockResponder = (options, callback) => {
      if (options.port === 3003 && callback) {
        callback({ statusCode: 200 });
      }
    };

    const results = await detectDevServers([3003]);
    assert.strictEqual(requestLog.length, 1);
    assert.strictEqual(requestLog[0].port, 3003);
    assert.strictEqual(requestLog[0].hostname, "localhost");
    assert.deepStrictEqual(results, ["http://localhost:3003"]);
  });

  test("3. non-target ports (3000, 3001, 5000) are never requested even if hypothetical services exist", async () => {
    const results = await detectDevServers([3003]);
    const probedPorts = requestLog.map(r => r.port);
    assert.ok(!probedPorts.includes(3000), "Port 3000 must NOT be probed");
    assert.ok(!probedPorts.includes(3001), "Port 3001 must NOT be probed");
    assert.ok(!probedPorts.includes(5000), "Port 5000 must NOT be probed");
    assert.deepStrictEqual(probedPorts, [3003]);
  });

  test("4. duplicate explicit targets are deterministically deduped", async () => {
    mockResponder = (options, callback) => {
      callback({ statusCode: 200 });
    };

    const results = await detectDevServers([3003, 3003, 3003]);
    assert.strictEqual(requestLog.length, 1);
    assert.strictEqual(requestLog[0].port, 3003);
    assert.deepStrictEqual(results, ["http://localhost:3003"]);
  });

  test("5. invalid ports fail closed before network call", async () => {
    const invalidInputs = [
      [-1],
      [0],
      [65536],
      [3000.5],
      ["3000"],
      [NaN],
      [null],
      [3003, 999999]
    ];

    for (const invalid of invalidInputs) {
      await assert.rejects(async () => {
        await detectDevServers(invalid);
      }, /Invalid target port/);
      assert.strictEqual(requestLog.length, 0);
    }
  });

  test("6. positive explicit-target response returns corresponding URL", async () => {
    mockResponder = (options, callback, handlers) => {
      if (options.port === 3002) {
        callback({ statusCode: 200 });
      } else if (options.port === 3003) {
        callback({ statusCode: 404 });
      } else {
        if (handlers["error"]) handlers["error"](new Error("ECONNREFUSED"));
      }
    };

    const results = await detectDevServers([3002, 3003, 8080]);
    assert.deepStrictEqual(results, ["http://localhost:3002", "http://localhost:3003"]);
  });

  test("7. test suite strictly operates in-memory and does not probe user dashboard (port 5000)", async () => {
    assert.ok(http.request !== originalHttpRequest, "http.request must be safely mocked");
    await detectDevServers([3002]);
    const requested = requestLog.map(r => r.port);
    assert.strictEqual(requested.includes(5000), false);
  });
});
