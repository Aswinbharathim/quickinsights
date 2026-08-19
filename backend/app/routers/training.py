from fastapi import APIRouter

from app import store
from app.models import TrainingStats
from app.vector_store import (
    collection_name_for_connection,
    count_points,
    recreate_collection,
    sql_examples_collection_name_for_connection,
)

router = APIRouter(prefix="/api/training", tags=["training"])


def _all_tables():
    return [table for tables in store.tables_store.values() for table in tables.values()]


def ensure_modules_populated(target_conn_id: str | None = None):
    """Auto-backfill table modules from tabDocType for existing connections
    if tables were introspected before module tagging was introduced."""
    from app import db
    conn_items = (
        [(target_conn_id, store.connections_store[target_conn_id])]
        if target_conn_id and target_conn_id in store.connections_store
        else list(store.connections_store.items())
    )
    for conn_id, conn in conn_items:
        tables = store.tables_store.get(conn_id, {})
        missing = any(not t.module for t in tables.values())
        if not missing:
            continue
        try:
            raw_conn = db.get_raw_connection(conn)
            with raw_conn.cursor() as cur:
                cur.execute("SELECT name, module FROM `tabDocType` WHERE module IS NOT NULL AND module != ''")
                mod_map = {row[0]: row[1] for row in cur.fetchall()}
            raw_conn.close()

            for name, table in tables.items():
                if not table.module:
                    mod = mod_map.get(table.doctype)
                    if mod:
                        tables[name] = table.model_copy(update={"module": mod})
        except Exception as e:
            print(f"Error backfilling modules for {conn_id}: {e}")


@router.get("/stats", response_model=TrainingStats)
def get_training_stats():
    all_tables = _all_tables()
    trained_tables = [t for t in all_tables if t.training_status == "trained"]

    schema_vectors = sum(
        count_points(collection_name_for_connection(conn_id)) for conn_id in store.connections_store
    )
    # Each connection now has its own SQL-example collection instead of one
    # shared one — sum across all of them the same way schema_vectors does.
    example_vectors = sum(
        count_points(sql_examples_collection_name_for_connection(conn_id)) for conn_id in store.connections_store
    )

    return TrainingStats(
        connections_count=len(store.connections_store),
        trained_tables_count=len(trained_tables),
        total_tables_count=len(all_tables),
        sql_example_count=len(store.sql_example_store),
        total_vectors=schema_vectors + example_vectors,
    )


@router.get("/modules", response_model=list[str])
def list_modules(connection_id: str | None = None):
    ensure_modules_populated(connection_id)
    modules = set()
    if connection_id:
        tables = store.tables_store.get(connection_id, {}).values()
        for table in tables:
            if table.module:
                modules.add(table.module)
    else:
        for table in _all_tables():
            if table.module:
                modules.add(table.module)
        for example in store.sql_example_store.values():
            if example.module:
                modules.add(example.module)
    return sorted(list(modules))


@router.delete("/all", status_code=204)
def delete_all_training_data():
    """Reset every table to untrained, wipe every SQL-example collection, and
    drop + recreate every connection's schema Qdrant collection."""
    store.sql_example_store.clear()
    for conn_id in store.connections_store:
        recreate_collection(sql_examples_collection_name_for_connection(conn_id))

    for conn_id, tables in store.tables_store.items():
        recreate_collection(collection_name_for_connection(conn_id))
        for name, table in tables.items():
            tables[name] = table.model_copy(
                update={"training_status": "untrained", "trained_at": None, "vector_count": 0}
            )
