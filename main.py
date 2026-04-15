import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from config import TOKEN

bot = Bot(token=TOKEN)
dp = Dispatcher()

# База данных "на коленке" (пока без PostgreSQL, чтобы ты мог запустить сейчас)
users = {} 

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    if user_id not in users:
        users[user_id] = {"balance": 1000, "wins": 0}
        await message.answer(f"Привет, {message.from_user.full_name}! 👋\nТебе начислено 1000 угадаек!")
    else:
        await message.answer("Ты уже в игре! Пиши /profile")

@dp.message(Command("profile"))
async def cmd_profile(message: types.Message):
    user_id = message.from_user.id
    data = users.get(user_id, {"balance": 0, "wins": 0})
    await message.answer(f"👤 Профиль:\n💰 Баланс: {data['balance']}\n🏆 Побед: {data['wins']}")

async def main():
    print("Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
