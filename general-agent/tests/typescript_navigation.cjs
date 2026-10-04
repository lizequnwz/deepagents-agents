"use strict";

// Explicit SDK contract check. The deterministic Python suite uses mock containers.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {analyze} = require("../general_agent/coding/typescript_controller.cjs");
const ts = require(process.argv[2]);
const directory = path.dirname(require.resolve(process.argv[2]));
const libraries = new Map(fs.readdirSync(directory).filter(name => /^lib\.[a-z0-9.]+\.d\.ts$/.test(name))
  .map(name => [directory + "/" + name, fs.readFileSync(directory + "/" + name, "utf8")]));
const documents = [
  {path: "math.ts", text: 'export function add(x:number) { return x + 1; }\n'},
  {path: "app.ts", text: 'import {add} from "./math";\nconst result = add(2);\nconst text: string = 3;\n'},
  {path: "unicode.ts", text: 'const icon = "😀"; const number = 1;\nconst result = number + 1;\n'},
  {path: "literal.js", text: 'const label="unrelatedName"; // unrelatedName\nfunction realName() {}\n'}
];
function run(operation, parameters = {}) { return analyze({operation, documents, ...parameters}, ts, libraries); }
const all = run("symbols");
const add = all.symbols.find(item => item.name === "add" && item.path === "math.ts");
assert.ok(add);
assert.equal(all.symbols.filter(item => item.name === "unrelatedName").length, 0);
const definition = run("definition", {path: "app.ts", line: 2, column: 16});
assert.equal(definition.definitions[0].path, "math.ts");
const references = run("references", {symbol: add.id});
assert.equal(references.references.length, 3);
assert.ok(references.references.some(item => item.is_definition));
const diagnostics = run("diagnostics", {path: "app.ts"});
assert.ok(diagnostics.diagnostics.some(item => item.code === 2322));
const unicode = run("symbols", {path: "unicode.ts"}).symbols.find(item => item.name === "number");
assert.equal(unicode.column, [...'const icon = "😀"; const '].length);
const importedOutside = analyze({operation:"diagnostics", documents:[{path:"a.ts",text:'import x from "/private/secret";'}]}, ts, libraries);
assert.ok(importedOutside.diagnostics.some(item => item.code === 2307));
assert.throws(() => analyze({operation:"symbols", documents:[{path:"../secret.ts",text:"x"}]}, ts, libraries));
assert.throws(() => analyze({operation:"symbols", documents:[{path:"x.ts",text:"x".repeat(256*1024+1)}]}, ts, libraries));
console.log("TypeScript 5.9.3 contract checks passed: symbols, imports, references, diagnostics, Unicode, and source bounds.");
