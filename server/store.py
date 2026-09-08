"""In-memory dataset registry shared by the API routes.

Holds the cleaned DataFrame, its profile, the cleaning report and the vector
store for each uploaded dataset, keyed by a short id handed back to the browser.
The analytics modules in src/ stay completely unaware of HTTP.
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from src.ingestion import CleaningReport, extract_pdf_text, load_dataset
from src.metadata import build_documents, dataset_fingerprint
from src.profiling import DatasetProfile, profile_dataset
from src.vectorstore import VectorStore


@dataclass
class Dataset:
    id: str
    name: str
    filename: str
    raw: pd.DataFrame
    clean: pd.DataFrame
    cleaning: CleaningReport
    profile: DatasetProfile
    fingerprint: str
    documents: list[dict[str, Any]] = field(default_factory=list)
    store: VectorStore | None = None
    chat: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] | None = None

    def vector_store(self) -> VectorStore:
        if self.store is None:
            self.store = VectorStore(f"ds-{self.fingerprint}")
            self.store.build(self.documents)
        return self.store


class DatasetRegistry:
    """Thread-safe, bounded store of active datasets."""

    def __init__(self, max_datasets: int = 6) -> None:
        self._items: dict[str, Dataset] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()
        self.max_datasets = max_datasets

    def add(self, dataset: Dataset) -> Dataset:
        with self._lock:
            self._items[dataset.id] = dataset
            self._order.append(dataset.id)
            # Drop the oldest datasets so long sessions cannot exhaust memory
            while len(self._order) > self.max_datasets:
                oldest = self._order.pop(0)
                self._items.pop(oldest, None)
        return dataset

    def get(self, dataset_id: str) -> Dataset | None:
        return self._items.get(dataset_id)

    def list(self) -> list[Dataset]:
        return [self._items[i] for i in self._order if i in self._items]

    def remove(self, dataset_id: str) -> bool:
        with self._lock:
            if dataset_id not in self._items:
                return False
            self._items.pop(dataset_id, None)
            self._order = [i for i in self._order if i != dataset_id]
            return True


REGISTRY = DatasetRegistry()


def ingest(file_bytes: bytes, filename: str, sheet: str | None = None) -> Dataset:
    """Run the full ingest pipeline and register the result."""
    raw, clean, report = load_dataset(file_bytes, filename, sheet)
    name = Path(filename).stem
    profile = profile_dataset(clean, name=name)
    dataset = Dataset(
        id=uuid.uuid4().hex[:12],
        name=name,
        filename=filename,
        raw=raw,
        clean=clean,
        cleaning=report,
        profile=profile,
        fingerprint=dataset_fingerprint(clean, name),
        documents=build_documents(profile, report),
    )
    return REGISTRY.add(dataset)


def add_pdf_context(dataset: Dataset, file_bytes: bytes, filename: str) -> int:
    """Chunk a PDF report into the dataset's retrieval corpus."""
    pages = extract_pdf_text(file_bytes)
    if not pages:
        return 0
    documents: list[dict[str, Any]] = []
    for page_number, text in pages:
        for offset in range(0, len(text), 1200):
            piece = text[offset : offset + 1200].strip()
            if len(piece) < 60:
                continue
            documents.append(
                {
                    "id": f"{dataset.name}::pdf::{filename}::{page_number}::{offset}",
                    "text": f"From report '{filename}', page {page_number}: {piece}",
                    "metadata": {
                        "dataset": dataset.name,
                        "kind": "report",
                        "column": f"{filename} p{page_number}",
                    },
                }
            )
    if not documents:
        return 0
    dataset.vector_store().build(documents)
    dataset.documents.extend(documents)
    return len(documents)
