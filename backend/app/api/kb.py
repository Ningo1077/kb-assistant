from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Chunk, Document, KnowledgeBase, User
from ..schemas import KBCreate, KBOut
from .deps import get_current_user, get_owned_kb

router = APIRouter(prefix="/kbs", tags=["知识库"])


def _to_out(kb: KnowledgeBase, doc_count: int, chunk_count: int) -> KBOut:
    return KBOut(
        id=kb.id,
        name=kb.name,
        description=kb.description,
        document_count=doc_count,
        chunk_count=chunk_count,
        created_at=kb.created_at,
    )


@router.get("", response_model=list[KBOut])
def list_kbs(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[KBOut]:
    kbs = db.scalars(
        select(KnowledgeBase).where(KnowledgeBase.owner_id == user.id).order_by(KnowledgeBase.id.desc())
    ).all()
    if not kbs:
        return []

    ids = [kb.id for kb in kbs]
    doc_counts = dict(
        db.execute(
            select(Document.kb_id, func.count(Document.id)).where(Document.kb_id.in_(ids)).group_by(Document.kb_id)
        ).all()
    )
    chunk_counts = dict(
        db.execute(
            select(Chunk.kb_id, func.count(Chunk.id)).where(Chunk.kb_id.in_(ids)).group_by(Chunk.kb_id)
        ).all()
    )
    return [_to_out(kb, doc_counts.get(kb.id, 0), chunk_counts.get(kb.id, 0)) for kb in kbs]


@router.post("", response_model=KBOut, status_code=201)
def create_kb(
    payload: KBCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> KBOut:
    kb = KnowledgeBase(owner_id=user.id, name=payload.name.strip(), description=payload.description.strip())
    db.add(kb)
    db.commit()
    db.refresh(kb)
    return _to_out(kb, 0, 0)


@router.get("/{kb_id}", response_model=KBOut)
def get_kb(kb_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> KBOut:
    kb = get_owned_kb(kb_id, db, user)
    doc_count = db.scalar(select(func.count(Document.id)).where(Document.kb_id == kb_id)) or 0
    chunk_count = db.scalar(select(func.count(Chunk.id)).where(Chunk.kb_id == kb_id)) or 0
    return _to_out(kb, doc_count, chunk_count)


@router.delete("/{kb_id}", status_code=204)
def delete_kb(kb_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> None:
    kb = get_owned_kb(kb_id, db, user)
    if db.scalar(select(func.count(Chunk.id)).where(Chunk.kb_id == kb_id)):
        db.execute(Chunk.__table__.delete().where(Chunk.kb_id == kb_id))
    if db.scalar(select(func.count(Document.id)).where(Document.kb_id == kb_id)):
        db.execute(Document.__table__.delete().where(Document.kb_id == kb_id))
    db.delete(kb)
    db.commit()
    return None
