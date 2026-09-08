"""Turn the analytics objects into plain JSON the React client can consume.

Kept separate from the routes so the serialisation rules (NaN handling, float
rounding, Plotly figure encoding) live in one place.
"""
from __future__ import annotations

import json
import math
from typing import Any

import numpy as np
import pandas as pd

from src.analysis import AnalysisResult, format_number
from src.ingestion import CleaningReport
from src.metadata import suggested_derived_metrics
from src.profiling import DatasetProfile
from src.vectorstore import RetrievedChunk


def clean_value(value: Any) -> Any:
    """JSON-safe scalar: NaN/Inf become None, numpy types become Python types."""
    if value is None:
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return None if (math.isnan(number) or math.isinf(number)) else number
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if value is pd.NaT:
        return None
    if isinstance(value, (np.ndarray, list, tuple)):
        return [clean_value(v) for v in value]
    if isinstance(value, dict):
        return {str(k): clean_value(v) for k, v in value.items()}
    return value


def frame_to_json(df: pd.DataFrame, limit: int | None = None) -> dict[str, Any]:
    """A DataFrame as {columns, rows, total} with every cell JSON-safe."""
    if df is None:
        return {"columns": [], "rows": [], "total": 0}
    total = len(df)
    frame = df.head(limit) if limit else df

    columns = []
    for name in frame.columns:
        series = frame[name]
        if pd.api.types.is_numeric_dtype(series):
            kind = "number"
        elif pd.api.types.is_datetime64_any_dtype(series):
            kind = "date"
        else:
            kind = "text"
        columns.append({"key": str(name), "type": kind})

    rows = []
    for record in frame.to_dict(orient="records"):
        rows.append({str(k): clean_value(v) for k, v in record.items()})

    return {"columns": columns, "rows": rows, "total": total}


def figure_to_json(figure: Any) -> dict[str, Any] | None:
    """Plotly figure -> {data, layout} dict, ready for Plotly.react in the browser."""
    if figure is None:
        return None
    try:
        payload = json.loads(figure.to_json())
    except Exception:  # noqa: BLE001 - a chart must never break an answer
        return None
    return {"data": payload.get("data", []), "layout": payload.get("layout", {})}


def column_profile_json(column: Any) -> dict[str, Any]:
    return {
        "name": column.name,
        "dtype": column.dtype,
        "role": column.role,
        "missing": column.missing,
        "missingPct": column.missing_pct,
        "unique": column.unique,
        "uniquePct": column.unique_pct,
        "sampleValues": column.sample_values,
        "min": clean_value(column.minimum),
        "max": clean_value(column.maximum),
        "mean": clean_value(column.mean),
        "median": clean_value(column.median),
        "std": clean_value(column.std),
        "zeros": column.zeros,
        "negatives": column.negatives,
        "outliers": column.outliers,
        "dateMin": column.date_min,
        "dateMax": column.date_max,
        "topValues": column.top_values,
        "defaultAggregation": column.default_aggregation,
    }


def profile_json(profile: DatasetProfile) -> dict[str, Any]:
    return {
        "name": profile.name,
        "rows": profile.rows,
        "columns": profile.columns,
        "memoryMb": profile.memory_mb,
        "duplicateRows": profile.duplicate_rows,
        "missingCells": profile.missing_cells,
        "missingPct": profile.missing_pct,
        "metrics": profile.metrics,
        "dimensions": profile.dimensions,
        "dates": profile.dates,
        "identifiers": profile.identifiers,
        "texts": profile.texts,
        "primaryMetric": profile.primary_metric,
        "primaryDate": profile.primary_date,
        "suggestedQuestions": profile.suggested_questions,
        "columnProfiles": [column_profile_json(c) for c in profile.column_profiles],
        "derivedMetrics": suggested_derived_metrics(profile),
    }


def cleaning_json(report: CleaningReport) -> dict[str, Any]:
    payload = report.as_dict()
    payload["changes"] = _cleaning_changes(report)
    return payload


def _cleaning_changes(report: CleaningReport) -> list[str]:
    changes: list[str] = []
    if report.duplicates_removed:
        changes.append(f"Removed {report.duplicates_removed:,} duplicate rows")
    if report.parsed_dates:
        changes.append("Parsed as dates: " + ", ".join(report.parsed_dates))
    if report.coerced_numeric:
        changes.append("Converted to numeric: " + ", ".join(report.coerced_numeric))
    if report.empty_columns_dropped:
        changes.append("Dropped empty columns: " + ", ".join(report.empty_columns_dropped))
    if report.whitespace_trimmed:
        changes.append(f"Trimmed whitespace in {len(report.whitespace_trimmed)} text columns")
    if report.columns_renamed:
        changes.append(f"Tidied {len(report.columns_renamed)} column names")
    if not changes:
        changes.append("Nothing needed changing - the file was already clean")
    return changes


def chunks_json(chunks: list[RetrievedChunk]) -> list[dict[str, Any]]:
    return [
        {
            "label": chunk.label,
            "kind": chunk.metadata.get("kind", "context"),
            "column": chunk.metadata.get("column") or None,
            "score": chunk.score,
            "source": chunk.source,
            "text": chunk.text,
        }
        for chunk in chunks
    ]


def result_json(result: AnalysisResult | None) -> dict[str, Any] | None:
    if result is None:
        return None
    return {
        "table": frame_to_json(result.table, limit=500),
        "valueColumn": result.value_column,
        "labelColumn": result.label_column,
        "scalar": clean_value(result.scalar),
        "scalarFormatted": format_number(result.scalar) if result.scalar is not None else None,
        "chartType": result.chart_type,
        "plan": clean_value(result.plan.as_dict()),
        "notes": result.notes,
    }


def kpi_json(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "label": card["label"],
            "value": clean_value(card["value"]),
            "display": format_number(card["value"], card.get("format", "num")),
            "format": card.get("format", "num"),
        }
        for card in cards
    ]
