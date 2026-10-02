import time

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS checks (
    username   TEXT PRIMARY KEY,
    status     TEXT NOT NULL,
    score      REAL NOT NULL DEFAULT 0,
    checked_at INTEGER NOT NULL,
    found_at   INTEGER,
    source     TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS subscribers (
    chat_id INTEGER PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS extra_words (
    word TEXT PRIMARY KEY
);
"""


class Storage:
    def __init__(self, path: str):
        self._path = path
        self._db: aiosqlite.Connection | None = None

    async def open(self) -> None:
        self._db = await aiosqlite.connect(self._path)
        await self._db.executescript(SCHEMA)
        # База от старой версии без колонки source
        async with self._db.execute("PRAGMA table_info(checks)") as cur:
            cols = {r[1] for r in await cur.fetchall()}
        if "source" not in cols:
            await self._db.execute("ALTER TABLE checks ADD COLUMN source TEXT NOT NULL DEFAULT ''")
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()

    @property
    def db(self) -> aiosqlite.Connection:
        assert self._db is not None, "Storage.open() не вызван"
        return self._db

    async def get_status(self, username: str) -> tuple[str, int] | None:
        async with self.db.execute(
            "SELECT status, checked_at FROM checks WHERE username = ?", (username,)
        ) as cur:
            row = await cur.fetchone()
        return (row[0], row[1]) if row else None

    async def all_usernames(self) -> set[str]:
        async with self.db.execute("SELECT username FROM checks WHERE status != 'error'") as cur:
            return {r[0] for r in await cur.fetchall()}

    async def save_check(self, username: str, status: str, score: float, source: str = "") -> bool:
        """Сохраняет результат. True, если юз только что стал свободным."""
        prev = await self.get_status(username)
        if prev and prev[0] == "invalid":
            return False  # отмечен через /bad — не воскрешаем
        newly_free = status == "free" and (prev is None or prev[0] != "free")
        now = int(time.time())
        await self.db.execute(
            """
            INSERT INTO checks (username, status, score, checked_at, found_at, source)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(username) DO UPDATE SET
                status = excluded.status,
                score = excluded.score,
                checked_at = excluded.checked_at,
                source = CASE WHEN excluded.source != '' THEN excluded.source ELSE checks.source END,
                found_at = CASE WHEN ? THEN excluded.found_at
                                WHEN excluded.status = 'free' THEN checks.found_at
                                ELSE NULL END
            """,
            (username, status, score, now, now if newly_free else None, source, newly_free),
        )
        await self.db.commit()
        return newly_free

    async def mark_invalid(self, usernames: list[str]) -> None:
        now = int(time.time())
        await self.db.executemany(
            """
            INSERT INTO checks (username, status, checked_at) VALUES (?, 'invalid', ?)
            ON CONFLICT(username) DO UPDATE SET status = 'invalid', found_at = NULL
            """,
            [(u, now) for u in usernames],
        )
        await self.db.commit()

    async def list_free(self, limit: int = 30) -> list[tuple[str, float]]:
        async with self.db.execute(
            "SELECT username, score FROM checks WHERE status = 'free' "
            "ORDER BY found_at DESC, score DESC LIMIT ?",
            (limit,),
        ) as cur:
            return [(r[0], r[1]) for r in await cur.fetchall()]

    async def counts(self) -> dict[str, int]:
        async with self.db.execute(
            "SELECT status, COUNT(*) FROM checks GROUP BY status"
        ) as cur:
            return {r[0]: r[1] for r in await cur.fetchall()}

    async def stats_by_source(self) -> list[tuple[str, int, int, int]]:
        """(источник, проверено, свободных, отмечено /bad)."""
        async with self.db.execute(
            "SELECT source, COUNT(*), SUM(status = 'free'), SUM(status = 'invalid') "
            "FROM checks WHERE source != '' GROUP BY source ORDER BY 3 DESC, 2 DESC"
        ) as cur:
            return [(r[0], r[1], r[2] or 0, r[3] or 0) for r in await cur.fetchall()]

    async def add_subscriber(self, chat_id: int) -> None:
        await self.db.execute("INSERT OR IGNORE INTO subscribers VALUES (?)", (chat_id,))
        await self.db.commit()

    async def remove_subscriber(self, chat_id: int) -> None:
        await self.db.execute("DELETE FROM subscribers WHERE chat_id = ?", (chat_id,))
        await self.db.commit()

    async def subscribers(self) -> list[int]:
        async with self.db.execute("SELECT chat_id FROM subscribers") as cur:
            return [r[0] for r in await cur.fetchall()]

    async def add_words(self, words: list[str]) -> None:
        await self.db.executemany(
            "INSERT OR IGNORE INTO extra_words VALUES (?)", [(w,) for w in words]
        )
        await self.db.commit()

    async def pop_extra_words(self) -> list[str]:
        async with self.db.execute("SELECT word FROM extra_words") as cur:
            words = [r[0] for r in await cur.fetchall()]
        await self.db.execute("DELETE FROM extra_words")
        await self.db.commit()
        return words
