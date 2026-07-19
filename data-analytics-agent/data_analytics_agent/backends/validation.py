"""Dialect-aware structural validation for read-only analytical SQL."""

from __future__ import annotations

from sqlglot import exp, parse
from sqlglot.errors import ParseError


class SQLValidationError(ValueError):
    """Raised when SQL is not exactly one safe read-only query."""


FORBIDDEN_NODE_NAMES = {
    "Alter",
    "Analyze",
    "Attach",
    "Command",
    "Commit",
    "Copy",
    "Create",
    "Delete",
    "Detach",
    "Drop",
    "Execute",
    "Grant",
    "Insert",
    "Into",
    "LoadData",
    "Lock",
    "Merge",
    "Pragma",
    "Reindex",
    "Revoke",
    "Rollback",
    "Set",
    "Transaction",
    "TruncateTable",
    "Update",
    "Use",
    "Vacuum",
}


def validate_readonly_sql(query: str, *, dialect: str) -> exp.Query:
    """Require one SELECT/CTE/set-operation query for the chosen dialect."""

    if not query or not query.strip():
        raise SQLValidationError("SQL cannot be empty.")
    try:
        statements = parse(query, read=dialect)
    except (ParseError, ValueError) as exc:
        raise SQLValidationError(
            f"Invalid {dialect} SQL: {exc}"
        ) from exc
    statements = [statement for statement in statements if statement is not None]
    if len(statements) != 1:
        raise SQLValidationError("Exactly one SQL statement is required.")

    statement = statements[0]
    if not isinstance(statement, (exp.Select, exp.SetOperation)):
        raise SQLValidationError(
            "Only read-only SELECT, CTE, and set-operation queries are allowed."
        )
    for node in statement.walk():
        if node.__class__.__name__ in FORBIDDEN_NODE_NAMES:
            raise SQLValidationError(
                f"Unsafe SQL operation {node.__class__.__name__} is not allowed."
            )
    return statement
