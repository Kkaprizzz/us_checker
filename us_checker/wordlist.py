"""Генерация и ранжирование кандидатов в юзы."""
from dataclasses import dataclass
from pathlib import Path

from wordfreq import top_n_list, zipf_frequency

from us_checker.filters import STOPWORDS, is_clean
from us_checker.stylize import generate as generate_styled

DATA_DIR = Path(__file__).parent / "data"

# Бонусы к скору: ручной список ценнее частотного словаря
PREMIUM_BONUS = 4.0
TRANSLIT_BONUS = 2.5
# Каждая буква сверх 5 снижает ценность
LENGTH_PENALTY = 0.8
# Формы слов (-ing, -ed, -ly) ценятся ниже базового слова
FORM_PENALTY = 1.0


@dataclass(frozen=True, order=True)
class Candidate:
    sort_key: float
    name: str
    source: str

    @property
    def score(self) -> float:
        return -self.sort_key


def _read_list(path: Path) -> list[str]:
    words: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0]
        words.extend(w.strip().lower() for w in line.split())
    return words


def score(name: str, source: str) -> float:
    s = zipf_frequency(name, "en")
    if source == "premium":
        s += PREMIUM_BONUS
    elif source == "translit":
        s += TRANSLIT_BONUS
    s -= (len(name) - 5) * LENGTH_PENALTY
    if source == "wordfreq" and name.endswith(("ing", "ed", "ly")):
        s -= FORM_PENALTY
    return round(s, 3)


ALL_SOURCES = ("styled", "premium", "translit", "dict")


def build_candidates(
    min_len: int = 5,
    max_len: int = 9,
    sources_enabled: tuple[str, ...] = ("styled",),
    wordfreq_top: int = 60000,
    extra: list[str] | None = None,
) -> list[Candidate]:
    """Возвращает уникальных кандидатов, самые «блатные» первыми.

    styled   — придуманные формы от сильных корней (godeless, incelious), основной режим
    premium  — ручной список ходовых слов (почти всё зарезервировано Telegram)
    translit — транслит русских слов
    dict     — частотный словарь wordfreq
    """
    best: dict[str, Candidate] = {}
    if extra:
        # Свои слова из /add — всегда первыми
        for w in extra:
            if is_clean(w, min_len, max_len):
                best[w] = Candidate(-100.0, w, "custom")
    if "styled" in sources_enabled:
        for w, sc in generate_styled(min_len, max_len).items():
            if w not in best and is_clean(w, min_len, max_len):
                best[w] = Candidate(-(sc + PREMIUM_BONUS), w, "styled")

    sources: list[tuple[str, list[str]]] = []
    if "premium" in sources_enabled:
        sources.append(("premium", _read_list(DATA_DIR / "premium.txt")))
    if "translit" in sources_enabled:
        sources.append(("translit", _read_list(DATA_DIR / "translit.txt")))
    if "dict" in sources_enabled and wordfreq_top > 0:
        vocab = top_n_list("en", wordfreq_top)
        vocab_set = set(vocab)
        # Множественное число, если в словаре есть единственное, — мусор
        freq_words = [
            w for w in vocab
            if w not in STOPWORDS
            and not (w.endswith("s") and w[:-1] in vocab_set)
        ]
        sources.append(("wordfreq", freq_words))

    for source, words in sources:
        for w in words:
            if not is_clean(w, min_len, max_len):
                continue
            c = Candidate(-score(w, source), w, source)
            if w not in best or c < best[w]:
                best[w] = c
    return sorted(best.values())
