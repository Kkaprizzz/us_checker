import re

_CLEAN_RE = re.compile(r"[a-z]+")

# Юзы с окончанием "bot" Telegram оставляет только для ботов
_RESERVED_SUFFIXES = ("bot",)

# Служебные слова: формально чистые, но никому не нужны
STOPWORDS = frozenset(
    """
    about above after again against along among another anyone anything around
    because become becomes before behind being below beside besides between beyond
    cannot could didnt doesnt during either enough every everyone everything
    first further having however itself might myself neither never nobody nothing
    other others ourselves perhaps rather really should since still their theirs
    them themselves there these thing things those though through thus together
    toward towards under unless until upon whatever whenever where whereas
    wherever whether which while whoever whole whose within without would
    yours yourself always another already almost although anyway
    """.split()
)


def is_clean(name: str, min_len: int = 5, max_len: int = 32) -> bool:
    """Только a-z, без цифр и подчёркиваний, в заданных рамках длины."""
    if not (min_len <= len(name) <= max_len):
        return False
    if not _CLEAN_RE.fullmatch(name):
        return False
    if name.endswith(_RESERVED_SUFFIXES):
        return False
    return True
