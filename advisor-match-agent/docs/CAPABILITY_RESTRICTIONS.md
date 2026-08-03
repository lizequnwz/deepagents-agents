# Runtime capability restrictions

This classification applies to the model-facing Advisor Match Agent and its loopback UI. The application intentionally has no generic human or model workspace.

| Inherited capability | Decision | Enforcement |
| --- | --- | --- |
| CSV/XLSX upload parsing | Keep with restrictions | One immutable original attachment; `.csv`/`.xlsx`; size, row, sheet, column, and sample bounds; opaque attachment ID and typed resolver only. One explicit all-rows firm may be applied to copied mapped values with persisted session provenance; the upload is never changed or derived. |
| Advisor reference access | Replace with narrow tool | `create_advisor_match` retrieves or reuses an attachment-scoped snapshot and returns only its opaque manifest; the model never receives master rows. |
| Matching/code execution | Replace with deterministic library | Versioned application functions perform normalization, indexed identity resolution, bounded firm comparison, duplicates, and validation. No model-authored code runs. |
| Result creation/modification | Replace with narrow tool | Only deterministic `advisor_matches.xlsx` regeneration from persisted decisions. Each verified revision is explicitly published under an opaque artifact ID. |
| Review-state access | Keep with restrictions | Corporation-scoped session ID; filters and cursor; maximum 20 records per tool page, skill default 10. |
| Skill filesystem reads | Keep with restrictions | `ls`, `glob`, and `read_file` resolve only under installed `/skills`; only `advisor-match` is installed. |
| Terminal/shell/arbitrary commands | Disable | Shell backend and execution tests removed; no execute tool is registered. |
| Python execution by model | Disable | Python is an application implementation detail only; no interpreter or code tool is exposed. |
| General filesystem reads/writes | Disable | Agent backend rejects every path outside `/skills`; attachments, snapshots, and artifacts resolve only through typed tools. |
| Network/web browsing | Disable | No browser, HTTP, search, or generic network tool is registered. |
| Package installation | Disable | No shell/package tool and no agent-writable package root. Runtime dependencies are operator-managed. |
| General-purpose subagent/delegation | Disable | Additive DeepAgents harness profile sets the general-purpose subagent to disabled. |
| Unrelated document/media skills | Omit | The source and installed skill trees contain only `advisor-match`. |
| Generic human workspace | Disable | No shared folders, arbitrary uploads, file browser, preview, promotion, rename, or general workspace endpoints. Originals and workbook artifacts remain downloadable by ID. |
| Advisor profile building | Do not register | Typed contract and skill reference remain `# TODO`; the agent does not offer or simulate a handoff. |

The sole model-facing tool set is `inspect_advisor_upload`, `validate_advisor_input`, `get_current_advisor_input`, `create_advisor_match`, `get_current_advisor_match`, `list_advisor_match_results`, `propose_crd_match`, `apply_advisor_match_decisions`, plus read-only installed-skill discovery.
