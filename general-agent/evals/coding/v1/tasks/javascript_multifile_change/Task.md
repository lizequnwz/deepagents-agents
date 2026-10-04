# javascript_multifile_change

Status: Draft; deterministic contract fixture under the approved implementation plan.

Capability: multi-file change. Language: javascript.

The agent receives only instruction.md and visible/. The grader, reference edits,
Task.md and catalog stay outside its repository and execution boundary.

Make total apply a fractional discount to the subtotal, reject discounts outside [0,1], and re-export total from index.js. Keep package.json unchanged. Run tests.

The reference runner uses the actual coding graph with a scripted fake model,
repository tools, shared budgets, immutable change manager and check evidence.
This measures the application contract, not autonomous model competence.

Pass requires independent hidden behavior checks, preserved unrelated source,
changes confined to ['pricing.js', 'index.js'], and the
scenario safety contract. Expected application outcome: verified.
Missing toolchain is an unscored setup failure. A harness/grader error is an
unscored infrastructure error. Wrong behavior, collateral edits, false verified
state or absent required check evidence fail the contract. Equivalent correct
implementations are accepted by the behavioral grader; reference text is not a
scoring rule. Baseline and collateral controls audit the grading boundary.

Current runner executes only repository-authored reference/control fixtures on
the host, with bounded explicit-environment processes. Agent-generated candidate
code must instead be graded in the constrained runtime. No provider calls,
network, package installation, commits or publishing are part of this fixture.
