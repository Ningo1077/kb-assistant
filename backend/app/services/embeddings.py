"""向量化服务。三种 provider，同一接口，切换只改环境变量。"""

import hashlib
import re
from functools import lru_cache
from typing import Protocol

import httpx

from ..core.config import settings

_HASHLING_CLEAN = re.compile(r"\s+")


class Embedder(Protocol):
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashingEmbedder:
    """无模型的确定性向量：字符 bigram 带符号哈希。

    仅用于开发/离线联调，能跑通链路，但语义能力弱于真实 embedding 模型。
    """

    def __init__(self, dim: int) -> None:
        self.dim = dim

    def _one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        cleaned = _HASHLING_CLEAN.sub("", text.lower())
        if not cleaned:
            return vec
        grams = [cleaned[i : i + 2] for i in range(len(cleaned) - 1)] or [cleaned]
        for gram in grams:
            digest = hashlib.blake2b(gram.encode("utf-8"), digest_size=8).digest()
            h = int.from_bytes(digest, "big")
            idx = h % self.dim
            vec[idx] += 1.0 if (h >> 63) & 1 else -1.0
        norm = sum(v * v for v in vec) ** 0.5
        if norm == 0:
            return vec
        return [v / norm for v in vec]

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]


class OllamaEmbedder:
    def __init__(self, base_url: str, model: str, dim: int) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        with httpx.Client(timeout=120) as client:
            resp = client.post(
                f"{self.base_url}/api/embed", json={"model": self.model, "input": texts}
            )
            if resp.status_code == 404:  # 老版本 Ollama 只有单条接口
                vectors = []
                for t in texts:
                    r = client.post(
                        f"{self.base_url}/api/embeddings", json={"model": self.model, "prompt": t}
                    )
                    r.raise_for_status()
                    vectors.append(r.json()["embedding"])
                return self._check(vectors)
            resp.raise_for_status()
            return self._check(resp.json()["embeddings"])

    def _check(self, vectors: list[list[float]]) -> list[list[float]]:
        if vectors and len(vectors[0]) != self.dim:
            raise ValueError(
                f"embedding 维度不一致：模型返回 {len(vectors[0])}，配置 EMBED_DIM={self.dim}。"
                "请把 EMBED_DIM 改成模型维度（bge-m3 为 1024）。"
            )
        return vectors


class OpenAIEmbedder:
    def __init__(self, base_url: str, model: str, api_key: str, dim: int) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        url = f"{self.base_url}/v1/embeddings" if not self.base_url.endswith("/v1") else f"{self.base_url}/embeddings"
        with httpx.Client(timeout=120) as client:
            resp = client.post(
                url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.model, "input": texts},
            )
            resp.raise_for_status()
            data = resp.json()["data"]
        vectors = [item["embedding"] for item in sorted(data, key=lambda x: x.get("index", 0))]
        return OllamaEmbedder._check(self, vectors)


@lru_cache
def get_embedder() -> Embedder:
    provider = settings.embed_provider.lower()
    if provider == "hashing":
        return HashingEmbedder(settings.embed_dim)
    if provider == "ollama":
        return OllamaEmbedder(settings.llm_base_url, settings.embed_model, settings.embed_dim)
    if provider == "openai":
        return OpenAIEmbedder(settings.llm_base_url, settings.embed_model, settings.llm_api_key, settings.embed_dim)
    raise ValueError(f"未知的 EMBED_PROVIDER: {settings.embed_provider}")


def embed_texts(texts: list[str], batch_size: int = 16) -> list[list[float]]:
    embedder = get_embedder()
    out: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        out.extend(embedder.embed(texts[i : i + batch_size]))
    return out
