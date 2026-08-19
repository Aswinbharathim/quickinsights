import csv
import io
import logging
from typing import Optional

import openpyxl
from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile

from app import rag, store
from app.models import (
    MasterDataBatchDeleteRequest,
    MasterDataImportProgress,
    MasterDataRecord,
)
from app.store import new_id_fn, now_fn

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/master-data", tags=["master-data"])


def _progress_key(connection_id: str, table_name: str) -> str:
    return f"{connection_id}:{table_name}"


@router.get("", response_model=list[MasterDataRecord])
def list_master_data(
    connection_id: Optional[str] = None,
    module: Optional[str] = None,
    table_name: Optional[str] = None,
):
    records = (r for r in store.master_data_record_store.values())
    if connection_id:
        records = (r for r in records if r.connection_id == connection_id)
    if module:
        records = (r for r in records if r.module == module)
    if table_name:
        records = (r for r in records if r.table_name == table_name)
    return sorted(records, key=lambda r: r.created_at, reverse=True)


@router.get("/tables", response_model=list[str])
def list_master_data_tables(connection_id: str):
    """Distinct table names this connection already has master data for —
    populates the "Table" filter dropdown on the Master Data page."""
    names = {
        r.table_name for r in store.master_data_record_store.values() if r.connection_id == connection_id
    }
    return sorted(names)


def _looks_like_header_row(cells) -> bool:
    """A real header row has several populated columns. Frappe's own
    list/report exports often prepend a "Column Labels:" (or similar) line
    with only ONE populated cell before the actual header row — this lets
    that line (and any other single-cell noise above the real headers) get
    skipped instead of being mistaken for the header row itself. Only used
    as a FALLBACK for non-Frappe files — see _find_header_row."""
    return sum(1 for c in cells if c not in (None, "")) >= 2


def _row_first_cell(row) -> str:
    return str(row[0] or "").strip().lower() if row else ""


# Frappe's "Data Import Template" export inserts several more of its own
# label rows between the real header row and the actual data — each one
# strictly noise, none of them a data row:
#   Column Labels:  <- the real header row
#   Column Name:    <- internal DB field names, not needed
#   Mandatory:
#   Type:
#   Info:
#   Start entering data below this line   <- single-cell marker
_TEMPLATE_METADATA_LABELS = {"column name:", "mandatory:", "type:", "info:"}


def _is_template_metadata_row(row) -> bool:
    first = _row_first_cell(row)
    return first in _TEMPLATE_METADATA_LABELS or first.startswith("start entering data")


def _unwrap_quotes(value: str) -> str:
    """Frappe wraps some column values (IDs in particular) in a literal
    extra pair of double quotes on export — e.g. the cell holds the 4
    characters `"Ag"`, not just `Ag` — almost certainly to stop Excel from
    reinterpreting the value (a common spreadsheet text-guard trick), not
    meaningful content. Strip one layer so the stored/embedded value is the
    real id, not a quoted string."""
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1]
    return value


def _find_header_row(raw_rows: list) -> tuple[int, bool]:
    """Returns (header_row_index, is_labeled). Frappe's own exports — both
    a plain list/report export AND the "Data Import Template" — always
    literally label the real header row "Column Labels:" in its first
    cell. That's a far more reliable signal than "first row with 2+
    populated cells": the Data Import Template has several earlier rows
    ("Table:", "Assay Elements" / "DocType:", "Assay Elements", ...) that
    would otherwise be mistaken for the header row by that generic check.
    Falls back to the generic heuristic only for files that don't use this
    convention at all."""
    for i, row in enumerate(raw_rows):
        if _row_first_cell(row) in ("column labels:", "column labels"):
            return i, True
    header_idx = next((i for i, row in enumerate(raw_rows) if _looks_like_header_row(row)), None)
    if header_idx is None:
        raise ValueError("Couldn't find a header row — need at least 2 populated columns in one row")
    return header_idx, False


def _parse_master_data_rows(filename: str, content: bytes) -> list[dict[str, str]]:
    """Unlike SQL examples' fixed Question/SQL/Module/Tags columns, master
    data has no fixed shape — every table's columns are different — so
    headers are kept exactly as they appear in the file (not lowercased),
    and every column becomes a field as-is."""
    if filename.endswith(".xlsx") or filename.endswith(".xls"):
        wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
        sheet = wb.active
        raw_rows = [list(row) for row in sheet.iter_rows(values_only=True)]
    else:
        text = content.decode("utf-8-sig", errors="replace")
        raw_rows = list(csv.reader(io.StringIO(text)))

    if not raw_rows:
        raise ValueError("File is empty")

    header_idx, is_labeled = _find_header_row(raw_rows)
    data_start = header_idx + 1
    if is_labeled:
        # Cell 0 of the header row is the "Column Labels:" label itself,
        # not a real column — Frappe's own convention is that the first
        # data column is always blank too (its Data Import Template says
        # so explicitly), so both header and data rows are read starting
        # from column 1.
        header_cells = raw_rows[header_idx][1:]
        while data_start < len(raw_rows) and _is_template_metadata_row(raw_rows[data_start]):
            data_start += 1
    else:
        header_cells = raw_rows[header_idx]

    headers = [str(cell or "").strip() for cell in header_cells]
    rows_data: list[dict[str, str]] = []
    for row in raw_rows[data_start:]:
        cells = row[1:] if is_labeled else row
        if not any(cell not in (None, "") for cell in cells):
            continue
        row_dict = {}
        for idx, cell in enumerate(cells):
            if idx >= len(headers) or not headers[idx]:
                continue
            value = _unwrap_quotes(str(cell if cell is not None else "").strip())
            # Skip empty values instead of storing "header: " noise.
            if value:
                row_dict[headers[idx]] = value
        if row_dict:
            rows_data.append(row_dict)
    return rows_data


def _run_master_data_import_job(
    connection_id: str, table_name: str, module: str | None, filename: str, content: bytes
) -> None:
    """Runs via BackgroundTasks — mirrors sql_examples.py's
    _run_sql_example_import_job exactly, one level simpler since there's
    only one sheet/row shape to worry about (no header-alias resolution,
    since these headers ARE the actual table's column names)."""
    key = _progress_key(connection_id, table_name)
    progress = store.master_data_import_progress_store.get(key)
    if not progress:
        return

    try:
        rows_data = _parse_master_data_rows(filename, content)
    except Exception as e:
        print(f"Error parsing master data import file for {key} -- {e}")
        logger.exception("Error parsing master data import file for %s", key)
        progress.status = "failed"
        progress.error = f"Failed to parse file: {e}"
        progress.completed_at = now_fn()
        return

    if not rows_data:
        progress.status = "failed"
        progress.error = "No data rows found in file"
        progress.completed_at = now_fn()
        return

    progress.total_rows = len(rows_data)
    errors: list[str] = []
    imported_count = 0

    for i, row in enumerate(rows_data, start=2):
        new_id = new_id_fn()
        record = MasterDataRecord(
            id=new_id,
            connection_id=connection_id,
            module=module,
            table_name=table_name,
            row_data=row,
            created_at=now_fn(),
            source="excel_import",
        )
        store.master_data_record_store[new_id] = record
        try:
            rag.train_master_data_row_now(new_id, connection_id, table_name, row, module=module)
        except Exception as e:
            print(f"Error embedding master data row {new_id} -- {e}")
            logger.exception("Error embedding master data row %s", new_id)
            errors.append(f"Row {i}: failed to embed — {e}")
            progress.failed_count += 1
        else:
            imported_count += 1
        progress.processed_rows += 1

    progress.status = "completed"
    progress.imported_count = imported_count
    progress.errors = errors
    progress.completed_at = now_fn()


@router.post("/import", response_model=MasterDataImportProgress, status_code=202)
async def import_master_data_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    connection_id: str = Form(...),
    table_name: str = Form(...),
    module: Optional[str] = Form(None),
):
    """connection_id and table_name are both required — master data is
    always "the data of a particular table" for a particular connection.
    Returns immediately (202) with a "running" MasterDataImportProgress; the
    actual parsing + per-row embedding happens in the background. Poll
    GET /import/progress?connection_id=&table_name= for status."""
    if connection_id not in store.connections_store:
        raise HTTPException(status_code=404, detail="Connection not found")
    if not table_name.strip():
        raise HTTPException(status_code=400, detail="table_name is required")

    filename = file.filename or ""
    content = await file.read()

    key = _progress_key(connection_id, table_name)
    progress = MasterDataImportProgress(status="running", table_name=table_name, started_at=now_fn())
    store.master_data_import_progress_store[key] = progress
    background_tasks.add_task(_run_master_data_import_job, connection_id, table_name, module, filename, content)
    return progress


@router.get("/import/progress", response_model=MasterDataImportProgress)
def get_master_data_import_progress(connection_id: str, table_name: str):
    if connection_id not in store.connections_store:
        raise HTTPException(status_code=404, detail="Connection not found")
    key = _progress_key(connection_id, table_name)
    return store.master_data_import_progress_store.get(key, MasterDataImportProgress())


@router.delete("/{item_id}", status_code=204)
def delete_master_data_record(item_id: str):
    existing = store.master_data_record_store.get(item_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Master data record not found")
    del store.master_data_record_store[item_id]
    try:
        rag.delete_master_data_vector(item_id, existing.connection_id)
    except Exception as e:
        print(f"Error deleting master data record {item_id} from Qdrant -- {e}")
        logger.exception("Error deleting master data record %s from Qdrant", item_id)


@router.post("/batch-delete", status_code=204)
def delete_master_data_batch(payload: MasterDataBatchDeleteRequest):
    for item_id in payload.ids:
        existing = store.master_data_record_store.get(item_id)
        if existing:
            del store.master_data_record_store[item_id]
            try:
                rag.delete_master_data_vector(item_id, existing.connection_id)
            except Exception as e:
                print(f"Error deleting master data record {item_id} from Qdrant -- {e}")
                logger.exception("Error deleting master data record %s from Qdrant", item_id)
