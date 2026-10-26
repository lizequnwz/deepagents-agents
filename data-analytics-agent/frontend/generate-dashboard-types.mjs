import { execFileSync } from "node:child_process";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { compile } from "json-schema-to-typescript";

const root = fileURLToPath(new URL("../", import.meta.url));
const schema = JSON.parse(execFileSync(`${root}.venv/bin/python`, ["-m", "scripts.export_dashboard_schema"], {
  cwd: root, encoding: "utf8",
}));
const generated = await compile(schema, "DashboardView", {
  bannerComment: "/* Generated from DashboardView. Run npm run generate:dashboard. Do not edit. */",
  additionalProperties: false,
  enableConstEnums: false,
  unknownAny: true,
  ignoreMinAndMaxItems: true,
});
const output = new URL("./src/generated/dashboard.ts", import.meta.url);
if (process.argv.includes("--check")) {
  if (await readFile(output, "utf8") !== generated) {
    throw new Error("Dashboard types are stale. Run npm run generate:dashboard.");
  }
} else {
  await mkdir(new URL("./src/generated/", import.meta.url), { recursive: true });
  await writeFile(output, generated);
}
