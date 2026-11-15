import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import auth, chat, documents, kb
from .core.config import settings
from .db import init_db
from .schemas import HealthOut

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logging.getLogger(__name__).info(
        "启动完成 | db=%s | embed=%s | llm=%s",
        "postgresql" if settings.is_postgres else "sqlite",
        settings.embed_provider,
        settings.llm_provider,
    )
    yield


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description=(
        "私有文档知识库问答服务：文档入库 → 混合检索 → 流式问答并标注引用来源。\n\n"
        "认证方式：先调用 /api/auth/login 获取 access_token，再点右上角 Authorize 填入。"
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    # 允许任意本机端口（Vite 换端口、调试页面等），其余来源一律拒绝。
    allow_origin_regex=(
        r"^https?://(localhost|127\.0\.0\.1|tauri\.localhost)(:\d+)?$"
        r"|^tauri://localhost$|^null$"
    ),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in (auth, kb, documents, chat):
    app.include_router(module.router, prefix=settings.api_prefix)


@app.get("/health", response_model=HealthOut, tags=["系统"])
def health() -> HealthOut:
    return HealthOut(
        status="ok",
        database="postgresql" if settings.is_postgres else "sqlite",
        embed_provider=settings.embed_provider,
        llm_provider=settings.llm_provider,
    )
