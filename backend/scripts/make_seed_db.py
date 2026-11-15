"""生成安装包用的空白 SQLite 数据库（只建表，不含任何用户/文档/会话数据）。

安装包绝不能携带开发机 backend/data/app.db —— 那里面可能有账号密码哈希、
上传的原始文档和聊天记录。打包脚本改为调用本脚本生成一份干净的空库。

用法：
    .venv/Scripts/python.exe scripts/make_seed_db.py
    .venv/Scripts/python.exe scripts/make_seed_db.py <输出路径>

默认输出到 src-tauri/nsis/seed/app.db（该路径被 .gitignore 的 *.db 忽略）。
"""

import sqlite3
import sys
from pathlib import Path

from sqlalchemy import create_engine

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.models import Base  # noqa: E402  注册全部 ORM 模型

DEFAULT_OUT = BACKEND.parent / "src-tauri" / "nsis" / "seed" / "app.db"


def main() -> int:
    out = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else DEFAULT_OUT.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()

    engine = create_engine(f"sqlite:///{out.as_posix()}")
    try:
        Base.metadata.create_all(engine)
    finally:
        engine.dispose()

    con = sqlite3.connect(out)
    try:
        tables = [
            row[0]
            for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
        ]
        rows = sum(
            con.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
            for table in tables
        )
    finally:
        con.close()

    # 只打印文件名，避免中文路径在 Windows 控制台里出现编码乱码
    print(f"seed db: {out.name} (clean)")
    print(f"tables={len(tables)} rows={rows}")
    if not tables or rows != 0:
        print("[ERROR] 空库校验失败：表缺失或包含数据")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
