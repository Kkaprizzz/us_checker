"""Словари разных языков, приведённые к a-z."""
import unicodedata
from functools import lru_cache

from wordfreq import top_n_list, zipf_frequency

LANGS = ("en", "it", "es", "fr", "pt", "fi", "id", "tr", "ru")

_RU = dict(zip(
    "абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
    ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p",
     "r", "s", "t", "u", "f", "h", "ts", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"],
))


def to_ascii(word: str) -> str:
    word = word.lower()
    if any("а" <= ch <= "я" or ch == "ё" for ch in word):
        word = "".join(_RU.get(ch, ch) for ch in word)
    word = unicodedata.normalize("NFKD", word)
    word = "".join(ch for ch in word if not unicodedata.combining(ch))
    return word.replace("ı", "i")


@lru_cache(maxsize=None)
def words(lang: str, n: int = 30000) -> tuple[str, ...]:
    out = []
    for w in top_n_list(lang, n):
        a = to_ascii(w)
        if a.isascii() and a.isalpha() and len(a) >= 3:
            out.append(a)
    return tuple(dict.fromkeys(out))


@lru_cache(maxsize=1)
def known_words() -> frozenset[str]:
    """Все «настоящие» слова всех языков: их Telegram держит в резерве, нам они не нужны."""
    known: set[str] = set()
    for lang in LANGS:
        known.update(words(lang, 30000))
    known.update(words("en", 120000))
    return frozenset(known)


def is_real(word: str) -> bool:
    return word in known_words() or zipf_frequency(word, "en") >= 1.0


def _deletes(word: str) -> set[str]:
    return {word[:i] + word[i + 1:] for i in range(len(word))}


@lru_cache(maxsize=1)
def _common_index() -> tuple[frozenset[str], frozenset[str]]:
    """Частые слова и их «удаления» — для поиска опечаток за O(длина)."""
    common = set()
    for lang in LANGS:
        n = 20000 if lang == "en" else 8000
        common.update(w for w in words(lang, n) if len(w) >= 4)
    dels: set[str] = set()
    for w in common:
        dels |= _deletes(w)
    return frozenset(common), frozenset(dels)


def looks_like_typo(word: str) -> bool:
    """Отличается от частого слова на одну букву (proping, breated) — выглядит как опечатка."""
    common, dels = _common_index()
    if word in dels:  # вставка лишней буквы в слово наоборот: word = слово без буквы
        return True
    return any(d in common or d in dels for d in _deletes(word))
