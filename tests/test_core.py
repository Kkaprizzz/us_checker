import pytest

from us_checker.checker import Status, parse_page
from us_checker.filters import is_clean
from us_checker.storage import Storage
from us_checker.wordlist import build_candidates

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
    ("money", True),
    ("boss", False),        # короче 5
    ("money1", False),
    ("mon_ey", False),
    ("Money", False),
    ("superbot", False),    # окончание bot только для ботов
    ("verylongname", False),
])
def test_is_clean(name, ok):
    assert is_clean(name, 5, 8) is ok


def test_candidates_are_clean_and_ranked():
    cands = build_candidates(5, 7, wordfreq_top=20000)
    names = [c.name for c in cands]
    assert len(names) == len(set(names))
    assert all(is_clean(n, 5, 7) for n in names)
    assert names.index("money") < names.index("between") if "between" in names else True
    assert "weeks" not in names  # множественное число отсекается
    assert cands[0].source == "premium"


@pytest.mark.asyncio
async def test_storage_newly_free(tmp_path):
    st = Storage(str(tmp_path / "t.db"))
    await st.open()
    assert await st.save_check("money", "free", 9.0) is True
    assert await st.save_check("money", "free", 9.0) is False
    assert await st.save_check("money", "taken", 9.0) is False
    assert await st.save_check("money", "free", 9.0) is True
    assert await st.list_free() == [("money", 9.0)]
    await st.close()


@pytest.mark.asyncio
async def test_scanner_pass_notifies_free(tmp_path):
    from us_checker.config import Config
    from us_checker.scanner import Scanner

    class FakeChecker:
        async def check(self, name):
            return Status.FREE if name in ("bratva", "zoloto") else Status.TAKEN

    found = []

    async def on_found(c):
        found.append(c.name)

    st = Storage(str(tmp_path / "s.db"))
    await st.open()
    cfg = Config(bot_token="x", check_delay=0, wordfreq_top=0, max_len=6)
    sc = Scanner(cfg, st, FakeChecker(), on_found)
    sc.running.set()
    await sc._pass()
    assert sorted(found) == ["bratva", "zoloto"]
    # Второй проход ничего не перепроверяет и не дублирует уведомления
    await sc._pass()
    assert len(found) == 2
    await st.close()
