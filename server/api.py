"""FastAPI application: the analytics pipeline exposed over HTTP.

Also serves the built React client from web/dist, so a single `python -m server`
runs the whole product with no Node.js on the machine.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import APIRouter, Body, FastAPI, File, HTTPException, Query, UploadFile  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from src.analysis import apply_filters, headline_kpis  # noqa: E402
from src.answer import answer_question, executive_summary  # noqa: E402
from src.charts import (  # noqa: E402
    correlation_heatmap,
    distribution_chart,
    missing_values_chart,
    overview_trend_chart,
    top_categories_chart,
)
from src.config import DATA_DIR, GROQ_API_KEY, GROQ_MODEL  # noqa: E402
from src.ingestion import IngestionError, excel_sheet_names  # noqa: E402
from src.llm import GroqClient  # noqa: E402
from src.planner import describe_plan  # noqa: E402
from src.profiling import correlation_matrix, detect_anomalies  # noqa: E402
from server import store  # noqa: E402
from server.schemas import (  # noqa: E402
    chunks_json,
    cleaning_json,
    figure_to_json,
    frame_to_json,
    kpi_json,
    profile_json,
    result_json,
)

WEB_DIST = ROOT / "web" / "dist"
SAMPLE_FILES = {
    "superstore": DATA_DIR / "superstore.csv",
    "supermarket": DATA_DIR / "supermarket_sales.csv",
}

api = APIRouter(prefix="/api")

_client: GroqClient | None = None


def get_client() -> GroqClient:
    global _client
    if _client is None:
        _client = GroqClient(GROQ_API_KEY, GROQ_MODEL)
    return _client


def require_dataset(dataset_id: str):
    dataset = store.REGISTRY.get(dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found. Upload it again.")
    return dataset


def dataset_summary(dataset) -> dict[str, Any]:
    return {
        "id": dataset.id,
        "name": dataset.name,
        "filename": dataset.filename,
        "rows": dataset.profile.rows,
        "columns": dataset.profile.columns,
    }


def dataset_payload(dataset) -> dict[str, Any]:
    return {
        **dataset_summary(dataset),
        "profile": profile_json(dataset.profile),
        "cleaning": cleaning_json(dataset.cleaning),
        "vectorStore": {
            "status": dataset.vector_store().status(),
            "backend": dataset.vector_store().backend,
            "chunks": dataset.vector_store().count(),
            "error": dataset.vector_store().error,
        },
    }


def filtered_frame(dataset, filters: list[dict[str, Any]] | None):
    """Apply UI filters, returning (frame, descriptions, warnings)."""
    if not filters:
        return dataset.clean, [], []
    return apply_filters(dataset.clean, filters)


# ---------------------------------------------------------------------------
# Meta
# ---------------------------------------------------------------------------


@api.get("/health")
def health() -> dict[str, Any]:
    client = get_client()
    return {
        "status": "ok",
        "llmConfigured": client.available,
        "model": client.model,
        "lastModelUsed": client.last_model_used,
        "lastError": client.last_error,
        "samples": [name for name, path in SAMPLE_FILES.items() if path.exists()],
        "datasets": [dataset_summary(d) for d in store.REGISTRY.list()],
    }


@api.get("/models")
def models() -> dict[str, Any]:
    client = get_client()
    return {"configured": client.model, "available": client.list_models()}


# ---------------------------------------------------------------------------
# Dataset lifecycle
# ---------------------------------------------------------------------------


@api.post("/datasets/upload")
async def upload_dataset(
    file: UploadFile = File(...), sheet: str | None = Query(default=None)
) -> dict[str, Any]:
    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    try:
        dataset = store.ingest(payload, file.filename or "dataset.csv", sheet)
    except IngestionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"{type(exc).__name__}: {exc}") from exc
    return dataset_payload(dataset)


@api.post("/datasets/sheets")
async def list_sheets(file: UploadFile = File(...)) -> dict[str, Any]:
    payload = await file.read()
    return {"sheets": excel_sheet_names(payload)}


@api.post("/datasets/sample/{name}")
def load_sample(name: str) -> dict[str, Any]:
    path = SAMPLE_FILES.get(name)
    if path is None or not path.exists():
        raise HTTPException(
            status_code=404,
            detail="Example dataset missing. Run: python data/fetch_data.py",
        )
    dataset = store.ingest(path.read_bytes(), path.name)
    return dataset_payload(dataset)


@api.get("/datasets/{dataset_id}")
def get_dataset(dataset_id: str) -> dict[str, Any]:
    return dataset_payload(require_dataset(dataset_id))


@api.delete("/datasets/{dataset_id}")
def delete_dataset(dataset_id: str) -> dict[str, Any]:
    return {"removed": store.REGISTRY.remove(dataset_id)}


@api.post("/datasets/{dataset_id}/context/pdf")
async def add_pdf(dataset_id: str, file: UploadFile = File(...)) -> dict[str, Any]:
    dataset = require_dataset(dataset_id)
    payload = await file.read()
    added = store.add_pdf_context(dataset, payload, file.filename or "report.pdf")
    return {
        "chunksAdded": added,
        "vectorStore": {
            "status": dataset.vector_store().status(),
            "chunks": dataset.vector_store().count(),
        },
    }


# ---------------------------------------------------------------------------
# Filter options and data
# ---------------------------------------------------------------------------


@api.get("/datasets/{dataset_id}/filters")
def filter_options(dataset_id: str) -> dict[str, Any]:
    dataset = require_dataset(dataset_id)
    profile = dataset.profile
    options = []
    for column in profile.dimensions:
        unique = dataset.clean[column].nunique()
        if unique > 60:
            continue
        values = sorted(dataset.clean[column].dropna().astype(str).unique().tolist())
        options.append({"column": column, "values": values})
        if len(options) >= 5:
            break

    date_range = None
    if profile.primary_date:
        dates = dataset.clean[profile.primary_date].dropna()
        if not dates.empty:
            date_range = {
                "column": profile.primary_date,
                "min": str(dates.min().date()),
                "max": str(dates.max().date()),
            }
    return {"categorical": options, "date": date_range}


@api.post("/datasets/{dataset_id}/rows")
def rows(
    dataset_id: str,
    body: dict[str, Any] = Body(default={}),
) -> dict[str, Any]:
    dataset = require_dataset(dataset_id)
    which = body.get("source", "clean")
    limit = int(body.get("limit", 100))
    offset = int(body.get("offset", 0))
    frame = dataset.raw if which == "raw" else dataset.clean
    if which != "raw":
        frame, _, _ = filtered_frame(dataset, body.get("filters"))
    window = frame.iloc[offset : offset + limit]
    payload = frame_to_json(window)
    payload["total"] = len(frame)
    payload["offset"] = offset
    return payload


@api.post("/datasets/{dataset_id}/export")
def export_rows(dataset_id: str, body: dict[str, Any] = Body(default={})) -> Any:
    """Filtered data as CSV text - the browser turns it into a download."""
    dataset = require_dataset(dataset_id)
    frame, _, _ = filtered_frame(dataset, body.get("filters"))
    return JSONResponse(
        {"filename": f"{dataset.name}_filtered.csv", "csv": frame.to_csv(index=False)}
    )


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


@api.post("/datasets/{dataset_id}/overview")
def overview(dataset_id: str, body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    dataset = require_dataset(dataset_id)
    profile = dataset.profile
    view, described, warnings = filtered_frame(dataset, body.get("filters"))

    if view.empty:
        raise HTTPException(status_code=400, detail="No rows match the current filters.")

    charts: list[dict[str, Any]] = []

    def add(key: str, title: str, figure: Any) -> None:
        payload = figure_to_json(figure)
        if payload:
            charts.append({"key": key, "title": title, "figure": payload})

    metric = profile.primary_metric
    if metric and profile.primary_date:
        add("trend", f"Monthly {metric}", overview_trend_chart(view, metric, profile.primary_date))
    if metric and profile.dimensions:
        add(
            "top",
            f"Top {profile.dimensions[0]} by {metric}",
            top_categories_chart(view, metric, profile.dimensions[0]),
        )
    if metric:
        add("distribution", f"Distribution of {metric}", distribution_chart(view, metric))
    matrix = correlation_matrix(view, profile)
    if not matrix.empty:
        add("correlation", "Correlation between metrics", correlation_heatmap(matrix))
    add("missing", "Missing values by column", missing_values_chart(view))

    anomalies = []
    if metric and profile.primary_date:
        flagged = detect_anomalies(view, metric, profile.primary_date)
        if not flagged.empty:
            anomalies = flagged.to_dict(orient="records")

    return {
        "rowsInView": len(view),
        "rowsTotal": profile.rows,
        "filtersApplied": described,
        "filterWarnings": warnings,
        "kpis": kpi_json(headline_kpis(view, profile)),
        "charts": charts,
        "anomalies": anomalies,
        "anomalyMetric": metric,
    }


@api.post("/datasets/{dataset_id}/summary")
def summary(dataset_id: str, body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    dataset = require_dataset(dataset_id)
    view, _, _ = filtered_frame(dataset, body.get("filters"))
    if view.empty:
        raise HTTPException(status_code=400, detail="No rows match the current filters.")
    client = get_client()
    text, facts = executive_summary(view, dataset.profile, client)
    payload = {
        "summary": text,
        "facts": facts,
        "source": "llm" if client.available and client.last_error is None else "computed",
        "model": client.last_model_used,
    }
    dataset.summary = payload
    return payload


# ---------------------------------------------------------------------------
# The assistant
# ---------------------------------------------------------------------------


@api.post("/datasets/{dataset_id}/ask")
def ask(dataset_id: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    dataset = require_dataset(dataset_id)
    question = str(body.get("question", "")).strip()
    if not question:
        raise HTTPException(status_code=400, detail="Ask a question first.")

    history = [
        {"role": str(turn.get("role")), "content": str(turn.get("content", ""))}
        for turn in (body.get("history") or [])
        if turn.get("content")
    ][-6:]

    client = get_client()
    answer = answer_question(
        question=question,
        df=dataset.clean,
        profile=dataset.profile,
        store=dataset.vector_store(),
        client=client,
        history=history,
        extra_filters=body.get("filters"),
    )

    if not answer.ok:
        return {
            "ok": False,
            "question": question,
            "error": answer.error,
            "context": chunks_json(answer.context_chunks),
            "planner": answer.planner_source,
        }

    payload = {
        "ok": True,
        "question": question,
        "narrative": answer.narrative,
        "result": result_json(answer.result),
        "figure": figure_to_json(answer.figure),
        "evidence": {
            **{k: v for k, v in answer.evidence.items() if k != "retrieved_chunks"},
            "planDescription": describe_plan(answer.result.plan),
        },
        "context": chunks_json(answer.context_chunks),
        "planner": answer.planner_source,
        "narrator": answer.narrator_source,
        "model": client.last_model_used,
    }
    dataset.chat.append({"question": question, "narrative": answer.narrative})
    return payload


# ---------------------------------------------------------------------------
# Retrieval inspector
# ---------------------------------------------------------------------------


@api.post("/datasets/{dataset_id}/retrieve")
def retrieve(dataset_id: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    dataset = require_dataset(dataset_id)
    query = str(body.get("query", "")).strip()
    limit = int(body.get("limit", 5))
    if not query:
        return {"chunks": []}
    return {"chunks": chunks_json(dataset.vector_store().query(query, k=limit))}


@api.get("/datasets/{dataset_id}/documents")
def documents(dataset_id: str) -> dict[str, Any]:
    dataset = require_dataset(dataset_id)
    counts: dict[str, int] = {}
    for document in dataset.documents:
        kind = document["metadata"]["kind"]
        counts[kind] = counts.get(kind, 0) + 1
    return {
        "counts": counts,
        "documents": [
            {
                "id": d["id"],
                "kind": d["metadata"]["kind"],
                "column": d["metadata"].get("column") or None,
                "text": d["text"],
            }
            for d in dataset.documents
        ],
        "vectorStore": {
            "status": dataset.vector_store().status(),
            "backend": dataset.vector_store().backend,
            "chunks": dataset.vector_store().count(),
            "error": dataset.vector_store().error,
        },
    }


# ---------------------------------------------------------------------------
# App assembly
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    app = FastAPI(
        title="RAG Data Analytics Assistant",
        description="Natural-language analytics over your own datasets.",
        version="1.0.0",
    )

    # The Vite dev server runs on another port during development
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:4173",
        ],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api)

    if WEB_DIST.exists():
        assets = WEB_DIST / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

        @app.get("/{full_path:path}")
        def serve_spa(full_path: str):
            candidate = WEB_DIST / full_path
            if full_path and candidate.is_file():
                return FileResponse(str(candidate))
            return FileResponse(str(WEB_DIST / "index.html"))

    else:

        @app.get("/")
        def missing_build() -> dict[str, Any]:
            return {
                "detail": "The React client has not been built yet.",
                "fix": "cd web && npm install && npm run build",
                "api": "/api/health",
            }

    return app


app = create_app()
