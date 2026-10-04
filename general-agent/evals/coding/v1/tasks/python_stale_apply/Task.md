# python_stale_apply

Status: Draft; deterministic contract fixture under the approved implementation plan.

Capability: stale edit/apply. Language: python.

The agent receives only instruction.md and visible/. The grader, reference edits,
Task.md and catalog stay outside its repository and execution boundary.

Fix increment to add two and run tests. The controller will inject an intervening original-checkout edit before application; application must refuse it without overwriting the user.

The reference runner uses the actual coding graph with a scripted fake model,
repository tools, shared budgets, immutable change manager and check evidence.
This measures the application contract, not autonomous model competence.

Pass requires independent hidden behavior checks, preserved unrelated source,
changes confined to ['increment.py'], and the
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
