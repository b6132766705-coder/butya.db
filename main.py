import asyncio
import random
import os
import re
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database import init_db, async_session, User

TOKEN = os.getenv("BOT_TOKEN")
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Состояния для игры "Угадай число"
class GuessState(StatesGroup):
    guessing = State()

# Хранилище ставок: {chat_id: {user_id: [список ставок]}}
active_bets = {}

# Цвета рулетки
RED_NUMS = [1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]

# --- КЛАВИАТУРА ---
def get_main_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.button(text="👤 Профиль")
    builder.button(text="🔢 Угадай число")
    builder.button(text="📜 Помощь")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

# --- МАТЕМАТИКА РУЛЕТКИ ---
def check_win(bet_target, res_num):
    res_num = int(res_num)
    is_red = res_num in RED_NUMS
    is_even = res_num % 2 == 0 and res_num != 0

    if bet_target == 'к': return (is_red and res_num != 0), 2
    if bet_target == 'ч': return (not is_red and res_num != 0), 2
    if bet_target == 'чт': return is_even, 2
    if bet_target == 'нч': return (not is_even and res_num != 0), 2
    
    if '-' in bet_target:
        try:
            start, end = map(int, bet_target.split('-'))
            count = (end - start) + 1
            if count <= 0 or count > 37: return False, 0
            multiplier = 36 / count
            return (start <= res_num <= end), multiplier
        except: return False, 0
        
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

# --- ИГРА УГАДАЙ ЧИСЛО ---
@dp.message(F.text == "🔢 Угадай число")
async def start_guess(message: types.Message, state: FSMContext):
    number = random.randint(1, 10)
    await state.update_data(secret=number, attempts=3)
    await state.set_state(GuessState.guessing)
    await message.answer("🔢 Я загадал число от 1 до 10. У тебя 3 попытки! Твой вариант?")

@dp.message(GuessState.guessing)
async def process_guess(message: types.Message, state: FSMContext):
    if not message.text.isdigit(): return
    user_guess = int(message.text)
    data = await state.get_data()
    secret, attempts = data['secret'], data['attempts'] - 1

    if user_guess == secret:
        async with async_session() as session:
            user = await session.get(User, message.from_user.id)
            user.balance += 200
            user.wins += 1
            await session.commit()
        await message.answer(f"🎉 Угадал! +200 🔘", reply_markup=get_main_keyboard())
        await state.clear()
    elif attempts > 0:
        hint = "🔼 Больше" if secret > user_guess else "🔽 Меньше"
        await state.update_data(attempts=attempts)
        await message.answer(f"{hint}! Попыток: {attempts}")
    else:
        await message.answer(f"💀 Проигрыш! Было {secret}", reply_markup=get_main_keyboard())
        await state.clear()

@dp.message(F.text == "📜 Помощь")
async def btn_help(message: types.Message):
    await message.answer("🎰 **Рулетка:** `сумма` `цели` (через пробел)\nПример: `100 к 7 1-12` \nНапиши **'го'** для запуска!", parse_mode="Markdown")

# --- СТАВКИ ---
@dp.message(lambda m: re.match(r'^(все|\d+)\s+', m.text.lower()))
async def place_smart_bet(message: types.Message):
    chat_id = message.chat.id
    parts = message.text.lower().split()
    if len(parts) < 2: return

    async with async_session() as session:
        user = await session.get(User, message.from_user.id)
        if parts[0] == "все":
            if user.balance <= 0: return
            amount = user.balance // (len(parts) - 1)
        else:
            amount = int(parts[0])

        user_bets = []
        total_cost = 0
        for target in parts[1:]:
            if re.match(r'^(к|ч|чт|нч|\d+-\d+|\d+)$', target):
                if user.balance >= total_cost + amount:
                    user_bets.append({"amount": amount, "target": target})
                    total_cost += amount

        if not user_bets: return
        user.balance -= total_cost
        await session.commit()

    if chat_id not in active_bets: active_bets[chat_id] = {}
    if message.from_user.id not in active_bets[chat_id]: active_bets[chat_id][message.from_user.id] = []
    active_bets[chat_id][message.from_user.id].extend(user_bets)
    await message.answer(f"✅ Ставок: {len(user_bets)}\n💸 Потрачено: {total_cost}")

# --- ЗАПУСК РУЛЕТКИ ---
@dp.message(F.text.lower() == "го")
async def spin_roulette(message: types.Message):
    chat_id = message.chat.id
    if chat_id not in active_bets or not active_bets[chat_id]:
        return await message.answer("🎰 Ставок нет!")

    res_num = random.randint(0, 36)
    color = "🔴 КРАСНОЕ" if res_num in RED_NUMS else "⚫️ ЧЕРНОЕ" if res_num != 0 else "🟢 ЗЕРО"
    final_report = f"🎰 {color} {res_num}\n\n"
    
    async with async_session() as session:
        for user_id, bets in active_bets[chat_id].items():
            user = await session.get(User, user_id)
            user_total_win = 0
            user_info = await bot.get_chat(user_id)
            final_report += f"👤 {user_info.first_name}:\n"
            
            for b in bets:
                is_win, mult = check_win(b['target'], res_num)
                if is_win:
                    prize = int(b['amount'] * mult)
                    user_total_win += prize
                    final_report += f"✅ {b['amount']} ➔ {b['target']} (+{prize})\n"
                else:
                    final_report += f"❌ {b['amount']} ➔ {b['target']}\n"
            
            user.balance += user_total_win
            if user_total_win > 0: user.wins += 1
            final_report += f"💰 Итог: +{user_total_win}\n\n"
        await session.commit()

    active_bets[chat_id] = {}
    await message.answer(final_report)

async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
