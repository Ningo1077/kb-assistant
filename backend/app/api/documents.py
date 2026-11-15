from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import settings
from ..db import get_db
from ..models import Document, User
from ..schemas import DocumentOut
from ..services.ingest import (
    STATUS_READY,
    file_sha256,
    ingest_document,
    validate_upload,
)
from .deps import get_current_user, get_owned_kb

router = APIRouter(prefix="/kbs/{kb_id}/documents", tags=["文档"])


@router.get("", response_model=list[DocumentOut])
def list_documents(
    kb_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[Document]:
    get_owned_kb(kb_id, db, user)
    return list(
        db.scalars(select(Document).where(Document.kb_id == kb_id).order_by(Document.id.desc())).all()
    )


@router.get("/{doc_id}", response_model=DocumentOut)
def get_document(
    kb_id: int, doc_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Document:
    get_owned_kb(kb_id, db, user)
    doc = db.get(Document, doc_id)
    if doc is None or doc.kb_id != kb_id:
        raise HTTPException(status_code=404, detail="文档不存在")
    return doc


@router.post("", response_model=DocumentOut, status_code=201)
async def upload_document(
    kb_id: int,
    background: BackgroundTasks,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Document:
    get_owned_kb(kb_id, db, user)

    filename = Path(file.filename or "unnamed").name.strip() or "unnamed"
    content = await file.read()
    try:
        validate_upload(filename, len(content))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(filename).suffix.lower()
    tmp_path = settings.upload_dir / f"tmp-{uuid4().hex}{suffix}"
    tmp_path.write_bytes(content)
    sha = file_sha256(tmp_path)

    existing = db.scalar(
        select(Document).where(Document.kb_id == kb_id, Document.sha256 == sha)
    )
    if existing is not None:
        tmp_path.unlink(missing_ok=True)
        if existing.status == STATUS_READY:
            # 秒传：同一知识库内内容完全相同的文件直接复用
            return existing
        background.add_task(ingest_document, existing.id)
        return existing

    final_path = settings.upload_dir / f"{sha[:16]}{suffix}"
    tmp_path.replace(final_path)

    doc = Document(
        kb_id=kb_id,
        filename=filename,
        mime_type=file.content_type or "",
        size_bytes=len(content),
        sha256=sha,
        storage_path=str(final_path),
        status="pending",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    background.add_task(ingest_document, doc.id)
    return doc


@router.post("/{doc_id}/reindex", response_model=DocumentOut)
def reindex(
    kb_id: int,
    doc_id: int,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Document:
    get_owned_kb(kb_id, db, user)
    doc = db.get(Document, doc_id)
    if doc is None or doc.kb_id != kb_id:
        raise HTTPException(status_code=404, detail="文档不存在")
    doc.status = "pending"
    doc.error_msg = ""
    db.commit()
    db.refresh(doc)
    background.add_task(ingest_document, doc.id)
    return doc


@router.delete("/{doc_id}", status_code=204)
def delete_document(
    kb_id: int, doc_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> None:
    get_owned_kb(kb_id, db, user)
    doc = db.get(Document, doc_id)
    if doc is None or doc.kb_id != kb_id:
        raise HTTPException(status_code=404, detail="文档不存在")
    storage = Path(doc.storage_path) if doc.storage_path else None
    db.delete(doc)
    db.commit()
    if storage is not None:
        storage.unlink(missing_ok=True)
