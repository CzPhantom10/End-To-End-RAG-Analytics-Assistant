"""The analytical engine.

An AnalysisPlan is a small, validated JSON structure describing *what* to
compute. This module executes it with pandas and returns the numbers plus a
full evidence trail. The LLM writes the plan; it never writes the answer's
numbers, and no model-generated code is executed.
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from .profiling import DatasetProfile

INTENTS = {
    "aggregate",     # one number, optionally grouped
    "topn",          # ranked groups
    "trend",         # metric over time
    "compare",       # two periods or two groups side by side
    "distribution",  # histogram / value counts
    "relationship",  # correlation between two metrics
    "correlation",   # correlation matrix
    "describe",      # dataset / column description
    "rows",          # show matching records
}

AGGREGATIONS = {"sum", "mean", "median", "count", "min", "max", "nunique", "std"}

GRAIN_TO_FREQ = {"day": "D", "week": "W", "month": "MS", "quarter": "QS", "year": "YS"}
GRAIN_TO_LABEL = {"day": "%Y-%m-%d", "week": "%Y-W%W", "month": "%Y-%m", "quarter": "%Y-Q", "year": "%Y"}

FILTER_OPS = {"==", "!=", ">", "<", ">=", "<=", "in", "not in", "contains", "between"}


class AnalysisError(Exception):
    """Raised when a plan cannot be executed against the dataset."""


@dataclass
class AnalysisPlan:
    intent: str = "aggregate"
    metric: str | None = None
    aggregation: str = "sum"
    derived_metric: dict[str, Any] | None = None
    dimensions: list[str] = field(default_factory=list)
    date_column: str | None = None
    time_grain: str | None = None
    filters: list[dict[str, Any]] = field(default_factory=list)
    sort: str | None = "desc"
    limit: int | None = None
    chart: str = "auto"
    second_metric: str | None = None
    explanation: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AnalysisPlan":
        dims = payload.get("dimensions") or []
        if isinstance(dims, str):
            dims = [dims]
        filters = payload.get("filters") or []
        if isinstance(filters, dict):
            filters = [filters]
        return cls(
            intent=str(payload.get("intent") or "aggregate").lower().strip(),
            metric=payload.get("metric") or None,
            aggregation=str(payload.get("aggregation") or "sum").lower().strip(),
            derived_metric=payload.get("derived_metric") or None,
            dimensions=[str(d) for d in dims if d],
            date_column=payload.get("date_column") or None,
            time_grain=(payload.get("time_grain") or None),
            filters=[f for f in filters if isinstance(f, dict)],
            sort=(payload.get("sort") or "desc"),
            limit=payload.get("limit"),
            chart=str(payload.get("chart") or "auto").lower().strip(),
            second_metric=payload.get("second_metric") or None,
            explanation=str(payload.get("explanation") or ""),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "metric": self.metric,
            "aggregation": self.aggregation,
            "derived_metric": self.derived_metric,
            "dimensions": self.dimensions,
            "date_column": self.date_column,
            "time_grain": self.time_grain,
            "filters": self.filters,
            "sort": self.sort,
            "limit": self.limit,
            "chart": self.chart,
            "second_metric": self.second_metric,
            "explanation": self.explanation,
        }


@dataclass
class AnalysisResult:
    plan: AnalysisPlan
    table: pd.DataFrame
    value_column: str | None
    label_column: str | None
    scalar: float | None = None
    chart_type: str = "table"
    evidence: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return self.table is None or self.table.empty


# --------------------------------------------------------------------------
# Column resolution
# --------------------------------------------------------------------------


def resolve_column(name: Any, columns: list[str]) -> str | None:
    """Map a model-supplied column name onto a real column, tolerantly."""
    if name is None:
        return None
    target = str(name).strip()
    if not target:
        return None
    if target in columns:
        return target

    lowered = {c.lower(): c for c in columns}
    if target.lower() in lowered:
        return lowered[target.lower()]

    def normalise(text: str) -> str:
        return "".join(ch for ch in text.lower() if ch.isalnum())

    normalised = {normalise(c): c for c in columns}
    if normalise(target) in normalised:
        return normalised[normalise(target)]

    matches = difflib.get_close_matches(target.lower(), list(lowered), n=1, cutoff=0.82)
    if matches:
        return lowered[matches[0]]
    return None


def _coerce_value(series: pd.Series, value: Any) -> Any:
    """Make a filter value comparable with the column it targets."""
    if pd.api.types.is_datetime64_any_dtype(series):
        try:
            return pd.to_datetime(value)
        except Exception:  # noqa: BLE001
            return value
    if pd.api.types.is_numeric_dtype(series):
        try:
            return float(value)
        except (TypeError, ValueError):
            return value
    return value


def _match_category(series: pd.Series, value: Any) -> Any:
    """Snap a filter value onto an actual category (case/spacing tolerant)."""
    if pd.api.types.is_numeric_dtype(series) or pd.api.types.is_datetime64_any_dtype(series):
        return value
    text = str(value).strip()
    uniques = series.dropna().astype(str).unique()
    lookup = {u.lower(): u for u in uniques}
    if text.lower() in lookup:
        return lookup[text.lower()]
    matches = difflib.get_close_matches(text.lower(), list(lookup), n=1, cutoff=0.85)
    return lookup[matches[0]] if matches else value


# --------------------------------------------------------------------------
# Filtering
# --------------------------------------------------------------------------


def apply_filters(
    df: pd.DataFrame, filters: list[dict[str, Any]]
) -> tuple[pd.DataFrame, list[str], list[str]]:
    """Apply plan filters. Returns (filtered_df, human_descriptions, warnings)."""
    working = df
    described: list[str] = []
    warnings: list[str] = []

    for spec in filters:
        column = resolve_column(spec.get("column"), list(df.columns))
        if column is None:
            warnings.append(f"Ignored filter on unknown column '{spec.get('column')}'.")
            continue
        op = str(spec.get("op") or spec.get("operator") or "==").strip().lower()
        if op in ("=", "eq"):
            op = "=="
        if op not in FILTER_OPS:
            warnings.append(f"Ignored filter with unsupported operator '{op}'.")
            continue
        value = spec.get("value")
        series = working[column]

        try:
            if op == "between":
                if not isinstance(value, (list, tuple)) or len(value) != 2:
                    warnings.append(f"Ignored malformed 'between' filter on {column}.")
                    continue
                low = _coerce_value(series, value[0])
                high = _coerce_value(series, value[1])
                mask = series.between(low, high)
                described.append(f"{column} between {value[0]} and {value[1]}")
            elif op in ("in", "not in"):
                values = value if isinstance(value, (list, tuple)) else [value]
                snapped = [_match_category(series, v) for v in values]
                mask = series.isin(snapped)
                if op == "not in":
                    mask = ~mask
                described.append(f"{column} {op} {snapped}")
            elif op == "contains":
                mask = series.astype(str).str.contains(str(value), case=False, na=False)
                described.append(f"{column} contains '{value}'")
            else:
                snapped = _match_category(series, value)
                comparable = _coerce_value(series, snapped)
                mask = {
                    "==": series == comparable,
                    "!=": series != comparable,
                    ">": series > comparable,
                    "<": series < comparable,
                    ">=": series >= comparable,
                    "<=": series <= comparable,
                }[op]
                described.append(f"{column} {op} {snapped}")
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Filter on {column} failed ({exc}); skipped.")
            continue

        filtered = working[mask.fillna(False)]
        if filtered.empty and not working.empty:
            label = described.pop() if described else column
            warnings.append(f"Filter '{label}' matched no rows, so it was skipped.")
            continue
        working = filtered

    return working, described, warnings


# --------------------------------------------------------------------------
# Aggregation helpers
# --------------------------------------------------------------------------


def _aggregate(grouped: pd.core.groupby.DataFrameGroupBy, metric: str, how: str) -> pd.Series:
    if how == "count":
        return grouped[metric].count()
    if how == "nunique":
        return grouped[metric].nunique()
    return getattr(grouped[metric], how)()


def _derived_series(
    df: pd.DataFrame, spec: dict[str, Any], by: list[str] | None
) -> tuple[pd.Series | float, str]:
    """Compute a ratio metric such as profit margin, aggregating before dividing."""
    columns = list(df.columns)
    numerator = resolve_column(spec.get("numerator"), columns)
    denominator = resolve_column(spec.get("denominator"), columns)
    if not numerator or not denominator:
        raise AnalysisError(
            f"Derived metric needs valid numerator and denominator columns "
            f"(got {spec.get('numerator')!r} / {spec.get('denominator')!r})."
        )
    scale = float(spec.get("scale") or 1)
    label = str(spec.get("name") or f"{numerator} / {denominator}")

    if by:
        grouped = df.groupby(by, dropna=True)
        top = grouped[numerator].sum()
        bottom = grouped[denominator].sum()
    else:
        top = df[numerator].sum()
        bottom = df[denominator].sum()

    result = (top / bottom.replace(0, np.nan) * scale) if by else (
        (top / bottom * scale) if bottom else float("nan")
    )
    if isinstance(result, pd.Series):
        result = result.replace([np.inf, -np.inf], np.nan).dropna()
    return result, label


def _resample_key(series: pd.Series, grain: str) -> pd.Series:
    """Period labels that sort chronologically as strings."""
    period = {"day": "D", "week": "W", "month": "M", "quarter": "Q", "year": "Y"}[grain]
    periods = series.dt.to_period(period)
    return periods.astype(str)


# --------------------------------------------------------------------------
# Plan validation + execution
# --------------------------------------------------------------------------


def validate_plan(plan: AnalysisPlan, df: pd.DataFrame, profile: DatasetProfile) -> tuple[AnalysisPlan, list[str]]:
    """Snap a raw plan onto real columns, filling in sensible defaults."""
    notes: list[str] = []
    columns = list(df.columns)

    if plan.intent not in INTENTS:
        notes.append(f"Unknown intent '{plan.intent}', treated as aggregate.")
        plan.intent = "aggregate"

    if plan.aggregation not in AGGREGATIONS:
        notes.append(f"Unknown aggregation '{plan.aggregation}', using sum.")
        plan.aggregation = "sum"

    # Metric
    if plan.metric:
        resolved = resolve_column(plan.metric, columns)
        if resolved is None:
            notes.append(f"Column '{plan.metric}' is not in the dataset; used {profile.primary_metric}.")
            resolved = profile.primary_metric
        plan.metric = resolved
    if plan.second_metric:
        plan.second_metric = resolve_column(plan.second_metric, columns)

    if plan.metric is None and plan.intent not in ("describe", "rows", "correlation", "distribution"):
        plan.metric = profile.primary_metric
        if plan.metric is None and plan.aggregation != "count":
            plan.aggregation = "count"

    # Counting rows does not need a numeric column
    if plan.aggregation in ("count", "nunique") and plan.metric is None and columns:
        plan.metric = columns[0]

    # Dimensions
    resolved_dims: list[str] = []
    for dim in plan.dimensions:
        resolved = resolve_column(dim, columns)
        if resolved is None:
            notes.append(f"Ignored unknown grouping column '{dim}'.")
            continue
        if resolved not in resolved_dims:
            resolved_dims.append(resolved)
    plan.dimensions = resolved_dims[:2]

    # Date column
    if plan.date_column:
        resolved = resolve_column(plan.date_column, columns)
        if resolved is None or not pd.api.types.is_datetime64_any_dtype(df[resolved]):
            if resolved is not None:
                notes.append(f"'{resolved}' is not a date column; used {profile.primary_date}.")
            resolved = profile.primary_date
        plan.date_column = resolved
    if plan.intent == "trend" and not plan.date_column:
        plan.date_column = profile.primary_date
        if not plan.date_column:
            notes.append("No date column available, so a trend cannot be computed.")
            plan.intent = "aggregate"

    if plan.time_grain:
        grain = str(plan.time_grain).lower().strip()
        aliases = {"monthly": "month", "yearly": "year", "annual": "year", "daily": "day",
                   "weekly": "week", "quarterly": "quarter", "m": "month", "y": "year"}
        grain = aliases.get(grain, grain)
        if grain not in GRAIN_TO_FREQ:
            notes.append(f"Unknown time grain '{plan.time_grain}', using month.")
            grain = "month"
        plan.time_grain = grain
    elif plan.intent == "trend":
        plan.time_grain = "month"

    # Sort / limit
    if plan.sort not in ("asc", "desc", None):
        plan.sort = "desc"
    if plan.limit is not None:
        try:
            plan.limit = max(1, min(int(plan.limit), 200))
        except (TypeError, ValueError):
            plan.limit = None
    if plan.intent == "topn":
        # "Which region is highest?" is a ranking question. Keeping a few
        # runners-up makes the chart readable and lets the answer say by how
        # much the leader leads.
        plan.limit = max(plan.limit or 10, 5)

    # Derived metric
    if plan.derived_metric:
        spec = plan.derived_metric
        if not isinstance(spec, dict) or not spec.get("numerator") or not spec.get("denominator"):
            notes.append("Derived metric specification was incomplete and was dropped.")
            plan.derived_metric = None

    return plan, notes


def execute_plan(plan: AnalysisPlan, df: pd.DataFrame, profile: DatasetProfile) -> AnalysisResult:
    """Run a validated plan and return numbers plus an evidence trail."""
    plan, notes = validate_plan(plan, df, profile)
    working, filter_text, filter_warnings = apply_filters(df, plan.filters)
    notes.extend(filter_warnings)

    if working.empty:
        raise AnalysisError("No rows match the requested filters.")

    evidence: dict[str, Any] = {
        "dataset": profile.name,
        "rows_in_dataset": len(df),
        "rows_after_filters": len(working),
        "filters": filter_text or ["none"],
        "columns_used": [],
        "operation": "",
        "date_range": None,
    }

    if plan.date_column and plan.date_column in working.columns:
        dates = working[plan.date_column].dropna()
        if len(dates):
            evidence["date_range"] = (
                f"{pd.Timestamp(dates.min()).date()} to {pd.Timestamp(dates.max()).date()}"
            )

    intent = plan.intent
    if intent == "correlation":
        result = _run_correlation(plan, working, profile, evidence)
    elif intent == "relationship":
        result = _run_relationship(plan, working, evidence)
    elif intent == "distribution":
        result = _run_distribution(plan, working, evidence)
    elif intent == "trend":
        result = _run_trend(plan, working, evidence)
    elif intent == "rows":
        result = _run_rows(plan, working, evidence)
    elif intent == "describe":
        result = _run_describe(plan, working, profile, evidence)
    else:  # aggregate, topn, compare
        result = _run_aggregate(plan, working, evidence)

    result.plan = plan
    result.notes = notes + result.notes
    result.evidence = {**evidence, **result.evidence}
    return result


# -- individual intent handlers -------------------------------------------


def _run_aggregate(plan: AnalysisPlan, df: pd.DataFrame, evidence: dict[str, Any]) -> AnalysisResult:
    dims = plan.dimensions

    if plan.derived_metric:
        values, label = _derived_series(df, plan.derived_metric, dims or None)
        evidence["columns_used"] = [
            plan.derived_metric.get("numerator"),
            plan.derived_metric.get("denominator"),
            *dims,
        ]
        evidence["operation"] = f"{label} = {plan.derived_metric.get('formula', 'ratio')}"
        if not dims:
            table = pd.DataFrame({label: [float(values)]})
            return AnalysisResult(plan, table, label, None, float(values), "kpi")
        series = values.sort_values(ascending=(plan.sort == "asc"))
        if plan.limit:
            series = series.head(plan.limit)
        table = series.reset_index()
        table.columns = list(dims) + [label]
        return AnalysisResult(plan, table, label, dims[0], None, _pick_chart(plan, table, dims))

    metric = plan.metric
    if metric is None or metric not in df.columns:
        raise AnalysisError("No usable metric column for this question.")

    agg = plan.aggregation
    value_name = f"{agg}({metric})" if agg != "sum" else f"Total {metric}"
    if agg == "count":
        value_name = "Row count"
    elif agg == "nunique":
        value_name = f"Distinct {metric}"
    elif agg == "mean":
        value_name = f"Average {metric}"

    evidence["columns_used"] = [metric, *dims]
    evidence["operation"] = (
        f"{agg.upper()} of {metric}" + (f" grouped by {', '.join(dims)}" if dims else "")
    )

    if not dims:
        if agg == "count":
            scalar = float(len(df))
        elif agg == "nunique":
            scalar = float(df[metric].nunique())
        else:
            scalar = float(getattr(df[metric], agg)())
        table = pd.DataFrame({value_name: [scalar]})
        return AnalysisResult(plan, table, value_name, None, scalar, "kpi")

    grouped = df.groupby(dims, dropna=True)
    series = _aggregate(grouped, metric, agg)
    if plan.sort:
        series = series.sort_values(ascending=(plan.sort == "asc"))
    if plan.limit:
        series = series.head(plan.limit)

    table = series.reset_index()
    table.columns = list(dims) + [value_name]
    chart = _pick_chart(plan, table, dims)
    return AnalysisResult(plan, table, value_name, dims[0], None, chart)


def _run_trend(plan: AnalysisPlan, df: pd.DataFrame, evidence: dict[str, Any]) -> AnalysisResult:
    date_col = plan.date_column
    if not date_col or date_col not in df.columns:
        raise AnalysisError("A date column is required for trend analysis.")
    grain = plan.time_grain or "month"
    working = df.dropna(subset=[date_col]).copy()
    if working.empty:
        raise AnalysisError("No rows with a valid date remain after filtering.")

    period_label = f"Period ({grain})"
    working[period_label] = _resample_key(working[date_col], grain)

    group_keys = [period_label] + plan.dimensions

    if plan.derived_metric:
        values, value_name = _derived_series(working, plan.derived_metric, group_keys)
        table = values.reset_index()
        table.columns = group_keys + [value_name]
        evidence["columns_used"] = [
            plan.derived_metric.get("numerator"),
            plan.derived_metric.get("denominator"),
            date_col,
            *plan.dimensions,
        ]
    else:
        metric = plan.metric
        if metric is None or metric not in working.columns:
            raise AnalysisError("No usable metric column for this trend.")
        value_name = f"{plan.aggregation.upper()} of {metric}" if plan.aggregation != "sum" else f"Total {metric}"
        series = _aggregate(working.groupby(group_keys, dropna=True), metric, plan.aggregation)
        table = series.reset_index()
        table.columns = group_keys + [value_name]
        evidence["columns_used"] = [metric, date_col, *plan.dimensions]

    table = table.sort_values(period_label).reset_index(drop=True)
    evidence["operation"] = (
        f"{plan.aggregation.upper()} of {plan.metric or 'derived metric'} by {grain} of {date_col}"
    )

    notes: list[str] = []
    # Period-over-period change is only meaningful for a single series
    if not plan.dimensions and len(table) > 1:
        table["Change"] = table[value_name].diff().round(2)
        table["Change %"] = (table[value_name].pct_change() * 100).round(1)

    chart = "line" if plan.chart in ("auto", "line") else plan.chart
    return AnalysisResult(plan, table, value_name, period_label, None, chart, notes=notes)


def _run_distribution(plan: AnalysisPlan, df: pd.DataFrame, evidence: dict[str, Any]) -> AnalysisResult:
    target = plan.metric or (plan.dimensions[0] if plan.dimensions else None)
    if target is None or target not in df.columns:
        raise AnalysisError("Specify a column to show the distribution of.")
    evidence["columns_used"] = [target]

    if pd.api.types.is_numeric_dtype(df[target]):
        evidence["operation"] = f"Distribution (histogram + quartiles) of {target}"
        series = df[target].dropna()
        stats = pd.DataFrame(
            {
                "Statistic": ["count", "mean", "std", "min", "25%", "50%", "75%", "max"],
                target: [
                    len(series),
                    series.mean(),
                    series.std(),
                    series.min(),
                    series.quantile(0.25),
                    series.median(),
                    series.quantile(0.75),
                    series.max(),
                ],
            }
        )
        stats[target] = stats[target].round(3)
        result = AnalysisResult(plan, stats, target, "Statistic", None, "histogram")
        result.evidence = {"raw_series_column": target}
        return result

    evidence["operation"] = f"Value counts of {target}"
    counts = df[target].value_counts(dropna=True)
    if plan.limit:
        counts = counts.head(plan.limit)
    table = counts.reset_index()
    table.columns = [target, "Count"]
    return AnalysisResult(plan, table, "Count", target, None, "bar")


def _run_relationship(plan: AnalysisPlan, df: pd.DataFrame, evidence: dict[str, Any]) -> AnalysisResult:
    x = plan.metric
    y = plan.second_metric
    if not x or not y or x not in df.columns or y not in df.columns:
        raise AnalysisError("Two numeric columns are needed to measure a relationship.")
    working = df[[x, y] + plan.dimensions].dropna(subset=[x, y])
    if working.empty:
        raise AnalysisError("No rows have both values present.")
    correlation = float(working[x].corr(working[y]))
    evidence["columns_used"] = [x, y, *plan.dimensions]
    evidence["operation"] = f"Pearson correlation between {x} and {y} over {len(working):,} rows"

    sample = working.sample(min(len(working), 5000), random_state=0)
    result = AnalysisResult(plan, sample, y, x, correlation, "scatter")
    result.notes = [f"Pearson r = {correlation:.3f} across {len(working):,} rows."]
    return result


def _run_correlation(
    plan: AnalysisPlan, df: pd.DataFrame, profile: DatasetProfile, evidence: dict[str, Any]
) -> AnalysisResult:
    metrics = [m for m in profile.metrics if m in df.columns]
    if len(metrics) < 2:
        raise AnalysisError("At least two numeric metrics are needed for a correlation matrix.")
    matrix = df[metrics].corr(numeric_only=True).round(3)
    evidence["columns_used"] = metrics
    evidence["operation"] = f"Pearson correlation matrix over {len(metrics)} metrics"
    table = matrix.reset_index().rename(columns={"index": "Metric"})
    return AnalysisResult(plan, table, None, "Metric", None, "heatmap")


def _run_rows(plan: AnalysisPlan, df: pd.DataFrame, evidence: dict[str, Any]) -> AnalysisResult:
    limit = plan.limit or 25
    working = df
    sort_col = plan.metric if plan.metric in df.columns else None
    if sort_col and plan.sort:
        working = working.sort_values(sort_col, ascending=(plan.sort == "asc"))
    table = working.head(limit).copy()
    evidence["columns_used"] = list(table.columns)[:12]
    evidence["operation"] = f"Returned {len(table)} matching rows"
    return AnalysisResult(plan, table, None, None, None, "table")


def _run_describe(
    plan: AnalysisPlan, df: pd.DataFrame, profile: DatasetProfile, evidence: dict[str, Any]
) -> AnalysisResult:
    rows = []
    for col in profile.column_profiles:
        if col.name not in df.columns:
            continue
        rows.append(
            {
                "Column": col.name,
                "Role": col.role,
                "Type": col.dtype,
                "Unique": col.unique,
                "Missing %": col.missing_pct,
                "Example": col.sample_values[0] if col.sample_values else "",
            }
        )
    evidence["operation"] = "Dataset schema and profile summary"
    evidence["columns_used"] = [r["Column"] for r in rows][:20]
    return AnalysisResult(plan, pd.DataFrame(rows), None, "Column", None, "table")


def _pick_chart(plan: AnalysisPlan, table: pd.DataFrame, dims: list[str]) -> str:
    if plan.chart not in ("auto", "", None):
        return plan.chart
    if len(dims) >= 2:
        return "grouped_bar"
    rows = len(table)
    if rows <= 1:
        return "kpi"
    if rows <= 6:
        return "bar"
    if rows <= 30:
        return "bar"
    return "table"


# --------------------------------------------------------------------------
# KPI helpers used by the dashboard
# --------------------------------------------------------------------------


def headline_kpis(df: pd.DataFrame, profile: DatasetProfile) -> list[dict[str, Any]]:
    """A handful of top-level numbers for the dashboard cards."""
    cards: list[dict[str, Any]] = [{"label": "Rows", "value": len(df), "format": "int"}]

    for metric in profile.metrics[:3]:
        series = df[metric].dropna()
        if series.empty:
            continue
        column = profile.column(metric)
        # Ratio columns (discount, rates) are averaged, not summed
        if column and column.default_aggregation == "mean":
            cards.append({"label": f"Avg {metric}", "value": float(series.mean()), "format": "num"})
        else:
            cards.append({"label": f"Total {metric}", "value": float(series.sum()), "format": "num"})

    from .metadata import suggested_derived_metrics

    for derived in suggested_derived_metrics(profile)[:2]:
        numerator, denominator = derived["numerator"], derived["denominator"]
        if numerator in df.columns and denominator in df.columns:
            bottom = float(df[denominator].sum())
            if bottom:
                value = float(df[numerator].sum()) / bottom * float(derived["scale"])
                cards.append(
                    {
                        "label": derived["name"],
                        "value": value,
                        "format": "pct" if derived["scale"] == "100" else "num",
                    }
                )

    if profile.dimensions:
        dim = profile.dimensions[0]
        cards.append({"label": f"Distinct {dim}", "value": int(df[dim].nunique()), "format": "int"})

    return cards[:6]


def format_number(value: float, kind: str = "num") -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "n/a"
    if kind == "int":
        return f"{int(value):,}"
    if kind == "pct":
        return f"{value:,.1f}%"
    magnitude = abs(value)
    if magnitude >= 1_000_000_000:
        return f"{value/1_000_000_000:,.2f}B"
    if magnitude >= 1_000_000:
        return f"{value/1_000_000:,.2f}M"
    if magnitude >= 1_000:
        return f"{value:,.0f}"
    return f"{value:,.2f}"
