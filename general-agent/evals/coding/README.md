# Coding contract fixtures

`v1/` contains 12 Python and JavaScript fixtures: bug repair, feature work,
multi-file edits, regression tests, source configuration, a pre-existing failure,
dirty user files, stale application, cancellation, shared budgets, scoped
instructions and delegated inspection.

Run the controlled suite from the repository root:

```bash
uv run python -m evals.coding.runner --trials 3 --output /tmp/coding-contract-results.json
uv run pytest tests/test_coding_evals.py
```

Python uses the project interpreter. JavaScript needs an existing Node.js
installation. No packages are installed and no provider calls are made. Missing
Node.js produces an unscored setup failure and a nonzero suite exit status.

Each task has an agent-visible `visible/` repository and `instruction.md`.
`Task.md`, `grader.txt`, `reference.json` and the catalog are control material;
the runner never copies them into the agent repository. Instructions are passed
as the task message. Graders run after the graph ends, outside its tool access.
Task specs remain Draft until reviewed individually; the implementation plan
authorized building this deterministic suite.

The runner uses the real coding graph, file tools, shared invocation budgets,
source context, check evidence and change broker with a scripted fake model.
Only repository-authored reference and negative controls execute on the host,
using bounded processes and an explicit environment. This is not a generic
host grader for agent-generated code: real candidate code must run inside the
constrained coding runtime. Docker containment is covered by the runtime tests;
this suite does not establish a live Docker result.

The JSON report records every trial, fixture/harness hash, dependency and
toolchain versions, baseline failures, hidden behavior, patch scope, preserved
original bytes, check outcome, run state, duration and admitted invocations.
Fake models do not report tokens, so reported tokens remain `null` and missing
usage is counted. Setup and infrastructure failures have no task score.

Hidden behavior checks accept equivalent implementations. Grader tests include
unchanged bugs, valid alternatives, skipped visible assertions, collateral
changes, omitted checks and missing/corrupt graders. `false_verified` detects
passing approved checks when hidden behavior still fails. One reference scenario
deliberately supplies false model prose about a known failing check; it passes
only when the application keeps the structured outcome `checks_failed`.

`contract_pass_rate` measures deterministic application contracts. It is not an
autonomous solved-task rate, a coding-model benchmark, or evidence of Copilot
parity. Comparing models requires separately approved provider-backed trials
with the same task inputs, limits and grading boundary.
