"""Фоновый перебор кандидатов."""
import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from us_checker.checker import RateLimited, Status, TmeChecker
from us_checker.config import Config
from us_checker.storage import Storage
from us_checker.wordlist import Candidate, build_candidates

log = logging.getLogger(__name__)

# Заведомо занятый юз: если он вдруг «свободен», значит t.me поменял вёрстку
CANARY = "durov"
PASS_PAUSE = 600  # пауза между полными проходами, сек

OnFound = Callable[[Candidate], Awaitable[None]]


class Scanner:
    def __init__(self, cfg: Config, storage: Storage, checker: TmeChecker, on_found: OnFound):
        self.cfg = cfg
        self.storage = storage
        self.checker = checker
        self.on_found = on_found
        self.running = asyncio.Event()
        self.position = 0
        self.total = 0
        self.current: str | None = None
        self.last_error: str | None = None
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self.running.set()
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    def pause(self) -> None:
        self.running.clear()

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def canary_ok(self) -> bool:
        try:
            return await self.checker.check(CANARY) == Status.TAKEN
        except RateLimited:
            return True

    async def check_one(self, cand: Candidate) -> Status:
        """Проверяет кандидата с ретраями на 429 и сохраняет результат."""
        while True:
            try:
                status = await self.checker.check(cand.name)
                break
            except RateLimited as e:
                log.warning("429 от t.me, ждём %.0fс", e.retry_after)
                await asyncio.sleep(e.retry_after)
        if status != Status.ERROR:
            if await self.storage.save_check(cand.name, status.value, cand.score):
                await self.on_found(cand)
        return status

    async def _loop(self) -> None:
        while True:
            await self.running.wait()
            if not await self.canary_ok():
                self.last_error = (
                    f"@{CANARY} определился как свободный — t.me поменял вёрстку "
                    "или блокирует запросы. Сканер на паузе."
                )
                log.error(self.last_error)
                self.pause()
                continue
            self.last_error = None
            await self._pass()
            await asyncio.sleep(PASS_PAUSE)

    async def _pass(self) -> None:
        cands = build_candidates(
            self.cfg.min_len,
            self.cfg.max_len,
            self.cfg.sources,
            self.cfg.wordfreq_top,
            extra=await self.storage.extra_words(),
        )
        self.total = len(cands)
        recheck_after = self.cfg.recheck_days * 86400
        errors_in_row = 0
        for i, cand in enumerate(cands):
            self.position = i
            await self.running.wait()
            prev = await self.storage.get_status(cand.name)
            if prev and prev[0] == "invalid":
                continue  # ты отметил его через /bad — больше не трогаем
            if prev and prev[0] != "error" and time.time() - prev[1] < recheck_after:
                continue
            self.current = cand.name
            status = await self.check_one(cand)
            errors_in_row = errors_in_row + 1 if status == Status.ERROR else 0
            if errors_in_row >= 10:
                log.warning("10 ошибок подряд, пауза 5 минут")
                await asyncio.sleep(300)
                errors_in_row = 0
            await asyncio.sleep(self.cfg.check_delay)
        self.position = self.total
        self.current = None
