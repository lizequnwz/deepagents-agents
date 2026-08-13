# Capability restrictions

| Capability | Status | Enforcement |
|---|---|---|
| General-purpose chat or planning | Not supported | Only four purpose-built REST operations exist. |
| Graph orchestration or interrupts | Not supported | Form submissions are independent synchronous requests. |
| Conversations, runs, polling, or cancellation | Not supported | No corresponding models, routes, or stores exist. |
| Database or local workflow persistence | Not supported | Request-scoped uploads may spool locally but are never reused or persisted by the application. |
| Pod affinity | Not required | Every configured request resends bytes and configuration. |
| Shell, code execution, package installation | Not exposed | Mapping calls have no tools. |
| Model-selected advisor matches | Not supported | Matching is deterministic policy version 5 code. |
| Reference data sent to the model | Not supported | Only bounded upload profiles reach the mapper. |
| Profile data fetching or simulation | Not supported | Reports are deterministic placeholders. |

Multipart request sizes, inspection bounds, row limits, exact physical mapping,
source hashes, reference schema, duplicate CRDs, text-safe workbook cells, and
workbook reconciliation are enforced in application code.
