"use strict";

const path = require("node:path");
const http = require("node:http");

function loopbackUrl(value) {
  const url = new URL(value);
  if (url.protocol !== "http:" || !["127.0.0.1", "[::1]"].includes(url.hostname) ||
      url.username || url.password || url.search || url.hash || url.pathname !== "/") {
    throw new Error("General Agent requires an explicit loopback HTTP API URL.");
  }
  return url.origin;
}

function sourcePath(root, filename) {
  const relative = path.relative(root, filename);
  if (!relative || path.isAbsolute(relative) || relative === ".." || relative.startsWith(".." + path.sep)) {
    throw new Error("The editor document is outside the selected project.");
  }
  return relative.split(path.sep).join("/");
}

function request(config, method, endpoint, body, signal) {
  // Native http connects directly and never inherits ambient proxy routing.
  const url = new URL(endpoint, loopbackUrl(config.apiUrl));
  if (url.origin !== loopbackUrl(config.apiUrl)) throw new Error("Endpoint escaped the local API.");
  return new Promise((resolve, reject) => {
    const outgoing = http.request(url, {
      method, signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(10000)]) : AbortSignal.timeout(10000),
      headers: {"X-Corp-ID": config.corpId, "Content-Type": "application/json"}
    }, response => {
      if (response.statusCode < 200 || response.statusCode >= 300) {
        response.resume(); reject(new Error("General Agent request failed (HTTP " + response.statusCode + ").")); return;
      }
      const chunks = []; let size = 0;
      response.on("data", chunk => {
        size += chunk.length;
        if (size > 2 * 1024 * 1024) { outgoing.destroy(new Error("General Agent response exceeds its size bound.")); return; }
        chunks.push(chunk);
      });
      response.on("error", reject);
      response.on("end", () => {
        try { resolve(response.statusCode === 204 ? undefined : JSON.parse(Buffer.concat(chunks).toString("utf8"))); }
        catch (error) { reject(error); }
      });
    });
    outgoing.on("error", reject);
    outgoing.setTimeout(10000, () => outgoing.destroy(new Error("General Agent request timed out.")));
    outgoing.end(body === undefined ? undefined : JSON.stringify(body));
  });
}

module.exports = {loopbackUrl, sourcePath, request};
