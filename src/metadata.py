"""Turn a DatasetProfile into text documents for the RAG index.

The vector store never holds raw rows - it holds *descriptions*: a data
dictionary, per-column cards, statistical summaries, business-metric
definitions, and the cleaning log. That is what the assistant retrieves to
understand an unfamiliar dataset before it plans an analysis.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from .ingestion import CleaningReport
from .profiling import DatasetProfile

# Plain-English definitions attached to columns whose names match. These are the
# "business definitions" layer of the retrieval corpus.
BUSINESS_GLOSSARY: dict[str, str] = {
    "sales": "Sales is gross revenue from an order line before costs are deducted.",
    "revenue": "Revenue is the total income generated from goods or services sold.",
    "profit": "Profit is revenue minus cost. Negative profit means the line lost money.",
    "margin": "Margin is profit expressed as a percentage of sales (profit / sales * 100).",
    "discount": "Discount is the fractional price reduction applied to an order line.",
    "quantity": "Quantity is the number of units sold on an order line.",
    "cost": "Cost is the expense incurred to produce or acquire the goods sold.",
    "price": "Price is the per-unit amount charged to the customer.",
    "region": "Region is a geographic grouping used to compare performance by territory.",
    "segment": "Segment is the customer type or market grouping (for example Consumer or Corporate).",
    "category": "Category is the top-level product grouping; sub-category is the finer breakdown.",
    "customer": "Customer identifies the buying party; useful for retention and concentration analysis.",
    "order date": "Order date is when the order was placed - use it for time-series analysis.",
    "ship date": "Ship date is when the order left the warehouse; the gap to order date is fulfilment time.",
}


def _glossary_for(column: str) -> str | None:
    lowered = column.lower()
    for key, definition in BUSINESS_GLOSSARY.items():
        if key in lowered:
            return definition
    return None


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:,.4g}"
    return str(value)


def build_documents(
    profile: DatasetProfile, cleaning: CleaningReport | None = None
) -> list[dict[str, Any]]:
    """Return [{id, text, metadata}] chunks describing the dataset."""
    docs: list[dict[str, Any]] = []
    ds = profile.name

    def add(doc_id: str, text: str, kind: str, column: str = "") -> None:
        docs.append(
            {
                "id": f"{ds}::{doc_id}",
                "text": text.strip(),
                "metadata": {"dataset": ds, "kind": kind, "column": column},
            }
        )

    # 1. Dataset overview
    add(
        "overview",
        f"""Dataset overview for "{ds}".
It has {profile.rows:,} rows and {profile.columns} columns.
Numeric business metrics: {', '.join(profile.metrics) or 'none'}.
Categorical dimensions to group by: {', '.join(profile.dimensions) or 'none'}.
Date/time columns: {', '.join(profile.dates) or 'none'}.
Identifier columns (keys, never aggregate these): {', '.join(profile.identifiers) or 'none'}.
Free-text columns: {', '.join(profile.texts) or 'none'}.
The headline metric is {profile.primary_metric or 'not determined'} and the main date column is {profile.primary_date or 'not determined'}.
Missing cells: {profile.missing_cells:,} ({profile.missing_pct}% of the table). Duplicate rows remaining: {profile.duplicate_rows:,}.""",
        kind="overview",
    )

    # 2. Data dictionary - one compact table of every column
    lines = ["Data dictionary for " + ds + " (column | role | type | unique | missing%):"]
    for col in profile.column_profiles:
        lines.append(
            f"- {col.name} | {col.role} | {col.dtype} | {col.unique:,} unique | {col.missing_pct}% missing"
        )
    add("data_dictionary", "\n".join(lines), kind="dictionary")

    # 3. One card per column, with stats and any business definition
    for col in profile.column_profiles:
        parts = [
            f'Column "{col.name}" in dataset "{ds}".',
            f"Semantic role: {col.role}. Storage type: {col.dtype}.",
            f"{col.unique:,} distinct values, {col.missing:,} missing ({col.missing_pct}%).",
        ]
        if col.role == "metric":
            parts.append(
                "Statistics: min "
                + _fmt(col.minimum)
                + ", max "
                + _fmt(col.maximum)
                + ", mean "
                + _fmt(col.mean)
                + ", median "
                + _fmt(col.median)
                + ", std "
                + _fmt(col.std)
                + "."
            )
            if col.negatives:
                parts.append(f"{col.negatives:,} values are negative.")
            if col.zeros:
                parts.append(f"{col.zeros:,} values are exactly zero.")
            if col.outliers:
                parts.append(f"About {col.outliers:,} values are IQR outliers.")
            parts.append(f"Default aggregation for this metric is {col.default_aggregation}.")
        elif col.role == "date":
            parts.append(f"Date range runs from {col.date_min} to {col.date_max}.")
            parts.append("Use this column for trends, month-over-month and year-over-year questions.")
        elif col.top_values:
            top = ", ".join(f"{k} ({v:,})" for k, v in list(col.top_values.items())[:8])
            parts.append(f"Most frequent values: {top}.")
        if col.sample_values:
            parts.append("Example values: " + ", ".join(col.sample_values[:5]) + ".")
        definition = _glossary_for(col.name)
        if definition:
            parts.append("Business definition: " + definition)
        add(f"column::{col.name}", " ".join(parts), kind="column", column=col.name)

    # 4. Statistical summary of all metrics together
    if profile.metrics:
        summary = ["Statistical summary of numeric metrics in " + ds + ":"]
        for name in profile.metrics:
            col = profile.column(name)
            if not col:
                continue
            summary.append(
                f"- {name}: total range {_fmt(col.minimum)} to {_fmt(col.maximum)}, "
                f"mean {_fmt(col.mean)}, median {_fmt(col.median)}, std {_fmt(col.std)}."
            )
        add("statistics", "\n".join(summary), kind="statistics")

    # 5. Derived business metrics worth computing on this dataset
    derived = suggested_derived_metrics(profile)
    if derived:
        lines = ["Derived business metrics available for " + ds + ":"]
        for item in derived:
            lines.append(f"- {item['name']}: {item['description']} Formula: {item['formula']}.")
        add("derived_metrics", "\n".join(lines), kind="business_rules")

    # 6. Cleaning log so the assistant can answer "what was changed?"
    if cleaning:
        parts = [
            f"Data preparation log for {ds}.",
            f"Loaded {cleaning.original_rows:,} rows x {cleaning.original_columns} columns; "
            f"after cleaning {cleaning.final_rows:,} rows x {cleaning.final_columns} columns.",
        ]
        if cleaning.duplicates_removed:
            parts.append(f"Removed {cleaning.duplicates_removed:,} exact duplicate rows.")
        if cleaning.parsed_dates:
            parts.append("Parsed as dates: " + ", ".join(cleaning.parsed_dates) + ".")
        if cleaning.coerced_numeric:
            parts.append("Converted to numeric: " + ", ".join(cleaning.coerced_numeric) + ".")
        if cleaning.empty_columns_dropped:
            parts.append("Dropped empty columns: " + ", ".join(cleaning.empty_columns_dropped) + ".")
        if cleaning.warnings:
            parts.append("Warnings: " + " ".join(cleaning.warnings))
        add("cleaning_log", " ".join(parts), kind="cleaning")

    return docs


def suggested_derived_metrics(profile: DatasetProfile) -> list[dict[str, str]]:
    """Ratio metrics that make sense given which columns exist."""
    lowered = {c.lower(): c for c in profile.metrics}
    found: list[dict[str, str]] = []

    def find(*keywords: str) -> str | None:
        for keyword in keywords:
            for low, actual in lowered.items():
                if keyword in low:
                    return actual
        return None

    profit = find("profit")
    sales = find("sales", "revenue", "amount", "total")
    quantity = find("quantity", "qty", "units")
    cost = find("cost")

    if profit and sales:
        found.append(
            {
                "name": "Profit Margin %",
                "description": "Share of revenue kept as profit; the standard profitability ratio.",
                "formula": f"sum({profit}) / sum({sales}) * 100",
                "numerator": profit,
                "denominator": sales,
                "scale": "100",
            }
        )
    if sales and quantity:
        found.append(
            {
                "name": "Average Selling Price",
                "description": "Revenue earned per unit sold.",
                "formula": f"sum({sales}) / sum({quantity})",
                "numerator": sales,
                "denominator": quantity,
                "scale": "1",
            }
        )
    if profit and cost:
        found.append(
            {
                "name": "Return on Cost %",
                "description": "Profit generated per unit of cost incurred.",
                "formula": f"sum({profit}) / sum({cost}) * 100",
                "numerator": profit,
                "denominator": cost,
                "scale": "100",
            }
        )
    return found


def schema_prompt_block(profile: DatasetProfile) -> str:
    """A compact schema description injected into the planner prompt.

    Deliberately terse: the planner needs exact column names and roles, not prose.
    """
    lines = [f'DATASET: "{profile.name}" ({profile.rows:,} rows)', "COLUMNS:"]
    for col in profile.column_profiles:
        bits = [f'  - "{col.name}" [{col.role}]']
        if col.role == "metric":
            bits.append(f"numeric, default agg={col.default_aggregation}")
        elif col.role == "date":
            bits.append(f"date range {col.date_min} to {col.date_max}")
        elif col.role in ("dimension", "text"):
            bits.append(f"{col.unique:,} distinct")
            if col.top_values:
                examples = ", ".join(list(col.top_values)[:6])
                bits.append(f"e.g. {examples}")
        elif col.role == "identifier":
            bits.append("key column - do not aggregate")
        lines.append(" ; ".join(bits))

    derived = suggested_derived_metrics(profile)
    if derived:
        lines.append("DERIVED METRICS AVAILABLE:")
        for item in derived:
            lines.append(f'  - "{item["name"]}" = {item["formula"]}')
    lines.append(f"PRIMARY METRIC: {profile.primary_metric or 'none'}")
    lines.append(f"PRIMARY DATE COLUMN: {profile.primary_date or 'none'}")
    return "\n".join(lines)


def dataset_fingerprint(df: pd.DataFrame, name: str) -> str:
    """Stable id for caching the vector index per dataset+shape."""
    columns = "|".join(map(str, df.columns))
    return f"{name}-{len(df)}-{df.shape[1]}-{abs(hash(columns)) % (10**10)}"
