"""Real Frappe/MariaDB schema introspection — ported from ask-frappe.py's
`introspect_frappe_schema`, adapted to work against an arbitrary connection's
live database rather than a single hardcoded one, and to return structured
data instead of raw DDL text (so it maps directly onto the DbTable model).

Every table's columns and row-count estimate are fetched with ONE bulk
information_schema query each (rather than one round trip per table), since
real Frappe installs commonly have hundreds of `tab*` tables and a per-table
round trip made discovery visibly slow.
"""
import logging

logger = logging.getLogger(__name__)

_LINK_FIELDTYPES = ("Link", "Dynamic Link")
_CHILD_FIELDTYPES = ("Table", "Table MultiSelect")

_SLIM_DDL_PREFIXES = ("KEY ", "UNIQUE KEY", "PRIMARY KEY", "CONSTRAINT", "ENGINE=", "AUTO_INCREMENT=")


def slim_ddl(ddl: str) -> str:
    """Strip noisy DDL lines (indexes, constraints, ENGINE, CHARSET) that waste
    tokens without helping the LLM understand columns. Ported from ask-frappe.py."""
    keep = []
    for line in ddl.splitlines():
        stripped = line.strip().upper()
        if stripped.startswith(_SLIM_DDL_PREFIXES) or ") ENGINE" in stripped:
            continue
        keep.append(line)
    return "\n".join(keep)


def fetch_table_ddl(raw_conn, table_name: str) -> str:
    """Real `SHOW CREATE TABLE`, exactly what ask-frappe.py embeds (via slim_ddl)."""
    with raw_conn.cursor() as cur:
        cur.execute(f"SHOW CREATE TABLE `{table_name}`")
        row = cur.fetchone()
        return row[1] if row else ""


def _fetch_all_columns(cur, database_name: str, tab_tables: list[str]) -> dict[str, list[dict]]:
    """One query for every table's columns, in declaration order."""
    if not tab_tables:
        return {}
    placeholders = ",".join(["%s"] * len(tab_tables))
    cur.execute(
        f"""
        SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = %s AND TABLE_NAME IN ({placeholders})
        ORDER BY TABLE_NAME, ORDINAL_POSITION
        """,
        (database_name, *tab_tables),
    )
    columns_by_table: dict[str, list[dict]] = {t: [] for t in tab_tables}
    for table_name, column_name, column_type in cur.fetchall():
        columns_by_table.setdefault(table_name, []).append(
            {"fieldname": column_name, "fieldtype": column_type}
        )
    return columns_by_table


def _fetch_all_row_counts(cur, database_name: str, tab_tables: list[str]) -> dict[str, int]:
    """One query for every table's approximate row count."""
    if not tab_tables:
        return {}
    placeholders = ",".join(["%s"] * len(tab_tables))
    cur.execute(
        f"""
        SELECT TABLE_NAME, TABLE_ROWS
        FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = %s AND TABLE_NAME IN ({placeholders})
        """,
        (database_name, *tab_tables),
    )
    return {row[0]: int(row[1]) if row[1] is not None else 0 for row in cur.fetchall()}


def introspect_schema(
    raw_conn,
    database_name: str,
    doctype_filter: list[str] | None = None,
    on_progress=None,
) -> dict:
    """Introspect every `tab*` table in a Frappe MariaDB database.

    Returns {table_name: {doctype, columns, foreign_keys, is_child_table,
                           parent_table, row_count}}.

    If given, on_progress(completed, total) is called once per table as the
    final per-table merge loop runs (the SQL fetches themselves are bulk
    queries and aren't subdivided further) — used to drive a progress bar for
    schema discovery, which used to be invisible for large schemas.
    """
    with raw_conn.cursor() as cur:
        cur.execute("SHOW TABLES")
        all_tables = [row[0] for row in cur.fetchall()]

    tab_tables = [t for t in all_tables if t.startswith("tab")]
    if doctype_filter:
        wanted = {"tab" + dt for dt in doctype_filter}
        tab_tables = [t for t in tab_tables if t in wanted]

    if on_progress:
        on_progress(0, len(tab_tables))

    # tabDocField relationship metadata and tabDocType module metadata only exist on real Frappe sites.
    link_fields: list[tuple[str, str, str]] = []
    child_fields: list[tuple[str, str, str]] = []
    modules_by_doctype: dict[str, str] = {}

    if "tabDocType" in all_tables:
        with raw_conn.cursor() as cur:
            try:
                cur.execute(
                    "SELECT name, module FROM `tabDocType` WHERE module IS NOT NULL AND module != ''"
                )
                modules_by_doctype = {row[0]: row[1] for row in cur.fetchall()}
            except Exception as e:
                print(f"Error fetching tabDocType modules -- {e}")
                logger.exception("Error fetching tabDocType modules")

    if "tabDocField" in all_tables:
        with raw_conn.cursor() as cur:
            try:
                cur.execute(
                    """
                    SELECT parent, fieldname, fieldtype, options
                    FROM tabDocField
                    WHERE fieldtype IN ('Link', 'Dynamic Link', 'Table', 'Table MultiSelect')
                      AND options IS NOT NULL AND options != ''
                    """
                )
                for parent, fieldname, fieldtype, options in cur.fetchall():
                    if fieldtype in _LINK_FIELDTYPES:
                        link_fields.append((parent, fieldname, options))
                    elif fieldtype in _CHILD_FIELDTYPES:
                        child_fields.append((parent, fieldname, options))
            except Exception as e:
                print(f"Error fetching tabDocField relationships -- {e}")
                logger.exception("Error fetching tabDocField relationships")

    parent_of_child = {options: parent for parent, _fieldname, options in child_fields}

    with raw_conn.cursor() as cur:
        columns_by_table = _fetch_all_columns(cur, database_name, tab_tables)
        row_counts = _fetch_all_row_counts(cur, database_name, tab_tables)

    results: dict[str, dict] = {}
    for i, table in enumerate(tab_tables, start=1):
        columns = columns_by_table.get(table, [])
        if not columns:
            if on_progress:
                on_progress(i, len(tab_tables))
            continue  # table disappeared or column read failed — skip rather than fabricate

        doctype = table[3:]  # strip leading "tab"
        col_names = {c["fieldname"] for c in columns}
        is_child = "parent" in col_names and "parenttype" in col_names
        parent_doctype = parent_of_child.get(doctype)
        module = modules_by_doctype.get(doctype) or (modules_by_doctype.get(parent_doctype) if parent_doctype else None)

        foreign_keys = []
        for parent, fieldname, ref_doctype in link_fields:
            if parent == doctype and fieldname in col_names:
                foreign_keys.append(
                    {"column": fieldname, "ref_table": "tab" + ref_doctype, "ref_column": "name"}
                )
        if is_child and parent_doctype:
            foreign_keys.append(
                {"column": "parent", "ref_table": "tab" + parent_doctype, "ref_column": "name"}
            )

        results[table] = {
            "doctype": doctype,
            "module": module,
            "columns": columns,
            "foreign_keys": foreign_keys,
            "is_child_table": is_child,
            "parent_table": ("tab" + parent_doctype) if (is_child and parent_doctype) else None,
            "row_count": row_counts.get(table, 0),
        }
        if on_progress:
            on_progress(i, len(tab_tables))

    return results
