"""Question -> AnalysisPlan.

The LLM's first job. It sees the dataset schema, the retrieved RAG context and
the recent conversation, and emits a JSON plan. It never sees the data rows and
never returns a number. A deterministic rule-based planner backs it up so the
app still answers basic questions with no API key configured.
"""
from __future__ import annotations

import re
from typing import Any

import pandas as pd

from .analysis import AnalysisPlan, resolve_column
from .llm import GroqClient, LLMError
from .metadata import schema_prompt_block, suggested_derived_metrics
from .profiling import DatasetProfile
from .vectorstore import RetrievedChunk

PLANNER_SYSTEM = """You are the planning component of a data analytics system.

You convert a business question into a JSON analysis plan. A separate pandas
engine executes your plan and computes the real numbers. You must never invent,
estimate or state any numeric result yourself.

Return ONLY a JSON object with these keys:

{
  "intent": one of "aggregate" | "topn" | "trend" | "distribution" | "relationship" | "correlation" | "rows" | "describe",
  "metric": exact column name to measure, or null,
  "aggregation": "sum" | "mean" | "median" | "count" | "min" | "max" | "nunique",
  "second_metric": exact column name (only for intent "relationship"), else null,
  "derived_metric": null, or {"name": str, "numerator": column, "denominator": column, "scale": "1" or "100", "formula": str},
  "dimensions": [exact column names to group by, at most 2, empty list for a single total],
  "date_column": exact date column name, or null,
  "time_grain": "day" | "week" | "month" | "quarter" | "year", or null,
  "filters": [{"column": exact column, "op": "==" | "!=" | ">" | "<" | ">=" | "<=" | "in" | "not in" | "contains" | "between", "value": scalar or list}],
  "sort": "desc" | "asc" | null,
  "limit": integer or null,
  "chart": "bar" | "line" | "pie" | "histogram" | "box" | "scatter" | "heatmap" | "table" | "kpi" | "auto",
  "explanation": one short sentence describing the analysis you planned
}

Rules:
- Use EXACT column names from the schema. Never invent a column.
- Never group by an identifier column.
- "highest / best / top / which X" -> intent "topn" with the ranking dimension and a limit.
- "over time / trend / month by month / by year" -> intent "trend" with date_column and time_grain.
- "compare A vs B" -> use filters with op "in" and a value list, or dimensions.
- Percentage / margin / rate / per-unit questions -> use derived_metric, not a plain metric.
- Date restrictions must be concrete ISO dates in a "between" filter, resolved from the date range in the schema.
- For a plain total with no breakdown, use intent "aggregate" with dimensions [].
- Choose "line" for time, "bar" for category comparison, "pie" only for a small parts-of-a-whole split,
  "histogram" for one numeric distribution, "scatter" for two metrics, "heatmap" for a correlation matrix.
"""


def build_planner_prompt(
    question: str,
    profile: DatasetProfile,
    context_chunks: list[RetrievedChunk],
    history: list[dict[str, str]] | None = None,
) -> str:
    parts = [schema_prompt_block(profile)]

    if context_chunks:
        parts.append("\nRETRIEVED CONTEXT (from the vector database):")
        for chunk in context_chunks:
            parts.append(f"[{chunk.label}] {chunk.text[:420]}")

    if history:
        parts.append("\nRECENT CONVERSATION (for resolving follow-ups like 'and for the West?'):")
        for turn in history[-4:]:
            parts.append(f"{turn['role'].upper()}: {turn['content'][:220]}")

    parts.append(f"\nQUESTION: {question}")
    parts.append("\nReturn only the JSON plan.")
    return "\n".join(parts)


def plan_question(
    question: str,
    profile: DatasetProfile,
    context_chunks: list[RetrievedChunk],
    client: GroqClient | None = None,
    history: list[dict[str, str]] | None = None,
) -> tuple[AnalysisPlan, str]:
    """Return (plan, planner_source). Falls back to rules if the LLM is unusable."""
    if client is not None and client.available:
        try:
            payload = client.plan(PLANNER_SYSTEM, build_planner_prompt(question, profile, context_chunks, history))
            return AnalysisPlan.from_dict(payload), "llm"
        except LLMError:
            pass
        except Exception:  # noqa: BLE001 - never let planning kill the request
            pass
    return rule_based_plan(question, profile), "rules"


# --------------------------------------------------------------------------
# Deterministic fallback planner
# --------------------------------------------------------------------------

TREND_WORDS = ("trend", "over time", "month by month", "monthly", "by month", "by year",
               "yearly", "quarterly", "time series", "growth", "each month")
TOP_WORDS = ("top", "highest", "best", "most", "largest", "leading", "biggest", "rank")
BOTTOM_WORDS = ("lowest", "worst", "least", "smallest", "bottom")
AVERAGE_WORDS = ("average", "avg", "mean", "typical")
COUNT_WORDS = ("how many", "number of", "count of", "count")
DISTRIBUTION_WORDS = ("distribution", "spread", "histogram", "outlier")
CORRELATION_WORDS = ("correlation", "correlate", "relationship between", "related to")
MARGIN_WORDS = ("margin", "profitability", "percent of", "percentage", "rate", "per unit")


def _mentions(question: str, phrases: tuple[str, ...]) -> bool:
    """Whole-word phrase match, so 'generated' does not match 'rate'."""
    lowered = question.lower()
    return any(re.search(r"\b" + re.escape(phrase) + r"\b", lowered) for phrase in phrases)


# Tokens that appear in many column names and so carry no signal on their own
GENERIC_TOKENS = {"name", "id", "code", "type", "no", "number", "key", "date"}


def _find_mentioned(question: str, candidates: list[str]) -> str | None:
    """Best column name referenced by the question, plural-tolerant."""
    lowered = question.lower()
    hits = [c for c in candidates if c.lower() in lowered]
    if hits:
        return max(hits, key=len)

    words = {w.rstrip("s") for w in re.findall(r"[a-z]+", lowered)}
    scored: list[tuple[int, bool, str]] = []
    for candidate in candidates:
        tokens = {t.rstrip("s") for t in re.findall(r"[a-z]+", candidate.lower())}
        meaningful = tokens - GENERIC_TOKENS
        if not meaningful:
            continue
        overlap = len(meaningful & words)
        if overlap:
            # Prefer readable label columns ("Customer Name") over key columns
            scored.append((overlap, "name" in tokens, candidate))
    if not scored:
        return None
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return scored[0][2]


def rule_based_plan(question: str, profile: DatasetProfile) -> AnalysisPlan:
    """A keyword planner. Handles the common shapes without an API key."""
    lowered = question.lower()
    plan = AnalysisPlan()

    metric = _find_mentioned(question, profile.metrics) or profile.primary_metric
    dimension = _find_mentioned(question, profile.dimensions)
    plan.metric = metric

    if _mentions(lowered, AVERAGE_WORDS):
        plan.aggregation = "mean"
    elif _mentions(lowered, COUNT_WORDS) and metric is None:
        plan.aggregation = "count"

    # Derived / margin questions
    if _mentions(lowered, MARGIN_WORDS):
        for derived in suggested_derived_metrics(profile):
            words = [w for w in re.findall(r"[a-z]+", derived["name"].lower()) if len(w) > 3]
            if words and all(_mentions(lowered, (w,)) for w in words[:2]):
                plan.derived_metric = derived
                break
        else:
            for derived in suggested_derived_metrics(profile):
                if "margin" in derived["name"].lower() and _mentions(lowered, ("margin",)):
                    plan.derived_metric = derived
                    break

    if _mentions(lowered, CORRELATION_WORDS):
        plan.intent = "correlation" if "matrix" in lowered or not dimension else "correlation"
        metrics_in_question = [m for m in profile.metrics if m.lower() in lowered]
        if len(metrics_in_question) >= 2:
            plan.intent = "relationship"
            plan.metric, plan.second_metric = metrics_in_question[0], metrics_in_question[1]
            plan.chart = "scatter"
        else:
            plan.chart = "heatmap"
        return plan

    if _mentions(lowered, DISTRIBUTION_WORDS):
        plan.intent = "distribution"
        plan.chart = "histogram"
        return plan

    if _mentions(lowered, TREND_WORDS) and profile.primary_date:
        plan.intent = "trend"
        plan.date_column = profile.primary_date
        plan.time_grain = "year" if ("year" in lowered and "month" not in lowered) else "month"
        plan.chart = "line"
        if dimension and ("by " + dimension.lower()) in lowered:
            plan.dimensions = [dimension]
        return plan

    if dimension:
        plan.intent = "topn"
        plan.dimensions = [dimension]
        plan.sort = "asc" if _mentions(lowered, BOTTOM_WORDS) else "desc"
        match = re.search(r"top\s+(\d+)", lowered)
        plan.limit = int(match.group(1)) if match else 10

        plan.chart = "bar"
        return plan

    plan.intent = "aggregate"
    plan.chart = "kpi"
    return plan


def apply_sidebar_filters(
    plan: AnalysisPlan, sidebar_filters: list[dict[str, Any]], columns: list[str]
) -> AnalysisPlan:
    """Merge UI filters into a plan without overriding filters the plan set itself."""
    existing = {resolve_column(f.get("column"), columns) for f in plan.filters}
    for spec in sidebar_filters:
        column = resolve_column(spec.get("column"), columns)
        if column and column not in existing:
            plan.filters.append(spec)
    return plan


def describe_plan(plan: AnalysisPlan) -> str:
    """One-line human description of a plan, used in the evidence panel."""
    bits: list[str] = []
    if plan.derived_metric:
        bits.append(f"Compute {plan.derived_metric.get('name')} ({plan.derived_metric.get('formula')})")
    elif plan.metric:
        bits.append(f"{plan.aggregation.upper()} of {plan.metric}")
    if plan.dimensions:
        bits.append("grouped by " + " and ".join(plan.dimensions))
    if plan.date_column and plan.time_grain:
        bits.append(f"by {plan.time_grain} of {plan.date_column}")
    if plan.filters:
        readable = ", ".join(
            f"{f.get('column')} {f.get('op', '==')} {f.get('value')}" for f in plan.filters
        )
        bits.append(f"filtered on {readable}")
    if plan.sort:
        bits.append(f"sorted {plan.sort}ending")
    if plan.limit:
        bits.append(f"limited to {plan.limit}")
    return "; ".join(bits) or "Describe the dataset"


def infer_date_bounds(df: pd.DataFrame, date_column: str | None) -> tuple[str, str] | None:
    if not date_column or date_column not in df.columns:
        return None
    series = df[date_column].dropna()
    if series.empty:
        return None
    return str(pd.Timestamp(series.min()).date()), str(pd.Timestamp(series.max()).date())
