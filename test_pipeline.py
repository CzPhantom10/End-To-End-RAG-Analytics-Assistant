"""End-to-end smoke test of the analytics pipeline, no Streamlit involved.

Run:  python test_pipeline.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# Windows consoles default to cp1252 and choke on the model's typography
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

from src.analysis import execute_plan, format_number, headline_kpis  # noqa: E402
from src.answer import answer_question, executive_summary  # noqa: E402
from src.charts import build_chart  # noqa: E402
from src.config import GROQ_API_KEY, GROQ_MODEL  # noqa: E402
from src.ingestion import load_dataset  # noqa: E402
from src.llm import GroqClient  # noqa: E402
from src.metadata import build_documents  # noqa: E402
from src.planner import rule_based_plan  # noqa: E402
from src.profiling import detect_anomalies, profile_dataset  # noqa: E402
from src.vectorstore import VectorStore  # noqa: E402

QUESTIONS = [
    "What were our total sales?",
    "Which region generated the highest profit?",
    "What are the top 10 customers by revenue?",
    "How did sales change month by month?",
    "Which region has the highest profit margin?",
    "Compare sales in 2017 with 2016",
    "Show me the distribution of discount",
    "What is the relationship between sales and profit?",
    "Which sub-category loses the most money?",
]


def banner(text: str) -> None:
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


def main() -> int:
    failures: list[str] = []

    banner("1. INGESTION")
    path = ROOT / "data" / "superstore.csv"
    raw, clean, report = load_dataset(path.read_bytes(), path.name)
    print(f"raw     : {raw.shape[0]:,} rows x {raw.shape[1]} cols")
    print(f"clean   : {clean.shape[0]:,} rows x {clean.shape[1]} cols")
    print(f"dates   : {report.parsed_dates}")
    print(f"numeric : {report.coerced_numeric}")
    print(f"dupes   : {report.duplicates_removed}")
    print(f"warnings: {report.warnings}")

    banner("2. PROFILING")
    profile = profile_dataset(clean, name="superstore")
    print(f"metrics    : {profile.metrics}")
    print(f"dimensions : {profile.dimensions}")
    print(f"dates      : {profile.dates}")
    print(f"identifiers: {profile.identifiers}")
    print(f"texts      : {profile.texts}")
    print(f"primary    : metric={profile.primary_metric!r} date={profile.primary_date!r}")
    for expected in ("Sales", "Profit", "Quantity"):
        if expected not in profile.metrics:
            failures.append(f"'{expected}' should be classified as a metric")
    for expected in ("Region", "Category", "Segment"):
        if expected not in profile.dimensions:
            failures.append(f"'{expected}' should be classified as a dimension")
    if "Order Date" not in profile.dates:
        failures.append("'Order Date' should be classified as a date")

    banner("3. KPIs")
    for card in headline_kpis(clean, profile):
        print(f"  {card['label']:<28} {format_number(card['value'], card['format'])}")

    banner("4. VECTOR STORE")
    documents = build_documents(profile, report)
    print(f"documents built: {len(documents)}")
    start = time.time()
    store = VectorStore("test-superstore", persist=False)
    store.build(documents)
    print(f"backend: {store.status()}  (built in {time.time()-start:.1f}s)")
    if store.error:
        print(f"note   : {store.error}")
    hits = store.query("which column measures profitability", k=3)
    for hit in hits:
        print(f"  [{hit.score:.3f}] {hit.label}: {hit.text[:90]}...")
    if not hits:
        failures.append("vector store returned no results")

    banner("5. ANOMALY DETECTION")
    anomalies = detect_anomalies(clean, "Sales", "Order Date")
    print(anomalies.to_string(index=False) if not anomalies.empty else "  none flagged")

    banner("6. RULE-BASED PLANNER (no API key path)")
    for question in QUESTIONS[:5]:
        plan = rule_based_plan(question, profile)
        try:
            result = execute_plan(plan, clean, profile)
            head = result.table.head(2).to_string(index=False).replace("\n", " | ")
            print(f"  OK  {question}\n      -> {plan.intent}/{plan.dimensions} :: {head[:110]}")
        except Exception as exc:  # noqa: BLE001
            print(f"  ERR {question} -> {type(exc).__name__}: {exc}")
            failures.append(f"rule planner failed on: {question}")

    banner("7. FULL PIPELINE WITH GROQ")
    if not GROQ_API_KEY:
        print("  no GROQ_API_KEY set - skipping")
    else:
        client = GroqClient(GROQ_API_KEY, GROQ_MODEL)
        for question in QUESTIONS:
            start = time.time()
            answer = answer_question(question, clean, profile, store, client)
            elapsed = time.time() - start
            if not answer.ok:
                print(f"\n  ERR [{elapsed:.1f}s] {question}\n      {answer.error}")
                failures.append(f"pipeline failed on: {question}")
                continue
            plan = answer.result.plan
            print(f"\n  Q: {question}   [{elapsed:.1f}s, planner={answer.planner_source}]")
            print(f"     plan  : {plan.intent} | metric={plan.metric} | dims={plan.dimensions} "
                  f"| agg={plan.aggregation} | derived={bool(plan.derived_metric)} "
                  f"| filters={plan.filters} | chart={answer.result.chart_type}")
            print(f"     op    : {answer.evidence.get('operation')}")
            print(f"     rows  : {answer.evidence.get('rows_after_filters'):,}")
            print(f"     table : {answer.result.table.head(3).to_string(index=False)[:200]}")
            print(f"     answer: {answer.narrative[:400]}")
            figure = build_chart(answer.result, raw_df=clean)
            print(f"     chart : {'built' if figure is not None else 'none'}")

        banner("8. EXECUTIVE SUMMARY")
        summary, facts = executive_summary(clean, profile, client)
        print(f"  facts computed: {len(facts)}")
        print(summary[:900])

    banner("RESULT")
    if failures:
        print(f"{len(failures)} problem(s):")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
