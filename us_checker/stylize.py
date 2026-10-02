"""Генератор «изысканных» юзов: придуманные формы от сильных корней.

Обычные словарные слова Telegram почти все зарезервировал, поэтому ищем
то, чего нет в словаре, но что звучит как слово: godeless, godelesse,
incelious, velora, noxelle…
"""
import math
from collections import Counter
from functools import lru_cache
from pathlib import Path

from wordfreq import top_n_list, zipf_frequency

DATA_DIR = Path(__file__).parent / "data"

# Суффикс -> эстетичный вес
SUFFIXES: dict[str, float] = {
    "less": 2.5, "lesse": 2.5, "ness": 1.5, "nesse": 2.0,
    "ious": 2.5, "ius": 2.0, "ous": 1.5,
    "esse": 2.5, "ess": 2.0, "elle": 2.5, "ella": 2.0, "ette": 1.5,
    "ique": 2.0, "ium": 2.0, "ion": 1.0, "ia": 1.5,
    "ora": 2.0, "ara": 1.5, "ira": 1.5, "ina": 1.5, "ine": 1.5,
    "ix": 2.0, "yx": 2.0, "ex": 1.0, "is": 1.0,
    "eon": 1.5, "ian": 1.0, "ism": 1.0, "ity": 1.0,
    "ful": 1.0, "full": 1.5, "fall": 1.0, "ish": 0.5,
    "ary": 1.0, "ory": 1.0, "ia": 1.5, "y": 0.5, "e": 1.0,
}

# Слова со «стильными» окончаниями, которые мутируем (godless -> godeless)
_MUTABLE_ENDINGS = ("less", "ness", "ous", "ful", "ess", "ive", "ism")

# Сочетания, на которых имя разваливается: hazeess, softneess
_UGLY = ("ee", "aa", "ii", "uu", "yy", "iu", "eie", "eia", "eio", "eiu", "yi", "uie")

# Словарное слово (zipf выше) считаем «очевидным» — скорее всего резерв
REAL_WORD_ZIPF = 1.0


def read_roots(path: Path = DATA_DIR / "roots.txt") -> dict[str, float]:
    roots: dict[str, float] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        for tok in line.split("#", 1)[0].split():
            name, _, w = tok.partition(":")
            roots[name.lower()] = float(w or 1)
    return roots


def join(root: str, suffix: str) -> set[str]:
    """Склейка корня и суффикса в нескольких естественных вариантах."""
    out = {root + suffix}
    vowels = "aeiouy"
    if root[-1] in vowels and suffix[0] in vowels and len(root) > 3:
        out.add(root[:-1] + suffix)  # grace + ious -> gracious
    if root[-1] not in vowels and suffix[0] not in vowels:
        out.add(root + "e" + suffix)  # god + less -> godeless
    if root[-1] == "e" and suffix[0] == "e":
        out.discard(root + suffix)  # без «ee» на стыке
    return out


def mutate(word: str) -> set[str]:
    """Стилизованные мутации настоящего слова."""
    out: set[str] = set()
    for end in _MUTABLE_ENDINGS:
        if word.endswith(end) and len(word) > len(end) + 2:
            stem = word[: -len(end)]
            if stem[-1] not in "aeiouy":
                out.add(stem + "e" + end)  # godless -> godeless
            if end == "ous":
                out.add(stem + "ious")  # famous -> famious
    for w in list(out) + [word]:
        if w.endswith(("ss", "ll")):
            out.add(w + "e")  # godeless -> godelesse
        elif w.endswith("s") and not w.endswith("ous"):
            out.add(w + "se")
    if word.endswith("y"):
        out.add(word[:-1] + "ie")
    out.discard(word)
    return out


class Pronounce:
    """Триграммная модель букв английского: насколько строка похожа на слово."""

    def __init__(self, vocab: list[str]):
        self.counts: Counter[str] = Counter()
        self.ctx: Counter[str] = Counter()
        for w in vocab:
            s = f"^^{w}$"
            for i in range(len(s) - 2):
                self.counts[s[i : i + 3]] += 1
                self.ctx[s[i : i + 2]] += 1

    def score(self, word: str) -> float:
        """Средний log-prob на символ (около -2 — норм, ниже -3.5 — каша)."""
        s = f"^^{word}$"
        total = 0.0
        for i in range(len(s) - 2):
            c = self.counts[s[i : i + 3]] + 0.1
            n = self.ctx[s[i : i + 2]] + 0.1 * 27
            total += math.log(c / n)
        return total / (len(s) - 2)


@lru_cache(maxsize=1)
def _model_and_vocab() -> tuple[Pronounce, tuple[str, ...]]:
    vocab = [w for w in top_n_list("en", 40000) if w.isascii() and w.isalpha() and len(w) > 2]
    return Pronounce(vocab), tuple(vocab)


def is_obvious(word: str) -> bool:
    return zipf_frequency(word, "en") >= REAL_WORD_ZIPF


def generate(min_len: int = 6, max_len: int = 9, min_pron: float = -2.6) -> dict[str, float]:
    """Возвращает {юз: скор} — придуманные, но произносимые формы."""
    model, vocab = _model_and_vocab()
    roots = read_roots()
    raw: dict[str, float] = {}

    def put(name: str, base: float) -> None:
        if name not in raw or raw[name] < base:
            raw[name] = base

    for root, rw in roots.items():
        for suf, sw in SUFFIXES.items():
            for name in join(root, suf):
                put(name, rw + sw)
                for m in mutate(name):
                    put(m, rw + sw - 0.3)

    # Мутации реальных слов со стильными окончаниями (godless -> godeless)
    for w in vocab:
        if 5 <= len(w) <= max_len and w.endswith(_MUTABLE_ENDINGS):
            weight = min(zipf_frequency(w, "en"), 5.0) / 2  # известнее корень — круче
            for m in mutate(w):
                put(m, weight + 1.0)

    out: dict[str, float] = {}
    for name, base in raw.items():
        if not (min_len <= len(name) <= max_len) or not name.isalpha() or not name.isascii():
            continue
        if name.endswith("bot") or is_obvious(name):
            continue
        if any(name[i] == name[i + 1] == name[i + 2] for i in range(len(name) - 2)):
            continue
        if any(d in name for d in _UGLY):
            continue
        pron = model.score(name)
        if pron < min_pron:
            continue
        out[name] = base + (pron + 2.6) * 2 - max(0, len(name) - 7) * 0.6
    return diversify(out)


def diversify(scores: dict[str, float], prefix: int = 4, step: float = 0.35) -> dict[str, float]:
    """Штрафует повторы одного корня, чтобы топ не забивался godess/godesse/godelle…"""
    seen: Counter[str] = Counter()
    out: dict[str, float] = {}
    for name, s in sorted(scores.items(), key=lambda x: -x[1]):
        key = name[:prefix]
        out[name] = round(s - seen[key] * step, 3)
        seen[key] += 1
    return out
