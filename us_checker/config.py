import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    """Минимальный загрузчик .env, чтобы не тащить лишнюю зависимость."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Config:
    bot_token: str
    admin_ids: frozenset[int] = field(default_factory=frozenset)
    min_len: int = 5
    max_len: int = 9
    check_delay: float = 1.5
    recheck_days: int = 7
    sources: tuple[str, ...] = ("styled",)
    wordfreq_top: int = 60000
    db_path: str = "us_checker.db"


def load_config() -> Config:
    _load_dotenv(Path.cwd() / ".env")
    token = os.environ.get("BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("BOT_TOKEN не задан. Скопируй .env.example в .env и впиши токен.")
    admin_ids = frozenset(
        int(x) for x in os.environ.get("ADMIN_IDS", "").replace(" ", "").split(",") if x
    )
    return Config(
        bot_token=token,
        admin_ids=admin_ids,
        # Telegram не даёт занять юз короче 5 символов
        min_len=max(5, int(os.environ.get("MIN_LEN", 5))),
        max_len=min(32, int(os.environ.get("MAX_LEN", 9))),
        check_delay=float(os.environ.get("CHECK_DELAY", 1.5)),
        recheck_days=int(os.environ.get("RECHECK_DAYS", 7)),
        sources=tuple(
            x for x in os.environ.get("SOURCES", "styled").replace(" ", "").lower().split(",") if x
        ),
        wordfreq_top=int(os.environ.get("WORDFREQ_TOP", 60000)),
        db_path=os.environ.get("DB_PATH", "us_checker.db"),
    )
