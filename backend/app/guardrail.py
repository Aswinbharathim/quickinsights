"""SELECT-only safety guardrail — ported directly from ask-frappe.py."""
import re

import sqlparse

# Anything in this set => blocked outright (matched as whole words).
# "into" blocks SELECT ... INTO OUTFILE/DUMPFILE/@var (which can write files).
FORBIDDEN = {
    "insert", "update", "delete", "drop", "alter", "create", "truncate",
    "replace", "grant", "revoke", "merge", "call", "exec", "execute",
    "lock", "unlock", "set", "rename", "load", "outfile", "dumpfile", "into",
}


def is_safe_select(sql: str):
    """Return (ok: bool, reason: str). Only a single SELECT/WITH statement is allowed."""
    clean = sqlparse.format(sql, strip_comments=True).strip().rstrip(";").strip()
    if not clean:
        return False, "Empty query."

    statements = [s for s in sqlparse.parse(clean) if str(s).strip()]
    if len(statements) != 1:
        return False, "Only a single statement is allowed."

    first_word = re.match(r"\s*([a-zA-Z]+)", clean)
    if not first_word or first_word.group(1).lower() not in ("select", "with"):
        got = first_word.group(1).upper() if first_word else "?"
        return False, f"Statement must start with SELECT or WITH (got: {got})."

    lowered = clean.lower()
    for kw in FORBIDDEN:
        if re.search(rf"\b{kw}\b", lowered):
            return False, f"Forbidden keyword detected: {kw.upper()}."

    return True, "ok"


def enforce_limit(sql: str, auto_limit: int) -> str:
    """Token/perf safety: if there's no LIMIT, append one."""
    if "limit" not in sql.lower():
        sql = sql.rstrip().rstrip(";") + f"\nLIMIT {auto_limit}"
    return sql
