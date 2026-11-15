"""入库管线：解析 → 清洗 → 分块 → 向量化 → 落库，状态机驱动前端进度条。"""

import hashlib
import logging
from pathlib import Path

from ..core.config import settings
from ..db import SessionLocal
from ..models import Chunk, Document
from .embeddings import embed_texts
from .text import MAX_FILE_BYTES, SUPPORTED_SUFFIXES, chunk_segments, parse_document

logger = logging.getLogger(__name__)

STATUS_PENDING = "pending"
STATUS_PARSING = "parsing"
STATUS_EMBEDDING = "embedding"
STATUS_READY = "ready"
STATUS_FAILED = "failed"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_upload(filename: str, size: int) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError(f"仅支持 {', '.join(sorted(SUPPORTED_SUFFIXES))}")
    if size > MAX_FILE_BYTES:
        raise ValueError(f"文件超过 {MAX_FILE_BYTES // 1024 // 1024}MB 限制")
    if size == 0:
        raise ValueError("文件为空")
    return suffix


def ingest_document(doc_id: int) -> None:
    """后台任务入口。自己管理 session，不能复用请求里的 session。"""
    db = SessionLocal()
    doc = db.get(Document, doc_id)
    if doc is None:
        db.close()
        return

    try:
        doc.status = STATUS_PARSING
        doc.error_msg = ""
        db.commit()

        segments = parse_document(Path(doc.storage_path))
        pieces = chunk_segments(segments, settings.chunk_size, settings.chunk_overlap)
        if not pieces:
            raise ValueError("切分后没有有效内容")

        doc.status = STATUS_EMBEDDING
        doc.page_count = len(segments)
        db.commit()

        vectors = embed_texts([p.content for p in pieces])

        db.execute(Chunk.__table__.delete().where(Chunk.doc_id == doc.id))
        db.add_all(
            [
                Chunk(
                    doc_id=doc.id,
                    kb_id=doc.kb_id,
                    chunk_index=piece.index,
                    content=piece.content,
                    char_count=len(piece.content),
                    page_no=piece.page_no,
                    embedding=vector,
                )
                for piece, vector in zip(pieces, vectors)
            ]
        )
        doc.chunk_count = len(pieces)
        doc.token_estimate = sum(len(p.content) for p in pieces) // 2  # 中文约 1.5 字符/token，粗估
        doc.status = STATUS_READY
        db.commit()
        logger.info("入库完成 doc=%s chunks=%s", doc.id, doc.chunk_count)
    except Exception as exc:  # 任何一步失败都要让用户看到原因，而不是卡在 processing
        db.rollback()
        doc = db.get(Document, doc_id)
        if doc is not None:
            doc.status = STATUS_FAILED
            doc.error_msg = str(exc)[:500]
            db.commit()
        logger.exception("入库失败 doc=%s", doc_id)
    finally:
        db.close()
