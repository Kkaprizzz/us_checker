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


def _csv(name: str) -> tuple[str, ...]:
    return tuple(x for x in os.environ.get(name, "").replace(" ", "").lower().split(",") if x)


@dataclass(frozen=True)
class Config:
    bot_token: str
    admin_ids: frozenset[int] = field(default_factory=frozenset)
    min_len: int = 5
    max_len: int = 9
    workers: int = 4
    rps: float = 3.0
    strategies: tuple[str, ...] = ()
    db_path: str = "us_checker.db"


def load_config() -> Config:
    _load_dotenv(Path.cwd() / ".env")
    token = os.environ.get("BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("BOT_TOKEN не задан. Скопируй .env.example в .env и впиши токен.")
    return Config(
        bot_token=token,
        admin_ids=frozenset(int(x) for x in _csv("ADMIN_IDS")),
        # Telegram не даёт занять юз короче 5 символов
        min_len=max(5, int(os.environ.get("MIN_LEN", 5))),
        max_len=min(32, int(os.environ.get("MAX_LEN", 9))),
        workers=max(1, int(os.environ.get("WORKERS", 4))),
        rps=float(os.environ.get("RPS", 3)),
        strategies=_csv("STRATEGIES"),
        db_path=os.environ.get("DB_PATH", "us_checker.db"),
    )
