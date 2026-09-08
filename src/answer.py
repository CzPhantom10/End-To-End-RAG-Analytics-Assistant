"""Orchestration: question in, evidence-backed answer out.

Pipeline per question:
  retrieve context (Chroma) -> plan (LLM) -> execute (pandas) -> narrate (LLM)

The narration step is given the computed table and is explicitly forbidden from
producing numbers that are not in it. If the LLM is unavailable the deterministic
narrator takes over, so the app degrades to "correct but plainer" rather than
breaking.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from .analysis import (
    AnalysisError,
    AnalysisPlan,
    AnalysisResult,
    execute_plan,
    format_number,
)
from .charts import build_chart
from .config import MAX_RETRIEVED_CHUNKS
from .llm import GroqClient, LLMError
from .planner import describe_plan, plan_question
from .profiling import DatasetProfile
from .vectorstore import RetrievedChunk, VectorStore

NARRATOR_SYSTEM = """You are the communication layer of a data analytics system.

A pandas engine has already computed the result. Your job is to explain it in
clear business language.

Hard rules:
- Use ONLY numbers that appear in the RESULT TABLE. Never compute new figures
  and never estimate. Quote figures exactly as the table formats them.
- If a number is not in the table, do not mention it.
- Keep it tight: 60-130 words. At most 6 bullet points, even if the table is longer.
- Structure: one direct answer sentence, then the key supporting figures as
  bullets, then a single line starting with "Insight:".
- Facts first, interpretation only in the Insight line.
- Never describe the analysis you were given, the filters, the plan, the pipeline
  or the tools. The user already sees those separately.
- Plain prose and short bullet lists only. No headings, no tables, no code.
"""


@dataclass
class Answer:
    question: str
    narrative: str
    result: AnalysisResult | None
    figure: Any = None
    evidence: dict[str, Any] = field(default_factory=dict)
    context_chunks: list[RetrievedChunk] = field(default_factory=list)
    planner_source: str = "rules"
    narrator_source: str = "template"
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.result is not None


def _table_for_prompt(result: AnalysisResult, max_rows: int = 25) -> str:
    """Render the result table with numbers already formatted the way we want
    them quoted, so the narrator copies clean figures instead of raw floats."""
    table = result.table
    if table is None or table.empty:
        return "(empty result)"

    trimmed = table.head(max_rows).copy()
    for column in trimmed.columns:
        if pd.api.types.is_float_dtype(trimmed[column]):
            trimmed[column] = trimmed[column].map(
                lambda v: "" if pd.isna(v) else f"{v:,.2f}"
            )
        elif pd.api.types.is_integer_dtype(trimmed[column]):
            trimmed[column] = trimmed[column].map(lambda v: f"{v:,}")

    with pd.option_context("display.width", 200, "display.max_columns", 20):
        rendered = trimmed.to_string(index=False, max_colwidth=40)
    suffix = ""
    if len(table) > max_rows:
        suffix = f"\n... ({len(table) - max_rows} more rows not shown)"
    return rendered + suffix


def _comparison_facts(result: AnalysisResult) -> list[str]:
    """Pre-compute the comparisons a narrator would otherwise estimate.

    Without these the model says "roughly 17% ahead" when the real figure is
    18.5%. Handing it the arithmetic keeps every number in the answer exact.
    """
    facts: list[str] = []
    table, value, label = result.table, result.value_column, result.label_column
    if table is None or table.empty or not value or value not in table.columns:
        return facts
    if not pd.api.types.is_numeric_dtype(table[value]):
        return facts

    series = table[value].dropna()
    if series.empty:
        return facts

    if result.plan.intent in ("topn", "aggregate") and label and label in table.columns and len(table) > 1:
        top, second = table.iloc[0], table.iloc[1]
        top_value, second_value = float(top[value]), float(second[value])
        if second_value:
            gap = (top_value - second_value) / abs(second_value) * 100
            facts.append(
                f"{top[label]} is {gap:.1f}% {'ahead of' if gap >= 0 else 'behind'} "
                f"{second[label]}, the next in the ranking."
            )
        total = float(series.sum())
        if total:
            facts.append(f"{top[label]} accounts for {top_value / total * 100:.1f}% of the listed total.")
        bottom = table.iloc[-1]
        facts.append(f"Lowest in this list: {bottom[label]} at {float(bottom[value]):,.2f}.")

    if result.plan.intent == "trend" and len(table) > 1:
        first, last = float(series.iloc[0]), float(series.iloc[-1])
        if first:
            facts.append(
                f"Change from the first period to the last: {(last - first) / abs(first) * 100:+.1f}%."
            )
        peak_row = table.loc[table[value].idxmax()]
        low_row = table.loc[table[value].idxmin()]
        facts.append(f"Highest period: {peak_row[label]} at {float(peak_row[value]):,.2f}.")
        facts.append(f"Lowest period: {low_row[label]} at {float(low_row[value]):,.2f}.")
        facts.append(f"Total across all periods: {float(series.sum()):,.2f}.")

    return facts


def _fallback_narrative(result: AnalysisResult) -> str:
    """Deterministic prose built straight from the numbers. No LLM involved."""
    plan = result.plan
    table = result.table
    value = result.value_column
    label = result.label_column

    if result.scalar is not None and (table is None or len(table) <= 1):
        name = value or "Result"
        return f"**{name}: {format_number(result.scalar)}**\n\nCalculated over {result.evidence.get('rows_after_filters', 0):,} rows."

    if table is None or table.empty:
        return "The analysis returned no rows."

    if plan.intent == "distribution":
        if "Statistic" in table.columns and value in table.columns:
            stats = dict(zip(table["Statistic"], table[value]))
            return (
                f"**{value}** across {int(stats.get('count', 0)):,} values.\n\n"
                f"- Average: {format_number(float(stats.get('mean', 0)))}\n"
                f"- Median: {format_number(float(stats.get('50%', 0)))}\n"
                f"- Range: {format_number(float(stats.get('min', 0)))} "
                f"to {format_number(float(stats.get('max', 0)))}\n"
                f"- Middle 50% sits between {format_number(float(stats.get('25%', 0)))} "
                f"and {format_number(float(stats.get('75%', 0)))}\n\n"
                f"Insight: the mean and median "
                f"{'are close, so the distribution is fairly symmetric' if abs(float(stats.get('mean', 0)) - float(stats.get('50%', 0))) < (float(stats.get('std', 1)) or 1) * 0.5 else 'differ, so the distribution is skewed'}."
            )
        top = table.iloc[0]
        return (
            f"Most common value: **{top[label]}** ({int(top[value]):,} rows).\n\n"
            + "\n".join(f"- {row[label]}: {int(row[value]):,}" for _, row in table.head(5).iterrows())
        )

    if plan.intent == "relationship":
        correlation = result.scalar or 0.0
        strength = (
            "very strong" if abs(correlation) > 0.8
            else "strong" if abs(correlation) > 0.6
            else "moderate" if abs(correlation) > 0.35
            else "weak" if abs(correlation) > 0.15
            else "negligible"
        )
        direction = "positive" if correlation >= 0 else "negative"
        return (
            f"**{plan.metric}** and **{plan.second_metric}** have a {strength} {direction} "
            f"relationship (Pearson r = {correlation:.3f}).\n\n"
            f"Insight: as {plan.metric} rises, {plan.second_metric} tends to "
            f"{'rise' if correlation >= 0 else 'fall'}, but r = {correlation:.3f} means "
            f"{'this explains much of the variation' if abs(correlation) > 0.6 else 'much of the variation comes from elsewhere'}."
        )

    if plan.intent == "correlation":
        return (
            f"Correlation matrix across {len(table)} metrics. "
            "Values near +1 move together, near -1 move in opposition, and near 0 are unrelated."
        )

    if plan.intent == "rows":
        return f"Showing {len(table):,} matching records across {len(table.columns)} columns."

    if plan.intent == "trend" and value in table.columns:
        first, last = table.iloc[0], table.iloc[-1]
        total = table[value].sum()
        change = ""
        if first[value]:
            pct = (last[value] - first[value]) / abs(first[value]) * 100
            change = f" That is a {pct:+.1f}% change from the first period to the last."
        peak = table.loc[table[value].idxmax()]
        return (
            f"**{value}** across {len(table)} periods totals **{format_number(float(total))}**.\n\n"
            f"- Peak period: **{peak[label]}** at {format_number(float(peak[value]))}\n"
            f"- First period ({first[label]}): {format_number(float(first[value]))}\n"
            f"- Last period ({last[label]}): {format_number(float(last[value]))}\n\n"
            f"Insight: the series {'rose' if last[value] >= first[value] else 'fell'} overall.{change}"
        )

    if value and value in table.columns and label and label in table.columns:
        top = table.iloc[0]
        lines = [f"**{top[label]}** leads with **{format_number(float(top[value]))}** ({value})."]
        lines.append("")
        for _, row in table.head(5).iterrows():
            lines.append(f"- {row[label]}: {format_number(float(row[value]))}")
        if len(table) > 1:
            second = table.iloc[1]
            if second[value]:
                gap = (float(top[value]) - float(second[value])) / abs(float(second[value])) * 100
                lines.append("")
                lines.append(
                    f"Insight: {top[label]} is {gap:.1f}% ahead of {second[label]}, the next highest."
                )
        return "\n".join(lines)

    return f"Returned {len(table):,} rows across {len(table.columns)} columns."


def _narrate(
    question: str,
    result: AnalysisResult,
    context_chunks: list[RetrievedChunk],
    client: GroqClient | None,
) -> tuple[str, str]:
    if client is None or not client.available:
        return _fallback_narrative(result), "template"

    context_text = "\n".join(f"[{c.label}] {c.text[:400]}" for c in context_chunks[:4])
    comparisons = _comparison_facts(result)
    comparison_text = (
        "\nPRE-COMPUTED COMPARISONS (use these exact figures, do not recalculate):\n"
        + "\n".join(f"- {fact}" for fact in comparisons)
        if comparisons
        else ""
    )
    prompt = f"""QUESTION: {question}

ANALYSIS PERFORMED: {describe_plan(result.plan)}

RESULT TABLE (this is the complete set of computed figures):
{_table_for_prompt(result)}
{comparison_text}

EVIDENCE:
- Dataset: {result.evidence.get('dataset')}
- Rows analysed: {result.evidence.get('rows_after_filters'):,} of {result.evidence.get('rows_in_dataset'):,}
- Filters applied: {', '.join(result.evidence.get('filters', ['none']))}
- Date range covered: {result.evidence.get('date_range') or 'not applicable'}

BACKGROUND CONTEXT (definitions only, contains no results):
{context_text or 'none'}

Write the business answer."""
    try:
        return client.narrate(NARRATOR_SYSTEM, prompt), "llm"
    except LLMError:
        return _fallback_narrative(result), "template"
    except Exception:  # noqa: BLE001
        return _fallback_narrative(result), "template"


def answer_question(
    question: str,
    df: pd.DataFrame,
    profile: DatasetProfile,
    store: VectorStore | None = None,
    client: GroqClient | None = None,
    history: list[dict[str, str]] | None = None,
    extra_filters: list[dict[str, Any]] | None = None,
) -> Answer:
    """Full RAG + analytics pipeline for a single question."""
    context_chunks: list[RetrievedChunk] = []
    if store is not None:
        try:
            context_chunks = store.query(question, k=MAX_RETRIEVED_CHUNKS)
        except Exception:  # noqa: BLE001 - retrieval is helpful, not essential
            context_chunks = []

    plan, planner_source = plan_question(question, profile, context_chunks, client, history)

    if extra_filters:
        from .planner import apply_sidebar_filters

        plan = apply_sidebar_filters(plan, extra_filters, list(df.columns))

    try:
        result = execute_plan(plan, df, profile)
    except AnalysisError as exc:
        return Answer(
            question=question,
            narrative="",
            result=None,
            context_chunks=context_chunks,
            planner_source=planner_source,
            error=str(exc),
        )
    except Exception as exc:  # noqa: BLE001
        return Answer(
            question=question,
            narrative="",
            result=None,
            context_chunks=context_chunks,
            planner_source=planner_source,
            error=f"{type(exc).__name__}: {exc}",
        )

    narrative, narrator_source = _narrate(question, result, context_chunks, client)
    figure = build_chart(result, raw_df=df)

    evidence = dict(result.evidence)
    evidence["plan_description"] = describe_plan(result.plan)
    evidence["planner"] = planner_source
    evidence["retrieved_chunks"] = [c.label for c in context_chunks]
    if result.notes:
        evidence["notes"] = result.notes

    return Answer(
        question=question,
        narrative=narrative,
        result=result,
        figure=figure,
        evidence=evidence,
        context_chunks=context_chunks,
        planner_source=planner_source,
        narrator_source=narrator_source,
    )


# --------------------------------------------------------------------------
# Executive summary
# --------------------------------------------------------------------------

SUMMARY_SYSTEM = """You are a senior business analyst writing an executive summary.

You are given real, pre-computed figures from a dataset. Use only those figures.
Write 4-6 short bullet points covering: overall scale, the leading category or
segment, the time pattern, and anything that looks like a risk or an anomaly.
Finish with one line headed "Recommended next question:" proposing a follow-up
worth asking. Never invent numbers. No headings, no tables."""


def build_summary_facts(df: pd.DataFrame, profile: DatasetProfile) -> list[str]:
    """Compute the facts the executive summary is allowed to talk about."""
    facts: list[str] = [f"Dataset '{profile.name}' has {profile.rows:,} rows and {profile.columns} columns."]

    for metric in profile.metrics[:3]:
        series = df[metric].dropna()
        if series.empty:
            continue
        facts.append(
            f"{metric}: total {format_number(float(series.sum()))}, "
            f"average {format_number(float(series.mean()))}, "
            f"min {format_number(float(series.min()))}, max {format_number(float(series.max()))}."
        )

    metric = profile.primary_metric
    if metric:
        for dimension in profile.dimensions[:3]:
            grouped = df.groupby(dimension)[metric].sum().sort_values(ascending=False)
            if grouped.empty:
                continue
            top = grouped.head(3)
            share = float(top.iloc[0]) / float(grouped.sum()) * 100 if grouped.sum() else 0
            listing = ", ".join(f"{idx} {format_number(float(val))}" for idx, val in top.items())
            facts.append(
                f"Top {dimension} by {metric}: {listing}. "
                f"The leader holds {share:.1f}% of total {metric}."
            )
            worst = grouped.tail(1)
            if float(worst.iloc[0]) < 0:
                facts.append(f"{worst.index[0]} has negative {metric} of {format_number(float(worst.iloc[0]))}.")

    if metric and profile.primary_date:
        series = (
            df[[profile.primary_date, metric]].dropna().set_index(profile.primary_date)[metric].resample("YS").sum()
        )
        if len(series) >= 2:
            listing = ", ".join(f"{idx.year}: {format_number(float(val))}" for idx, val in series.items())
            facts.append(f"{metric} by year - {listing}.")
            first, last = float(series.iloc[0]), float(series.iloc[-1])
            if first:
                facts.append(f"Change from {series.index[0].year} to {series.index[-1].year}: {(last-first)/abs(first)*100:+.1f}%.")

        from .profiling import detect_anomalies

        anomalies = detect_anomalies(df, metric, profile.primary_date)
        if not anomalies.empty:
            listing = ", ".join(
                f"{row.period} ({row.direction}, z={row.z_score})" for row in anomalies.itertuples()
            )
            facts.append(f"Anomalous months detected in {metric}: {listing}.")

    if profile.missing_cells:
        facts.append(f"Data quality: {profile.missing_pct}% of cells are missing.")

    return facts


def executive_summary(
    df: pd.DataFrame, profile: DatasetProfile, client: GroqClient | None = None
) -> tuple[str, list[str]]:
    """Return (summary_markdown, facts_used)."""
    facts = build_summary_facts(df, profile)
    if client is None or not client.available:
        return "- " + "\n- ".join(facts), facts
    prompt = "COMPUTED FACTS:\n" + "\n".join(f"- {f}" for f in facts) + "\n\nWrite the executive summary."
    try:
        return client.complete(SUMMARY_SYSTEM, prompt, temperature=0.3, max_tokens=700), facts
    except Exception:  # noqa: BLE001
        return "- " + "\n- ".join(facts), facts
