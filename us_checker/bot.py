import asyncio
import logging

import aiohttp
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject
from aiogram.types import BotCommand, Message

from us_checker.checker import RateLimited, Status, TmeChecker
from us_checker.config import Config, load_config
from us_checker.filters import is_clean
from us_checker.scanner import Scanner
from us_checker.storage import Storage
from us_checker.wordlist import Candidate, build_candidates, score

log = logging.getLogger(__name__)

HELP = (
    "<b>Ищу свободные изысканные юзы</b> (только a-z, без цифр и _): "
    "godeless, incelious, noxelle…\n\n"
    "/scan — запустить поиск\n"
    "/pause — пауза\n"
    "/free — что уже нашлось\n"
    "/bad <code>юз юз …</code> — Telegram сказал «некорректный», больше не показывать\n"
    "/preview — какие юзы сейчас в очереди\n"
    "/check <code>юз</code> — проверить один юз\n"
    "/add <code>слово слово …</code> — добавить свои слова в приоритет\n"
    "/stats — прогресс\n"
    "/stop — не присылать находки\n\n"
    "⚠️ «Свободен» = на t.me пусто. Такой юз всё равно может быть в резерве "
    "у Telegram — проверь в настройках, а нерабочие скидывай в /bad."
)


def build_router(cfg: Config, storage: Storage, scanner: Scanner, checker: TmeChecker) -> Router:
    router = Router()
    if cfg.admin_ids:
        router.message.filter(F.from_user.id.in_(cfg.admin_ids))

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
        await msg.answer("🔎 Поиск запущен. Находки буду кидать сюда.")

    @router.message(Command("pause"))
    async def pause(msg: Message) -> None:
        scanner.pause()
        await msg.answer("⏸ Поиск на паузе. /scan — продолжить.")

    @router.message(Command("stats"))
    async def stats(msg: Message) -> None:
        c = await storage.counts()
        state = "работает" if scanner.running.is_set() else "на паузе"
        text = (
            f"Сканер: <b>{state}</b>\n"
            f"Проход: {scanner.position}/{scanner.total}"
            + (f" (сейчас @{scanner.current})" if scanner.current else "")
            + f"\nПроверено: {sum(c.values())}\n"
            f"Свободных: <b>{c.get('free', 0)}</b> · занятых: {c.get('taken', 0)}"
            f" · ошибок: {c.get('error', 0)}"
        )
        if scanner.last_error:
            text += f"\n\n❗ {scanner.last_error}"
        await msg.answer(text)

    @router.message(Command("free"))
    async def free(msg: Message) -> None:
        rows = await storage.list_free(50)
        if not rows:
            await msg.answer("Пока пусто. Запусти /scan.")
            return
        lines = [f"@{name} · {s:.1f}" for name, s in rows]
        await msg.answer("<b>Свободные (по ценности):</b>\n" + "\n".join(lines))

    @router.message(Command("check"))
    async def check(msg: Message, command: CommandObject) -> None:
        name = (command.args or "").strip().lstrip("@").lower()
        if not name:
            await msg.answer("Пример: /check money")
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
            await storage.save_check(name, status.value, score(name, "premium"))
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
            await msg.answer("Пример: /bad godeless incelious")
            return
        await storage.mark_invalid(names)
        await msg.answer(f"Убрал {len(names)} шт. Больше их не покажу.")

    @router.message(Command("preview"))
    async def preview(msg: Message) -> None:
        cands = build_candidates(
            cfg.min_len, cfg.max_len, cfg.sources, cfg.wordfreq_top,
            extra=await storage.extra_words(),
        )
        top = [f"{c.name} · {c.score:.1f}" for c in cands[:40]]
        await msg.answer(
            f"В очереди {len(cands)} кандидатов ({', '.join(cfg.sources)}). Топ-40:\n"
            + "\n".join(top)
        )

    @router.message(Command("add"))
    async def add(msg: Message, command: CommandObject) -> None:
        words = [w.lstrip("@").lower() for w in (command.args or "").split()]
        good = [w for w in words if is_clean(w, cfg.min_len, cfg.max_len)]
        bad = sorted(set(words) - set(good))
        if good:
            await storage.add_words(good)
        text = f"Добавил: {len(good)}. Попадут в следующий проход."
        if bad:
            text += f"\nПропустил (не проходят фильтр {cfg.min_len}-{cfg.max_len} a-z): {', '.join(bad)}"
        await msg.answer(text)

    return router


async def run(cfg: Config) -> None:
    bot = Bot(cfg.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    storage = Storage(cfg.db_path)
    await storage.open()

    async def on_found(cand: Candidate) -> None:
        text = (
            f"🔥 <b>@{cand.name}</b> — похоже свободен\n"
            f"Ценность: {cand.score:.1f} · {cand.source}\n"
            f"https://t.me/{cand.name}"
        )
        for chat_id in await storage.subscribers():
            try:
                await bot.send_message(chat_id, text, disable_web_page_preview=True)
            except Exception:
                log.exception("не смог отправить в %s", chat_id)

    async with aiohttp.ClientSession() as session:
        checker = TmeChecker(session)
        scanner = Scanner(cfg, storage, checker, on_found)
        dp = Dispatcher()
        dp.include_router(build_router(cfg, storage, scanner, checker))
        await bot.set_my_commands([
            BotCommand(command="scan", description="Запустить поиск"),
            BotCommand(command="pause", description="Пауза"),
            BotCommand(command="free", description="Найденные юзы"),
            BotCommand(command="check", description="Проверить юз"),
            BotCommand(command="bad", description="Отметить нерабочие юзы"),
            BotCommand(command="preview", description="Очередь кандидатов"),
            BotCommand(command="add", description="Добавить свои слова"),
            BotCommand(command="stats", description="Прогресс"),
        ])
        try:
            await dp.start_polling(bot)
        finally:
            await scanner.stop()
            await storage.close()
            await bot.session.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(run(load_config()))
