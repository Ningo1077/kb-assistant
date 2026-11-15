"""切换 embedding 模型后，重建全部文档的向量索引。

换 provider / 换模型 / 改 EMBED_DIM 之后，旧的 chunks 向量与查询向量语义、维度
都不兼容（SQLite 下 numpy 会直接报形状不匹配），必须重建。脚本直接调用入库管线，
不经过 HTTP 接口，因此不需要登录 token，也能处理属于其它用户的文档。

用法（任选一个 backend 根目录，cwd 会切换到它，决定使用哪份 app.db 与 .env）：

    .venv/Scripts/python.exe scripts/reindex_all.py
    .venv/Scripts/python.exe scripts/reindex_all.py "<已安装版 backend 目录>"

执行前请确保本地模型服务（Ollama 等）已启动，且目标 backend/.env 已切好配置。
"""

import os
import sys
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else DEFAULT_ROOT
    if not (root / "app" / "main.py").exists():
        print(f"错误：{root} 不是有效的 backend 目录")
        return 2

    os.chdir(root)
    sys.path.insert(0, str(root))

    from sqlalchemy import select  # noqa: E402

    from app.core.config import settings  # noqa: E402
    from app.db import SessionLocal  # noqa: E402
    from app.models import Document  # noqa: E402
    from app.services.ingest import ingest_document  # noqa: E402

    print(f"backend : {root}")
    print(f"配置    : EMBED_PROVIDER={settings.embed_provider} "
          f"EMBED_MODEL={settings.embed_model} EMBED_DIM={settings.embed_dim}")
    print(f"数据库  : {settings.database_url}")
    print(f"LLM     : {settings.llm_provider} / {settings.llm_model} @ {settings.llm_base_url}")

    db = SessionLocal()
    docs = list(db.scalars(select(Document).order_by(Document.id)).all())
    print(f"待重建文档: {len(docs)}")

    # 环境迁移后，历史文档的 storage_path 可能仍指向旧机器的绝对路径。
    # 在当前 backend/data/uploads 下按同名文件自愈；文件本来就在，只是路径过期。
    upload_root = (root / "data" / "uploads").resolve()
    fixed = 0
    for doc in docs:
        raw = doc.storage_path or ""
        if raw and Path(raw).is_file():
            continue
        candidate = upload_root / Path(raw).name
        if candidate.is_file():
            doc.storage_path = str(candidate)
            fixed += 1
            print(f"  [修复路径] doc={doc.id} -> {candidate}")
        else:
            print(f"  [警告] doc={doc.id} 源文件缺失: {raw or '(空)'}；"
                  "其旧向量可能与新维度不兼容，建议手动删除该文档")
    if fixed:
        db.commit()
        print(f"已修正 {fixed} 个文档路径")
    ids = [d.id for d in docs]
    db.close()

    ok = fail = 0
    for doc_id in ids:
        ingest_document(doc_id)
        db = SessionLocal()
        fresh = db.get(Document, doc_id)
        status, err, chunks, filename = (
            fresh.status, fresh.error_msg, fresh.chunk_count, fresh.filename
        )
        db.close()
        if status == "ready":
            ok += 1
            print(f"  [OK]   doc={doc_id} chunks={chunks} {filename}")
        else:
            fail += 1
            print(f"  [FAIL] doc={doc_id} status={status} {filename} :: {err}")

    print(f"完成: {ok} 成功 / {fail} 失败")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
