import asyncio
from collections import Counter

import pytest

from us_checker.checker import Status, parse_page
from us_checker.filters import is_clean
from us_checker.gen import Candidate, NameEngine
from us_checker.gen.lexicon import is_real, looks_like_typo
from us_checker.gen.quality import is_ugly
from us_checker.storage import Storage

TAKEN_HTML = """
<meta property="og:title" content="Pavel Durov">
<div class="tgme_page_title" dir="auto"><span dir="auto">Pavel Durov</span></div>
"""
FREE_HTML = """
<title>Telegram: Contact @zqxwvbn</title>
<meta property="og:title" content="Telegram: Contact @zqxwvbn">
<div class="tgme_page_description">If you have <strong>Telegram</strong>, you can contact
<a class="tgme_username_link" href="tg://resolve?domain=zqxwvbn">@zqxwvbn</a> right away.</div>
"""


def test_parse_taken():
    assert parse_page("durov", TAKEN_HTML) == Status.TAKEN


def test_parse_free():
    assert parse_page("zqxwvbn", FREE_HTML) == Status.FREE


@pytest.mark.parametrize("name,ok", [
    ("velora", True),
    ("boss", False),
    ("velora1", False),
    ("vel_ora", False),
    ("Velora", False),
    ("superbot", False),
])
def test_is_clean(name, ok):
    assert is_clean(name, 5, 8) is ok


def test_filters():
    assert is_real("money") and is_real("darkness") and is_real("amore")
    assert not is_real("godeless")
    assert looks_like_typo("proping") and looks_like_typo("breated")
    assert not looks_like_typo("velora")
    assert is_ugly("xkqzt") and is_ugly("hazeess")
    assert not is_ugly("lumora")


@pytest.fixture(scope="module")
def engine():
    e = NameEngine(seed=42)
    e.warmup()
    return e


@pytest.fixture(scope="module")
def sample(engine):
    return engine.batch(300)


def test_batch_is_clean_new_and_unique(sample):
    names = [c.name for c in sample]
    assert len(sample) == 300
    assert len(set(names)) == len(names)
    assert all(is_clean(n, 5, 9) for n in names)
    assert not any(is_real(n) for n in names)


def test_batch_is_diverse(sample):
    # Много разных стратегий, ни одна не забивает выдачу
    sources = Counter(c.source for c in sample)
    assert len(sources) >= 15
    assert max(sources.values()) / len(sample) < 0.15
    # Нет засилья одних и тех же окончаний
    ends = Counter(c.name[-3:] for c in sample)
    assert max(ends.values()) / len(sample) < 0.06
    # И длины разные
    assert len({len(c.name) for c in sample}) >= 4


def test_only_filter():
    e = NameEngine(only=("syll_dark", "classical"), seed=1)
    assert {s.key for s, _ in e.strategies} == {"syll_dark", "classical"}
    with pytest.raises(ValueError):
        NameEngine(only=("nope",))


@pytest.mark.asyncio
async def test_storage_newly_free_and_invalid(tmp_path):
    st = Storage(str(tmp_path / "t.db"))
    await st.open()
    assert await st.save_check("velora", "free", 3.0, "classical") is True
    assert await st.save_check("velora", "free", 3.0) is False
    assert await st.save_check("velora", "taken", 3.0) is False
    assert await st.save_check("velora", "free", 3.0) is True
    assert await st.list_free() == [("velora", 3.0)]
    await st.mark_invalid(["velora"])
    assert await st.list_free() == []
    assert await st.save_check("velora", "free", 3.0) is False  # /bad не воскрешаем
    assert await st.stats_by_source() == [("classical", 1, 0, 1)]
    await st.close()


@pytest.mark.asyncio
async def test_scanner_parallel_workers(tmp_path):
    from us_checker.config import Config
    from us_checker.scanner import Scanner

    in_flight = 0
    peak = 0

    class FakeChecker:
        async def check(self, name):
            nonlocal in_flight, peak
            in_flight += 1
            peak = max(peak, in_flight)
            await asyncio.sleep(0.01)
            in_flight -= 1
            if name == "durov":
                return Status.TAKEN
            return Status.FREE if name.startswith("v") else Status.TAKEN

    class FakeEngine:
        seen: set[str] = set()

        def warmup(self):
            pass

        def batch(self, n):
            names = ["velora", "kushon", "vyzern", "lumora", "veskog", "druzos"]
            out = [Candidate(x, "test", 1.0) for x in names if x not in self.seen]
            self.seen.update(names)
            return out

    found = []

    async def on_found(c):
        found.append(c.name)

    st = Storage(str(tmp_path / "s.db"))
    await st.open()
    await st.add_words(["vandrel"])
    cfg = Config(bot_token="x", workers=4, rps=0)
    sc = Scanner(cfg, st, FakeChecker(), on_found, engine=FakeEngine())
    sc.start()
    for _ in range(200):
        await asyncio.sleep(0.01)
        if sc.checked >= 8:
            break
    await sc.stop()
    assert sorted(found) == ["vandrel", "velora", "veskog", "vyzern"]
    assert peak > 1  # проверки реально шли параллельно
    await st.close()


@pytest.mark.asyncio
async def test_rate_limiter_spacing():
    import time

    from us_checker.scanner import RateLimiter

    rl = RateLimiter(rps=50)
    t = time.monotonic()
    await asyncio.gather(*(rl.wait() for _ in range(6)))
    assert time.monotonic() - t >= 0.09  # 5 интервалов по 20 мс
