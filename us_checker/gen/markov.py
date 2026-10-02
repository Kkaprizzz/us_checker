"""Буквенная марковская цепь: учится на словаре и рожает похожие несуществующие слова."""
import random
from collections import defaultdict

END = "$"


class CharMarkov:
    def __init__(self, order: int = 3):
        self.order = order
        self.table: dict[str, tuple[list[str], list[int]]] = {}

    def train(self, words) -> "CharMarkov":
        counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for w in words:
            s = "^" * self.order + w + END
            for i in range(len(w) + 1):
                counts[s[i : i + self.order]][s[i + self.order]] += 1
        self.table = {k: (list(v), list(v.values())) for k, v in counts.items()}
        return self

    def sample(self, rng: random.Random, min_len: int, max_len: int, tries: int = 20) -> str | None:
        for _ in range(tries):
            state = "^" * self.order
            out = []
            while True:
                choices = self.table.get(state)
                if not choices:
                    break
                ch = rng.choices(*choices)[0]
                if ch == END:
                    break
                out.append(ch)
                if len(out) > max_len:
                    break
                state = state[1:] + ch
            word = "".join(out)
            if min_len <= len(word) <= max_len:
                return word
        return None
