# General Agent HTML user guide

Open [index.html](index.html) in a current browser. The file contains the guide
and both interactive Archify architecture viewers. It needs no server,
external script, font download, or network request to display its content.
You can share the single HTML file. Source-reference links require the original
repository layout.

The guide covers setup, document and file work, repository tasks, check evidence,
review/apply/revert, private dependencies, optional navigation and browser tools,
connectors, editors, and recovery. It includes local search, copy controls,
light/dark themes, a review checklist, and a print view.

The diagrams are also available separately:

- [General assistant architecture](architecture/general-assistant.html)
- [Coding workbench architecture](architecture/coding-workbench.html)

Each diagram passed all nine Archify showcase checks. Delivery receipts contain
the exact specification and HTML hashes. Browser receipts cover 1440×900,
1600×1000, 1920×1080, and 2048×1320. Independent image inspection is recorded
separately from automated browser evidence.

Writing follows selected ASD-STE100 principles: short sentences, active verbs,
one instruction per step, and consistent terms. This is not a formal dictionary
compliance audit. UI UX Pro Max supplied the documentation pattern and design
guidance. The report uses system fonts to remain offline.

Only documentation and report artifacts were created for this request.
The report does not execute agent tasks or modify application settings.

## Validation

`check_report.py` checks the final HTML with the application's existing Playwright
installation. It creates a report receipt and screenshots in `evidence/`.
It opens only local report artifacts. It does not start the application, call a
model, or contact configured connectors.

```bash
.venv/bin/python docs/usage-guide/check_report.py
git diff --check
```

The report receipt records layout, interaction, local links, embedded diagram
hashes, observed network requests, text contrast, and sentence-length checks.
See [architecture/handoff.json](architecture/handoff.json) for diagram receipts.
