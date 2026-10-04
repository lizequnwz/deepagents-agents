"use strict";

// Only source snapshots and the read-only image SDK enter this language service.
const path = require("node:path");
const crypto = require("node:crypto");
const fs = require("node:fs");

function analyze(request, ts, libraries = new Map()) {
  if (ts.version !== "5.9.3") throw new Error("Unsupported TypeScript SDK version.");
  if (!["symbols", "definition", "references", "diagnostics"].includes(request.operation)) throw new Error("Invalid navigation operation.");
  const files = new Map(); let total = 0;
  if (!Array.isArray(request.documents) || request.documents.length > 200) throw new Error("Invalid source inventory.");
  for (const document of request.documents) {
    if (typeof document.path !== "string" || document.path.length > 1024 || document.path.startsWith("/") ||
        document.path.split("/").some(part => !part || part === "." || part === "..") || document.path.includes("\\") ||
        typeof document.text !== "string" || Buffer.byteLength(document.text) > 256 * 1024) throw new Error("Invalid source document.");
    total += Buffer.byteLength(document.text);
    if (total > 2 * 1024 * 1024) throw new Error("Source inventory exceeds its bound.");
    const name = "/repo/" + document.path;
    if (files.has(name)) throw new Error("Duplicate source document.");
    files.set(name, document.text);
  }
  const options = {noEmit: true, allowJs: true, checkJs: true, target: ts.ScriptTarget.ES2022,
    module: ts.ModuleKind.ESNext, moduleResolution: ts.ModuleResolutionKind.Bundler,
    jsx: ts.JsxEmit.Preserve, allowImportingTsExtensions: true, skipLibCheck: true};
  const read = name => files.get(name) ?? libraries.get(name);
  const host = {
    getCompilationSettings: () => options, getScriptFileNames: () => [...files.keys()],
    getScriptVersion: () => "1", getScriptSnapshot: name => read(name) === undefined ? undefined : ts.ScriptSnapshot.fromString(read(name)),
    getCurrentDirectory: () => "/repo", getDefaultLibFileName: opts => ts.getDefaultLibFilePath(opts),
    fileExists: name => read(name) !== undefined, readFile: read,
    readDirectory: () => [...files.keys()], useCaseSensitiveFileNames: () => true,
    directoryExists: directory => [...files.keys(), ...libraries.keys()].some(name => name.startsWith(directory + "/")),
    getDirectories: () => []
  };
  const service = ts.createLanguageService(host);
  const output = {protocol: 1, language: "typescript", typescript_version: ts.version,
    executes_repository_code: false, columns: "zero-based Unicode characters; lines are one-based",
    limitations: "Uses approved snapshot files and SDK standard libraries. Project tsconfig, plugins, package types and path aliases are not loaded.",
    symbols: [], definitions: [], references: [], diagnostics: [], truncated: false};
  const symbols = [];
  function span(name, textSpan, extra = {}) {
    if (!files.has(name)) return undefined;
    const source = service.getProgram().getSourceFile(name);
    const location = source.getLineAndCharacterOfPosition(textSpan.start);
    const start = source.getLineStarts()[location.line];
    return {id: "ts:" + crypto.createHash("sha256").update(name + ":" + textSpan.start).digest("hex").slice(0, 24),
      path: name.slice(6), line: location.line + 1, column: [...source.text.slice(start, textSpan.start)].length,
      length_utf16: textSpan.length, ...extra};
  }
  function tree(name, item) {
    if (item.nameSpan) {
      const record = span(name, item.nameSpan, {name: item.text, kind: item.kind});
      symbols.push({...record, _file: name, _position: item.nameSpan.start});
      if (symbols.length > 5000) throw new Error("Symbol inventory exceeds its bound.");
    }
    for (const child of item.childItems || []) tree(name, child);
  }
  try {
    const selected = request.path ? ["/repo/" + request.path] : [...files.keys()];
    for (const name of files.keys()) tree(name, service.getNavigationTree(name));
    if (request.operation === "symbols") {
      const query = String(request.query || "").toLowerCase();
      const matches = symbols.filter(item => selected.includes(item._file) && item.name.toLowerCase().includes(query));
      output.truncated = matches.length > 500;
      output.symbols = matches.slice(0, 500).map(({_file, _position, ...item}) => item);
    } else if (request.operation === "definition") {
      const name = "/repo/" + request.path;
      if (files.has(name)) {
        const source = service.getProgram().getSourceFile(name);
        const starts = source.getLineStarts();
        if (!Number.isInteger(request.line) || !Number.isInteger(request.column) || request.line < 1 || request.line > starts.length || request.column < 0) throw new Error("Invalid definition position.");
        const start = starts[request.line - 1];
        const line = source.text.slice(start, starts[request.line] ?? source.text.length).replace(/[\r\n]+$/, "");
        if (request.column > [...line].length) throw new Error("Invalid definition column.");
        const position = start + [...line].slice(0, request.column).join("").length;
        const definitions = service.getDefinitionAtPosition(name, position) || [];
        output.definitions = definitions.map(item => span(item.fileName, item.textSpan, {name: item.name, kind: item.kind})).filter(Boolean).slice(0, 100);
        output.ambiguous = output.definitions.length !== 1;
      }
    } else if (request.operation === "references") {
      const targets = symbols.filter(item => item.id === request.symbol || item.name === request.symbol).slice(0, 10);
      output.approximate = !String(request.symbol).startsWith("ts:");
      const found = new Map();
      for (const target of targets) {
        const references = (service.findReferences(target._file, target._position) || []).flatMap(group => group.references);
        for (const reference of references) {
          const record = span(reference.fileName, reference.textSpan, {is_definition: reference.isDefinition === true});
          if (record) found.set(record.id, record);
        }
      }
      output.references = [...found.values()].slice(0, 1000);
      output.truncated = found.size > 1000;
    } else {
      for (const name of selected.filter(value => files.has(value))) {
        for (const diagnostic of [...service.getSyntacticDiagnostics(name), ...service.getSemanticDiagnostics(name)]) {
          const record = span(name, {start: diagnostic.start || 0, length: diagnostic.length || 0},
            {code: diagnostic.code, severity: diagnostic.category === ts.DiagnosticCategory.Error ? "error" : "warning",
             message: ts.flattenDiagnosticMessageText(diagnostic.messageText, "\n").slice(0, 1000)});
          if (output.diagnostics.length < 200) output.diagnostics.push(record);
          else output.truncated = true;
        }
      }
    }
    return output;
  } finally { service.dispose(); }
}

if (require.main === module) {
  let size = 0; const chunks = [];
  process.stdin.on("data", chunk => {
    size += chunk.length;
    if (size > 3 * 1024 * 1024) process.exit(1);
    chunks.push(chunk);
  });
  process.stdin.on("end", () => {
    try {
      // The application may select an explicit operator-installed local SDK.
      // Source snapshots cannot select a package, plugin, or configuration.
      const sdk = process.argv[2] || "/opt/general-agent/typescript-sdk/node_modules/typescript/lib/typescript.js";
      if (!require("node:path").isAbsolute(sdk) || require("node:path").basename(sdk) !== "typescript.js") {
        throw new Error("An absolute TypeScript SDK file is required.");
      }
      const ts = require(sdk);
      if (ts.version !== "5.9.3") throw new Error("TypeScript 5.9.3 is required.");
      const directory = require("node:path").dirname(sdk);
      const libraries = new Map();
      for (const name of fs.readdirSync(directory).filter(value => /^lib\.[a-z0-9.]+\.d\.ts$/.test(value))) {
        libraries.set(directory + "/" + name, fs.readFileSync(directory + "/" + name, "utf8"));
      }
      const result = JSON.stringify(analyze(JSON.parse(Buffer.concat(chunks).toString("utf8")), ts, libraries));
      if (Buffer.byteLength(result) > 250000) throw new Error("Navigation output exceeds its bound.");
      process.stdout.write(result);
    } catch (error) { process.stderr.write("TypeScript snapshot analysis failed.\n"); process.exitCode = 1; }
  });
}

module.exports = {analyze};
