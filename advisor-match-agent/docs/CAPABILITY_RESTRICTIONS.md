# Runtime capability restrictions

This classification applies to the model-facing Advisor Match Agent. Operator APIs and the human workspace UI remain corporation-scoped and loopback-only, but do not grant capabilities to the model.

| Inherited capability | Decision | Enforcement |
| --- | --- | --- |
| CSV/XLSX upload parsing | Keep with restrictions | One chat attachment; `.csv`/`.xlsx`; size, row, sheet, column, and sample bounds; typed upload resolver only. |
| Advisor reference access | Replace with narrow tool | `find_all_advisors_in_database` returns a run-scoped manifest; the model never receives master rows. |
| Matching/code execution | Replace with deterministic library | Versioned application functions perform normalization, matching, scoring, duplicates, and validation. No model-authored code runs. |
| Result creation/modification | Replace with narrow tool | Only deterministic `advisor_matches.xlsx` regeneration from persisted decisions. Original uploads are immutable. |
| Review-state access | Keep with restrictions | Corporation-scoped session ID; filters and cursor; maximum 20 records per tool page, skill default 10. |
| Skill filesystem reads | Keep with restrictions | `ls`, `glob`, and `read_file` resolve only under installed `/skills`; only `advisor-match` is installed. |
| Terminal/shell/arbitrary commands | Disable | Shell backend and execution tests removed; no execute tool is registered. |
| Python execution by model | Disable | Python is an application implementation detail only; no interpreter or code tool is exposed. |
| General filesystem reads/writes | Disable | Agent backend rejects every path outside `/skills`; uploads and exports use typed tools. |
| Network/web browsing | Disable | No browser, HTTP, search, or generic network tool is registered. |
| Package installation | Disable | No shell/package tool and no agent-writable package root. Runtime dependencies are operator-managed. |
| General-purpose subagent/delegation | Disable | Additive DeepAgents harness profile sets the general-purpose subagent to disabled. |
| Unrelated document/media skills | Disable at runtime | Source copies remain for base-history compatibility, but startup replaces the installed tree with `advisor-match` only. |
| Human workspace upload/download | Keep with restrictions | Loopback UI/API, corporation scope, path/symlink defenses, supported types, and no corresponding model filesystem capability. |
| Advisor profile building | Do not register | Typed contract and skill reference are `# TODO`; the agent only offers the future handoff after approval. |

The sole model-facing tool set is `profile_advisor_file`, `find_all_advisors_in_database`, `start_advisor_match`, `list_advisor_match_items`, `propose_manual_crd_override`, `apply_advisor_review_decisions`, plus read-only installed-skill discovery.
