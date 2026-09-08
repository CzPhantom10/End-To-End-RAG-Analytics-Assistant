"""Automatic data profiling.

Turns a cleaned DataFrame into a structured description of itself: per-column
statistics plus a *semantic role* for every column (metric, dimension, date,
identifier, text). The roles are what let the planner reason about a dataset it
has never seen - "Sales is a metric, Region is a dimension" - without the LLM
having to guess.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from .config import PROFILE_SAMPLE_ROWS

# Roles a column can play in an analysis
ROLE_METRIC = "metric"          # numeric, meaningful to sum/average
ROLE_DIMENSION = "dimension"    # categorical, meaningful to group by
ROLE_DATE = "date"              # temporal
ROLE_IDENTIFIER = "identifier"  # keys / codes - never aggregate these
ROLE_TEXT = "text"              # free text, high cardinality

# Name fragments that strongly suggest a column is an identifier
ID_NAME_HINTS = ("id", "code", "key", "number", "no.", "uuid", "guid", "sku", "ref")

# Name fragments that suggest an additive business metric
METRIC_NAME_HINTS = (
    "sales", "revenue", "profit", "amount", "cost", "price", "value", "total",
    "quantity", "qty", "units", "spend", "margin", "income", "discount", "fee",
    "budget", "count", "volume", "gmv", "sum",
)

# Metrics that must be averaged rather than summed
RATIO_NAME_HINTS = ("rate", "ratio", "percent", "pct", "%", "score", "avg", "average", "index")


@dataclass
class ColumnProfile:
    name: str
    dtype: str
    role: str
    missing: int
    missing_pct: float
    unique: int
    unique_pct: float
    sample_values: list[str] = field(default_factory=list)
    # Numeric-only
    minimum: float | None = None
    maximum: float | None = None
    mean: float | None = None
    median: float | None = None
    std: float | None = None
    zeros: int | None = None
    negatives: int | None = None
    outliers: int | None = None
    # Date-only
    date_min: str | None = None
    date_max: str | None = None
    # Categorical-only
    top_values: dict[str, int] = field(default_factory=dict)
    # How to aggregate this column by default
    default_aggregation: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DatasetProfile:
    name: str
    rows: int
    columns: int
    memory_mb: float
    duplicate_rows: int
    missing_cells: int
    missing_pct: float
    column_profiles: list[ColumnProfile]

    # Convenience views used everywhere else in the app
    metrics: list[str] = field(default_factory=list)
    dimensions: list[str] = field(default_factory=list)
    dates: list[str] = field(default_factory=list)
    identifiers: list[str] = field(default_factory=list)
    texts: list[str] = field(default_factory=list)

    primary_metric: str | None = None
    primary_date: str | None = None
    suggested_questions: list[str] = field(default_factory=list)

    def column(self, name: str) -> ColumnProfile | None:
        for profile in self.column_profiles:
            if profile.name == name:
                return profile
        return None

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["column_profiles"] = [c.as_dict() for c in self.column_profiles]
        return payload


def _sample(df: pd.DataFrame) -> pd.DataFrame:
    if len(df) > PROFILE_SAMPLE_ROWS:
        return df.sample(PROFILE_SAMPLE_ROWS, random_state=0)
    return df


def _count_outliers(series: pd.Series) -> int:
    """IQR rule. Cheap, robust, and easy to explain in the UI."""
    values = series.dropna()
    if len(values) < 10:
        return 0
    q1, q3 = values.quantile(0.25), values.quantile(0.75)
    iqr = q3 - q1
    if iqr == 0:
        return 0
    low, high = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    return int(((values < low) | (values > high)).sum())


def _classify(series: pd.Series, name: str, row_count: int) -> tuple[str, str | None]:
    """Return (role, default_aggregation) for one column."""
    lowered = name.lower().strip()
    tokens = set(lowered.replace("_", " ").replace("-", " ").split())
    non_null = series.dropna()
    unique = int(non_null.nunique())
    unique_ratio = unique / max(len(non_null), 1)

    name_is_id = any(hint in lowered for hint in ID_NAME_HINTS) or "id" in tokens

    if pd.api.types.is_datetime64_any_dtype(series):
        return ROLE_DATE, None

    if pd.api.types.is_bool_dtype(series):
        return ROLE_DIMENSION, None

    if pd.api.types.is_numeric_dtype(series):
        name_is_metric = any(hint in lowered for hint in METRIC_NAME_HINTS)
        # Codes and keys (Row ID, Postal Code, Product Code) are never metrics,
        # however few distinct values they happen to have.
        if name_is_id and not name_is_metric:
            return ROLE_IDENTIFIER, None
        # Numeric codes with very few distinct whole-number values act like dimensions
        looks_like_code = unique <= 12 and (
            len(non_null) == 0 or bool((non_null % 1 == 0).all())
        )
        if looks_like_code and not name_is_metric:
            return ROLE_DIMENSION, None
        # Fractions and percentages must be averaged - summing them is meaningless
        is_ratio = any(hint in lowered for hint in RATIO_NAME_HINTS)
        if not is_ratio and len(non_null):
            low, high = float(non_null.min()), float(non_null.max())
            if 0.0 <= low and high <= 1.0 and unique > 2:
                is_ratio = True
        return ROLE_METRIC, "mean" if is_ratio else "sum"

    # Object / categorical from here on
    if name_is_id and unique_ratio > 0.5:
        return ROLE_IDENTIFIER, None
    if unique_ratio > 0.6 and unique > 200:
        # Long free text vs. a high-cardinality dimension like Product Name
        avg_len = float(non_null.astype(str).str.len().mean()) if len(non_null) else 0.0
        if avg_len > 60:
            return ROLE_TEXT, None
        return ROLE_DIMENSION, None
    return ROLE_DIMENSION, None


def _pick_primary_metric(profile_map: dict[str, ColumnProfile], metrics: list[str]) -> str | None:
    if not metrics:
        return None
    priority = ["sales", "revenue", "amount", "total", "profit", "value", "price", "quantity"]
    lowered = {m: m.lower() for m in metrics}
    for keyword in priority:
        for metric in metrics:
            if keyword in lowered[metric]:
                return metric
    # Fall back to the metric with the largest spread - usually the headline number
    best, best_std = metrics[0], -1.0
    for metric in metrics:
        std = profile_map[metric].std or 0.0
        if std > best_std:
            best, best_std = metric, std
    return best


def rank_dimensions(profile_map: dict[str, ColumnProfile], dimensions: list[str]) -> list[str]:
    """Order dimensions by how useful they are to group by.

    A good business dimension has a handful of distinct values and a readable
    name; a customer ID with thousands of values makes a terrible first chart.
    """

    def score(name: str) -> tuple[int, int]:
        column = profile_map.get(name)
        unique = column.unique if column else 0
        lowered = name.lower()
        if unique <= 1:
            band = 0                      # a constant column groups into nothing
        elif any(hint in lowered for hint in ID_NAME_HINTS):
            band = 0                      # last resort
        elif 2 <= unique <= 12:
            band = 4                      # ideal for a bar chart
        elif unique <= 40:
            band = 3
        elif unique <= 500:
            band = 2
        else:
            band = 1
        return band, -unique

    return sorted(dimensions, key=score, reverse=True)


def _suggest_questions(
    metrics: list[str], dimensions: list[str], dates: list[str], primary_metric: str | None
) -> list[str]:
    """Concrete starter questions built from the columns this dataset actually has."""
    questions: list[str] = []
    metric = primary_metric or (metrics[0] if metrics else None)
    if not metric:
        return ["Summarise this dataset.", "Which columns have missing values?"]

    if dates:
        questions.append(f"Show me the {metric.lower()} trend over time")
        questions.append(f"Which month had the highest {metric.lower()}?")
    if dimensions:
        first = dimensions[0]
        questions.append(f"Which {first.lower()} generated the highest {metric.lower()}?")
        if len(dimensions) > 1:
            questions.append(f"Compare {metric.lower()} across {dimensions[1].lower()}")
        if len(dimensions) > 2:
            questions.append(f"What are the top 10 {dimensions[2].lower()} by {metric.lower()}?")
        else:
            questions.append(f"What are the top 10 {first.lower()} by {metric.lower()}?")
    if len(metrics) > 1:
        questions.append(
            f"What is the relationship between {metrics[0].lower()} and {metrics[1].lower()}?"
        )
    questions.append(f"What is the total {metric.lower()}?")
    return questions[:8]


def profile_dataset(df: pd.DataFrame, name: str = "dataset") -> DatasetProfile:
    """Build a full DatasetProfile from a cleaned DataFrame."""
    sample = _sample(df)
    row_count = len(df)
    column_profiles: list[ColumnProfile] = []

    for col in df.columns:
        series = df[col]
        sampled = sample[col]
        missing = int(series.isna().sum())
        unique = int(series.nunique(dropna=True))
        role, aggregation = _classify(series, str(col), row_count)

        profile = ColumnProfile(
            name=str(col),
            dtype=str(series.dtype),
            role=role,
            missing=missing,
            missing_pct=round(missing / max(row_count, 1) * 100, 2),
            unique=unique,
            unique_pct=round(unique / max(row_count, 1) * 100, 2),
            sample_values=[str(v) for v in series.dropna().head(5).tolist()],
            default_aggregation=aggregation,
        )

        if pd.api.types.is_numeric_dtype(series) and role in (ROLE_METRIC, ROLE_IDENTIFIER):
            numeric = series.dropna()
            if len(numeric):
                profile.minimum = float(numeric.min())
                profile.maximum = float(numeric.max())
                profile.mean = float(numeric.mean())
                profile.median = float(numeric.median())
                profile.std = float(numeric.std()) if len(numeric) > 1 else 0.0
                profile.zeros = int((numeric == 0).sum())
                profile.negatives = int((numeric < 0).sum())
                profile.outliers = _count_outliers(sampled.dropna())
        elif role == ROLE_DATE:
            dates = series.dropna()
            if len(dates):
                profile.date_min = str(pd.Timestamp(dates.min()).date())
                profile.date_max = str(pd.Timestamp(dates.max()).date())
        elif role in (ROLE_DIMENSION, ROLE_TEXT):
            counts = series.value_counts(dropna=True).head(10)
            profile.top_values = {str(k): int(v) for k, v in counts.items()}

        column_profiles.append(profile)

    profile_map = {p.name: p for p in column_profiles}
    metrics = [p.name for p in column_profiles if p.role == ROLE_METRIC]
    dimensions = rank_dimensions(
        profile_map, [p.name for p in column_profiles if p.role == ROLE_DIMENSION]
    )
    dates = [p.name for p in column_profiles if p.role == ROLE_DATE]
    identifiers = [p.name for p in column_profiles if p.role == ROLE_IDENTIFIER]
    texts = [p.name for p in column_profiles if p.role == ROLE_TEXT]

    primary_metric = _pick_primary_metric(profile_map, metrics)
    primary_date = dates[0] if dates else None
    if len(dates) > 1:
        # Prefer an "order"/"transaction" style date over a shipping/created one
        for candidate in dates:
            if any(k in candidate.lower() for k in ("order", "transaction", "invoice", "sale", "purchase")):
                primary_date = candidate
                break

    total_cells = max(row_count * max(df.shape[1], 1), 1)
    missing_cells = int(df.isna().sum().sum())

    return DatasetProfile(
        name=name,
        rows=row_count,
        columns=df.shape[1],
        memory_mb=round(df.memory_usage(deep=True).sum() / 1_048_576, 2),
        duplicate_rows=int(df.duplicated().sum()),
        missing_cells=missing_cells,
        missing_pct=round(missing_cells / total_cells * 100, 2),
        column_profiles=column_profiles,
        metrics=metrics,
        dimensions=dimensions,
        dates=dates,
        identifiers=identifiers,
        texts=texts,
        primary_metric=primary_metric,
        primary_date=primary_date,
        suggested_questions=_suggest_questions(metrics, dimensions, dates, primary_metric),
    )


def correlation_matrix(df: pd.DataFrame, profile: DatasetProfile) -> pd.DataFrame:
    """Correlations between true metrics only - identifiers would be noise."""
    numeric_cols = [c for c in profile.metrics if c in df.columns]
    if len(numeric_cols) < 2:
        return pd.DataFrame()
    return _sample(df)[numeric_cols].corr(numeric_only=True).round(3)


def detect_anomalies(
    df: pd.DataFrame, metric: str, date_column: str, grain: str = "MS", z_threshold: float = 2.0
) -> pd.DataFrame:
    """Flag time periods whose metric total is an outlier (z-score on the series).

    Returns a frame with period, value, z_score and direction; empty if the
    series is too short to judge.
    """
    if metric not in df.columns or date_column not in df.columns:
        return pd.DataFrame()
    working = df[[date_column, metric]].dropna()
    if working.empty:
        return pd.DataFrame()
    series = (
        working.set_index(date_column)[metric]
        .resample(grain)
        .sum()
        .rename("value")
        .to_frame()
    )
    if len(series) < 6:
        return pd.DataFrame()
    mean, std = series["value"].mean(), series["value"].std()
    if not std or np.isnan(std):
        return pd.DataFrame()
    series["z_score"] = ((series["value"] - mean) / std).round(2)
    flagged = series[series["z_score"].abs() >= z_threshold].copy()
    if flagged.empty:
        return pd.DataFrame()
    flagged["direction"] = np.where(flagged["z_score"] > 0, "unusually high", "unusually low")
    flagged = flagged.reset_index().rename(columns={date_column: "period"})
    flagged["period"] = flagged["period"].dt.strftime("%Y-%m")
    return flagged
