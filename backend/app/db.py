from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .core.config import BASE_DIR, settings


def _resolve_url(url: str) -> str:
    """SQLite 的相对路径按 backend/ 解析，避免受启动目录影响。"""
    prefix = "sqlite:///"
    if url.startswith(prefix) and not url.startswith("sqlite:////") and not url.startswith("sqlite:///C:"):
        raw = url[len(prefix):]
        if raw.startswith("./"):
            raw = raw[2:]
        p = Path(raw)
        if not p.is_absolute():
            p = BASE_DIR / p
        p.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{p.as_posix()}"
    return url


DATABASE_URL = _resolve_url(settings.database_url)
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=_connect_args, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from . import models  # noqa: F401  确保模型已注册

    if DATABASE_URL.startswith("postgresql"):
        with engine.begin() as conn:
            conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
            conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    Base.metadata.create_all(engine)

    if DATABASE_URL.startswith("postgresql"):
        with engine.begin() as conn:
            # HNSW 近似最近邻索引：查询从 O(N) 降到 O(logN)
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw "
                "ON chunks USING hnsw (embedding vector_cosine_ops)"
            )
            # 关键词检索索引（中文需 zhparser，这里用 trigram 兜底）
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS idx_chunks_content_trgm ON chunks USING gin (content gin_trgm_ops)"
            )

    settings.upload_dir.mkdir(parents=True, exist_ok=True)
