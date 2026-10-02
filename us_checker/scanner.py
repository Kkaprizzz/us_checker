"""Генерация в отдельном потоке + параллельные воркеры проверки."""
import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from us_checker.checker import RateLimited, Status, TmeChecker
from us_checker.config import Config
from us_checker.gen import Candidate, NameEngine
from us_checker.gen.quality import score as name_score
from us_checker.storage import Storage

log = logging.getLogger(__name__)

# Заведомо занятый юз: если он вдруг «свободен», значит t.me поменял вёрстку
CANARY = "durov"
CANARY_EVERY = 500
QUEUE_LOW = 100
GEN_BATCH = 60

OnFound = Callable[[Candidate], Awaitable[None]]


class RateLimiter:
    """Общий лимит запросов в секунду на всех воркеров + общая пауза после 429."""

    def __init__(self, rps: float):
        self.interval = 1.0 / rps if rps > 0 else 0.0
        self._next = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            delay = self._next - now
            self._next = max(now, self._next) + self.interval
        if delay > 0:
            await asyncio.sleep(delay)

    def backoff(self, seconds: float) -> None:
        self._next = max(self._next, time.monotonic() + seconds)


class Scanner:
    def __init__(
        self,
        cfg: Config,
        storage: Storage,
        checker: TmeChecker,
        on_found: OnFound,
        engine: NameEngine | None = None,
    ):
        self.cfg = cfg
        self.storage = storage
        self.checker = checker
        self.on_found = on_found
        self.engine = engine or NameEngine(cfg.min_len, cfg.max_len, only=cfg.strategies)
        self.limiter = RateLimiter(cfg.rps)
        self.queue: asyncio.Queue[Candidate] = asyncio.Queue()
        self.running = asyncio.Event()
        self.checked = 0
        self.found = 0
        self.started_at = 0.0
        self.last_error: str | None = None
        self._tasks: list[asyncio.Task] = []
        self._ready = False
        self._prepare_lock = asyncio.Lock()

    # --- управление ---

    def start(self) -> None:
        self.running.set()
        if not self._tasks:
            self.started_at = time.monotonic()
            self._tasks = [asyncio.create_task(self._producer())]
            self._tasks += [
                asyncio.create_task(self._worker(i)) for i in range(self.cfg.workers)
            ]

    def pause(self) -> None:
        self.running.clear()

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []

    @property
    def rate(self) -> float:
        elapsed = time.monotonic() - self.started_at if self.started_at else 0
        return self.checked / elapsed * 60 if elapsed > 0 else 0.0

    async def prepare(self) -> None:
        """Прогрев генератора (в потоке) и загрузка уже проверенных юзов."""
        async with self._prepare_lock:
            if self._ready:
                return
            await asyncio.to_thread(self.engine.warmup)
            self.engine.seen |= await self.storage.all_usernames()
            self._ready = True

    async def preview(self, n: int) -> list[Candidate]:
        await self.prepare()
        return await asyncio.to_thread(self.engine.batch, n)

    # --- внутренности ---

    async def _producer(self) -> None:
        await self.prepare()
        last_canary = -CANARY_EVERY
        while True:
            await self.running.wait()
            if self.checked - last_canary >= CANARY_EVERY:
                last_canary = self.checked
                await self._canary()
                continue
            for w in await self.storage.pop_extra_words():
                # Свои слова из /add — вне очереди
                self.engine.seen.add(w)
                await self._put_front(Candidate(w, "custom", name_score(w)))
            if self.queue.qsize() < QUEUE_LOW:
                # Генерация тяжёлая — в отдельном потоке, чтобы не тормозить бота
                for cand in await asyncio.to_thread(self.engine.batch, GEN_BATCH):
                    await self.queue.put(cand)
            else:
                await asyncio.sleep(1)

    async def _put_front(self, cand: Candidate) -> None:
        rest = []
        while not self.queue.empty():
            rest.append(self.queue.get_nowait())
        await self.queue.put(cand)
        for c in rest:
            await self.queue.put(c)

    async def _worker(self, idx: int) -> None:
        while True:
            await self.running.wait()
            cand = await self.queue.get()
            status = await self._check(cand.name)
            self.checked += 1
            if status == Status.ERROR:
                continue
            if await self.storage.save_check(cand.name, status.value, cand.score, cand.source):
                self.found += 1
                await self.on_found(cand)

    async def _check(self, name: str) -> Status:
        for _ in range(5):
            await self.limiter.wait()
            try:
                return await self.checker.check(name)
            except RateLimited as e:
                log.warning("429 от t.me, все воркеры ждут %.0fс", e.retry_after)
                self.limiter.backoff(e.retry_after)
        return Status.ERROR

    async def _canary(self) -> None:
        if await self._check(CANARY) == Status.FREE:
            self.last_error = (
                f"@{CANARY} определился как свободный — t.me поменял вёрстку "
                "или блокирует запросы. Сканер на паузе."
            )
            log.error(self.last_error)
            self.pause()
        else:
            self.last_error = None
