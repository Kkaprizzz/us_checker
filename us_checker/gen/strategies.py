"""Стратегии генерации. Каждая звучит по-своему — так выдача не сливается в одно."""
import random
from functools import cached_property

from wordfreq import zipf_frequency

from us_checker.gen.lexicon import LANGS, words
from us_checker.gen.markov import CharMarkov

LANG_TITLES = {
    "en": "английский", "it": "итальянский", "es": "испанский", "fr": "французский",
    "pt": "португальский", "fi": "финский", "id": "индонезийский", "tr": "турецкий",
    "ru": "русский транслит",
}


class Strategy:
    key = ""
    title = ""

    def make(self, rng: random.Random, min_len: int, max_len: int) -> str | None:
        raise NotImplementedError


class MarkovLang(Strategy):
    """Несуществующие слова со звучанием конкретного языка: velluccia, korvanen…"""

    def __init__(self, lang: str, order: int = 3):
        self.lang = lang
        self.order = order
        self.key = f"markov_{lang}"
        self.title = f"звучит как {LANG_TITLES.get(lang, lang)}"

    @cached_property
    def chain(self) -> CharMarkov:
        return CharMarkov(self.order).train(words(self.lang, 25000))

    def make(self, rng, min_len, max_len):
        return self.chain.sample(rng, min_len, max_len)


class MarkovMix(Strategy):
    """Гибрид всех языков сразу — самые экзотичные формы."""

    key = "markov_mix"
    title = "смесь языков"

    @cached_property
    def chain(self) -> CharMarkov:
        vocab: list[str] = []
        for lang in LANGS:
            vocab.extend(words(lang, 6000))
        return CharMarkov(2).train(vocab)

    def make(self, rng, min_len, max_len):
        return self.chain.sample(rng, min_len, max_len)


# Слоговые конструкторы в разных «стилях»
SYLLABLE_STYLES: dict[str, dict[str, list[str]]] = {
    "elven": {
        "onset": ["l", "r", "th", "v", "s", "n", "m", "el", "f", "ae", "il", "sel", "cal", "ny"],
        "nucleus": ["a", "e", "i", "ia", "ae", "ie", "o", "ea", "y"],
        "coda": ["", "", "l", "n", "r", "th", "s", "nd", "ll", "riel", "wen", "ion"],
    },
    "dark": {
        "onset": ["k", "z", "v", "r", "x", "gr", "dr", "kr", "m", "n", "th", "sk", "v", "mor"],
        "nucleus": ["o", "u", "a", "y", "e", "au", "ae"],
        "coda": ["", "x", "k", "th", "rn", "z", "s", "g", "ks", "r", "rk", "n", "m"],
    },
    "future": {
        "onset": ["x", "z", "v", "n", "k", "q", "t", "zy", "ky", "ne", "ve", "ax"],
        "nucleus": ["e", "y", "a", "o", "i", "eo", "io"],
        "coda": ["", "x", "n", "on", "r", "ix", "ex", "s", "nt", "q", "yn"],
    },
    "soft": {
        "onset": ["b", "m", "l", "s", "p", "n", "f", "j", "ch", "sh", "w"],
        "nucleus": ["a", "o", "u", "i", "e", "ou", "oo", "ay"],
        "coda": ["", "", "", "n", "m", "l", "sh", "ly", "ny", "bi", "mi"],
    },
    "east": {
        "onset": ["k", "s", "t", "h", "m", "n", "r", "y", "sh", "ch", "ts", "z", "ky", "ry"],
        "nucleus": ["a", "i", "u", "e", "o"],
        "coda": ["", "", "", "n"],
    },
}


class Syllables(Strategy):
    """Конструктор из слогов в стиле: эльфийский, тёмный, кибер, мягкий, восточный."""

    def __init__(self, style: str):
        self.style = style
        self.key = f"syll_{style}"
        self.title = f"слоги «{style}»"
        self.parts = SYLLABLE_STYLES[style]

    def make(self, rng, min_len, max_len):
        p = self.parts
        n = rng.choice((2, 2, 3, 3, 4)) if self.style == "east" else rng.choice((2, 2, 2, 3))
        name = ""
        for i in range(n):
            onset = rng.choice(p["onset"]) if (i or rng.random() < 0.85) else ""
            coda = rng.choice(p["coda"]) if (i == n - 1 or rng.random() < 0.3) else ""
            name += onset + rng.choice(p["nucleus"]) + coda
        return name


CLASSICAL = {
    "pre": ["aeth", "pyr", "chron", "lyc", "necr", "astr", "hel", "noct", "cael", "umbr",
            "vel", "cyr", "thal", "xen", "zeph", "myr", "sol", "lum", "ign", "aur", "cryst",
            "eld", "vor", "sil", "syl", "ther", "orph", "nyx", "styx", "ast", "ari", "cor",
            "drac", "ferr", "glac", "hydr", "lun", "mal", "nym", "obs", "pall", "quin", "rav",
            "sept", "tac", "val", "verd", "vesp"],
    "link": ["a", "e", "i", "o", "y", "", "", "ae", "eo"],
    "end": ["on", "os", "is", "ar", "yn", "eth", "ith", "us", "ix", "ea", "ia", "or", "en",
            "ara", "ira", "ion", "ys", "um", "ax", "esh", "ul", "ane", "ora", "iel", "yth"],
}


class Classical(Strategy):
    """Греко-латинская основа + окончание: aethon, nyxara, zephyth…"""

    key = "classical"
    title = "греко-латынь"

    def make(self, rng, min_len, max_len):
        c = CLASSICAL
        return rng.choice(c["pre"]) + rng.choice(c["link"]) + rng.choice(c["end"])


def _rare_words(min_len: int, max_len: int) -> list[str]:
    """Редкие, но красивые реальные слова — сырьё для мутаций."""
    out = []
    for w in words("en", 80000):
        if min_len <= len(w) <= max_len + 1 and 1.5 <= zipf_frequency(w, "en") <= 3.6:
            out.append(w)
    return out


_TWISTS: list[tuple[str, str]] = [
    ("i", "y"), ("y", "i"), ("c", "k"), ("k", "c"), ("ph", "f"), ("f", "ph"), ("s", "z"),
    ("ks", "x"), ("cs", "x"), ("x", "ks"), ("u", "oo"), ("ou", "u"), ("er", "yr"), ("or", "yr"),
    ("qu", "kw"), ("ck", "k"), ("oo", "u"), ("ee", "i"), ("a", "ae"), ("e", "ae"), ("o", "au"),
    ("ch", "kh"), ("th", "t"), ("t", "th"), ("v", "w"), ("w", "v"), ("ia", "ya"), ("ie", "y"),
]


class Twist(Strategy):
    """Редкое реальное слово с одной-двумя стильными подменами: obsydian, mystik, ethereon…"""

    key = "twist"
    title = "мутация редкого слова"

    def __init__(self):
        self._cache: dict[tuple[int, int], list[str]] = {}

    def make(self, rng, min_len, max_len):
        key = (min_len, max_len)
        if key not in self._cache:
            self._cache[key] = _rare_words(min_len, max_len)
        pool = self._cache[key]
        w = rng.choice(pool)
        for _ in range(rng.choice((1, 1, 2))):
            r = rng.random()
            if r < 0.6:
                a, b = rng.choice([t for t in _TWISTS if t[0] in w] or [("", "")])
                if a:
                    idx = [i for i in range(len(w)) if w.startswith(a, i)]
                    i = rng.choice(idx)
                    w = w[:i] + b + w[i + len(a):]
            elif r < 0.75 and w.endswith("e"):
                w = w[:-1] + rng.choice(("a", "o", "ia", "y"))
            elif r < 0.9:
                w = w + rng.choice(("a", "o", "ia", "e", "is", "us", "y"))
            else:
                i = rng.randrange(1, len(w) - 1)
                w = w[:i] + w[i + 1:]  # выкинуть букву
        return w


class Blend(Strategy):
    """Слияние двух слов по общему куску: lunar+arcade -> lunarcade. Читается как одно слово."""

    key = "blend"
    title = "слияние слов"

    @cached_property
    def pool(self) -> list[str]:
        return [w for w in words("en", 20000) if 4 <= len(w) <= 7 and zipf_frequency(w, "en") >= 2.5]

    def make(self, rng, min_len, max_len):
        for _ in range(60):
            a, b = rng.choice(self.pool), rng.choice(self.pool)
            if a == b:
                continue
            for k in (3, 2):
                if a[-k:] == b[:k] and len(a) - k >= 2 and len(b) - k >= 2:
                    name = a + b[k:]
                    if min_len <= len(name) <= max_len:
                        return name
        return None


class Reverse(Strategy):
    """Перевёрнутые слова, которые звучат как новые: dragon -> nogard."""

    key = "reverse"
    title = "перевёртыш"

    @cached_property
    def pool(self) -> list[str]:
        return [w for w in words("en", 40000) if zipf_frequency(w, "en") >= 2.0]

    def make(self, rng, min_len, max_len):
        w = rng.choice(self.pool)[::-1]
        return w if min_len <= len(w) <= max_len else None


AFFIX_ROOTS = ["god", "sin", "nox", "lux", "void", "vex", "noir", "lust", "fate", "muse", "omen",
               "goth", "luna", "soul", "dusk", "onyx", "vel", "aura", "nova", "rune", "myth", "hex"]
AFFIX_ENDS = ["less", "elle", "ious", "esse", "ique", "ora", "ix", "ium", "ara", "yx", "ette",
              "ine", "ian", "eon", "ica", "ova", "ane", "ith", "elia", "ory", "ade", "ism"]


class Affix(Strategy):
    """Сильный корень + эстетичный суффикс (godeless, noxelle) — в небольшой доле."""

    key = "affix"
    title = "корень + суффикс"

    def make(self, rng, min_len, max_len):
        root, end = rng.choice(AFFIX_ROOTS), rng.choice(AFFIX_ENDS)
        glue = "e" if root[-1] not in "aeiouy" and end[0] not in "aeiouy" and rng.random() < 0.5 else ""
        if root[-1] in "aeiouy" and end[0] in "aeiouy":
            root = root[:-1]
        return root + glue + end


def default_strategies() -> list[tuple[Strategy, float]]:
    """(стратегия, вес). Вес — доля в выдаче."""
    out: list[tuple[Strategy, float]] = [(MarkovLang(lang), 1.0) for lang in LANGS]
    out += [
        (MarkovMix(), 1.5),
        (Classical(), 1.5),
        (Twist(), 2.0),
        (Blend(), 1.0),
        (Reverse(), 0.7),
        (Affix(), 0.6),
    ]
    out += [(Syllables(style), 0.8) for style in SYLLABLE_STYLES]
    return out
