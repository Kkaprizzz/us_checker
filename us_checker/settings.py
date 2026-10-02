"""Настройки, которые меняются прямо из бота и хранятся в базе."""
import json
from dataclasses import asdict, dataclass, field

from us_checker.config import Config

MIN_LEN_FLOOR = 5   # Telegram не даёт занять короче
MAX_LEN_CEIL = 16   # длиннее — уже не «короткий юз»
WORKERS_MAX = 16
RPS_STEPS = (0.5, 1, 2, 3, 4, 5, 7, 10, 15, 20)


@dataclass
class Settings:
    min_len: int = 5
    max_len: int = 9
    workers: int = 4
    rps: float = 3.0
    disabled: set[str] = field(default_factory=set)

    @classmethod
    def from_config(cls, cfg: Config, all_keys: list[str]) -> "Settings":
        disabled = set()
        if cfg.strategies:
            disabled = {k for k in all_keys if not k.startswith(cfg.strategies)}
        return cls(cfg.min_len, cfg.max_len, cfg.workers, cfg.rps, disabled)

    def to_json(self) -> str:
        d = asdict(self)
        d["disabled"] = sorted(self.disabled)
        return json.dumps(d)

    @classmethod
    def from_json(cls, raw: str) -> "Settings":
        d = json.loads(raw)
        d["disabled"] = set(d.get("disabled", []))
        known = cls.__dataclass_fields__
        return cls(**{k: v for k, v in d.items() if k in known})

    # --- изменения с проверкой границ ---

    def shift_min(self, delta: int) -> None:
        self.min_len = max(MIN_LEN_FLOOR, min(self.max_len, self.min_len + delta))

    def shift_max(self, delta: int) -> None:
        self.max_len = max(self.min_len, min(MAX_LEN_CEIL, self.max_len + delta))

    def shift_workers(self, delta: int) -> None:
        self.workers = max(1, min(WORKERS_MAX, self.workers + delta))

    def shift_rps(self, delta: int) -> None:
        # Ближайшая ступень к текущему значению, потом шаг
        i = min(range(len(RPS_STEPS)), key=lambda j: abs(RPS_STEPS[j] - self.rps))
        self.rps = float(RPS_STEPS[max(0, min(len(RPS_STEPS) - 1, i + delta))])

    def toggle(self, key: str, all_keys: list[str]) -> bool:
        """Вкл/выкл стратегию. False, если это была последняя включённая."""
        if key in self.disabled:
            self.disabled.discard(key)
            return True
        if len(set(all_keys) - self.disabled) <= 1:
            return False
        self.disabled.add(key)
        return True

    def set_group(self, keys: list[str], on: bool, all_keys: list[str]) -> bool:
        if on:
            self.disabled -= set(keys)
            return True
        if not set(all_keys) - self.disabled - set(keys):
            return False
        self.disabled |= set(keys)
        return True

    def enabled(self, all_keys: list[str]) -> set[str]:
        return set(all_keys) - self.disabled
