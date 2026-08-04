# Capability Restrictions

| Capability | Policy | Enforcement |
|---|---|---|
| Dynamic tools / ReAct loop | Not supported | Graph nodes call fixed services directly. |
| Shell, code execution, package install | Not supported | No runtime node exposes them. |
| Network browsing | Not supported | Only the configured advisor source adapter is used. |
| Subagents / delegation | Not supported | The graph contains no agent or subgraph planner. |
| Generic file access | Not supported | `Workspace` resolves protected corp-scoped IDs only. |
| Full master table in model context | Forbidden | Matching and snapshot access stay deterministic. |
| Row-by-row LLM identity decisions | Forbidden | Matcher and review policy own all decisions. |
| Persistent conversations/checkpoints | Not supported | `InMemorySaver` and `RuntimeStore` are process-local. |
| Profile building | Not implemented | Remains an unregistered `# TODO`. |

Prompts are not security boundaries. Corp scope, path validation, file
integrity, row limits, matching policy, review rules, and workbook validation
are enforced in application code. The services are loopback-only and corp IDs
are not authentication.
