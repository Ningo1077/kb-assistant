"""混合检索：向量召回 + 关键词召回，用 RRF 融合排序。

纯向量对型号、人名、专有名词不敏感，关键词一路正好补上这个洞。
"""

import re
from dataclasses import dataclass

import numpy as np
from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session

from ..core.config import settings
from ..models import Chunk
from .embeddings import embed_texts

_RRF_K = 60
_CANDIDATE_LIMIT = 3000


@dataclass
class Hit:
    chunk: Chunk
    score: float
    similarity: float = 0.0
    vector_rank: int | None = None
    keyword_rank: int | None = None


def _vec_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{float(x):.6f}" for x in vec) + "]"


def _vector_search(db: Session, kb_id: int, qvec: list[float], k: int) -> list[tuple[Chunk, float]]:
    if settings.is_postgres:
        rows = db.execute(
            text(
                "SELECT id, (embedding <=> CAST(:q AS vector)) AS dist FROM chunks "
                "WHERE kb_id = :kb AND embedding IS NOT NULL ORDER BY dist LIMIT :k"
            ),
            {"q": _vec_literal(qvec), "kb": kb_id, "k": k},
        ).all()
        if not rows:
            return []
        dist_map = {int(r[0]): float(r[1]) for r in rows}
        chunks = {c.id: c for c in db.scalars(select(Chunk).where(Chunk.id.in_(dist_map.keys())))}
        return [(chunks[cid], 1.0 - dist) for cid, dist in dist_map.items() if cid in chunks]

    chunks = db.scalars(
        select(Chunk).where(Chunk.kb_id == kb_id, Chunk.embedding.is_not(None)).limit(_CANDIDATE_LIMIT)
    ).all()
    if not chunks:
        return []
    mat = np.asarray([c.embedding for c in chunks], dtype=np.float32)
    q = np.asarray(qvec, dtype=np.float32)
    q = q / (np.linalg.norm(q) + 1e-9)
    sims = (mat @ q) / (np.linalg.norm(mat, axis=1) + 1e-9)
    order = np.argsort(-sims)[:k]
    return [(chunks[i], float(sims[i])) for i in order]


def _terms(query: str) -> list[str]:
    terms: set[str] = set()
    for run in re.findall(r"[\u4e00-\u9fff]+|[A-Za-z0-9_]+", query):
        if re.fullmatch(r"[A-Za-z0-9_]+", run):
            if len(run) >= 2:
                terms.add(run.lower())
        elif len(run) == 1:
            terms.add(run)
        else:
            terms.update(run[i : i + 2] for i in range(len(run) - 1))
    return sorted(terms, key=len, reverse=True)[:6]


def _keyword_search(db: Session, kb_id: int, query: str, k: int) -> list[tuple[Chunk, float]]:
    terms = _terms(query)
    if not terms:
        return []
    conds = [Chunk.content.contains(t) for t in terms[:3]]
    candidates = db.scalars(
        select(Chunk).where(Chunk.kb_id == kb_id, or_(*conds)).limit(200)
    ).all()
    scored: list[tuple[Chunk, float]] = []
    whole = query.strip().lower()
    for c in candidates:
        low = c.content.lower()
        score = float(sum(low.count(t) for t in terms))
        if whole and whole in low:
            score += 5.0
        if score > 0:
            scored.append((c, score))
    scored.sort(key=lambda x: -x[1])
    return scored[:k]


def retrieve(
    db: Session,
    kb_id: int,
    query: str,
    top_k: int | None = None,
    recall_k: int | None = None,
) -> list[Hit]:
    top_k = top_k or settings.retrieve_top_k
    recall_k = recall_k or settings.retrieve_recall_k

    qvec = embed_texts([query])[0]
    vec_hits = _vector_search(db, kb_id, qvec, recall_k)
    kw_hits = _keyword_search(db, kb_id, query, recall_k)

    sim_map = {chunk.id: float(sim) for chunk, sim in vec_hits}

    fused: dict[int, float] = {}
    store: dict[int, Chunk] = {}
    vrank: dict[int, int] = {}
    krank: dict[int, int] = {}

    for rank, (chunk, _) in enumerate(vec_hits, start=1):
        fused[chunk.id] = fused.get(chunk.id, 0.0) + 1.0 / (_RRF_K + rank)
        store[chunk.id] = chunk
        vrank[chunk.id] = rank
    for rank, (chunk, _) in enumerate(kw_hits, start=1):
        fused[chunk.id] = fused.get(chunk.id, 0.0) + 1.0 / (_RRF_K + rank)
        store[chunk.id] = chunk
        krank[chunk.id] = rank

    ranked = sorted(fused.items(), key=lambda x: -x[1])[:top_k]
    if not ranked:
        return []

    best = ranked[0][1] or 1.0
    return [
        Hit(
            chunk=store[cid],
            score=round(score / best, 4),
            similarity=round(sim_map.get(cid, 0.0), 4),
            vector_rank=vrank.get(cid),
            keyword_rank=krank.get(cid),
        )
        for cid, score in ranked
    ]
