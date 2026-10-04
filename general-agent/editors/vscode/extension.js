"use strict";

const vscode = require("vscode");
const {randomUUID} = require("node:crypto");
const {sourcePath, request} = require("./client");
const buffers = new Map();

function configuration() {
  const settings = vscode.workspace.getConfiguration("generalAgentInline");
  return {enabled: settings.get("enabled"), apiUrl: settings.get("apiUrl"), corpId: settings.get("corpId"), sessionId: settings.get("sessionId")};
}

async function close(buffer) {
  if (buffer.controller) buffer.controller.abort();
  if (buffer.documentId) {
    await request(buffer.config, "DELETE", `/sessions/${buffer.config.sessionId}/documents/${buffer.documentId}`).catch(() => {});
  }
}

function activate(context) {
  const output = vscode.window.createOutputChannel("General Agent Inline");
  context.subscriptions.push(output);
  context.subscriptions.push(vscode.commands.registerCommand("generalAgentInline.accepted", async (config, documentId, suggestionId) => {
    await request(config, "POST", `/sessions/${config.sessionId}/documents/${documentId}/accepted`, {suggestion_id: suggestionId}).catch(() => {});
  }));
  context.subscriptions.push(vscode.languages.registerInlineCompletionItemProvider({scheme: "file"}, {
    async provideInlineCompletionItems(document, position, completionContext, token) {
      const config = configuration();
      if (!config.enabled || !vscode.workspace.isTrusted || !/^[a-f0-9]{32}$/.test(config.sessionId)) return [];
      const key = document.uri.toString();
      let buffer = buffers.get(key);
      if (buffer && JSON.stringify(buffer.config) !== JSON.stringify(config)) {
        await close(buffer); buffers.delete(key); buffer = undefined;
      }
      if (!buffer) { buffer = {config}; buffers.set(key, buffer); }
      if (buffer.controller) buffer.controller.abort();
      const controller = new AbortController();
      buffer.controller = controller;
      const requestId = randomUUID().replaceAll("-", "");
      const version = document.version;
      const cancellation = token.onCancellationRequested(() => controller.abort());
      try {
        if (token.isCancellationRequested) { controller.abort(); return []; }
        const session = await request(config, "GET", `/sessions/${config.sessionId}/editor`, undefined, controller.signal);
        const relative = sourcePath(session.project.root, document.uri.fsPath);
        const payload = {content: document.getText(), version};
        if (Buffer.byteLength(payload.content, "utf8") > 200000 || token.isCancellationRequested) return [];
        if (!buffer.documentId) {
          const opened = await request(config, "POST", `/sessions/${config.sessionId}/documents`, {...payload, path: relative}, controller.signal);
          buffer.documentId = opened.document_id;
        } else {
          await request(config, "PUT", `/sessions/${config.sessionId}/documents/${buffer.documentId}`, payload, controller.signal);
        }
        const cancel = () => request(config, "POST", `/sessions/${config.sessionId}/documents/${buffer.documentId}/cancel`, {request_id: requestId}).catch(() => {});
        controller.signal.addEventListener("abort", cancel, {once: true});
        if (token.isCancellationRequested) { controller.abort(); return []; }
        const result = await request(config, "POST", `/sessions/${config.sessionId}/documents/${buffer.documentId}/complete`,
          {version, offset_utf16: document.offsetAt(position), request_id: requestId}, AbortSignal.any([controller.signal, AbortSignal.timeout(8000)]));
        if (token.isCancellationRequested || document.version !== version || result.version !== version || result.status !== "completed") return [];
        return result.items.map(edit => {
          const item = new vscode.InlineCompletionItem(edit.text, new vscode.Range(document.positionAt(edit.start_utf16), document.positionAt(edit.end_utf16)));
          item.command = {command: "generalAgentInline.accepted", title: "Record acceptance", arguments: [config, buffer.documentId, result.suggestion_id]};
          return item;
        });
      } catch (error) {
        if (!controller.signal.aborted) output.appendLine(String(error.message));
        return [];
      } finally {
        if (cancellation) cancellation.dispose();
        if (buffer.controller === controller) buffer.controller = undefined;
      }
    }
  }));
  context.subscriptions.push(vscode.workspace.onDidCloseTextDocument(document => {
    const key = document.uri.toString(); const buffer = buffers.get(key);
    if (buffer) { buffers.delete(key); void close(buffer); }
  }));
}

async function deactivate() {
  await Promise.allSettled([...buffers.values()].map(close));
  buffers.clear();
}

module.exports = {activate, deactivate};
