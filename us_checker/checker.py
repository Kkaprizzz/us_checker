"""Проверка юза через публичную страницу t.me/<username>."""
import asyncio
import enum
import re

import aiohttp


class Status(str, enum.Enum):
    FREE = "free"    # страница пустая: юз никому не принадлежит (вероятно свободен)
    TAKEN = "taken"  # есть пользователь / канал / группа / бот
    ERROR = "error"


_TITLE_RE = re.compile(r'class="tgme_page_title"')
_OG_TITLE_RE = re.compile(r'<meta property="og:title" content="([^"]*)"')

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def parse_page(username: str, html: str) -> Status:
    """У занятого юза на странице есть заголовок с именем.
    У свободного — заглушка «Telegram: Contact @username» без заголовка."""
    if _TITLE_RE.search(html):
        return Status.TAKEN
    m = _OG_TITLE_RE.search(html)
    if m and m.group(1).strip().lower() != f"telegram: contact @{username}".lower():
        return Status.TAKEN
    return Status.FREE


class RateLimited(Exception):
    def __init__(self, retry_after: float):
        super().__init__(f"rate limited, retry after {retry_after}s")
        self.retry_after = retry_after


class TmeChecker:
    def __init__(self, session: aiohttp.ClientSession, timeout: float = 15):
        self._session = session
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    async def check(self, username: str) -> Status:
        url = f"https://t.me/{username}"
        try:
            async with self._session.get(
                url, headers=HEADERS, timeout=self._timeout, allow_redirects=True
            ) as resp:
                if resp.status == 429:
                    raise RateLimited(float(resp.headers.get("Retry-After", 60)))
                if resp.status != 200:
                    return Status.ERROR
                html = await resp.text()
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return Status.ERROR
        return parse_page(username, html)
