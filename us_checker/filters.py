import re

_CLEAN_RE = re.compile(r"[a-z]+")


def is_clean(name: str, min_len: int = 5, max_len: int = 32) -> bool:
    """Только a-z, без цифр и подчёркиваний, не на «bot» (такие только для ботов)."""
    return (
        min_len <= len(name) <= max_len
        and bool(_CLEAN_RE.fullmatch(name))
        and not name.endswith("bot")
    )
