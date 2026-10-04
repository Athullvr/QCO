"""Dense vector index over HS descriptions (numpy, cosine). Spike-grade: in-memory + .npy cache; the schema's hs_master/pgvector can replace it later.
Embedders: local fastembed (default, no API key) or OpenAI-compatible /v1/embeddings."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import requests

from .source import HsEntry

LOCAL_MODEL = "BAAI/bge-small-en-v1.5"


class LocalEmbedder:
    def __init__(self, model: str = LOCAL_MODEL):
        from fastembed import TextEmbedding
        self.name, self._m = f"fastembed:{model}", TextEmbedding(model)

    def embed(self, texts: list[str], *, query: bool = False) -> np.ndarray:
        if query: texts = ["Represent this sentence for searching relevant passages: " + t for t in texts]
        return np.array(list(self._m.embed(texts)), dtype=np.float32)


class OpenAIEmbedder:
    def __init__(self, api_key: str, model: str, base_url: str = "https://api.openai.com"):
        self.name, self.key, self.model, self.base = f"openai:{model}", api_key, model, base_url

    def embed(self, texts: list[str], *, query: bool = False) -> np.ndarray:
        out = []
        for i in range(0, len(texts), 256):
            r = requests.post(f"{self.base}/v1/embeddings", headers={"Authorization": f"Bearer {self.key}"},
                              json={"model": self.model, "input": texts[i:i + 256]}, timeout=120)
            r.raise_for_status(); out += [d["embedding"] for d in r.json()["data"]]
        return np.array(out, dtype=np.float32)


def _unit(a: np.ndarray) -> np.ndarray: return a / np.clip(np.linalg.norm(a, axis=1, keepdims=True), 1e-9, None)


class HsIndex:
    def __init__(self, entries: list[HsEntry], embedder, cache_dir: Path | None = None):
        self.entries, self.embedder = entries, embedder
        cf = cache_dir / f"hs_{embedder.name.replace(':', '_').replace('/', '_')}_{len(entries)}.npy" if cache_dir else None
        if cf and cf.exists(): self.mat = np.load(cf)
        else:
            self.mat = _unit(embedder.embed([f"{e.code} {e.context}" if e.level == 6 else e.context for e in entries]))
            if cf: cf.parent.mkdir(parents=True, exist_ok=True); np.save(cf, self.mat)

    def search(self, query: str, k: int = 30, *, level: int | None = 6) -> list[tuple[HsEntry, float]]:
        q = _unit(self.embedder.embed([query], query=True))[0]
        sims = self.mat @ q
        if level: sims = np.where([e.level == level for e in self.entries], sims, -1.0)
        idx = np.argsort(-sims)[:k]
        return [(self.entries[i], float(sims[i])) for i in idx]
