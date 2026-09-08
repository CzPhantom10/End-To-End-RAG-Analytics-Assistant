"""ChromaDB-backed retrieval layer.

Uses Chroma's built-in ONNX all-MiniLM-L6-v2 embedding function, so there is no
torch dependency and no second API key - the model downloads once (~80 MB) and
then runs locally. If Chroma cannot start at all (offline first run, locked
file), we fall back to a small TF-IDF-ish keyword index so the app still works
and the UI says which backend answered.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

from .config import CHROMA_DIR


@dataclass
class RetrievedChunk:
    text: str
    metadata: dict[str, Any]
    score: float
    source: str

    @property
    def label(self) -> str:
        kind = self.metadata.get("kind", "context")
        column = self.metadata.get("column")
        return f"{kind}:{column}" if column else kind


# --------------------------------------------------------------------------
# Fallback keyword index
# --------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


class KeywordIndex:
    """Minimal BM25-flavoured index used only when Chroma is unavailable."""

    def __init__(self) -> None:
        self.docs: list[dict[str, Any]] = []
        self.doc_freq: Counter[str] = Counter()

    def add(self, documents: list[dict[str, Any]]) -> None:
        self.docs = []
        self.doc_freq = Counter()
        for doc in documents:
            tokens = _tokenize(doc["text"])
            self.docs.append({**doc, "tokens": Counter(tokens), "length": max(len(tokens), 1)})
            for token in set(tokens):
                self.doc_freq[token] += 1

    def query(self, text: str, k: int) -> list[RetrievedChunk]:
        if not self.docs:
            return []
        query_tokens = _tokenize(text)
        total = len(self.docs)
        scored: list[tuple[float, dict[str, Any]]] = []
        for doc in self.docs:
            score = 0.0
            for token in query_tokens:
                tf = doc["tokens"].get(token, 0)
                if not tf:
                    continue
                idf = math.log(1 + total / (1 + self.doc_freq[token]))
                score += (tf / doc["length"]) * idf
            if score > 0:
                scored.append((score, doc))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [
            RetrievedChunk(
                text=doc["text"], metadata=doc["metadata"], score=round(score, 4), source="keyword"
            )
            for score, doc in scored[:k]
        ]


# --------------------------------------------------------------------------
# Chroma index
# --------------------------------------------------------------------------


class VectorStore:
    """Wraps a Chroma collection with a graceful keyword fallback."""

    def __init__(self, collection_name: str, persist: bool = True) -> None:
        self.collection_name = re.sub(r"[^a-zA-Z0-9_-]", "-", collection_name)[:60].strip("-")
        if len(self.collection_name) < 3:
            self.collection_name = f"ds-{self.collection_name}"
        self.persist = persist
        self.backend = "none"
        self.error: str | None = None
        self._collection = None
        self._fallback = KeywordIndex()

    # -- setup -------------------------------------------------------------

    def _init_chroma(self) -> bool:
        try:
            import chromadb
            from chromadb.utils import embedding_functions

            if self.persist:
                CHROMA_DIR.mkdir(parents=True, exist_ok=True)
                client = chromadb.PersistentClient(path=str(CHROMA_DIR))
            else:
                client = chromadb.EphemeralClient()

            embedder = embedding_functions.ONNXMiniLM_L6_V2()
            self._collection = client.get_or_create_collection(
                name=self.collection_name,
                embedding_function=embedder,
                metadata={"hnsw:space": "cosine"},
            )
            self.backend = "chroma"
            return True
        except Exception as exc:  # noqa: BLE001 - any failure means fall back
            self.error = f"{type(exc).__name__}: {exc}"
            return False

    def build(self, documents: list[dict[str, Any]], force: bool = False) -> None:
        """Index the documents. Safe to call repeatedly for the same dataset."""
        if not documents:
            return

        if self._collection is None and self.backend != "keyword":
            if not self._init_chroma():
                self.backend = "keyword"

        if self.backend == "chroma" and self._collection is not None:
            try:
                existing = self._collection.count()
                if existing and not force:
                    return  # already indexed in a previous session
                if existing and force:
                    self._collection.delete(where={"dataset": documents[0]["metadata"]["dataset"]})
                self._collection.upsert(
                    ids=[d["id"] for d in documents],
                    documents=[d["text"] for d in documents],
                    metadatas=[d["metadata"] for d in documents],
                )
                return
            except Exception as exc:  # noqa: BLE001
                self.error = f"{type(exc).__name__}: {exc}"
                self.backend = "keyword"

        self.backend = "keyword"
        self._fallback.add(documents)

    # -- retrieval ---------------------------------------------------------

    def query(self, question: str, k: int = 6) -> list[RetrievedChunk]:
        if self.backend == "chroma" and self._collection is not None:
            try:
                result = self._collection.query(query_texts=[question], n_results=k)
                chunks: list[RetrievedChunk] = []
                documents = (result.get("documents") or [[]])[0]
                metadatas = (result.get("metadatas") or [[]])[0]
                distances = (result.get("distances") or [[]])[0]
                for text, metadata, distance in zip(documents, metadatas, distances):
                    chunks.append(
                        RetrievedChunk(
                            text=text,
                            metadata=dict(metadata or {}),
                            # cosine distance -> similarity
                            score=round(max(0.0, 1.0 - float(distance)), 4),
                            source="chroma",
                        )
                    )
                return chunks
            except Exception as exc:  # noqa: BLE001
                self.error = f"{type(exc).__name__}: {exc}"
                self.backend = "keyword"
        return self._fallback.query(question, k)

    def count(self) -> int:
        if self.backend == "chroma" and self._collection is not None:
            try:
                return int(self._collection.count())
            except Exception:  # noqa: BLE001
                return 0
        return len(self._fallback.docs)

    def status(self) -> str:
        if self.backend == "chroma":
            return f"ChromaDB (ONNX MiniLM-L6-v2) - {self.count()} chunks"
        if self.backend == "keyword":
            return f"Keyword fallback - {self.count()} chunks"
        return "not built"


def build_store(collection_name: str, documents: list[dict[str, Any]]) -> VectorStore:
    store = VectorStore(collection_name)
    store.build(documents)
    return store
