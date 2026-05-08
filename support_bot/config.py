import os
from dataclasses import dataclass
from pathlib import Path


def parse_int_set(raw: str) -> set[int]:
    result: set[int] = set()
    for item in raw.split(","):
        item = item.strip()
        if item.isdigit():
            result.add(int(item))
    return result


def optional_int(raw: str | None) -> int | None:
    if not raw:
        return None
    raw = raw.strip()
    return int(raw) if raw.isdigit() else None


@dataclass(slots=True)
class Settings:
    bot_token: str
    moderators: set[int]
    db_path: Path
    uploads_dir: Path
    support_title: str
    public_base_url: str | None
    webhook_path: str
    webhook_secret: str | None
    host: str
    port: int
    run_mode: str
    max_download_mb: int
    webapp_dev_user_id: int | None

    @classmethod
    def from_env(cls) -> "Settings":
        token = os.getenv("BOT_TOKEN", "").strip()
        if not token:
            raise RuntimeError("BOT_TOKEN не задан. Скопируйте .env.example в .env и заполните токен.")

        run_mode = os.getenv("RUN_MODE", "polling").strip().lower()
        if run_mode not in {"polling", "webhook"}:
            raise RuntimeError("RUN_MODE должен быть polling или webhook.")

        public_base_url = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/") or None
        webhook_path = os.getenv("WEBHOOK_PATH", "/telegram/webhook").strip()
        if not webhook_path.startswith("/"):
            webhook_path = "/" + webhook_path

        return cls(
            bot_token=token,
            moderators=parse_int_set(os.getenv("MODERATORS", "")),
            db_path=Path(os.getenv("DB_PATH", "data/support.db")),
            uploads_dir=Path(os.getenv("UPLOADS_DIR", "data/uploads")),
            support_title=os.getenv("SUPPORT_TITLE", "Поддержка").strip() or "Поддержка",
            public_base_url=public_base_url,
            webhook_path=webhook_path,
            webhook_secret=os.getenv("WEBHOOK_SECRET", "").strip() or None,
            host=os.getenv("HOST", "0.0.0.0"),
            port=int(os.getenv("PORT", "8080")),
            run_mode=run_mode,
            max_download_mb=int(os.getenv("MAX_DOWNLOAD_MB", "20")),
            webapp_dev_user_id=optional_int(os.getenv("WEBAPP_DEV_USER_ID")),
        )

    @property
    def webhook_url(self) -> str:
        if not self.public_base_url:
            raise RuntimeError("PUBLIC_BASE_URL нужен для webhook-режима.")
        return f"{self.public_base_url}{self.webhook_path}"
