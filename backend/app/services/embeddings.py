"""Embedding providers with graceful degradation.

Resolution order (``EMBEDDING_PROVIDER``):

* ``local``  – deterministic hashing embedder, no model download, always works.
* ``st``     – sentence-transformers (best quality, needs the package + weights).
* ``api``    – any OpenAI-compatible ``/embeddings`` endpoint.
* ``auto``   – first available of the above, falling back to ``local``.

The hashing embedder is a real vector representation (signed feature hashing of
word unigrams and bigrams with sublinear term weighting), so retrieval quality
is meaningful even on a laptop with no GPU and no API key.
"""

from __future__ import annotations

import hashlib
import itertools
import math
from collections import Counter
from functools import lru_cache
from typing import Protocol

import httpx

from ..config import EMBEDDING_SCHEMA_VERSION, get_settings
from .textutils import STOPWORDS, tokenize

_HASH_CACHE: dict[str, tuple[int, float]] = {}


def _feature_hash(token: str) -> tuple[int, float]:
    cached = _HASH_CACHE.get(token)
    if cached is not None:
        return cached
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    value = int.from_bytes(digest, "big")
    index = value % 4096  # prime-ish bucket count keeps collisions low
    sign = 1.0 if (value >> 63) & 1 else -1.0
    result = (index, sign)
    if len(_HASH_CACHE) < 20000:
        _HASH_CACHE[token] = result
    return result


def hashing_embed(text: str, dimensions: int = 512) -> list[float]:
    tokens = tokenize(text)
    if not tokens:
        return [0.0] * dimensions
    counts: Counter[str] = Counter(tokens)
    bigrams = [f"{a}_{b}" for a, b in itertools.pairwise(tokens)]
    counts.update(Counter(bigrams))

    vector = [0.0] * dimensions
    for token, freq in counts.items():
        weight = (1.0 + math.log(freq)) * (0.45 if token in STOPWORDS else 1.0)
        if "_" in token:
            weight *= 0.6
        index, sign = _feature_hash(token)
        vector[index % dimensions] += sign * weight
        # A second, decorrelated bucket reduces collision damage.
        index2, sign2 = _feature_hash(f"x{token}")
        vector[index2 % dimensions] += sign2 * weight * 0.5

    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0.0:
        return vector
    return [round(v / norm, 6) for v in vector]


class EmbeddingProvider(Protocol):
    name: str
    model: str
    dimensions: int

    def embed(self, text: str) -> list[float]: ...
    def embed_many(self, texts: list[str]) -> list[list[float]]: ...


class HashingEmbeddingProvider:
    name = "hashing"
    model = f"{EMBEDDING_SCHEMA_VERSION}-d512"

    def __init__(self, dimensions: int = 512) -> None:
        self.dimensions = dimensions
        self.model = f"{EMBEDDING_SCHEMA_VERSION}-d{dimensions}"

    def embed(self, text: str) -> list[float]:
        return hashing_embed(text, self.dimensions)

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


class SentenceTransformerEmbeddingProvider:
    name = "sentence-transformers"

    def __init__(self, model_name: str) -> None:
        from sentence_transformers import SentenceTransformer  # type: ignore

        self._model = SentenceTransformer(model_name)
        self.model = model_name
        self.dimensions = int(self._model.get_sentence_embedding_dimension())

    def embed(self, text: str) -> list[float]:
        return [float(v) for v in self._model.encode(text, normalize_embeddings=True)]

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(texts, normalize_embeddings=True, batch_size=16)
        return [[float(v) for v in row] for row in vectors]


class ApiEmbeddingProvider:
    name = "api"

    def __init__(self, base_url: str, api_key: str, model: str, fallback: EmbeddingProvider) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self._fallback = fallback
        self.dimensions = fallback.dimensions

    def _post(self, texts: list[str]) -> list[list[float]]:
        with httpx.Client(timeout=45.0) as client:
            response = client.post(
                f"{self.base_url}/embeddings",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.model, "input": texts},
            )
            response.raise_for_status()
            payload = response.json()
        return [[float(v) for v in item["embedding"]] for item in payload["data"]]

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        try:
            return self._post(texts)
        except Exception:
            return self._fallback.embed_many(texts)

    def embed(self, text: str) -> list[float]:
        return self.embed_many([text])[0]


@lru_cache(maxsize=8)
def _cached_provider(key: str) -> EmbeddingProvider:
    settings = get_settings()
    requested = settings.embedding_provider.lower()
    local = HashingEmbeddingProvider(settings.embedding_dimensions)

    order: list[str]
    if requested == "local":
        order = ["local"]
    elif requested == "st":
        order = ["st"]
    elif requested == "api":
        order = ["api", "local"]
    else:
        order = ["st", "api", "local"]

    for candidate in order:
        try:
            if candidate == "st":
                return SentenceTransformerEmbeddingProvider(settings.embedding_model)
            if candidate == "api":
                if settings.llm_base_url and settings.llm_api_key:
                    return ApiEmbeddingProvider(
                        settings.llm_base_url,
                        settings.llm_api_key,
                        _embedding_model_name(settings.llm_model),
                        local,
                    )
                continue
            return local
        except Exception:
            continue
    return local


def _embedding_model_name(llm_model: str) -> str:
    if "gpt-3.5" in llm_model:
        return "text-embedding-3-small"
    if "gpt-4" in llm_model:
        return "text-embedding-3-small"
    if "gemini" in llm_model:
        return "text-embedding-004"
    if "llama" in llm_model:
        return "nomic-embed-text"
    return "text-embedding-3-small"


def get_provider() -> EmbeddingProvider:
    settings = get_settings()
    return _cached_provider(f"{settings.embedding_provider}:{settings.embedding_model}:{settings.embedding_dimensions}")


def embed(text: str) -> list[float]:
    return get_provider().embed(text)


def embed_many(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    provider = get_provider()
    batch = 64
    vectors: list[list[float]] = []
    for start in range(0, len(texts), batch):
        vectors.extend(provider.embed_many(texts[start : start + batch]))
    return vectors
