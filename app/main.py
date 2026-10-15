from __future__ import annotations

import json
import logging
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import plotly
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from app import analysis, assistant, storage
from app.config import DATA_DIR, MAX_COLUMNS, MAX_ROWS, MAX_UPLOAD_BYTES
from app.observability import configure_logging


app = FastAPI(title="InsightForge", description="AI and data intelligence workspace", version="1.0.0")
configure_logging()
logger = logging.getLogger("insightforge")
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
app.mount("/vendor", StaticFiles(directory=Path(plotly.__file__).parent / "package_data"), name="vendor")
HTTP_REQUESTS = Counter("insightforge_http_requests_total", "HTTP requests", ["method", "route", "status"])
HTTP_DURATION = Histogram("insightforge_http_request_duration_seconds", "HTTP request latency", ["method", "route"])


@app.middleware("http")
async def observe_requests(request, call_next):
    import time
    start = time.perf_counter()
    response = await call_next(request)
    route = request.scope.get("route")
    route_name = getattr(route, "path", "unmatched")
    if route_name != "/api/metrics":
        HTTP_REQUESTS.labels(request.method, route_name, str(response.status_code)).inc()
        HTTP_DURATION.labels(request.method, route_name).observe(time.perf_counter() - start)
    return response


@app.on_event("startup")
def startup():
    storage.initialize()


@app.on_event("shutdown")
def shutdown():
    storage.close()


@app.exception_handler(Exception)
async def unexpected_error_handler(_, exc: Exception):
    logger.exception("Unhandled request error", exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "The request could not be completed."})


def read_dataset(dataset_id: str) -> pd.DataFrame:
    try:
        return storage.load_dataframe(dataset_id)
    except FileNotFoundError:
        raise HTTPException(404, "Dataset not found")
    except (pd.errors.ParserError, UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(422, f"Could not read dataset: {exc}")


def validate_column_names(df: pd.DataFrame) -> pd.DataFrame:
    names = []
    seen = set()
    for index, raw in enumerate(df.columns):
        name = str(raw).strip() or f"column_{index + 1}"
        base, candidate, suffix = name, name, 2
        while candidate in seen:
            candidate = f"{base}_{suffix}"
            suffix += 1
        names.append(candidate)
        seen.add(candidate)
    df.columns = names
    return df


class CleanRequest(BaseModel):
    drop_duplicates: bool = True
    impute: str = Field(default="none", pattern="^(none|median|mean|mode)$")


class ChartRequest(BaseModel):
    kind: str = Field(pattern="^(histogram|bar|scatter|box)$")
    x: str
    y: str | None = None


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)


class AnomalyRequest(BaseModel):
    columns: list[str] | None = None
    method: str = Field(default="isolation_forest", pattern="^(isolation_forest|iqr|zscore)$")


class StatisticalTestRequest(BaseModel):
    test: str = Field(pattern="^(normality_shapiro|two_group_ttest|spearman)$")
    column: str
    group_column: str | None = None
    group_a: str | None = None
    group_b: str | None = None


class DecisionBriefRequest(BaseModel):
    date_column: str
    metric_column: str
    segment_column: str | None = None
    aggregation: str = Field(default="sum", pattern="^(sum|mean|count)$")
    period: str = Field(default="auto", pattern="^(auto|day|week|month)$")


@app.get("/", include_in_schema=False)
def home():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/api/health")
def health():
    database = "postgresql" if storage._postgres_enabled() else "local files"
    ready = storage.database_health()
    return {"status": "ok" if ready else "degraded", "database": database, "database_ready": ready, "ai_enabled": bool(assistant.LLM_API_KEY)}


@app.get("/api/metrics", include_in_schema=False)
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/api/datasets")
def datasets():
    return {"datasets": storage.list_datasets()}


@app.post("/api/datasets")
async def upload_dataset(file: UploadFile = File(...)):
    if not file.filename or Path(file.filename).suffix.lower() != ".csv":
        raise HTTPException(400, "Upload a .csv file")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temp_path = None
    size = 0
    try:
        with tempfile.NamedTemporaryFile(dir=DATA_DIR, suffix=".csv", delete=False) as tmp:
            temp_path = Path(tmp.name)
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, f"CSV exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB upload limit")
                tmp.write(chunk)
        try:
            df = pd.read_csv(temp_path, low_memory=False)
        except (pd.errors.ParserError, UnicodeDecodeError, pd.errors.EmptyDataError) as exc:
            raise HTTPException(422, f"Could not parse CSV: {exc}")
        if df.empty and len(df.columns) == 0:
            raise HTTPException(422, "CSV has no columns")
        if len(df) > MAX_ROWS or len(df.columns) > MAX_COLUMNS:
            raise HTTPException(413, f"CSV exceeds the limit of {MAX_ROWS:,} rows or {MAX_COLUMNS} columns")
        df = validate_column_names(df)
        df.to_csv(temp_path, index=False)
        dataset_id = uuid.uuid4().hex
        now = datetime.now(timezone.utc).isoformat()
        metadata = {"id": dataset_id, "name": Path(file.filename).name[:160], "rows": int(len(df)), "columns": int(len(df.columns)), "column_names": [str(c) for c in df.columns], "created_at": now, "updated_at": now, "active_file": "original.csv"}
        storage.save_dataset(dataset_id, temp_path, metadata, df)
        temp_path = None
        return {"dataset": metadata, "profile": analysis.profile(df)}
    finally:
        await file.close()
        if temp_path and temp_path.exists():
            temp_path.unlink(missing_ok=True)


@app.get("/api/datasets/{dataset_id}/profile")
def dataset_profile(dataset_id: str):
    return analysis.profile(read_dataset(dataset_id))


@app.get("/api/datasets/{dataset_id}/analysis")
def dataset_analysis(dataset_id: str):
    return analysis.overview(read_dataset(dataset_id))


@app.post("/api/datasets/{dataset_id}/clean")
def clean_dataset(dataset_id: str, request: CleanRequest):
    df = read_dataset(dataset_id)
    cleaned, report = analysis.clean_dataframe(df, request.drop_duplicates, request.impute)
    meta = storage.load_metadata(dataset_id)
    if len(cleaned) > MAX_ROWS:
        raise HTTPException(413, "Cleaned dataset exceeds row limit")
    filename = "cleaned.csv"
    output_path = storage.dataset_dir(dataset_id) / filename
    cleaned.to_csv(output_path, index=False)
    storage.replace_rows(dataset_id, cleaned)
    meta["active_file"] = filename
    meta["rows"] = len(cleaned)
    meta["columns"] = len(cleaned.columns)
    meta["column_names"] = [str(c) for c in cleaned.columns]
    storage.save_metadata(dataset_id, meta)
    return {"report": report, "profile": analysis.profile(cleaned)}


@app.post("/api/datasets/{dataset_id}/chart")
def dataset_chart(dataset_id: str, request: ChartRequest):
    try:
        return Response(analysis.chart(read_dataset(dataset_id), request.kind, request.x, request.y), media_type="application/json")
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@app.post("/api/datasets/{dataset_id}/analysis/anomalies")
def dataset_anomalies(dataset_id: str, request: AnomalyRequest):
    try:
        return analysis.detect_anomalies(read_dataset(dataset_id), request.columns, request.method)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@app.post("/api/datasets/{dataset_id}/analysis/statistical-test")
def dataset_statistical_test(dataset_id: str, request: StatisticalTestRequest):
    try:
        return analysis.statistical_test(read_dataset(dataset_id), request.test, request.column, request.group_column, request.group_a, request.group_b)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@app.post("/api/datasets/{dataset_id}/analysis/decision-brief")
def dataset_decision_brief(dataset_id: str, request: DecisionBriefRequest):
    try:
        return analysis.decision_brief(
            read_dataset(dataset_id), request.date_column, request.metric_column,
            request.segment_column, request.aggregation, request.period,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@app.post("/api/datasets/{dataset_id}/ask")
async def ask_dataset(dataset_id: str, request: AskRequest):
    df = read_dataset(dataset_id)
    try:
        return await assistant.answer(request.question, df)
    except Exception as exc:
        raise HTTPException(502, "The AI service failed. Check its configuration and try again.") from exc


@app.get("/api/datasets/{dataset_id}/download")
def download_dataset(dataset_id: str):
    try:
        path = storage.csv_path(dataset_id)
        name = storage.load_metadata(dataset_id)["name"]
    except FileNotFoundError:
        raise HTTPException(404, "Dataset not found")
    stem = re.sub(r"[^A-Za-z0-9._-]", "_", Path(name).stem)[:100] or "dataset"
    return FileResponse(path, filename=f"{stem}-analysis.csv", media_type="text/csv")


@app.delete("/api/datasets/{dataset_id}", status_code=204)
def remove_dataset(dataset_id: str):
    try:
        storage.delete_dataset(dataset_id)
    except FileNotFoundError:
        raise HTTPException(404, "Dataset not found")
    return Response(status_code=204)
