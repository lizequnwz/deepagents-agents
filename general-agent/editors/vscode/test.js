"use strict";

const {test} = require("node:test");
const assert = require("node:assert/strict");
const {loopbackUrl, sourcePath, request} = require("./client");

test("only explicit loopback URLs are accepted", () => {
  assert.equal(loopbackUrl("http://127.0.0.1:8001"), "http://127.0.0.1:8001");
  assert.equal(loopbackUrl("http://[::1]:8001"), "http://[::1]:8001");
  for (const url of ["http://localhost:8001", "https://example.com", "http://127.0.0.1/x", "http://secret@127.0.0.1", "http://127.0.0.1/?x=1"]) {
    assert.throws(() => loopbackUrl(url));
  }
});

test("source mapping stays under the registered project", () => {
  assert.equal(sourcePath("/repo", "/repo/src/a.js"), "src/a.js");
  for (const filename of ["/other/a.js", "/repo-other/a.js", "/repo"]) {
    assert.throws(() => sourcePath("/repo", filename));
  }
});

test("direct HTTP client scopes requests and rejects redirects and oversized responses", async () => {
  const http = require("node:http");
  const {EventEmitter} = require("node:events");
  const original = http.request;
  let status = 200, content = Buffer.from('{"version":3}'), observed;
  http.request = (url, options, callback) => {
    observed = {url, options};
    const outgoing = new EventEmitter();
    outgoing.setTimeout = deadline => { observed.deadline = deadline; };
    outgoing.destroy = error => outgoing.emit("error", error);
    outgoing.end = body => {
      observed.body = body;
      queueMicrotask(() => {
        const response = new EventEmitter();
        response.statusCode = status;
        response.resume = () => {};
        callback(response);
        response.emit("data", content);
        response.emit("end");
      });
    };
    return outgoing;
  };
  try {
    const config = {apiUrl: "http://127.0.0.1:8001", corpId: "A123456"};
    assert.deepEqual(await request(config, "POST", "/complete", {version: 3}), {version: 3});
    assert.equal(observed.url.origin, config.apiUrl);
    assert.equal(observed.options.headers["X-Corp-ID"], "A123456");
    assert.equal(observed.deadline, 10000);
    assert.equal(observed.body, '{"version":3}');
    assert.ok(observed.options.signal instanceof AbortSignal);
    assert.throws(() => request(config, "GET", "https://example.com"));
    status = 302;
    await assert.rejects(request(config, "GET", "/redirect"), /HTTP 302/);
    status = 200; content = Buffer.alloc(2 * 1024 * 1024 + 1, "x");
    await assert.rejects(request(config, "GET", "/oversized"), /size bound/);
  } finally {
    http.request = original;
  }
});
