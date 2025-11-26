import asyncio
from dotenv import load_dotenv
from datetime import datetime, time, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, CommandObject
from openai import OpenAI
from typing import Dict, Set
import json
import os

system_prompt = """Ты полезный ассистент. При ответах соблюдай следующие правила форматирования:

1. НЕ используй markdown-символы, если не хочешь создать форматирование:
   - Избегай одиночных * _ ~ ` | [ ] ( )
   - Не используй ** __ ~~ ``` || ### для случайного выделения

2. МОЖНО использовать ТОЛЬКО если нужно форматирование Telegram:
   - *жирный текст* - для важного
   - _курсив_ - для акцента
   - __подчеркнутый__ - для выделения
   - ~зачеркнутый~ - для исправлений
   - ||спойлер|| - для скрытия информации
   - ```моноширинный``` - для кода/команд
   - [текст](ссылка) - для ссылок(только сайты)

3. Для списков используй обычные символы:
   - Используй • или - для маркеров
   - Используй 1. 2. 3. для нумерации

4. Пиши естественно, избегая случайных спецсимволов в обычном тексте.

Твои ответы должны корректно отображаться в Telegram без артефактов форматирования."""

load_dotenv("config.env")
API_OPENROUTER = os.getenv("API_OPENROUTER")
API_TOKEN = os.getenv("API_TG")
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL")

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=API_OPENROUTER,
)

DEFAULT_DAILY_LIMIT = 10
DAILY_REQUEST_LIMIT = DEFAULT_DAILY_LIMIT

ADMIN_IDS = [842294603]

VIP_USERS = [
    842294603,
]

USER_DATA_FILE = "user_data.json"
VIP_DATA_FILE = "vip_users.json"
SETTINGS_FILE = "bot_settings.json"
user_requests: Dict[int, Dict] = {}

active_requests: Set[int] = set()

MAX_MESSAGE_LENGTH = 4096


def load_settings():
    global DAILY_REQUEST_LIMIT
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r') as f:
                settings = json.load(f)
                DAILY_REQUEST_LIMIT = settings.get('daily_limit', DEFAULT_DAILY_LIMIT)
                print(f"✅ Загружены настройки: дневной лимит = {DAILY_REQUEST_LIMIT}")
        except Exception as e:
            print(f"Ошибка загрузки настроек: {e}")
            DAILY_REQUEST_LIMIT = DEFAULT_DAILY_LIMIT
    else:
        save_settings()


def save_settings():
    try:
        settings = {
            'daily_limit': DAILY_REQUEST_LIMIT,
            'updated_at': datetime.now().isoformat()
        }
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=2)
    except Exception as e:
        print(f"Ошибка сохранения настроек: {e}")


def load_vip_users():
    global VIP_USERS
    if os.path.exists(VIP_DATA_FILE):
        try:
            with open(VIP_DATA_FILE, 'r') as f:
                VIP_USERS = json.load(f)
        except Exception as e:
            print(f"Ошибка загрузки VIP пользователей: {e}")


def save_vip_users():
    try:
        with open(VIP_DATA_FILE, 'w') as f:
            json.dump(VIP_USERS, f, indent=2)
    except Exception as e:
        print(f"Ошибка сохранения VIP пользователей: {e}")


def load_user_data():
    global user_requests
    if os.path.exists(USER_DATA_FILE):
        try:
            with open(USER_DATA_FILE, 'r') as f:
                user_requests = {int(k): v for k, v in json.load(f).items()}
        except Exception as e:
            print(f"Ошибка загрузки данных: {e}")
            user_requests = {}
    else:
        user_requests = {}


def save_user_data():
    try:
        with open(USER_DATA_FILE, 'w') as f:
            json.dump(user_requests, f, indent=2, default=str)
    except Exception as e:
        print(f"Ошибка сохранения данных: {e}")


def get_today_string():
    return datetime.now().strftime("%Y-%m-%d")


def check_user_limit(user_id: int) -> tuple[bool, int]:
    if user_id in VIP_USERS:
        return True, -1

    today = get_today_string()

    if user_id not in user_requests:
        user_requests[user_id] = {"count": 0, "date": today}

    user_data = user_requests[user_id]

    if user_data.get("date") != today:
        user_data["count"] = 0
        user_data["date"] = today
        save_user_data()

    remaining = DAILY_REQUEST_LIMIT - user_data["count"]
    can_use = remaining > 0

    return can_use, remaining


def increment_user_count(user_id: int):
    if user_id in VIP_USERS:
        return

    today = get_today_string()

    if user_id not in user_requests:
        user_requests[user_id] = {"count": 0, "date": today}

    user_requests[user_id]["count"] += 1
    save_user_data()


def split_text(text: str, max_length: int = MAX_MESSAGE_LENGTH) -> list:
    if len(text) <= max_length:
        return [text]

    parts = []
    while text:
        if len(text) <= max_length:
            parts.append(text)
            break

        split_pos = max_length

        newline_pos = text.rfind('\n', 0, max_length)
        if newline_pos != -1 and newline_pos > max_length * 0.7:
            split_pos = newline_pos
        else:
            space_pos = text.rfind(' ', 0, max_length)
            if space_pos != -1 and space_pos > max_length * 0.7:
                split_pos = space_pos

        parts.append(text[:split_pos].strip())
        text = text[split_pos:].strip()

    return parts


async def send_long_message(message: types.Message, text: str, parse_mode: str = None):
    parts = split_text(text)

    for i, part in enumerate(parts):
        try:
            if len(parts) > 1:
                part_text = f"📝 Часть {i + 1}/{len(parts)}\n\n{part}"
            else:
                part_text = part

            try:
                await message.answer(part_text, parse_mode=parse_mode)
            except Exception as format_error:
                print(f"Ошибка форматирования: {format_error}")
                await message.answer(part_text)

            if i < len(parts) - 1:
                await asyncio.sleep(0.5)

        except Exception as e:
            await message.answer(f"Ошибка при отправке части {i + 1}: {str(e)}")


async def get_ai_response(user_text: str) -> str:
    try:
        loop = asyncio.get_event_loop()
        completion = await loop.run_in_executor(
            None,
            lambda: client.chat.completions.create(
                extra_body={},
                model=DEFAULT_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_text}
                ]
            )
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f"Произошла ошибка при обращении к AI: {str(e)}"


@dp.message(Command("prompt"))
async def handle_prompt(message: types.Message, command: CommandObject):
    user_id = message.from_user.id
    user_name = message.from_user.full_name

    if user_id in active_requests:
        await message.answer(
            "⏳ Пожалуйста, дождитесь ответа на предыдущий запрос перед отправкой нового.\n"
            "Ваш запрос уже обрабатывается..."
        )
        return

    can_use, remaining = check_user_limit(user_id)

    if not can_use:
        await message.answer(
            f"❌ {user_name}, вы исчерпали дневной лимит запросов ({DAILY_REQUEST_LIMIT}).\n"
            f"🔄 Лимит обновится завтра.\n\n"
            f"💎 Для получения безлимитного доступа обратитесь к администратору."
        )
        return

    user_text = command.args

    if not user_text:
        await message.answer("Пожалуйста, напишите текст после команды /prompt")
        return

    active_requests.add(user_id)

    if remaining == -1:
        status_text = "👑 VIP-статус: безлимитные запросы"
    else:
        status_text = f"📊 Осталось запросов сегодня: {remaining - 1}/{DAILY_REQUEST_LIMIT}"

    processing_msg = await message.answer(
        f"🤖 Обрабатываю ваш запрос...\n{status_text}"
    )

    try:
        answer = await get_ai_response(user_text)
        increment_user_count(user_id)

        await processing_msg.delete()

        if len(answer) > MAX_MESSAGE_LENGTH:
            await message.answer(f"📊 Получен длинный ответ ({len(answer)} символов). Разбиваю на части...")
            await asyncio.sleep(0.5)

        await send_long_message(message, answer, parse_mode="Markdown")

    except Exception as e:
        try:
            await processing_msg.delete()
        except:
            pass
        await message.answer(f"❌ Произошла ошибка: {str(e)}")
    finally:
        active_requests.discard(user_id)


@dp.message(Command("start"))
async def handle_start(message: types.Message):
    user_id = message.from_user.id
    user_name = message.from_user.full_name

    can_use, remaining = check_user_limit(user_id)

    if user_id in VIP_USERS:
        status = "👑 У вас VIP-статус с безлимитным доступом!"
    else:
        status = f"📊 У вас осталось {remaining}/{DAILY_REQUEST_LIMIT} запросов на сегодня"

    welcome_text = f"""
👋 Привет, {user_name}!

Я AI-бот с дневными лимитами на использование.

{status}

📝 Команды:
/prompt [текст] - отправить запрос к AI
/status - проверить оставшиеся запросы
/help - помощь

Пример:
/prompt Расскажи о космосе
    """
    await message.answer(welcome_text)


@dp.message(Command("status"))
async def handle_status(message: types.Message):
    user_id = message.from_user.id
    user_name = message.from_user.full_name

    can_use, remaining = check_user_limit(user_id)

    is_processing = "🔄 Обрабатывается запрос" if user_id in active_requests else "✅ Готов к работе"

    if user_id in VIP_USERS:
        status_text = f"""
👤 Пользователь: {user_name}
👑 Статус: VIP
♾ Запросов: Безлимит
✅ Доступ: Разрешен
🚀 Состояние: {is_processing}
        """
    else:
        if can_use:
            access_status = "✅ Разрешен"
        else:
            access_status = "❌ Исчерпан на сегодня"

        user_data = user_requests.get(user_id, {"count": 0, "date": get_today_string()})
        used_today = user_data["count"]

        status_text = f"""
👤 Пользователь: {user_name}
📊 Статус: Обычный пользователь
📈 Использовано сегодня: {used_today}/{DAILY_REQUEST_LIMIT}
💫 Осталось: {remaining}
🔄 Доступ: {access_status}
🚀 Состояние: {is_processing}
⏰ Лимит обновится: завтра в 00:00
        """

    await message.answer(status_text)


@dp.message(Command("help"))
async def handle_help(message: types.Message):
    help_text = f"""
📖 **Справка по боту**

🤖 Этот бот использует AI для ответов на ваши вопросы.

**Команды:**
• /prompt [текст] - отправить запрос к AI
• /status - проверить ваш статус и лимиты
• /help - показать эту справку
• /start - начать работу с ботом

**Лимиты:**
• Обычные пользователи: {DAILY_REQUEST_LIMIT} запросов в день
• VIP пользователи: без ограничений
• Лимит обновляется каждый день в 00:00

**Пример использования:**
/prompt Объясни теорию относительности простыми словами

💎 Для получения VIP-доступа обратитесь к администратору.

⚠️ **Важно:** Нельзя отправлять новый запрос, пока не получен ответ на предыдущий!
    """
    await message.answer(help_text, parse_mode="Markdown")


@dp.message(Command("set_limit"))
async def handle_set_limit(message: types.Message, command: CommandObject):
    global DAILY_REQUEST_LIMIT

    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ У вас нет прав для выполнения этой команды.")
        return

    args = command.args
    if not args:
        await message.answer(
            f"📋 **Использование команды:**\n"
            f"/set_limit [число]\n\n"
            f"Текущий лимит: {DAILY_REQUEST_LIMIT} запросов в день\n\n"
            f"Пример: /set_limit 20",
            parse_mode="Markdown"
        )
        return

    try:
        new_limit = int(args.split()[0])
        if new_limit < 1:
            await message.answer("❌ Лимит должен быть больше 0")
            return
        if new_limit > 1000:
            await message.answer("❌ Лимит не может быть больше 1000")
            return

    except (ValueError, IndexError):
        await message.answer("❌ Неверный формат. Используйте целое число.\nПример: /set_limit 20")
        return

    old_limit = DAILY_REQUEST_LIMIT
    DAILY_REQUEST_LIMIT = new_limit
    save_settings()

    change_text = f"""
✅ **Дневной лимит успешно изменен!**

📊 Старый лимит: {old_limit} запросов
📈 Новый лимит: {new_limit} запросов
📅 Применено: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

ℹ️ Изменение затронет всех обычных пользователей.
VIP пользователи по-прежнему имеют безлимитный доступ.
    """

    await message.answer(change_text, parse_mode="Markdown")


@dp.message(Command("add_vip"))
async def handle_add_vip(message: types.Message, command: CommandObject):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ У вас нет прав для выполнения этой команды.")
        return

    args = command.args
    if not args:
        await message.answer(
            "📋 **Использование команды:**\n"
            "/add_vip [user_id]\n\n"
            "Пример: /add_vip 123456789",
            parse_mode="Markdown"
        )
        return

    try:
        new_vip_id = int(args.split()[0])
    except (ValueError, IndexError):
        await message.answer("❌ Неверный формат ID. Используйте числовой ID пользователя.")
        return

    if new_vip_id not in VIP_USERS:
        VIP_USERS.append(new_vip_id)
        save_vip_users()
        await message.answer(
            f"✅ Пользователь {new_vip_id} добавлен в VIP список!\n"
            f"👑 Всего VIP пользователей: {len(VIP_USERS)}"
        )
    else:
        await message.answer(f"ℹ️ Пользователь {new_vip_id} уже в VIP списке.")


@dp.message(Command("remove_vip"))
async def handle_remove_vip(message: types.Message, command: CommandObject):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ У вас нет прав для выполнения этой команды.")
        return

    args = command.args
    if not args:
        await message.answer(
            "📋 **Использование команды:**\n"
            "/remove_vip [user_id]\n\n"
            "Пример: /remove_vip 123456789",
            parse_mode="Markdown"
        )
        return

    try:
        vip_id_to_remove = int(args.split()[0])
    except (ValueError, IndexError):
        await message.answer("❌ Неверный формат ID. Используйте числовой ID пользователя.")
        return

    if vip_id_to_remove in VIP_USERS:
        VIP_USERS.remove(vip_id_to_remove)
        save_vip_users()
        await message.answer(
            f"✅ Пользователь {vip_id_to_remove} удален из VIP списка!\n"
            f"👑 Осталось VIP пользователей: {len(VIP_USERS)}"
        )
    else:
        await message.answer(f"ℹ️ Пользователь {vip_id_to_remove} не найден в VIP списке.")


@dp.message(Command("list_vip"))
async def handle_list_vip(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ У вас нет прав для выполнения этой команды.")
        return

    if not VIP_USERS:
        await message.answer("📋 VIP список пуст.")
        return

    vip_list = "👑 **Список VIP пользователей:**\n\n"
    for i, vip_id in enumerate(VIP_USERS, 1):
        vip_list += f"{i}. ID: `{vip_id}`\n"

    vip_list += f"\n📊 Всего: {len(VIP_USERS)} пользователей"

    await message.answer(vip_list, parse_mode="Markdown")


@dp.message(Command("admin_help"))
async def handle_admin_help(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ У вас нет прав для выполнения этой команды.")
        return

    admin_help_text = f"""
🔧 Админские команды:

  Управление лимитами:
• /set_limit [число] - установить дневной лимит запросов
  Текущий лимит: {DAILY_REQUEST_LIMIT}

  Управление VIP:
• /add_vip [user_id] - добавить пользователя в VIP
• /remove_vip [user_id] - удалить пользователя из VIP
• /list_vip - показать список всех VIP пользователей

  Статистика:
• /admin_help - показать эту справку

  Примеры использования:
• /set_limit 20
• /add_vip 123456789
• /remove_vip 123456789

📊 Текущая статистика:
• Дневной лимит: {DAILY_REQUEST_LIMIT} запросов
• VIP пользователей: {len(VIP_USERS)}
• Активных запросов: {len(active_requests)}
    """

    await message.answer(admin_help_text)


async def reset_daily_limits():
    while True:
        now = datetime.now()
        tomorrow = now + timedelta(days=1)
        midnight = datetime.combine(tomorrow.date(), time.min)
        seconds_until_midnight = (midnight - now).total_seconds()

        await asyncio.sleep(seconds_until_midnight)

        global user_requests
        user_requests = {}
        save_user_data()
        print(f"🔄 Дневные лимиты сброшены в {datetime.now()}")


async def main():
    print("=" * 50)
    print("Бот запущен")

    load_settings()
    load_user_data()
    load_vip_users()

    print(f"Дневной лимит: {DAILY_REQUEST_LIMIT} запросов")
    print(f"VIP пользователей: {len(VIP_USERS)}")
    print(f"Администраторов: {len(ADMIN_IDS)}")
    print("=" * 50)

    asyncio.create_task(reset_daily_limits())

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
