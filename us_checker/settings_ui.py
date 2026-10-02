"""Экран /settings с инлайн-кнопками."""
from aiogram.types import InlineKeyboardButton as Btn
from aiogram.types import InlineKeyboardMarkup

from us_checker.settings import Settings

LANG_LABELS = {
    "markov_en": "🇬🇧 англ", "markov_it": "🇮🇹 итал", "markov_es": "🇪🇸 исп",
    "markov_fr": "🇫🇷 франц", "markov_pt": "🇵🇹 порт", "markov_fi": "🇫🇮 фин",
    "markov_id": "🇮🇩 индонез", "markov_tr": "🇹🇷 тур", "markov_ru": "🇷🇺 рус",
    "markov_mix": "🌍 микс",
}
SYLL_LABELS = {
    "syll_elven": "🧝 эльф", "syll_dark": "🖤 тьма", "syll_future": "🤖 кибер",
    "syll_soft": "🧸 мягкие", "syll_east": "🏯 восток",
}
OTHER_LABELS = {
    "classical": "🏛 греко-латынь", "twist": "🔀 мутации", "blend": "🧬 слияния",
    "reverse": "🔁 перевёртыши", "affix": "✨ корень+суффикс",
}
GROUPS = {
    "lang": ("Языки", LANG_LABELS),
    "syll": ("Слоги", SYLL_LABELS),
    "other": ("Другое", OTHER_LABELS),
}


def label(key: str) -> str:
    for _, labels in GROUPS.values():
        if key in labels:
            return labels[key]
    return key


def render_text(st: Settings, all_keys: list[str]) -> str:
    on = len(st.enabled(all_keys))
    return (
        "<b>⚙️ Настройки</b>\n\n"
        f"Длина юзов: <b>{st.min_len}–{st.max_len}</b>\n"
        f"Параллельных проверок: <b>{st.workers}</b>\n"
        f"Лимит запросов: <b>{st.rps:g}/с</b>\n"
        f"Стратегий включено: <b>{on}/{len(all_keys)}</b>\n\n"
        "Жми на стратегию, чтобы включить ✅ или выключить ▫️. "
        "Изменения применяются сразу."
    )


def render_keyboard(st: Settings, all_keys: list[str]) -> InlineKeyboardMarkup:
    rows: list[list[Btn]] = [
        [Btn(text=f"📏 мин {st.min_len}", callback_data="s:nop"),
         Btn(text="−", callback_data="s:min:-1"), Btn(text="+", callback_data="s:min:1")],
        [Btn(text=f"📏 макс {st.max_len}", callback_data="s:nop"),
         Btn(text="−", callback_data="s:max:-1"), Btn(text="+", callback_data="s:max:1")],
        [Btn(text=f"👷 воркеры {st.workers}", callback_data="s:nop"),
         Btn(text="−", callback_data="s:w:-1"), Btn(text="+", callback_data="s:w:1")],
        [Btn(text=f"⚡ {st.rps:g} запр/с", callback_data="s:nop"),
         Btn(text="−", callback_data="s:r:-1"), Btn(text="+", callback_data="s:r:1")],
    ]
    for gkey, (title, labels) in GROUPS.items():
        keys = [k for k in labels if k in all_keys]
        if not keys:
            continue
        rows.append([
            Btn(text=f"— {title} —", callback_data="s:nop"),
            Btn(text="все ✅", callback_data=f"s:g:{gkey}:1"),
            Btn(text="все ▫️", callback_data=f"s:g:{gkey}:0"),
        ])
        row: list[Btn] = []
        for k in keys:
            mark = "▫️" if k in st.disabled else "✅"
            row.append(Btn(text=f"{mark} {labels[k]}", callback_data=f"s:t:{k}"))
            if len(row) == 3:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
    rows.append([
        Btn(text="↩️ По умолчанию", callback_data="s:reset"),
        Btn(text="Готово", callback_data="s:close"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def group_keys(gkey: str, all_keys: list[str]) -> list[str]:
    return [k for k in GROUPS[gkey][1] if k in all_keys]
