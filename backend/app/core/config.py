import secrets
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]

# 这些示例值一旦进生产，任何人都能伪造 JWT；检测到就自动换成本机随机密钥。
_WEAK_SECRETS = {
    "",
    "dev-secret-change-me",
    "dev-only-secret-please-change-me",
    "changeme",
    "secret",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Knowledge Assistant API"
    api_prefix: str = "/api"

    database_url: str = f"sqlite:///{(BASE_DIR / 'data' / 'app.db').as_posix()}"
    upload_dir: Path = BASE_DIR / "data" / "uploads"

    # 留空即自动生成并持久化到 data/secret.key（已加入 .gitignore）。
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7

    # 逗号分隔；桌面端与 Vite 开发服务器默认允许，其余来源一律拒绝。
    cors_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "tauri://localhost,http://tauri.localhost"
    )

    embed_provider: str = "hashing"
    embed_dim: int = 512
    embed_model: str = "bge-m3"

    llm_provider: str = "mock"
    llm_model: str = "qwen2.5:7b"
    llm_base_url: str = "http://localhost:11434"
    llm_api_key: str = ""

    chunk_size: int = 800
    chunk_overlap: int = 120
    retrieve_top_k: int = 5
    retrieve_recall_k: int = 20
    max_context_chars: int = 6000

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgresql")

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


def _resolve_jwt_secret(raw: str) -> str:
    """显式配置优先；示例值/空值替换为每台机器独立的随机密钥。"""
    if raw not in _WEAK_SECRETS:
        return raw

    path = BASE_DIR / "data" / "secret.key"
    if path.is_file():
        saved = path.read_text(encoding="utf-8").strip()
        if saved:
            return saved

    generated = secrets.token_urlsafe(48)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(generated, encoding="utf-8")
    return generated


@lru_cache
def get_settings() -> Settings:
    cfg = Settings()
    cfg.jwt_secret = _resolve_jwt_secret(cfg.jwt_secret)
    return cfg


settings = get_settings()
