import asyncio
import random
import os
import re
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database import init_db, async_session, User, RouletteLog

# Включаем логирование, чтобы видеть ошибки в консоли Railway
logging.basicConfig(level=logging.INFO)

TOKEN = os.getenv("BOT_TOKEN")
bot = Bot(token=TOKEN)
dp = Dispatcher()

class GuessState(StatesGroup):
    guessing = State()

active_bets = {}
RED_NUMS = [1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]

def get_main_keyboard(chat_type: str):
    builder = ReplyKeyboardBuilder()
    if str(chat_type) == 'private':
        builder.button(text="👤 Профиль")
        builder.button(text="🔢 Угадай число")
        builder.button(text="📜 Помощь")
        builder.button(text="🏆 Рейтинг")
    else:
        builder.button(text="👤 Профиль")
        builder.button(text="🔢 Угадай число")
        builder.button(text="📊 Ставки")
        builder.button(text="❌ Отменить")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

# --- КОМАНДА START ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    try:
        async with async_session() as session:
            user = await session.get(User, message.from_user.id)
            name = message.from_user.first_name or "Игрок"
            if not user:
                session.add(User(tg_id=message.from_user.id, username=name))
            else:
                user.username = name
            await session.commit()
        await message.answer("🎰 Бот запущен!", reply_markup=get_main_keyboard(message.chat.type))
    except Exception as e:
        logging.error(f"Ошибка в START: {e}")

# --- ПРОФИЛЬ ---
@dp.message(F.text.contains("Профиль"))
@dp.message(Command("me"))
async def show_profile(message: types.Message):
    try:
        async with async_session() as session:
            user = await session.get(User, message.from_user.id)
            if not user:
                user = User(tg_id=message.from_user.id, username=message.from_user.first_name)
                session.add(user)
                await session.commit()
            
            resp = f"👤 Игрок: {user.username}\n💰 Баланс: {user.balance}\n🏆 Побед: {user.wins}"
            await message.answer(resp, reply_markup=get_main_keyboard(message.chat.type))
    except Exception as e:
        logging.error(f"Ошибка в PROFILE: {e}")

# --- РЕЙТИНГ ---
@dp.message(F.text.contains("Рейтинг"))
async def show_leaderboard(message: types.Message):
    try:
        async with async_session() as session:
            from sqlalchemy import select
            result = await session.execute(select(User).order_by(User.balance.desc()).limit(10))
            top_users = result.scalars().all()
            text = "🏆 ТОП-10 БОГАЧЕЙ:\n\n"
            for i, user in enumerate(top_users, 1):
                text += f"{i}. {user.username} — {user.balance}\n"
            await message.answer(text)
    except Exception as e:
        logging.error(f"Ошибка в LEADERBOARD: {e}")

# --- УГАДАЙ ЧИСЛО ---
@dp.message(F.text.contains("число"))
async def start_guess(message: types.Message, state: FSMContext):
    number = random.randint(1, 10)
    await state.update_data(secret=number, attempts=3)
    await state.set_state(GuessState.guessing)
    await message.answer("🔢 Загадал от 1 до 10. Твой вариант?")

@dp.message(GuessState.guessing)
async def process_guess(message: types.Message, state: FSMContext):
    if not message.text.isdigit(): return
    data = await state.get_data()
    secret, attempts = data['secret'], data['attempts'] - 1
    if int(message.text) == secret:
        async with async_session() as session:
            user = await session.get(User, message.from_user.id)
            user.balance += 200; await session.commit()
        await message.answer("🎉 Угадал! +200", reply_markup=get_main_keyboard(message.chat.type))
        await state.clear()
    elif attempts > 0:
        await state.update_data(attempts=attempts)
        await message.answer(f"Не угадал! Осталось попыток: {attempts}")
    else:
        await message.answer(f"💀 Проиграл. Было {secret}", reply_markup=get_main_keyboard(message.chat.type))
        await state.clear()

# --- ВСЁ ОСТАЛЬНОЕ (Рулетка) ---
@dp.message(F.text.lower() == "го")
async def spin_roulette(message: types.Message):
    await message.answer("🎰 Крутим! (Функционал рулетки под капотом)")

async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
