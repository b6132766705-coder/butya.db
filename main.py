
Action: file_editor create /app/backend/telegram_bot/bot.py --file-text "import asyncio
import random
import os
import re
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

from database import init_db, async_session, User, RouletteLog

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.getenv(\"BOT_TOKEN\")
if not TOKEN:
    raise ValueError(\"BOT_TOKEN не установлен! Добавьте его в переменные окружения.\")

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)


class GuessState(StatesGroup):
    guessing = State()


# Словарь активных ставок: {chat_id: {user_id: [bets]}}
active_bets = {}

# Красные числа в рулетке
RED_NUMS = [1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]


# ---------- КЛАВИАТУРА ----------
def get_main_keyboard(chat_type: str):
    \"\"\"Создание клавиатуры в зависимости от типа чата\"\"\"
    builder = ReplyKeyboardBuilder()

    if chat_type == 'private':
        builder.button(text=\"👤 Профиль\")
        builder.button(text=\"🔢 Угадай число\")
        builder.button(text=\"📜 Помощь\")
        builder.button(text=\"🏆 Рейтинг\")
    else:
        builder.button(text=\"👤 Профиль\")
        builder.button(text=\"🔢 Угадай число\")
        builder.button(text=\"📊 Ставки\")
        builder.button(text=\"❌ Отменить\")

    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)


# ---------- МАТЕМАТИКА ----------
def check_win(bet_target: str, res_num: int) -> tuple[bool, float]:
    \"\"\"
    Проверка выигрыша ставки
    Возвращает (выиграл ли, множитель)
    \"\"\"
    res_num = int(res_num)
    is_red = res_num in RED_NUMS

    # Красное
    if bet_target == 'к':
        return (is_red and res_num != 0), 2

    # Чёрное
    if bet_target == 'ч':
        return (not is_red and res_num != 0), 2

    # Чётное
    if bet_target == 'чт':
        return (res_num % 2 == 0 and res_num != 0), 2

    # Нечётное
    if bet_target == 'нч':
        return (res_num % 2 != 0), 2

    # Диапазон (например 1-18)
    if '-' in bet_target:
        try:
            start, end = map(int, bet_target.split('-'))
            if start > end:
                start, end = end, start
            count = (end - start) + 1
            if count <= 0 or count > 36:
                return False, 0
            return (start <= res_num <= end and res_num != 0), (36 / count)
        except ValueError:
            return False, 0

    # Конкретное число
    if bet_target.isdigit():
        target_num = int(bet_target)
        if 0 <= target_num <= 36:
            return (target_num == res_num), 36
        return False, 0

    return False, 0


# ---------- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ----------
async def get_or_create_user(session, tg_id: int, username: str) -> User:
    \"\"\"Получить пользователя или создать нового\"\"\"
    user = await session.get(User, tg_id)
    if not user:
        user = User(tg_id=tg_id, username=username, balance=1000, wins=0)
        session.add(user)
        await session.commit()
        await session.refresh(user)
    return user


def escape_markdown(text: str) -> str:
    \"\"\"Экранирование специальных символов для MarkdownV2\"\"\"
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return ''.join(f'\\{char}' if char in escape_chars else char for char in str(text))


# ---------- ХЕНДЛЕРЫ ----------

@dp.message(Command(\"start\"))
async def cmd_start(message: types.Message):
    \"\"\"Обработчик команды /start\"\"\"
    try:
        async with async_session() as session:
            user = await session.get(User, message.from_user.id)
            if not user:
                user = User(
                    tg_id=message.from_user.id,
                    username=message.from_user.first_name or \"Игрок\",
                    balance=1000,
                    wins=0
                )
                session.add(user)
            else:
                user.username = message.from_user.first_name or user.username
            await session.commit()

        await message.answer(
            \"🎰 Добро пожаловать в Рулетку!\n\n\"
            \"💰 Ваш начальный баланс: 1000 🔘\n\"
            \"Используйте кнопки ниже для навигации.\",
            reply_markup=get_main_keyboard(message.chat.type)
        )
    except Exception as e:
        logger.error(f\"Ошибка в cmd_start: {e}\")
        await message.answer(\"Произошла ошибка. Попробуйте позже.\")


@dp.message(F.text.lower().in_([\"б\", \"b\", \"баланс\", \"👤 профиль\"]))
async def show_profile(message: types.Message):
    \"\"\"Показать профиль пользователя\"\"\"
    try:
        async with async_session() as session:
            user = await get_or_create_user(
                session,
                message.from_user.id,
                message.from_user.first_name or \"Игрок\"
            )

            response = (
                f\"👤 Игрок: {user.username}\n\"
                f\"💰 Баланс: {user.balance} 🔘\n\"
                f\"🏆 Побед: {user.wins}\"
            )
            await message.answer(response, reply_markup=get_main_keyboard(message.chat.type))
    except Exception as e:
        logger.error(f\"Ошибка в show_profile: {e}\")
        await message.answer(\"Не удалось загрузить профиль.\")


@dp.message(F.text == \"🔢 Угадай число\")
async def start_guess(message: types.Message, state: FSMContext):
    \"\"\"Начать игру 'Угадай число'\"\"\"
    number = random.randint(1, 10)
    await state.update_data(secret=number, attempts=3)
    await state.set_state(GuessState.guessing)
    await message.answer(\"🔢 Я загадал число от 1 до 10. Твой вариант?\")


@dp.message(GuessState.guessing)
async def process_guess(message: types.Message, state: FSMContext):
    \"\"\"Обработка попытки угадать число\"\"\"
    if not message.text or not message.text.isdigit():
        await message.answer(\"Введите число от 1 до 10!\")
        return

    user_guess = int(message.text)
    if user_guess < 1 or user_guess > 10:
        await message.answer(\"Число должно быть от 1 до 10!\")
        return

    data = await state.get_data()
    secret = data.get('secret')
    attempts = data.get('attempts', 0) - 1

    if user_guess == secret:
        try:
            async with async_session() as session:
                user = await get_or_create_user(
                    session,
                    message.from_user.id,
                    message.from_user.first_name or \"Игрок\"
                )
                user.balance += 200
                user.wins += 1
                await session.commit()
            await message.answer(
                \"🎉 Правильно! +200 🔘\",
                reply_markup=get_main_keyboard(message.chat.type)
            )
        except Exception as e:
            logger.error(f\"Ошибка при начислении выигрыша: {e}\")
            await message.answer(\"Ты угадал, но произошла ошибка с начислением.\")
        await state.clear()
    elif attempts > 0:
        await state.update_data(attempts=attempts)
        hint = \"🔼 Больше!\" if secret > user_guess else \"🔽 Меньше!\"
        await message.answer(f\"{hint} Осталось попыток: {attempts}\")
    else:
        await message.answer(
            f\"💀 Не угадал! Было загадано: {secret}\",
            reply_markup=get_main_keyboard(message.chat.type)
        )
        await state.clear()


@dp.message(F.text == \"📜 Помощь\")
async def btn_help(message: types.Message):
    \"\"\"Показать справку\"\"\"
    help_text = (
        \"🎰 КАК ИГРАТЬ В РУЛЕТКУ:\n\n\"
        \"Формат ставки: сумма цель\n\"
        \"Примеры:\n\"
        \"• 100 к - 100 на красное\n\"
        \"• 100 ч - 100 на чёрное\n\"
        \"• 50 чт - 50 на чётное\n\"
        \"• 50 нч - 50 на нечётное\n\"
        \"• 100 7 - 100 на число 7\n\"
        \"• 100 1-18 - 100 на диапазон\n\"
        \"• все к - всё на красное\n\n\"
        \"Напиши 'го' для запуска рулетки!\n\n\"
        \"🔢 УГАДАЙ ЧИСЛО:\n\"
        \"Угадай число от 1 до 10 за 3 попытки.\n\"
        \"Награда: +200 🔘\"
    )
    await message.answer(help_text)


@dp.message(F.text == \"📊 Ставки\")
async def txt_my_bets(message: types.Message):
    \"\"\"Показать текущие ставки пользователя\"\"\"
    chat_bets = active_bets.get(message.chat.id, {})
    user_bets = chat_bets.get(message.from_user.id, [])

    if not user_bets:
        await message.answer(\"❌ У тебя нет активных ставок.\")
        return

    text = \"📊 Твои текущие ставки:\n\n\"
    total = 0
    for bet in user_bets:
        text += f\"• {bet['amount']} ➔ {bet['target']}\n\"
        total += bet['amount']
    text += f\"\n💰 Всего поставлено: {total}\"

    await message.answer(text)


@dp.message(F.text == \"❌ Отменить\")
async def txt_cancel_bets(message: types.Message):
    \"\"\"Отменить все ставки пользователя\"\"\"
    chat_id = message.chat.id
    user_id = message.from_user.id

    chat_bets = active_bets.get(chat_id, {})
    user_bets = chat_bets.get(user_id, [])

    if not user_bets:
        await message.answer(\"❌ Нечего отменять!\")
        return

    total_return = sum(bet['amount'] for bet in user_bets)

    try:
        async with async_session() as session:
            user = await get_or_create_user(
                session,
                user_id,
                message.from_user.first_name or \"Игрок\"
            )
            user.balance += total_return
            await session.commit()

        del active_bets[chat_id][user_id]
        if not active_bets[chat_id]:
            del active_bets[chat_id]

        await message.answer(
            f\"❌ Ставки отменены!\n💰 Возвращено: +{total_return} 🔘\",
            reply_markup=get_main_keyboard(message.chat.type)
        )
    except Exception as e:
        logger.error(f\"Ошибка при отмене ставок: {e}\")
        await message.answer(\"Произошла ошибка при отмене ставок.\")


# ---------- СТАВКИ ----------
@dp.message(lambda m: m.text and re.match(r'^(все|\d+)\s+', m.text.lower()))
async def place_smart_bet(message: types.Message):
    \"\"\"Обработка ставок\"\"\"
    if message.chat.type == 'private':
        await message.answer(\"🎰 В рулетку играем только в группах!\nДобавь меня в группу.\")
        return

    parts = message.text.lower().split()
    if len(parts) < 2:
        return

    try:
        async with async_session() as session:
            user = await get_or_create_user(
                session,
                message.from_user.id,
                message.from_user.first_name or \"Игрок\"
            )

            # Определяем сумму ставки
            targets = parts[1:]
            if parts[0] == \"все\":
                if user.balance <= 0:
                    await message.answer(\"💸 У тебя нет денег!\")
                    return
                amount = user.balance // len(targets) if targets else user.balance
            else:
                try:
                    amount = int(parts[0])
                except ValueError:
                    return

            if amount <= 0:
                await message.answer(\"❌ Сумма должна быть больше 0!\")
                return

            # Проверяем и создаём ставки
            user_bets = []
            total_cost = 0

            valid_targets = ['к', 'ч', 'чт', 'нч']
            for target in targets:
                # Проверка валидности цели
                is_valid = (
                    target in valid_targets or
                    target.isdigit() and 0 <= int(target) <= 36 or
                    re.match(r'^\d+-\d+$', target)
                )

                if is_valid and user.balance >= total_cost + amount:
                    user_bets.append({\"amount\": amount, \"target\": target})
                    total_cost += amount

            if not user_bets:
                await message.answer(\"❌ Недостаточно средств или неверные цели!\")
                return

            user.balance -= total_cost
            await session.commit()

        # Сохраняем ставки
        if message.chat.id not in active_bets:
            active_bets[message.chat.id] = {}
        if message.from_user.id not in active_bets[message.chat.id]:
            active_bets[message.chat.id][message.from_user.id] = []

        active_bets[message.chat.id][message.from_user.id].extend(user_bets)

        # Формируем отчёт
        report = f\"✅ {message.from_user.first_name}, ставки приняты!\n\"
        report += f\"💸 Потрачено: {total_cost} 🔘\n\n\"
        report += \"📊 Твои ставки:\n\"
        for bet in user_bets:
            report += f\"• {bet['amount']} ➔ {bet['target']}\n\"

        await message.answer(report, reply_markup=get_main_keyboard(message.chat.type))

    except Exception as e:
        logger.error(f\"Ошибка при размещении ставки: {e}\")
        await message.answer(\"Произошла ошибка при размещении ставки.\")


# ---------- РУЛЕТКА ----------
@dp.message(F.text.lower() == \"го\")
async def spin_roulette(message: types.Message):
    \"\"\"Запуск рулетки\"\"\"
    chat_id = message.chat.id

    if chat_id not in active_bets or not active_bets[chat_id]:
        await message.answer(\"🎰 Ставок нет! Сначала сделайте ставки.\")
        return

    # Генерируем результат
    res_num = random.randint(0, 36)

    if res_num == 0:
        color = \"🟢 ЗЕРО\"
    elif res_num in RED_NUMS:
        color = \"🔴 КРАСНОЕ\"
    else:
        color = \"⚫️ ЧЁРНОЕ\"

    final_report = f\"🎰 Выпало: {color} {res_num}\n\n\"

    try:
        async with async_session() as session:
            # Логируем результат
            log_entry = RouletteLog(number=res_num, color=color)
            session.add(log_entry)

            # Обрабатываем ставки
            for user_id, bets in list(active_bets[chat_id].items()):
                user = await session.get(User, user_id)
                if not user:
                    continue

                user_total_win = 0
                final_report += f\"👤 {user.username}:\n\"

                for bet in bets:
                    win, mult = check_win(bet['target'], res_num)
                    if win:
                        prize = int(bet['amount'] * mult)
                        user_total_win += prize
                        final_report += f\"  ✅ {bet['amount']} ➔ {bet['target']} (+{prize})\n\"
                    else:
                        final_report += f\"  ❌ {bet['amount']} ➔ {bet['target']}\n\"

                user.balance += user_total_win
                if user_total_win > 0:
                    user.wins += 1

                final_report += f\"  💰 Итог: +{user_total_win} 🔘\n\n\"

            await session.commit()

        # Очищаем ставки
        active_bets[chat_id] = {}

        await message.answer(final_report, reply_markup=get_main_keyboard(message.chat.type))

    except Exception as e:
        logger.error(f\"Ошибка при запуске рулетки: {e}\")
        await message.answer(\"Произошла ошибка при запуске рулетки.\")


# ---------- УПРАВЛЕНИЕ ----------
@dp.message(F.text.lower() == \"лог\")
async def show_roulette_log(message: types.Message):
    \"\"\"Показать историю рулетки\"\"\"
    try:
        async with async_session() as session:
            from sqlalchemy import select
            result = await session.execute(
                select(RouletteLog)
                .order_by(RouletteLog.id.desc())
                .limit(10)
            )
            logs = result.scalars().all()

            if not logs:
                await message.answer(\"📜 История пуста.\")
                return

            text = \"📜 Последние 10 выпадений:\n\n\"
            for log in logs:
                text += f\"▫️ {log.color} {log.number}\n\"

            await message.answer(text)
    except Exception as e:
        logger.error(f\"Ошибка при показе лога: {e}\")
        await message.answer(\"Не удалось загрузить историю.\")


@dp.message(F.text == \"🏆 Рейтинг\")
async def show_leaderboard(message: types.Message):
    \"\"\"Показать рейтинг игроков\"\"\"
    try:
        async with async_session() as session:
            from sqlalchemy import select
            result = await session.execute(
                select(User)
                .order_by(User.balance.desc())
                .limit(10)
            )
            top_users = result.scalars().all()

            if not top_users:
                await message.answer(\"🏆 Рейтинг пуст.\")
                return

            text = \"🏆 ТОП-10 БОГАЧЕЙ:\n\n\"
            medals = [\"🥇\", \"🥈\", \"🥉\"]
            for i, user in enumerate(top_users, 1):
                medal = medals[i-1] if i <= 3 else f\"{i}.\"
                name = user.username or f\"ID: {user.tg_id}\"
                text += f\"{medal} {name} — {user.balance} 🔘\n\"

            await message.answer(text, reply_markup=get_main_keyboard(message.chat.type))
    except Exception as e:
        logger.error(f\"Ошибка при показе рейтинга: {e}\")
        await message.answer(\"Не удалось загрузить рейтинг.\")


async def main():
    \"\"\"Главная функция запуска бота\"\"\"
    logger.info(\"Инициализация базы данных...\")
    await init_db()
    logger.info(\"База данных готова.\")

    logger.info(\"Запуск бота...\")
    await dp.start_polling(bot)


if __name__ == \"__main__\":
    asyncio.run(main())
"
Observation: Create successful: /app/backend/telegram_bot/bot.py
