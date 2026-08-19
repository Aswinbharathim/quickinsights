"""Qdrant vector store layer.

Layout (unlike ask-frappe.py's single `frappe_knowledge` collection):
  - one collection per database connection, holding that connection's trained
    table schemas + column docs: `qi_schema_<connection_id>`
  - one collection per database connection, holding that connection's own SQL
    examples: `qi_sql_examples_<connection_id>` — every example is required
    to belong to a connection (see models.py's SqlExampleBase), so retrieval
    scoping is done by which collection is searched, not by a payload filter
    on a shared collection.
  - one collection per database connection, holding that connection's own
    imported master/reference-table data:
    `qi_master_data_<connection_id>` — same required-connection, one
    collection per connection design as SQL examples.
"""
import logging
import uuid

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from app import store
from app.config import QDRANT_URL

logger = logging.getLogger(__name__)

_client: QdrantClient | None = None


def get_qdrant() -> QdrantClient:
    global _client
    if _client is None:
        _client = QdrantClient(url=QDRANT_URL) if QDRANT_URL else QdrantClient(path="./qdrant_data")
    return _client


def collection_name_for_connection(conn_id: str) -> str:
    return f"qi_schema_{conn_id}"


def sql_examples_collection_name_for_connection(conn_id: str) -> str:
    return f"qi_sql_examples_{conn_id}"


def master_data_collection_name_for_connection(conn_id: str) -> str:
    return f"qi_master_data_{conn_id}"


def ensure_collection(name: str) -> QdrantClient:
    client = get_qdrant()
    existing = [c.name for c in client.get_collections().collections]
    if name not in existing:
        try:
            embed_dim = store.get_app_settings_raw()["embed_dim"]
            client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=embed_dim, distance=Distance.COSINE),
            )
        except Exception as e:
            # Training fans out many concurrent tasks that can all reach this
            # branch for a brand-new collection at once — only one create call
            # wins the race. If the collection exists now, someone else's
            # create_collection beat us to it, which is fine; anything else
            # (a real connectivity error) should still propagate.
            still_missing = name not in [c.name for c in client.get_collections().collections]
            if still_missing:
                print(f"Error creating Qdrant collection {name} -- {e}")
                logger.exception("Error creating Qdrant collection %s", name)
                raise
    return client


def stable_id(key: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, key))


def upsert_point(collection: str, key: str, text: str, vector: list[float], payload: dict) -> None:
    client = ensure_collection(collection)
    point = PointStruct(id=stable_id(key), vector=vector, payload={"text": text, **payload})
    client.upsert(collection_name=collection, points=[point])


def delete_point(collection: str, key: str) -> None:
    client = ensure_collection(collection)
    client.delete(collection_name=collection, points_selector=[stable_id(key)])


def search(
    collection: str,
    vector: list[float],
    top_k: int,
    category: str | None = None,
    vote: str | None = None,
    module: str | None = None,
) -> list[dict]:
    # No connection_id filter here anymore — every collection this is called
    # against (qi_schema_<id>, qi_sql_examples_<id>) is already scoped to one
    # connection by name, so there's nothing left to filter on that axis.
    client = ensure_collection(collection)
    conditions = []
    if category:
        conditions.append(FieldCondition(key="category", match=MatchValue(value=category)))
    if vote:
        conditions.append(FieldCondition(key="vote", match=MatchValue(value=vote)))
    if module:
        conditions.append(FieldCondition(key="module", match=MatchValue(value=module)))
    qfilter = Filter(must=conditions) if conditions else None
    result = client.query_points(
        collection_name=collection,
        query=vector,
        query_filter=qfilter,
        limit=top_k,
    )
    return [{"score": hit.score, **hit.payload} for hit in result.points]


def count_points(collection: str) -> int:
    client = get_qdrant()
    try:
        return client.count(collection_name=collection, exact=True).count
    except Exception as e:
        print(f"Error counting points in {collection} -- {e}")
        logger.exception("Error counting points in %s", collection)
        return 0


def recreate_collection(name: str) -> None:
    client = get_qdrant()
    try:
        client.delete_collection(name)
    except Exception as e:
        print(f"Error deleting Qdrant collection {name} -- {e}")
        logger.exception("Error deleting Qdrant collection %s", name)
    ensure_collection(name)


def delete_collection(name: str) -> None:
    client = get_qdrant()
    try:
        client.delete_collection(name)
    except Exception as e:
        print(f"Error deleting Qdrant collection {name} -- {e}")
        logger.exception("Error deleting Qdrant collection %s", name)
