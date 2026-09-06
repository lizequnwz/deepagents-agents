# Optional execution review

SQL and Python approvals are independent and disabled by default. Enable
REQUIRE_SQL_APPROVAL or REQUIRE_PYTHON_APPROVAL to review execution. An edit
replaces the exact query/code while preserving named saved-dataset bindings.
A rejection gives feedback to the specialist. Pending approvals survive restart
through SQLite graph checkpoints and persisted review metadata.

Source execution belongs to the SQL specialist. Python receives saved Parquet
inputs in a fresh subprocess with execution/output budgets. These are local
execution boundaries, not an enterprise sandbox or governance platform. The
application targets one local user. Additional enterprise controls are outside
this release's scope.
