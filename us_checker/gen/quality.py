"""Оценка «похоже ли на слово» и отсев уродцев."""
import math
import re
from collections import Counter
from functools import lru_cache

from us_checker.gen.lexicon import LANGS, words

_VOWELS = set("aeiouy")
# Стыки, на которых имя разваливается
_UGLY_RE = re.compile(
    r"(.)\1\1"             # три одинаковые буквы
    r"|[aeiouy]{4}"        # четыре гласные подряд
    r"|[^aeiouy]{4}"       # четыре согласные подряд
    r"|q(?!u)"             # q без u
    r"|ee|ii|uu|yy|aa"
    r"|^[^aeiouy]{3}"      # три согласные в начале
    r"|[^aeiouy]{3}$"
    r"|[jqvwxh]$|^x[^aeiouy]"
)


class Pronounce:
    """Триграммная модель букв по смеси языков."""

    def __init__(self, vocab):
        self.counts: Counter[str] = Counter()
        self.ctx: Counter[str] = Counter()
        for w in vocab:
            s = f"^^{w}$"
            for i in range(len(s) - 2):
                self.counts[s[i : i + 3]] += 1
                self.ctx[s[i : i + 2]] += 1

    def score(self, word: str) -> float:
        s = f"^^{word}$"
        total = 0.0
        for i in range(len(s) - 2):
            c = self.counts[s[i : i + 3]] + 0.1
            n = self.ctx[s[i : i + 2]] + 2.7
            total += math.log(c / n)
        return total / (len(s) - 2)


@lru_cache(maxsize=1)
def model() -> Pronounce:
    vocab: list[str] = []
    for lang in LANGS:
        vocab.extend(words(lang, 15000))
    return Pronounce(vocab)


def is_ugly(name: str) -> bool:
    if _UGLY_RE.search(name):
        return True
    vowels = sum(ch in _VOWELS for ch in name)
    return not (0.25 <= vowels / len(name) <= 0.65)


def score(name: str) -> float:
    """Чем выше, тем звучнее. Короткие ценятся больше."""
    pron = model().score(name)
    return round((pron + 3.0) * 3 - max(0, len(name) - 6) * 0.5, 3)
