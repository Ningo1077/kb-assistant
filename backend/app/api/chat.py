import json
import time
from collections.abc import Iterator
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import settings
from ..db import SessionLocal, get_db
from ..models import Conversation, Document, Feedback, Message, User
from ..schemas import ChatIn, ConversationOut, FeedbackIn, MessageOut
from ..services.llm import build_messages, stream_answer
from ..services.retrieval import retrieve
from .deps import get_current_user, get_owned_kb

router = APIRouter(prefix="/chat", tags=["问答"])


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("")
def chat(
    payload: ChatIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> StreamingResponse:
    kb = get_owned_kb(payload.kb_id, db, user)

    conv: Conversation | None = None
    if payload.conversation_id:
        conv = db.get(Conversation, payload.conversation_id)
        if conv is None or conv.user_id != user.id or conv.kb_id != kb.id:
            raise HTTPException(status_code=404, detail="会话不存在")
    if conv is None:
        conv = Conversation(
            user_id=user.id, kb_id=kb.id, title=payload.question.strip()[:24] or "新对话"
        )
        db.add(conv)
        db.commit()
        db.refresh(conv)

    history = [(m.role, m.content) for m in conv.messages if m.role in ("user", "assistant")][-6:]
    db.add(Message(conversation_id=conv.id, role="user", content=payload.question))
    db.commit()

    hits = retrieve(db, kb.id, payload.question)

    doc_names: dict[int, str] = {}
    if hits:
        doc_ids = {h.chunk.doc_id for h in hits}
        doc_names = dict(
            db.execute(select(Document.id, Document.filename).where(Document.id.in_(doc_ids))).all()
        )

    citations: list[dict] = []
    snippets: list[dict] = []
    budget = settings.max_context_chars
    for i, hit in enumerate(hits, start=1):
        content = hit.chunk.content[: min(1200, budget)]
        budget -= len(content)
        if budget <= 0:
            break
        item = {
            "index": i,
            "chunk_id": hit.chunk.id,
            "doc_id": hit.chunk.doc_id,
            "filename": doc_names.get(hit.chunk.doc_id, "未知文档"),
            "page_no": hit.chunk.page_no,
            "snippet": content[:300],
            "score": hit.score,
            "similarity": hit.similarity,
        }
        citations.append(item)
        snippets.append({**item, "content": content})

    messages = build_messages(payload.question, snippets, history)
    conv_id = conv.id

    def generate() -> Iterator[str]:
        buffer: list[str] = []
        started = time.perf_counter()
        message_id: int | None = None
        error: str | None = None

        yield _sse({"type": "meta", "conversation_id": conv_id, "citations": citations})

        try:
            for delta in stream_answer(messages):
                if not delta:
                    continue
                buffer.append(delta)
                yield _sse({"type": "delta", "content": delta})
        except Exception as exc:  # 模型不可用要让前端看到，而不是静默失败
            error = str(exc)
            yield _sse({"type": "error", "message": f"生成失败：{error}"})
        finally:
            answer = "".join(buffer)
            latency = int((time.perf_counter() - started) * 1000)
            session = SessionLocal()
            try:
                msg = Message(
                    conversation_id=conv_id,
                    role="assistant",
                    content=answer,
                    citations=citations,
                    latency_ms=latency,
                )
                session.add(msg)
                session.flush()
                message_id = msg.id
                stored = session.get(Conversation, conv_id)
                if stored is not None:
                    stored.updated_at = datetime.now()
                session.commit()
            finally:
                session.close()
            yield _sse({"type": "done", "message_id": message_id, "latency_ms": latency, "error": error})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/conversations", response_model=list[ConversationOut])
def list_conversations(
    kb_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[Conversation]:
    get_owned_kb(kb_id, db, user)
    return list(
        db.scalars(
            select(Conversation)
            .where(Conversation.user_id == user.id, Conversation.kb_id == kb_id)
            .order_by(Conversation.updated_at.desc())
            .limit(50)
        ).all()
    )


@router.get("/conversations/{conv_id}/messages", response_model=list[MessageOut])
def list_messages(
    conv_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[Message]:
    conv = db.get(Conversation, conv_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status_code=404, detail="会话不存在")
    return list(db.scalars(select(Message).where(Message.conversation_id == conv_id).order_by(Message.id)).all())


@router.delete("/conversations/{conv_id}", status_code=204)
def delete_conversation(
    conv_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> None:
    conv = db.get(Conversation, conv_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status_code=404, detail="会话不存在")
    db.delete(conv)
    db.commit()
    return None


@router.post("/feedback", status_code=201)
def submit_feedback(
    payload: FeedbackIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    msg = db.get(Message, payload.message_id)
    if msg is None:
        raise HTTPException(status_code=404, detail="消息不存在")
    conv = db.get(Conversation, msg.conversation_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权评价该消息")
    db.add(Feedback(message_id=msg.id, rating=payload.rating, comment=payload.comment))
    db.commit()
    return {"ok": True}
