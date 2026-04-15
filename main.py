import asyncio
import random
import os
import re
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from aiogram.fsm.context import FSMContext

from database import init_db, async_session, User

TOKEN = os.getenv("BOT_TOKEN")
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Хранилище ставок: {chat_id: {user_id: [список ставок]}}
active_bets = {}

# Цвета рулетки
RED_NUMS = [1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]

# --- КЛАВИАТУРА (REPLY) ---
def get_main_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.button(text="👤 Профиль")
    builder.button(text="🔢 Угадай число")
    builder.button(text="📜 Помощь")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

# --- ВСПОМОГАТЕЛЬНЫЕ функции -----------
def check_win(bet_target, res_num):
    res_num = int(res_num)
    is_red = res_num in RED_NUMS
    is_even = res_num % 2 == 0 and res_num != 0

    # Ставки на цвет и четность — всегда х2
    if bet_target == 'к': return (is_red and res_num != 0), 2
    if bet_target == 'ч': return (not is_red and res_num != 0), 2
    if bet_target == 'чт': return is_even, 2
    if bet_target == 'нч': return (not is_even and res_num != 0), 2
    
    # СТАВКА НА ДИАПАЗОН (умная математика)
    if '-' in bet_target:
        try:
            start, end = map(int, bet_target.split('-'))
            # Считаем, сколько чисел внутри диапазона
            count = (end - start) + 1
            
            if count <= 0 or count > 37: return False, 0
            
            # Вычисляем множитель: 36 делим на количество чисел
            # Используем float деление, чтобы получить точный коэффициент
            multiplier = 36 / count
            
            # Проверяем, попало ли выпавшее число в диапазон
            return (start <= res_num <= end), multiplier
        except: 
            return False, 0
        
    # Ставка на конкретное число — всегда х36
    if bet_target.isdigit():
        return (int(bet_target) == res_num), 36
        
    return False, 0

# --- ХЕНДЛЕРЫ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    async with async_session() as session:
        user = await session.get(User, message.from_user.id)
        if not user:
            session.add(User(tg_id=message.from_user.id))
            await session.commit()
    await message.answer("🎰 Добро пожаловать! Используй кнопки ниже:", reply_markup=get_main_keyboard())

@dp.message(F.text == "👤 Профиль")
async def show_profile(message: types.Message):
    async with async_session() as session:
        user = await session.get(User, message.from_user.id)
        await message.answer(f"👤 Игрок: {message.from_user.first_name}\n💰 Баланс: {user.balance} 🔘\n🏆 Побед: {user.wins}")

# --- ОБРАБОТЧИК ДЛЯ КНОПКИ "🔢 Угадай число" ---
@dp.message(F.text == "🔢 Угадай число")
async def btn_start_guess(message: types.Message, state: FSMContext):
    # Просто вызываем ту же функцию, что и для команды /guess
    await start_guess(message, state)

# --- ОБРАБОТЧИК ДЛЯ КНОПКИ "📜 Помощь" ---
@dp.message(F.text == "📜 Помощь")
async def btn_help(message: types.Message):
    help_text = (
        "🎮 **Как играть?**\n\n"
        "🔢 **Угадай число:** Я загадываю число от 1 до 10, у тебя 3 попытки.\n\n"
        "🎰 **Рулетка (в чатах):**\n"
        "Пиши: `сумма` `цели` через пробел.\n"
        "Пример: `100 к 7 чт 1-5` — это 4 ставки по 100.\n"
        "Затем напиши **'го'**, чтобы крутить!"
    )
    await message.answer(help_text, parse_mode="Markdown")

# --- НОВЫЙ ОБРАБОТЧИК МУЛЬТИ-СТАВОК (ОДНА СУММА - МНОГО ЦЕЛЕЙ) ---
# --- ОБРАБОТЧИК СТАВОК (ВКЛЮЧАЯ "ВСЕ") ---
@dp.message(lambda m: re.match(r'^(все|\d+)\s+', m.text.lower()))
async def place_smart_bet(message: types.Message):
    chat_id = message.chat.id
    parts = message.text.lower().split()
    if len(parts) < 2: return

    async with async_session() as session:
        user = await session.get(User, message.from_user.id)
        
        # Определяем сумму ставки
        if parts[0] == "все":
            if user.balance <= 0: return await message.reply("❌ У тебя 0 на балансе!")
            # Делим весь баланс на количество целей
            amount = user.balance // (len(parts) - 1)
            if amount < 1: return await message.reply("❌ Слишком мало денег для такого количества ставок!")
        else:
            amount = int(parts[0])

        user_bets = []
        total_cost = 0

        for target in parts[1:]:
            if re.match(r'^(к|ч|чт|нч|\d+-\d+|\d+)$', target):
                if user.balance >= total_cost + amount:
                    user_bets.append({"amount": amount, "target": target})
                    total_cost += amount
                else:
                    break

        if not user_bets:
            return await message.reply("❌ Недостаточно средств или неверный формат!")

        user.balance -= total_cost
        await session.commit()

    # Сохраняем ставки
    if chat_id not in active_bets: active_bets[chat_id] = {}
    if message.from_user.id not in active_bets[chat_id]: active_bets[chat_id][message.from_user.id] = []
    active_bets[chat_id][message.from_user.id].extend(user_bets)

    report = f"✅ Ставок: {len(user_bets)}\n💸 Потрачено: {total_cost}\n\n📊 Твои ставки:\n"
    for b in user_bets:
        report += f"• {b['amount']} ➔ {b['target']}\n"
    await message.answer(report)


# --- ЗАПУСК ПО КОМАНДЕ "ГО" ---
@dp.message(F.text.lower() == "го")
async def spin_roulette(message: types.Message):
    chat_id = message.chat.id
    if chat_id not in active_bets or not active_bets[chat_id]:
        return await message.answer("🎰 Ставок еще нет! Напишите ставку, например: `100 к`")

    res_num = random.randint(0, 36)
    color_emoji = "🔴 КРАСНОЕ" if res_num in RED_NUMS else "⚫️ ЧЕРНОЕ" if res_num != 0 else "🟢 ЗЕРО"
    
    final_report = f"🎰 {color_emoji} {res_num}\n\n"
    
    async with async_session() as session:
        # Проходим по всем игрокам в этом чате
        for user_id, bets in active_bets[chat_id].items():
            user = await session.get(User, user_id)
            user_total_win = 0
            user_name = (await bot.get_chat(user_id)).first_name
            
            final_report += f"👤 {user_name}:\n"
            
            for b in bets:
                # Внутри spin_roulette:
            is_win, mult = check_win(b['target'], res_num)
            if is_win:
                # Округляем до целого числа, если множитель дробный
                prize = int(b['amount'] * mult) 
                user_total_win += prize
                final_report += f"✅ {b['amount']} ➔ {b['target']} (Выигрыш: {prize})\n"
            else:
                final_report += f"❌ {b['amount']} ➔ {b['target']}\n"

            
            user.balance += user_total_win
            if user_total_win > 0: user.wins += 1
            final_report += f"💰 Итог: +{user_total_win}\n\n"
        
        await session.commit()

    active_bets[chat_id] = {} # Очищаем стол
    await message.answer(final_report)

async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
