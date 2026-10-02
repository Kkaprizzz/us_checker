"""Бесконечный поток разнообразных кандидатов."""
import random
import threading
from collections import Counter, deque
from dataclasses import dataclass

from us_checker.gen import quality
from us_checker.gen.lexicon import _common_index, is_real, known_words, looks_like_typo
from us_checker.gen.strategies import Strategy, default_strategies


# Окончания словоформ: с ними имя звучит как сломанное слово, а не как ник
_GRAMMAR_ENDINGS = ("ed", "ing", "ings", "ly", "tion", "tions", "ment", "mente", "ness", "ies")


# Вероятность оставить имя в зависимости от того, на сколько оно длиннее минимума
_LENGTH_KEEP = (1.0, 1.0, 0.85, 0.6, 0.4)


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
        # batch() крутится в отдельном потоке, configure() зовётся из бота
        self._lock = threading.Lock()
        self.min_len, self.max_len = min_len, max_len
        self.all_strategies = strategies or default_strategies()
        self.strategies = self.all_strategies
        if only:
            # STRATEGIES=markov,syll_dark — по префиксу ключа
            self.configure(enabled={s.key for s, _ in self.all_strategies if s.key.startswith(only)})
        self.min_score = min_score
        self.rng = random.Random(seed)
        self.seen: set[str] = set()
        # Скользящее окно для разнообразия: не больше 2 одинаковых начал/концовок
        self._recent: deque[str] = deque(maxlen=window)
        self._starts: Counter[str] = Counter()
        self._ends: Counter[str] = Counter()

    @property
    def keys(self) -> list[str]:
        return [s.key for s, _ in self.all_strategies]

    def configure(
        self,
        min_len: int | None = None,
        max_len: int | None = None,
        enabled: set[str] | None = None,
    ) -> None:
        """Меняет настройки на лету."""
        strategies = self.strategies
        if enabled is not None:
            strategies = [(s, w) for s, w in self.all_strategies if s.key in enabled]
            if not strategies:
                raise ValueError("нужна хотя бы одна стратегия")
        with self._lock:
            self.strategies = strategies
            if min_len is not None:
                self.min_len = min_len
            if max_len is not None:
                self.max_len = max_len

    def fits(self, cand: "Candidate") -> bool:
        """Подходит ли уже сгенерённый кандидат под текущие настройки."""
        if cand.source == "custom":
            return True
        return (
            self.min_len <= len(cand.name) <= self.max_len
            and any(s.key == cand.source for s, _ in self.strategies)
        )

    def warmup(self) -> None:
        """Загрузка словарей и обучение цепей (несколько секунд)."""
        known_words()
        _common_index()
        quality.model()
        rng = random.Random(0)
        for s, _ in self.all_strategies:
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
        extra = len(name) - self.min_len
        if self.rng.random() > (_LENGTH_KEEP[extra] if extra < len(_LENGTH_KEEP) else 0.3):
            return None
        sc = quality.score(name)
        return sc if sc >= self.min_score else None

    def batch(self, n: int, max_tries: int | None = None) -> list[Candidate]:
        with self._lock:
            return self._batch(n, max_tries)

    def _batch(self, n: int, max_tries: int | None = None) -> list[Candidate]:
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
