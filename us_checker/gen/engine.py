"""Бесконечный поток разнообразных кандидатов."""
import random
from collections import Counter, deque
from dataclasses import dataclass

from us_checker.gen import quality
from us_checker.gen.lexicon import _common_index, is_real, known_words, looks_like_typo
from us_checker.gen.strategies import Strategy, default_strategies


# Окончания словоформ: с ними имя звучит как сломанное слово, а не как ник
_GRAMMAR_ENDINGS = ("ed", "ing", "ings", "ly", "tion", "tions", "ment", "mente", "ness", "ies")


# Вероятность оставить имя данной длины
_LENGTH_KEEP = {5: 1.0, 6: 1.0, 7: 0.85, 8: 0.6, 9: 0.4}


@dataclass(frozen=True)
class Candidate:
    name: str
    source: str
    score: float


class NameEngine:
    def __init__(
        self,
        min_len: int = 5,
        max_len: int = 9,
        strategies: list[tuple[Strategy, float]] | None = None,
        only: tuple[str, ...] = (),
        min_score: float = 1.0,
        seed: int | None = None,
        window: int = 80,
    ):
        self.min_len, self.max_len = min_len, max_len
        self.strategies = strategies or default_strategies()
        if only:
            # STRATEGIES=markov,syll_dark — по префиксу ключа
            self.strategies = [(s, w) for s, w in self.strategies if s.key.startswith(only)]
            if not self.strategies:
                raise ValueError(f"нет стратегий под фильтр {only}")
        self.min_score = min_score
        self.rng = random.Random(seed)
        self.seen: set[str] = set()
        # Скользящее окно для разнообразия: не больше 2 одинаковых начал/концовок
        self._recent: deque[str] = deque(maxlen=window)
        self._starts: Counter[str] = Counter()
        self._ends: Counter[str] = Counter()

    def warmup(self) -> None:
        """Загрузка словарей и обучение цепей (несколько секунд)."""
        known_words()
        _common_index()
        quality.model()
        rng = random.Random(0)
        for s, _ in self.strategies:
            s.make(rng, self.min_len, self.max_len)

    def _diverse(self, name: str) -> bool:
        return self._starts[name[:3]] < 2 and self._ends[name[-3:]] < 2

    def _remember(self, name: str) -> None:
        if len(self._recent) == self._recent.maxlen:
            old = self._recent[0]
            self._starts[old[:3]] -= 1
            self._ends[old[-3:]] -= 1
        self._recent.append(name)
        self._starts[name[:3]] += 1
        self._ends[name[-3:]] += 1
        self.seen.add(name)

    def accept(self, name: str | None) -> float | None:
        """Скор, если имя годится, иначе None."""
        if not name or not (self.min_len <= len(name) <= self.max_len):
            return None
        if not (name.isascii() and name.isalpha() and name.islower()):
            return None
        if name in self.seen or name.endswith("bot") or quality.is_ugly(name):
            return None
        if name.endswith(_GRAMMAR_ENDINGS) or not self._diverse(name):
            return None
        if is_real(name) or looks_like_typo(name):
            return None
        # Короткие ценнее: длинные пропускаем реже
        if self.rng.random() > _LENGTH_KEEP.get(len(name), 0.3):
            return None
        sc = quality.score(name)
        return sc if sc >= self.min_score else None

    def batch(self, n: int, max_tries: int | None = None) -> list[Candidate]:
        strategies, weights = zip(*self.strategies)
        out: list[Candidate] = []
        tries = max_tries or n * 400
        while len(out) < n and tries > 0:
            # Сначала выбираем стратегию, потом добиваемся от неё годного имени,
            # чтобы доли в выдаче соответствовали весам, а не «проходимости» фильтров
            strat = self.rng.choices(strategies, weights)[0]
            for _ in range(80):
                tries -= 1
                name = strat.make(self.rng, self.min_len, self.max_len)
                sc = self.accept(name)
                if sc is not None:
                    self._remember(name)
                    out.append(Candidate(name, strat.key, sc))
                    break
        return out
