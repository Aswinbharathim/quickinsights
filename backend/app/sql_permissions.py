"""Deterministic, post-generation SQL row-filter enforcement.

This runs AFTER the LLM generates SQL and AFTER guardrail.is_safe_select has
already approved it, and BEFORE the query ever reaches the database. It
injects additional WHERE conditions derived from the caller's verified
Frappe User Permissions (see app/frappe_auth.py's Identity.row_filters) --
the LLM never sees or decides these filters; it doesn't even know they
exist. Nothing here is string-concatenated from anything the browser sent
directly: row_filters only ever arrives as a claim inside a signature-
verified token (see frappe_auth.py), never as a request field.

Deliberately conservative, not a general SQL rewriter: this targets the
common case handled by this app's own generated SQL (a single outer SELECT,
optionally with JOINs, over the table(s) actually being restricted). If the
restricted table is only reachable through a WITH/CTE body, this FAILS
CLOSED -- raising PermissionError to block the query -- rather than risk
executing an unfiltered read. A blocked question is always safer than a
leaked row.
"""
import re

import sqlparse
from sqlparse.sql import Where
from sqlparse.tokens import Keyword

from app.guardrail import is_safe_select

_FROM_JOIN_RE = re.compile(
    r"(?:from|join)\s+(?:`([^`]+)`|([A-Za-z_]\w*))(?:\s+(?:as\s+)?([A-Za-z_]\w*))?",
    re.IGNORECASE,
)
_BOUNDARY_KEYWORDS = {"GROUP BY", "ORDER BY", "LIMIT", "HAVING"}
# Words that can immediately follow a table name without being an alias --
# without this, "FROM `tabDoctor` WHERE ..." or "... `tabDoctor` LIMIT 500"
# would be mis-parsed as aliasing the table to "WHERE"/"LIMIT".
_RESERVED_NOT_ALIASES = {
    "WHERE", "LIMIT", "ORDER", "GROUP", "HAVING", "JOIN", "ON", "AND", "OR",
    "INNER", "LEFT", "RIGHT", "OUTER", "UNION", "USING", "SET",
}


def _quote(value: str) -> str:
    escaped = str(value).replace("\\", "\\\\").replace("'", "''")
    return f"'{escaped}'"


def _table_aliases(sql: str) -> dict[str, list[str]]:
    """table_name -> every identifier (alias, or the backticked table name
    itself when unaliased) this query could reference it by. Regex-based and
    intentionally scoped to this app's own generated SQL shape, not
    arbitrary SQL -- see module docstring."""
    aliases: dict[str, list[str]] = {}
    for backticked, bare, alias in _FROM_JOIN_RE.findall(sql):
        table = backticked or bare
        if not table:
            continue
        if alias and alias.upper() in _RESERVED_NOT_ALIASES:
            alias = ""
        ref = alias or f"`{table}`"
        aliases.setdefault(table, []).append(ref)
    return aliases


def referenced_tables(sql: str) -> set[str]:
    """Every table name this query references via FROM/JOIN (same
    regex-based scope as the rest of this module) -- used both by
    apply_row_filters above and by callers enforcing an allowed-table list
    of their own (e.g. rag.answer_question's schema-scope check)."""
    return set(_table_aliases(sql).keys())


def apply_row_filters(sql: str, row_filters: dict[str, dict[str, list[str]]]) -> str:
    """row_filters: {table_name: {column_name: [allowed values]}}.

    Returns the rewritten SQL with those filters injected as AND conditions.
    A table not referenced by this particular query is simply skipped (no
    filter to apply). Raises PermissionError if a restricted table can't be
    safely targeted (WITH/CTE query, or the rewrite fails re-validation) --
    fail closed rather than execute unfiltered.
    """
    if not row_filters:
        return sql

    aliases = _table_aliases(sql)
    conditions: list[str] = []
    for table, columns in row_filters.items():
        refs = aliases.get(table)
        if not refs:
            continue  # this query doesn't touch that table at all
        for column, allowed_values in columns.items():
            if not allowed_values:
                # An explicit empty allow-list means "no rows" for this user.
                conditions.append("1=0")
                continue
            values_sql = ", ".join(_quote(v) for v in allowed_values)
            per_ref = [f"{ref}.`{column}` IN ({values_sql})" for ref in refs]
            conditions.append("(" + " OR ".join(per_ref) + ")")  # any aliased occurrence satisfies it

    if not conditions:
        return sql

    cleaned = sql.rstrip().rstrip(";")

    if re.match(r"^\s*with\b", cleaned, re.IGNORECASE):
        raise PermissionError(
            "This question's query uses a WITH/CTE structure the permission guardrail "
            "can't safely filter yet -- please rephrase without a CTE."
        )

    parsed = sqlparse.parse(cleaned)
    if len(parsed) != 1:
        raise PermissionError("Permission guardrail expected exactly one SQL statement.")
    stmt = parsed[0]

    clause = " AND ".join(conditions)
    out_parts: list[str] = []
    inserted = False
    for tok in stmt.tokens:
        if isinstance(tok, Where):
            # sqlparse groups the WHERE clause as its own token up to (but
            # excluding) a following top-level GROUP BY/ORDER BY/LIMIT, so
            # this only ever touches the outer query's own WHERE, never one
            # nested inside a subquery's Parenthesis group.
            rest = str(tok)[len("WHERE"):].strip()
            out_parts.append(f"WHERE ({clause}) AND ({rest}) ")
            inserted = True
            continue
        if not inserted and tok.ttype is Keyword and tok.value.upper() in _BOUNDARY_KEYWORDS:
            out_parts.append(f"WHERE ({clause}) ")
            inserted = True
        out_parts.append(str(tok))

    if not inserted:
        out_parts.append(f" WHERE ({clause})")

    rewritten = "".join(out_parts)

    # Defense in depth: the rewrite must still be exactly one safe SELECT/WITH.
    # Catches any corruption from the token surgery above before it ever
    # reaches the database.
    ok, reason = is_safe_select(rewritten)
    if not ok:
        raise PermissionError(f"Permission-filtered query failed the safety guardrail: {reason}")
    return rewritten
