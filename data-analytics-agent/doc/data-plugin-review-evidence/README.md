# Review evidence

This directory supports the standalone review of the installed Codex Data 1.0.8 plugin. It is not plugin source and does not modify the installation.

- `unit-tests.log`: the installed root test selection, run in a temporary copy. The result is 1,407 passes and 32 failures, including file-level failures. The review distinguishes missing-toolchain failures from two prose-contract assertions.
- `print-browser-retry.log` and `mobile-browser-retry.log`: shipped browser checks using the existing Chromium headless shell. Initial sandbox-blocked attempts are retained separately without being counted as product failures.
- `split-build.log`, `rebuild.log`, `offline-export.log`: the prebuilt customer build and portable export. Two unchanged builds have the same HTML hash.
- `probes.log`: small source-boundary probes. `probes.mjs` preserves their operations and accepts the temporary plugin copy as its first argument. No network request is sent: the Worker is called directly with synthetic Request objects.
- `demo-browser.*`, `demo-*.png`: observations and opening screenshots of the synthetic base fixture. The script retains the exact local test paths. Its blocked HTTPS route is not a general offline certification of all plugin functionality.
- `sources.json`: supporting source paths, validated line intervals, and SHA-256 hashes.
- `installed-hashes-before.json`, `installed-integrity.json`: installation integrity check over 705 files.
- `report-validation.json`: checks of the review HTML, with final Markdown/HTML hashes. Embedded HTML downloads omit self-referential document hashes; this adjacent receipt contains the exact final hashes.
- `print-validation.json`, `report-print-check.pdf`, `print-*.png`, `report-*.png`: PDF and browser layout inspection evidence for the review, not plugin test results.

The tests used Node 24.19.0 from the bundled Codex runtime. The temporary plugin copy was `/private/tmp/codex-data-standalone-review-20260914/plugin`. No npm installation occurred. The browser runs used bundled `playwright-core` and Chromium 148.0.7778.96; the temporary plugin received a symlink to that Playwright package. Initial sandbox restrictions prevented local listening/browser startup, so the same local checks were retried with permitted execution outside the sandbox.

The full root test selection, executed from the temporary plugin root, was:

```sh
node --test tests/*.test.mjs scripts/prebuilt/*.test.mjs templates/data-app/base/tests/*.test.mjs
```

The standalone boundary probes can be rerun with:

```sh
node probes.mjs /absolute/path/to/temporary/plugin-copy
```

`build-report.mjs`, `validate-report.mjs`, and `inspect-pdf.mjs` generate and validate the deliverables. They use the review machine's existing Node libraries and browser through explicit local paths. These authoring dependencies are not required to open the generated HTML. `marked` is used for generation; Playwright and PDF.js with the existing canvas module are used only for validation. The HTML embeds all display code, diagrams, screenshots, and available receipt downloads; the Markdown uses local source and evidence links.

The source file inventory is a content-integrity check, not a publisher signature or security attestation. No deployed Sites identity flow, warehouse query, refresh scheduler, or real user study was run.
