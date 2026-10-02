import asyncio
import logging
from html import escape

import aiohttp
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.types import BotCommand, CallbackQuery, Message

from us_checker.checker import RateLimited, Status, TmeChecker
from us_checker.config import Config, load_config
from us_checker.filters import is_clean
from us_checker.gen import Candidate
from us_checker.gen.quality import score as name_score
from us_checker.gen.strategies import default_strategies
from us_checker.scanner import Scanner
from us_checker.settings import WORKERS_MAX, Settings
from us_checker.settings_ui import group_keys, label, render_keyboard, render_text
from us_checker.storage import Storage

log = logging.getLogger(__name__)

STRATEGY_TITLES = {s.key: s.title for s, _ in default_strategies()}
SETTINGS_KEY = "settings"

HELP = (
    "<b>Ищу свободные оригинальные юзы</b> (только a-z, без цифр и _).\n"
    "20 разных стратегий: несуществующие слова в духе разных языков, тёмные, "
    "эльфийские и восточные слоги, греко-латынь, мутации редких слов, слияния, перевёртыши.\n\n"
    "/scan — запустить поиск\n"
    "/pause — пауза\n"
    "/free — что уже нашлось\n"
    "/preview — показать 40 свежих кандидатов (без проверки)\n"
    "/styles — какие стратегии сколько нашли\n"
    "/bad <code>юз юз …</code> — Telegram не дал поставить, больше не показывать\n"
    "/check <code>юз</code> — проверить один юз\n"
    "/add <code>слово …</code> — проверить свои варианты вне очереди\n"
    "/settings — длина, языки, стили, скорость\n"
    "/stats — прогресс\n"
    "/stop — не присылать находки\n\n"
    "⚠️ «Свободен» = на t.me пусто. Финальная проверка — поставить в настройках."
)


def build_router(
    cfg: Config,
    storage: Storage,
    scanner: Scanner,
    checker: TmeChecker,
    settings: Settings,
) -> Router:
    router = Router()
    if cfg.admin_ids:
        router.message.filter(F.from_user.id.in_(cfg.admin_ids))
        router.callback_query.filter(F.from_user.id.in_(cfg.admin_ids))
    all_keys = scanner.engine.keys

    @router.message(Command("settings"))
    async def settings_cmd(msg: Message) -> None:
        await msg.answer(render_text(settings, all_keys), reply_markup=render_keyboard(settings, all_keys))

    @router.callback_query(F.data.startswith("s:"))
    async def settings_cb(cb: CallbackQuery) -> None:
        parts = cb.data.split(":")
        action = parts[1]
        note = None
        if action == "nop":
            await cb.answer()
            return
        if action == "close":
            await cb.message.edit_reply_markup(reply_markup=None)
            await cb.answer("Сохранено")
            return
        if action == "min":
            settings.shift_min(int(parts[2]))
        elif action == "max":
            settings.shift_max(int(parts[2]))
        elif action == "w":
            settings.shift_workers(int(parts[2]))
        elif action == "r":
            settings.shift_rps(int(parts[2]))
        elif action == "t":
            if not settings.toggle(parts[2], all_keys):
                note = "Хотя бы одна стратегия должна остаться"
            else:
                note = f"{label(parts[2])}: {'выкл' if parts[2] in settings.disabled else 'вкл'}"
        elif action == "g":
            if not settings.set_group(group_keys(parts[2], all_keys), parts[3] == "1", all_keys):
                note = "Хотя бы одна стратегия должна остаться"
        elif action == "reset":
            fresh = Settings.from_config(cfg, all_keys)
            settings.__dict__.update(fresh.__dict__)
        scanner.apply(settings)
        await storage.set_kv(SETTINGS_KEY, settings.to_json())
        try:
            await cb.message.edit_text(
                render_text(settings, all_keys), reply_markup=render_keyboard(settings, all_keys)
            )
        except TelegramBadRequest:
            pass  # «message is not modified» — упёрлись в границу
        await cb.answer(note or "")

    @router.message(Command("start", "help"))
    async def start(msg: Message) -> None:
        await storage.add_subscriber(msg.chat.id)
        await msg.answer(HELP)

    @router.message(Command("stop"))
    async def stop(msg: Message) -> None:
        await storage.remove_subscriber(msg.chat.id)
        await msg.answer("Ок, находки больше не шлю. /start — вернуть.")

    @router.message(Command("scan"))
    async def scan(msg: Message) -> None:
        await storage.add_subscriber(msg.chat.id)
        scanner.start()
        await msg.answer(
            f"🔎 Поиск запущен: длина {settings.min_len}–{settings.max_len}, "
            f"{settings.workers} воркеров, до {settings.rps:g} проверок/с. "
            "Находки буду кидать сюда. Настроить — /settings."
        )

    @router.message(Command("pause"))
    async def pause(msg: Message) -> None:
        scanner.pause()
        await msg.answer("⏸ Поиск на паузе. /scan — продолжить.")

    @router.message(Command("stats"))
    async def stats(msg: Message) -> None:
        c = await storage.counts()
        state = "работает" if scanner.running.is_set() else "на паузе"
        text = (
            f"Сканер: <b>{state}</b> · {scanner.rate:.0f} проверок/мин\n"
            f"За сессию: проверено {scanner.checked}, найдено {scanner.found}\n"
            f"Очередь: {scanner.queue.qsize()}\n"
            f"Всего в базе: {sum(c.values())} · свободных <b>{c.get('free', 0)}</b>"
            f" · занятых {c.get('taken', 0)} · в /bad {c.get('invalid', 0)}"
        )
        if scanner.last_error:
            text += f"\n\n❗ {scanner.last_error}"
        await msg.answer(text)

    @router.message(Command("styles"))
    async def styles(msg: Message) -> None:
        rows = await storage.stats_by_source()
        if not rows:
            await msg.answer("Статистики пока нет. Запусти /scan.")
            return
        lines = [
            f"{STRATEGY_TITLES.get(src, src)}: {total} пров. · ✅ {free}" + (f" · 🚫 {bad}" if bad else "")
            for src, total, free, bad in rows
        ]
        await msg.answer("<b>Стратегии</b>\n" + "\n".join(lines))

    @router.message(Command("free"))
    async def free(msg: Message) -> None:
        rows = await storage.list_free(50)
        if not rows:
            await msg.answer("Пока пусто. Запусти /scan.")
            return
        await msg.answer("<b>Свободные (свежие сверху):</b>\n" + "\n".join(f"@{n}" for n, _ in rows))

    @router.message(Command("preview"))
    async def preview(msg: Message) -> None:
        await msg.answer("Генерирую…")
        cands = await scanner.preview(40)
        lines = [f"{c.name} · {escape(STRATEGY_TITLES.get(c.source, c.source))}" for c in cands]
        await msg.answer("\n".join(lines) or "Ничего не сгенерилось — проверь STRATEGIES.")

    @router.message(Command("check"))
    async def check(msg: Message, command: CommandObject) -> None:
        name = (command.args or "").strip().lstrip("@").lower()
        if not name:
            await msg.answer("Пример: /check velora")
            return
        if not is_clean(name, 5, 32):
            await msg.answer("Нужно от 5 символов, только a-z, без цифр и _ (и не на «bot»).")
            return
        try:
            status = await checker.check(name)
        except RateLimited as e:
            await msg.answer(f"t.me просит подождать {e.retry_after:.0f}с, попробуй позже.")
            return
        if status != Status.ERROR:
            await storage.save_check(name, status.value, name_score(name), "custom")
        text = {
            Status.FREE: f"✅ @{name} — на t.me пусто, похоже свободен",
            Status.TAKEN: f"❌ @{name} — занят",
            Status.ERROR: f"⚠️ @{name} — не удалось проверить",
        }[status]
        await msg.answer(text)

    @router.message(Command("bad"))
    async def bad(msg: Message, command: CommandObject) -> None:
        names = [w.lstrip("@").lower() for w in (command.args or "").replace(",", " ").split()]
        if not names:
            await msg.answer("Пример: /bad velora kushon")
            return
        await storage.mark_invalid(names)
        await msg.answer(f"Убрал {len(names)} шт. Больше их не покажу.")

    @router.message(Command("add"))
    async def add(msg: Message, command: CommandObject) -> None:
        words = [w.lstrip("@").lower() for w in (command.args or "").replace(",", " ").split()]
        good = [w for w in words if is_clean(w, 5, 32)]
        bad_words = sorted(set(words) - set(good))
        if good:
            await storage.add_words(good)
        text = f"Добавил: {len(good)}. Проверю вне очереди, когда идёт /scan."
        if bad_words:
            text += "\nПропустил (нужно от 5 символов, только a-z): " + ", ".join(bad_words)
        await msg.answer(text)

    return router


async def run(cfg: Config) -> None:
    bot = Bot(cfg.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    storage = Storage(cfg.db_path)
    await storage.open()

    async def on_found(cand: Candidate) -> None:
        text = (
            f"🔥 <b>@{cand.name}</b> — похоже свободен\n"
            f"{escape(STRATEGY_TITLES.get(cand.source, cand.source))}\n"
            f"https://t.me/{cand.name}"
        )
        for chat_id in await storage.subscribers():
            try:
                await bot.send_message(chat_id, text, disable_web_page_preview=True)
            except Exception:
                log.exception("не смог отправить в %s", chat_id)

    connector = aiohttp.TCPConnector(limit=WORKERS_MAX * 2)
    async with aiohttp.ClientSession(connector=connector) as session:
        checker = TmeChecker(session)
        scanner = Scanner(cfg, storage, checker, on_found)
        # Настройки из базы важнее .env: .env — только значения по умолчанию
        raw = await storage.get_kv(SETTINGS_KEY)
        settings = Settings.from_json(raw) if raw else Settings.from_config(cfg, scanner.engine.keys)
        settings.disabled &= set(scanner.engine.keys)
        if not settings.enabled(scanner.engine.keys):
            settings.disabled.clear()
        scanner.apply(settings)
        dp = Dispatcher()
        dp.include_router(build_router(cfg, storage, scanner, checker, settings))
        await bot.set_my_commands([
            BotCommand(command="scan", description="Запустить поиск"),
            BotCommand(command="pause", description="Пауза"),
            BotCommand(command="free", description="Найденные юзы"),
            BotCommand(command="preview", description="Примеры кандидатов"),
            BotCommand(command="styles", description="Статистика стратегий"),
            BotCommand(command="bad", description="Отметить нерабочие юзы"),
            BotCommand(command="check", description="Проверить юз"),
            BotCommand(command="add", description="Свои варианты вне очереди"),
            BotCommand(command="settings", description="Настройки"),
            BotCommand(command="stats", description="Прогресс"),
        ])
        # Прогреваем генератор в фоне, пока бот уже отвечает
        asyncio.create_task(scanner.prepare())
        try:
            await dp.start_polling(bot)
        finally:
            await scanner.stop()
            await storage.close()
            await bot.session.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(run(load_config()))
