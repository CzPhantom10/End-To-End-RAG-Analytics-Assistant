"""Dataset ingestion: load raw files, validate them, and clean them.

Everything here is deterministic pandas work - no LLM involved. The cleaning
report it produces is later fed to the profiler and to the RAG index so the
assistant can explain what happened to the data before it was analysed.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

SUPPORTED_TABULAR = {".csv", ".tsv", ".txt", ".xlsx", ".xls"}
SUPPORTED_DOCUMENT = {".pdf"}

# Column names that look like dates even when pandas reads them as strings
DATE_NAME_HINTS = ("date", "time", "day", "month", "year", "timestamp", "period")

# Symbols that commonly wrap numbers in exported business data
CURRENCY_PATTERN = r"[,$€£₹%\s]"


def is_text_series(series: pd.Series) -> bool:
    """True for text columns on both pandas 2.x (object) and 3.x (str dtype)."""
    if pd.api.types.is_datetime64_any_dtype(series):
        return False
    if pd.api.types.is_numeric_dtype(series) or pd.api.types.is_bool_dtype(series):
        return False
    if pd.api.types.is_object_dtype(series):
        return True
    try:
        return bool(pd.api.types.is_string_dtype(series))
    except Exception:  # noqa: BLE001
        return False


@dataclass
class CleaningReport:
    """Everything we changed while cleaning, so the UI can show its work."""

    original_rows: int = 0
    original_columns: int = 0
    final_rows: int = 0
    final_columns: int = 0
    duplicates_removed: int = 0
    empty_columns_dropped: list[str] = field(default_factory=list)
    columns_renamed: dict[str, str] = field(default_factory=dict)
    parsed_dates: list[str] = field(default_factory=list)
    coerced_numeric: list[str] = field(default_factory=list)
    whitespace_trimmed: list[str] = field(default_factory=list)
    missing_before: int = 0
    missing_after: int = 0
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "original_rows": self.original_rows,
            "original_columns": self.original_columns,
            "final_rows": self.final_rows,
            "final_columns": self.final_columns,
            "duplicates_removed": self.duplicates_removed,
            "empty_columns_dropped": self.empty_columns_dropped,
            "columns_renamed": self.columns_renamed,
            "parsed_dates": self.parsed_dates,
            "coerced_numeric": self.coerced_numeric,
            "whitespace_trimmed": self.whitespace_trimmed,
            "missing_before": self.missing_before,
            "missing_after": self.missing_after,
            "warnings": self.warnings,
        }


class IngestionError(Exception):
    """Raised when a file cannot be turned into a usable DataFrame."""


def _sniff_separator(sample: str) -> str:
    """Pick the delimiter that produces the most consistent column count."""
    candidates = [",", ";", "\t", "|"]
    lines = [ln for ln in sample.splitlines()[:20] if ln.strip()]
    if not lines:
        return ","
    best, best_score = ",", -1.0
    for sep in candidates:
        counts = [ln.count(sep) for ln in lines]
        if not counts or max(counts) == 0:
            continue
        # Reward many fields, punish inconsistency between rows
        score = float(np.mean(counts)) - float(np.std(counts)) * 2
        if score > best_score:
            best, best_score = sep, score
    return best


def read_any(file_bytes: bytes, filename: str, sheet_name: str | None = None) -> pd.DataFrame:
    """Read CSV / TSV / Excel bytes into a raw DataFrame."""
    lower = filename.lower()

    if lower.endswith((".xlsx", ".xls")):
        try:
            frame = pd.read_excel(io.BytesIO(file_bytes), sheet_name=sheet_name or 0)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user verbatim
            raise IngestionError(f"Could not read Excel file: {exc}") from exc
        if isinstance(frame, dict):  # sheet_name=None returns every sheet
            frame = next(iter(frame.values()))
        return frame

    # Text formats: decode with a few fallbacks, then sniff the separator
    text = None
    for encoding in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
        try:
            text = file_bytes.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise IngestionError("Could not decode file as text (tried utf-8, latin-1, cp1252).")

    sep = "\t" if lower.endswith(".tsv") else _sniff_separator(text[:20000])
    try:
        return pd.read_csv(io.StringIO(text), sep=sep, engine="python", skipinitialspace=True)
    except Exception as exc:  # noqa: BLE001
        raise IngestionError(f"Could not parse delimited file: {exc}") from exc


def excel_sheet_names(file_bytes: bytes) -> list[str]:
    try:
        return list(pd.ExcelFile(io.BytesIO(file_bytes)).sheet_names)
    except Exception:  # noqa: BLE001
        return []


def _tidy_column_name(name: Any) -> str:
    text = str(name).strip()
    text = text.replace("\n", " ")
    text = re.sub(r"\s+", " ", text)
    return text or "unnamed"


def _looks_like_date_column(series: pd.Series, name: str) -> bool:
    if pd.api.types.is_datetime64_any_dtype(series):
        return True
    if not is_text_series(series):
        return False
    lowered = name.lower()
    name_hint = any(hint in lowered for hint in DATE_NAME_HINTS)
    sample = series.dropna().astype(str).head(200)
    if sample.empty:
        return False
    # Pure integers (IDs, years-as-codes) should not be swept into datetimes
    if sample.str.fullmatch(r"\d{1,8}").mean() > 0.8 and not name_hint:
        return False
    parsed = pd.to_datetime(sample, errors="coerce", format="mixed")
    ratio = parsed.notna().mean()
    return ratio > (0.7 if name_hint else 0.95)


def _looks_like_numeric_column(series: pd.Series) -> bool:
    """Detect numbers hiding behind currency symbols, thousands separators, %."""
    if not is_text_series(series):
        return False
    sample = series.dropna().astype(str).head(300)
    if sample.empty:
        return False
    cleaned = sample.str.replace(CURRENCY_PATTERN, "", regex=True)
    cleaned = cleaned.str.replace(r"^\((.*)\)$", r"-\1", regex=True)  # (123) -> -123
    return pd.to_numeric(cleaned, errors="coerce").notna().mean() > 0.9


def _to_numeric(series: pd.Series) -> pd.Series:
    cleaned = series.astype(str).str.replace(CURRENCY_PATTERN, "", regex=True)
    cleaned = cleaned.str.replace(r"^\((.*)\)$", r"-\1", regex=True)
    return pd.to_numeric(cleaned, errors="coerce")


def clean_dataframe(raw: pd.DataFrame) -> tuple[pd.DataFrame, CleaningReport]:
    """Normalise a raw DataFrame and record every change in a CleaningReport."""
    report = CleaningReport(
        original_rows=len(raw),
        original_columns=raw.shape[1],
        missing_before=int(raw.isna().sum().sum()),
    )
    df = raw.copy()

    # 1. Tidy column names, de-duplicating any collisions
    renames: dict[str, str] = {}
    seen: dict[str, int] = {}
    new_columns = []
    for col in df.columns:
        tidy = _tidy_column_name(col)
        if tidy in seen:
            seen[tidy] += 1
            tidy = f"{tidy} ({seen[tidy]})"
        else:
            seen[tidy] = 0
        if tidy != str(col):
            renames[str(col)] = tidy
        new_columns.append(tidy)
    df.columns = new_columns
    report.columns_renamed = renames

    # 2. Drop columns and rows that are entirely empty
    empty_cols = [c for c in df.columns if df[c].isna().all()]
    if empty_cols:
        df = df.drop(columns=empty_cols)
        report.empty_columns_dropped = list(empty_cols)
    df = df.dropna(how="all")

    # Unnamed index columns written by a previous to_csv()
    junk = [c for c in df.columns if re.fullmatch(r"(?i)unnamed:?\s*\d*", str(c))]
    for col in junk:
        if pd.api.types.is_numeric_dtype(df[col]) and df[col].is_unique:
            df = df.drop(columns=[col])
            report.empty_columns_dropped.append(col)

    # 3. Trim whitespace on text columns
    for col in df.columns:
        if is_text_series(df[col]):
            original = df[col].astype(str)
            trimmed = original.str.strip()
            trimmed = trimmed.replace({"": np.nan, "nan": np.nan, "None": np.nan, "NULL": np.nan})
            if not trimmed.fillna("").equals(original.fillna("")):
                report.whitespace_trimmed.append(col)
            df[col] = trimmed

    # 4. Coerce disguised numerics, then parse dates
    for col in df.columns:
        if _looks_like_numeric_column(df[col]):
            df[col] = _to_numeric(df[col])
            report.coerced_numeric.append(col)

    for col in df.columns:
        if _looks_like_date_column(df[col], str(col)):
            parsed = pd.to_datetime(df[col], errors="coerce", format="mixed")
            if parsed.notna().mean() > 0.5:
                df[col] = parsed
                report.parsed_dates.append(col)

    # 5. Remove exact duplicate rows
    duplicate_count = int(df.duplicated().sum())
    if duplicate_count:
        df = df.drop_duplicates()
        report.duplicates_removed = duplicate_count

    df = df.reset_index(drop=True)

    report.final_rows = len(df)
    report.final_columns = df.shape[1]
    report.missing_after = int(df.isna().sum().sum())

    if report.final_rows == 0:
        report.warnings.append("Cleaning left zero rows - check the source file.")
    if report.final_columns < 2:
        report.warnings.append("Dataset has fewer than 2 usable columns.")
    high_missing = [c for c in df.columns if df[c].isna().mean() > 0.5]
    if high_missing:
        report.warnings.append("Columns more than 50% empty: " + ", ".join(high_missing[:8]))

    return df, report


def load_dataset(
    file_bytes: bytes, filename: str, sheet_name: str | None = None
) -> tuple[pd.DataFrame, pd.DataFrame, CleaningReport]:
    """Full ingest: returns (raw_df, clean_df, cleaning_report)."""
    raw = read_any(file_bytes, filename, sheet_name)
    if raw.empty:
        raise IngestionError("File parsed successfully but contains no rows.")
    clean, report = clean_dataframe(raw)
    return raw, clean, report


def extract_pdf_text(file_bytes: bytes) -> list[tuple[int, str]]:
    """Return [(page_number, text)] for a PDF. Empty list if pypdf is missing."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return []
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
    except Exception:  # noqa: BLE001
        return []
    pages: list[tuple[int, str]] = []
    for index, page in enumerate(reader.pages, start=1):
        try:
            text = (page.extract_text() or "").strip()
        except Exception:  # noqa: BLE001
            text = ""
        if text:
            pages.append((index, text))
    return pages
