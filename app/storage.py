import json
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from app.config import DATA_DIR, DATABASE_URL

_pool = None


def _postgres_enabled() -> bool:
    return bool(DATABASE_URL)


@contextmanager
def _connection():
    if _pool is None:
        import psycopg
        with psycopg.connect(DATABASE_URL) as conn:
            yield conn
    else:
        with _pool.connection() as conn:
            yield conn


def initialize() -> None:
    global _pool
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not _postgres_enabled():
        return
    from alembic import command
    from alembic.config import Config
    project_root = Path(__file__).resolve().parent.parent
    migration_config = Config(str(project_root / "alembic.ini"))
    migration_config.set_main_option("script_location", str(project_root / "migrations"))
    command.upgrade(migration_config, "head")
    from psycopg_pool import ConnectionPool
    if _pool is None:
        _pool = ConnectionPool(DATABASE_URL, min_size=1, max_size=8, open=False)
        _pool.open(wait=True)
    # Import local catalogs created before the PostgreSQL catalog was enabled.
    for folder in DATA_DIR.iterdir():
        file = folder / "metadata.json"
        if folder.is_dir() and file.is_file():
            try:
                meta = json.loads(file.read_text(encoding="utf-8"))
                with _connection() as conn:
                    _upsert_metadata(meta, conn, insert_only=True)
                    stored_rows = conn.execute("SELECT count(*) FROM insightforge_dataset_rows WHERE dataset_id = %s", (meta["id"],)).fetchone()[0]
                    active_file = folder / meta.get("active_file", "original.csv")
                    if stored_rows == 0 and meta.get("rows", 0) and active_file.is_file():
                        import pandas as pd
                        _write_rows(conn, meta["id"], pd.read_csv(active_file, low_memory=False))
            except (OSError, json.JSONDecodeError, KeyError, ValueError):
                continue


def close() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def _safe_id(dataset_id: str) -> str:
    if not re.fullmatch(r"[a-f0-9]{32}", dataset_id):
        raise ValueError("Invalid dataset ID")
    return dataset_id


def dataset_dir(dataset_id: str) -> Path:
    return DATA_DIR / _safe_id(dataset_id)


def metadata_path(dataset_id: str) -> Path:
    return dataset_dir(dataset_id) / "metadata.json"


def _write_metadata_file(dataset_id: str, metadata: dict) -> None:
    target = metadata_path(dataset_id)
    temp = target.with_suffix(".json.tmp")
    temp.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    temp.replace(target)


def _upsert_metadata(metadata: dict, conn, insert_only: bool = False) -> None:
    from psycopg.types.json import Jsonb
    conflict = "DO NOTHING" if insert_only else "DO UPDATE SET name=EXCLUDED.name, row_count=EXCLUDED.row_count, column_count=EXCLUDED.column_count, updated_at=EXCLUDED.updated_at, active_file=EXCLUDED.active_file, metadata=EXCLUDED.metadata"
    conn.execute(f"""
        INSERT INTO insightforge_datasets
          (id, name, row_count, column_count, created_at, updated_at, active_file, metadata)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (id) {conflict}
    """, (metadata["id"], metadata["name"], metadata["rows"], metadata["columns"], metadata["created_at"], metadata["updated_at"], metadata.get("active_file", "original.csv"), Jsonb(metadata)))


def _write_rows(conn, dataset_id: str, dataframe) -> None:
    from psycopg.types.json import Jsonb
    conn.execute("DELETE FROM insightforge_dataset_rows WHERE dataset_id = %s", (dataset_id,))
    with conn.cursor() as cursor:
        for start in range(0, len(dataframe), 1000):
            records = json.loads(dataframe.iloc[start:start + 1000].to_json(orient="records", date_format="iso", double_precision=15))
            cursor.executemany(
                "INSERT INTO insightforge_dataset_rows (dataset_id, row_number, record) VALUES (%s, %s, %s)",
                ((dataset_id, start + index, Jsonb(record)) for index, record in enumerate(records)),
            )


def save_dataset(dataset_id: str, csv_path: Path, metadata: dict, dataframe=None) -> None:
    folder = dataset_dir(dataset_id)
    folder.mkdir(parents=True, exist_ok=False)
    csv_path.replace(folder / "original.csv")
    _write_metadata_file(dataset_id, metadata)
    if _postgres_enabled():
        with _connection() as conn:
            _upsert_metadata(metadata, conn)
            if dataframe is not None:
                _write_rows(conn, dataset_id, dataframe)


def replace_rows(dataset_id: str, dataframe) -> None:
    if not _postgres_enabled():
        return
    _safe_id(dataset_id)
    with _connection() as conn:
        _write_rows(conn, dataset_id, dataframe)


def load_dataframe(dataset_id: str):
    import pandas as pd
    if _postgres_enabled():
        metadata = load_metadata(dataset_id)
        with _connection() as conn:
            rows = conn.execute("SELECT record FROM insightforge_dataset_rows WHERE dataset_id = %s ORDER BY row_number", (dataset_id,)).fetchall()
        if rows:
            return pd.DataFrame([row[0] for row in rows])
        if metadata.get("rows", 0) == 0:
            return pd.DataFrame(columns=metadata.get("column_names", []))
        raise FileNotFoundError(dataset_id)
    return pd.read_csv(csv_path(dataset_id), low_memory=False)


def load_metadata(dataset_id: str) -> dict:
    _safe_id(dataset_id)
    if _postgres_enabled():
        with _connection() as conn:
            row = conn.execute("SELECT metadata FROM insightforge_datasets WHERE id = %s", (dataset_id,)).fetchone()
        if row:
            return row[0]
    path = metadata_path(dataset_id)
    if not path.is_file():
        raise FileNotFoundError(dataset_id)
    return json.loads(path.read_text(encoding="utf-8"))


def save_metadata(dataset_id: str, metadata: dict) -> None:
    metadata["updated_at"] = datetime.now(timezone.utc).isoformat()
    _write_metadata_file(dataset_id, metadata)
    if _postgres_enabled():
        with _connection() as conn:
            _upsert_metadata(metadata, conn)


def csv_path(dataset_id: str) -> Path:
    folder = dataset_dir(dataset_id)
    meta = load_metadata(dataset_id)
    path = folder / meta.get("active_file", "original.csv")
    if not path.is_file():
        raise FileNotFoundError(dataset_id)
    return path


def list_datasets() -> list[dict]:
    if _postgres_enabled():
        with _connection() as conn:
            rows = conn.execute("SELECT id, name, row_count, column_count, created_at, updated_at FROM insightforge_datasets ORDER BY created_at DESC").fetchall()
        return [{"id": row[0].strip(), "name": row[1], "rows": row[2], "columns": row[3], "created_at": row[4].isoformat(), "updated_at": row[5].isoformat()} for row in rows]
    results = []
    for folder in DATA_DIR.iterdir():
        meta_file = folder / "metadata.json"
        if folder.is_dir() and meta_file.is_file():
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                results.append({k: meta[k] for k in ("id", "name", "rows", "columns", "created_at", "updated_at") if k in meta})
            except (OSError, json.JSONDecodeError):
                continue
    return sorted(results, key=lambda item: item.get("created_at", ""), reverse=True)


def database_health() -> bool:
    if not _postgres_enabled():
        return True
    try:
        with _connection() as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        return False


def delete_dataset(dataset_id: str) -> None:
    folder = dataset_dir(dataset_id)
    if not folder.is_dir():
        raise FileNotFoundError(dataset_id)
    if _postgres_enabled():
        with _connection() as conn:
            conn.execute("DELETE FROM insightforge_datasets WHERE id = %s", (dataset_id,))
    for item in folder.iterdir():
        if item.is_file():
            item.unlink()
    folder.rmdir()
