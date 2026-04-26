import os
import asyncio
import logging
import random
import aiosqlite
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

# --- НАСТРОЙКИ ---
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 1316137517
DB_PATH = "/app/data/butya.db"

# 1. Инициализация
logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()



# --- ФУНКЦИИ ---
async def init_db():
    if not os.path.exists("/app/data"):
        os.makedirs("/app/data", exist_ok=True)
    
    async with aiosqlite.connect(DB_PATH) as db:
        # Пользователи
        await db.execute('''CREATE TABLE IF NOT EXISTS users 
                           (id INTEGER PRIMARY KEY, balance INTEGER DEFAULT 10000, 
                            last_bonus TEXT, name TEXT, last_active TEXT, 
                            last_steal TEXT, shame_mark TEXT, clan_id INTEGER)''')
        
        # ТАБЛИЦА КЛАНОВ (Её не хватало!)
        await db.execute('''CREATE TABLE IF NOT EXISTS clans
                           (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                            name TEXT UNIQUE, 
                            owner_id INTEGER, 
                            balance INTEGER DEFAULT 0)''')
        
        # Таблица заявок
        await db.execute('''CREATE TABLE IF NOT EXISTS clan_requests 
                           (user_id INTEGER, clan_id INTEGER, 
                            PRIMARY KEY (user_id, clan_id))''')
        
        # История и инвентарь
        await db.execute('''CREATE TABLE IF NOT EXISTS history (number INTEGER)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS inventory 
                           (user_id INTEGER, item_name TEXT, amount INTEGER DEFAULT 1,
                            PRIMARY KEY (user_id, item_name))''')
        
        await db.execute("ALTER TABLE clans ADD COLUMN multiplier REAL DEFAULT 1.0")
        await db.execute("ALTER TABLE clans ADD COLUMN level INTEGER DEFAULT 1")
        await db.commit()
    except:
        pass # Если колонки уже есть, просто идем дальше


async def get_user(user_id, name):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT balance, last_bonus FROM users WHERE id = ?", (user_id,)) as cursor:
            res = await cursor.fetchone()
            
        if not res:
            await db.execute("INSERT INTO users (id, balance, name) VALUES (?, ?, ?)", (user_id, 10000, name))
            await db.commit()
            return (10000, None)
        else:
            await db.execute("UPDATE users SET name = ? WHERE id = ?", (name, user_id))
            await db.commit()
            return res

async def update_balance(user_id, amount):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (int(amount), user_id))
        await db.commit()

def fmt(num: int) -> str:
    """Форматирует числа, добавляя пробелы (10000 -> 10 000)"""
    return f"{num:,}".replace(",", " ")


# --- СОСТОЯНИЯ ---
class GameStates(StatesGroup):
    guessing = State()

pending_bets = {}
pending_duels = {}

class ClanStates(StatesGroup):
    waiting_for_name = State()


# --- КЛАВИАТУРЫ ---
def get_main_kb(chat_type):
    if chat_type == 'private':
        # Кнопки для лички (добавил Клан)
        buttons = [
            [KeyboardButton(text="🎮 Играть"), KeyboardButton(text="👤 Профиль")],
            [KeyboardButton(text="🏆 Рейтинг"), KeyboardButton(text="🛡 Клан")], # Вот она
            [KeyboardButton(text="🎁 Бонус"), KeyboardButton(text="🎒 Инвентарь")]
        ]
    else:
        # Кнопки для групп
        buttons = [
            [KeyboardButton(text="🎮 Играть"), KeyboardButton(text="👤 Профиль")],
            [KeyboardButton(text="📊 Ставки"), KeyboardButton(text="🚫 Отмена")]
        ]
    
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


# --- КОМАНДЫ ---

@dp.message(Command("start"))
async def cmd_start(message: Message):
    await get_user(message.from_user.id, message.from_user.full_name)
    await message.answer(
        f"Привет! Я — <b>Угадайка бот</b>. 🎰\n"
        f"Даю тебе стартовый капитал: {fmt(10000)} Угадаек!\n\n"
        f"Жми «Играть», чтобы испытать удачу!", 
        reply_markup=get_main_kb(message.chat.type),
        parse_mode="HTML"
    )


# --- СПИСОК КОМАНД ---
@dp.message(Command("commands", "comands", "help"))
async def cmd_commands(message: Message):
    help_text = (
        "🎮 <b>Все команды «Угадайка бот»:</b>\n\n"
        "<b>💰 Экономика:</b>\n"
        "• /start — Начать игру и получить бонус\n"
        "• <code>👤 Профиль</code> или <code>б</code> — Баланс\n"
        "• <code>🎁 Бонус</code> — Ежедневный подарок\n"
        "• <code>п [сумма]</code> (ответ) — Передать Угадайки\n"
        "• <code>🏆 Рейтинг</code> — Топ богачей\n\n"
        
        "<b>🎰 Азарт:</b>\n"
        "• <code>[сумма] [ставка]</code> — Ставка (число, к, ч)\n"
        "• <code>го</code> — Запуск рулетки\n"
        "• <code>лог</code> — История игр\n"
        "• <code>дуэль [сумма]</code> — Вызвать на бой\n"
        
        "<b>🛡 Кланы:</b>\n"
        "• <code>клан</code> — Меню клана\n"
        "• <code>Вступить [Название]</code> — Заявка\n\n"
        
        "<b>📜 Прочее:</b>\n"
        "• /rules — Правила игры\n"
        "• /commands — Этот список"
    )
    await message.answer(help_text, parse_mode="HTML")

# --- ПРАВИЛА ---
@dp.message(Command("rules"))
async def cmd_rules(message: Message):
    rules_text = (
        "📜 <b>Правила «Угадайка бот»</b>\n\n"
        "1️⃣ <b>Ставки:</b> Принимаются числа от 0 до 36, цвета (к, ч) и чет/нечет.\n"
        "2️⃣ <b>Запуск:</b> Только тот, кто сделал ставку, может прописать «го».\n"
        "3️⃣ <b>Кланы:</b> Создание клана стоит 20 000. Лидер управляет казной.\n"
        "4️⃣ <b>Награда:</b> Приглашай друзей в чат и получай <b>10 000</b> за каждого!\n"
        "5️⃣ <b>Штрафы:</b> Неудачная попытка кражи вешает клеймо клоуна на 3 часа.\n\n"
        # В блоке правил добавь строчку:
        "🛡 Щит — автоматически защищает от ограбления (расходуется при нападении)."

        "<i>Удачи в игре!</i>"
    )
    await message.answer(rules_text, parse_mode="HTML")


@dp.message(F.text == "👤 Профиль")
@dp.message(F.text.lower() == "б")
async def show_profile(message: Message):
    uid = message.from_user.id
    await get_user(uid, message.from_user.full_name) 
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT balance, shame_mark FROM users WHERE id = ?", (uid,)) as cursor:
            res = await cursor.fetchone()
    
    balance, shame_str = res
    status = "🟢 Обычный гражданин"
    
    if shame_str:
        shame_time = datetime.fromisoformat(shame_str)
        if datetime.now() < shame_time:
            left = shame_time - datetime.now()
            m = (left.seconds // 60) + 1
            status = f"🤡 Неудачливый воришка (еще {m} мин.)"

    await message.answer(f"👤 **Профиль:** {message.from_user.first_name}\n💰 **Баланс:** {fmt(balance)} Угадаек\n📝 **Статус:** {status}", parse_mode="Markdown")

@dp.message(F.text.lower().startswith("п "), F.reply_to_message)
async def transfer(message: Message):
    try:
        amount = int(message.text.split()[1])
        sender_id = message.from_user.id
        receiver = message.reply_to_message.from_user
        if amount <= 0 or sender_id == receiver.id: return
        
        res = await get_user(sender_id, message.from_user.full_name)
        bal = res[0]
        
        if bal < amount: return await message.answer("❌ Недостаточно Угадаек!")
        
        await update_balance(sender_id, -amount)
        await update_balance(receiver.id, amount)
        await message.answer(f"✅ Переведено {fmt(amount)} Угадаек для {receiver.first_name}")
    except: pass

@dp.message(F.text == "🎁 Бонус")
async def get_bonus(message: Message):
    res = await get_user(message.from_user.id, message.from_user.full_name)
    balance, last_bonus_str = res
    now = datetime.now()
    
    if last_bonus_str:
        last_b = datetime.fromisoformat(last_bonus_str)
        if now - last_b < timedelta(hours=24):
            left = timedelta(hours=24) - (now - last_b)
            h, rem = divmod(left.seconds, 3600)
            m, _ = divmod(rem, 60)
            return await message.answer(f"⏳ Бонус уже получен!\nВозвращайся через **{h} ч. {m} мин.**")

    bonus_amount = random.randint(100, 5000)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET balance = balance + ?, last_bonus = ? WHERE id = ?", 
                    (bonus_amount, now.isoformat(), message.from_user.id))
        await db.commit()
        
    await message.answer(f"🎁 Ты получил бонус: **{fmt(bonus_amount)}** Угадаек!")

# --- ЕДИНЫЙ РЕЙТИНГ (Кнопка + Команда) ---
@dp.message(F.text == "🏆 Рейтинг")
@dp.message(Command("top"))
async def show_rating(message: Message):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT name, balance, id FROM users ORDER BY balance DESC LIMIT 10") as cursor:
            top_users = await cursor.fetchall()
    
    if not top_users:
        return await message.answer("🏆 Список богачей пока пуст!")

    text = "🏆 <b>ТОП-10 МИЛЛИОНЕРОВ:</b>\n\n"
    medals = ["🥇", "🥈", "🥉"]
    
    for i, (name, bal, uid) in enumerate(top_users):
        place = medals[i] if i < 3 else f"<b>{i+1}.</b>"
        display_name = name if name else "Игрок"
        # Ссылка на профиль игрока
        text += f"{place} <a href='tg://user?id={uid}'>{display_name}</a> — <b>{fmt(bal)}</b>\n"
    
    await message.answer(text, parse_mode="HTML", disable_web_page_preview=True)


@dp.message(F.text == "📊 Ставки")
async def show_my_bets(message: Message):
    cid = message.chat.id
    uid = message.from_user.id
    if cid not in pending_bets or not any(b['user_id'] == uid for b in pending_bets[cid]):
        return await message.answer("У тебя нет активных ставок.")
    
    my_bets = [b for b in pending_bets[cid] if b['user_id'] == uid]
    text = "📝 Твои текущие ставки:\n"
    for b in my_bets:
        for t in b['targets']:
            text += f"• {fmt(b['amount'])} ➔ {t}\n"
    await message.answer(text)

@dp.message(F.text == "🚫 Отмена")
async def cancel_my_bets(message: Message):
    cid = message.chat.id
    uid = message.from_user.id
    if cid in pending_bets:
        user_bets = [b for b in pending_bets[cid] if b['user_id'] == uid]
        if user_bets:
            refund = sum(b['amount'] * len(b['targets']) for b in user_bets)
            pending_bets[cid] = [b for b in pending_bets[cid] if b['user_id'] != uid]
            await update_balance(uid, refund)
            return await message.answer(f"✅ Ставки отменены. Возвращено: {fmt(refund)}")
    await message.answer("У тебя нет активных Ставок")

@dp.message(F.text == "🎒 Инвентарь")
async def show_inventory(message: Message):
    uid = message.from_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT item_name, amount FROM inventory WHERE user_id = ? AND amount > 0", (uid,)) as cur:
            items = await cur.fetchall()
    
    if not items:
        return await message.answer("🎒 Твой инвентарь пуст. Пора бы чем-то закупиться!")
    
    text = "🎒 <b>Твой инвентарь:</b>\n\n"
    for name, count in items:
        text += f"• <b>{name}</b> — {count} шт.\n"
    
    text += "\n<i>Предметы можно использовать или продать (скоро!)</i>"
    await message.answer(text, parse_mode="HTML")

@dp.message(F.text.lower().startswith("использовать"))
async def use_item(message: Message):
    parts = message.text.split()
    if len(parts) < 2:
        return await message.answer("❓ Напиши название предмета. Пример: <code>использовать Шар</code>")

    item_name = " ".join(parts[1:]).strip()
    uid = message.from_user.id

    async with aiosqlite.connect(DB_PATH) as db:
        # Проверяем наличие предмета
        async with db.execute("SELECT amount FROM inventory WHERE user_id = ? AND item_name = ?", (uid, item_name)) as cur:
            row = await cur.fetchone()
        
        if not row or row[0] <= 0:
            return await message.answer(f"❌ У тебя нет предмета «<b>{item_name}</b>»", parse_mode="HTML")

        # --- ЛОГИКА ЭФФЕКТОВ ---
        if item_name.lower() == "шар":
            # Получаем текущий баланс
            async with db.execute("SELECT balance FROM users WHERE id = ?", (uid,)) as cur:
                user_row = await cur.fetchone()
                current_balance = user_row[0]

            new_balance = int(current_balance * 1.74)
            profit = new_balance - current_balance
            
            # Обновляем баланс
            await db.execute("UPDATE users SET balance = ? WHERE id = ?", (new_balance, uid))
            result_text = f"🔮 <b>Магия Шара!</b>\n\nТвои Угадайки умножились на <b>1.74</b>!\n➕ Прибавка: <b>{fmt(profit)}</b>"
        
        else:
            return await message.answer(f"⚙️ Предмет «<b>{item_name}</b>» пока не имеет активного эффекта.")

        # Списываем 1 единицу предмета после использования
        await db.execute("UPDATE inventory SET amount = amount - 1 WHERE user_id = ? AND item_name = ?", (uid, item_name))
        await db.commit()

    await message.answer(result_text, parse_mode="HTML")



# --- НАГРАДА ЗА ПРИГЛАШЕНИЕ ---
@dp.message(F.new_chat_members)
async def welcome_and_reward(message: Message):
    inviter = message.from_user
    new_members = message.new_chat_members
    
    humans_added = [m for m in new_members if not m.is_bot]
    if not humans_added: return

    total_reward = len(humans_added) * 10000
    await get_user(inviter.id, inviter.full_name)
    await update_balance(inviter.id, total_reward)
    
    names = ", ".join([m.first_name for m in humans_added])
    await message.answer(
        f"💎 <b>В Угадайка бот пополнение!</b>\n\n"
        f"👤 {inviter.first_name} привел новых игроков: <b>{names}</b>\n"
        f"💰 Твой баланс пополнен на <b>+{fmt(total_reward)}</b> Угадаек!",
        parse_mode="HTML"
    )



# --- МИНИ-ИГРА: УГАДАЙ ЧИСЛО ---
@dp.message(F.text == "🎮 Играть")
async def start_guess(message: Message, state: FSMContext):
    num = random.randint(1, 10)
    await state.set_state(GameStates.guessing)
    await state.update_data(target=num, attempts=3)
    await message.answer("Я загадал число от 1 до 10. У тебя 3 попытки! Пиши число:")

@dp.message(GameStates.guessing)
async def process_guess(message: Message, state: FSMContext):
    if message.text.lower() == "отмена":
        await state.clear()
        return await message.answer("Игра отменена.", reply_markup=get_main_kb(message.chat.type))

    if not message.text.isdigit(): 
        return await message.answer("Пожалуйста, введи только цифры! (Или напиши «Отмена»)")
    
    # ... дальше идет твой старый код проверки попыток ...
        
    guess = int(message.text)
    data = await state.get_data()
    target = data['target']
    attempts = data['attempts'] - 1

    if guess == target:
        await update_balance(message.from_user.id, 50)
        await message.answer(f"🎉 Угадал! +{fmt(50)} Угадаек.", reply_markup=get_main_kb(message.chat.type))
        await state.clear()
    elif attempts > 0:
        hint = "Больше!" if target > guess else "Меньше!"
        await state.update_data(attempts=attempts)
        await message.answer(f"Неверно. {hint} Осталось попыток: {attempts}")
    else:
        await message.answer(f"Попытки кончились! Это было {target}.", reply_markup=get_main_kb(message.chat.type))
        await state.clear()
#-------------------------------------------------------------------------
# ------------------------------- КЛАНЫ ----------------------------------
#-------------------------------------------------------------------------

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

@dp.message(F.text.lower() == "клан")
@dp.message(F.text == "🛡 Клан")
async def clan_menu(message: Message):
    uid = message.from_user.id
    
    async with aiosqlite.connect(DB_PATH) as db:
        # 1. Ищем клан пользователя
        async with db.execute("SELECT clan_id FROM users WHERE id = ?", (uid,)) as cur:
            user_row = await cur.fetchone()
            clan_id = user_row[0] if user_row else None

        if not clan_id:
            # Если нет клана — предлагаем создать или вступить
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✨ Создать клан (20к)", callback_data="clan_create_flow")],
                [InlineKeyboardButton(text="🏆 Топ кланов", callback_data="clan_top")]
            ])
            return await message.answer("🛡 <b>Кланы</b>\n\nВы пока не состоите в клане. Объединяйтесь с друзьями, чтобы захватить лидерство!", reply_markup=kb, parse_mode="HTML")

        # 2. Получаем данные клана
        query = """
            SELECT clans.name, clans.owner_id, clans.balance, users.name 
            FROM clans 
            JOIN users ON clans.owner_id = users.id 
            WHERE clans.id = ?
        """
        async with db.execute(query, (clan_id,)) as cur:
            clan_data = await cur.fetchone()
        
        c_name, c_owner_id, c_bal, owner_name = clan_data

        async with db.execute("SELECT COUNT(id) FROM users WHERE clan_id = ?", (clan_id,)) as cur:
            members_count = (await cur.fetchone())[0]

        # 3. Формируем кнопки
        buttons = [
            [InlineKeyboardButton(text="💰 Пополнить казну", callback_data="clan_deposit")],
            [InlineKeyboardButton(text="👥 Список участников", callback_data="clan_members")]
        ]

        if uid == c_owner_id:
            # Кнопки только для лидера
            buttons.append([InlineKeyboardButton(text="⚙️ Управление кланом", callback_data="clan_admin")])
            buttons.append([InlineKeyboardButton(text="💎 Магазин улучшений", callback_data="clan_upgrades")])
        else:
            # Кнопка для выхода обычного участника
            buttons.append([InlineKeyboardButton(text="🚪 Покинуть клан", callback_data="clan_leave_confirm")])

        kb = InlineKeyboardMarkup(inline_keyboard=buttons)

        # 4. Текст сообщения
        role_icon = "👑" if uid == c_owner_id else "👤"
        role_name = "Лидер" if uid == c_owner_id else "Участник"

        text = (
            f"🛡 <b>Клан: {c_name}</b>\n"
            f"👑 <b>Лидер:</b> {owner_name}\n"
            f"👤 <b>Заместитель:</b> —\n"
            f"💰 <b>Казна:</b> {fmt(c_bal)} Угадаек\n"
            f"👥 <b>Количество членов:</b> {members_count}/10\n\n"
            f"<b>Твоя роль:</b> {role_icon} {role_name}"
        )

        await message.answer(text, reply_markup=kb, parse_mode="HTML")

# --- СОЗДАНИЕ КЛАНА ---
@dp.message(F.text.lower() == "создать клан")
async def create_clan_start(message: Message, state: FSMContext):
    uid = message.from_user.id
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT balance, clan_id FROM users WHERE id = ?", (uid,)) as cur:
            bal, c_id = await cur.fetchone()
            
        if c_id:
            return await message.answer("❌ Ты уже состоишь в клане! Сначала покинь его.")
        if bal < 20000:
            return await message.answer("❌ Создание клана стоит 20 000 Угадаек. Накопи еще немного!")
            
    await state.set_state(ClanStates.waiting_for_name)
    await message.answer("🛡 Введи название для своего нового клана (до 20 символов):", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🚫 Отмена")]], resize_keyboard=True))

@dp.message(ClanStates.waiting_for_name)
async def create_clan_finish(message: Message, state: FSMContext):
    if message.text == "🚫 Отмена":
        await state.clear()
        return await message.answer("Создание клана отменено.", reply_markup=get_main_kb(message.chat.type))
        
    clan_name = message.text.strip()
    if len(clan_name) > 20:
        return await message.answer("Слишком длинное название! Придумай что-то короче (до 20 символов).")
        
    uid = message.from_user.id
    
    async with aiosqlite.connect(DB_PATH) as db:
        # Проверяем, не занято ли имя
        async with db.execute("SELECT id FROM clans WHERE name = ?", (clan_name,)) as cur:
            if await cur.fetchone():
                return await message.answer("❌ Клан с таким названием уже существует! Придумай другое.")
                
        # Списываем деньги и создаем
        await db.execute("UPDATE users SET balance = balance - 20000 WHERE id = ?", (uid,))
        cursor = await db.execute("INSERT INTO clans (name, owner_id, balance) VALUES (?, ?, 0)", (clan_name, uid))
        new_clan_id = cursor.lastrowid
        await db.execute("UPDATE users SET clan_id = ? WHERE id = ?", (new_clan_id, uid))
        await db.commit()
        
    await state.clear()
    await message.answer(f"🎉 <b>Клан «{clan_name}» успешно создан!</b>\nТеперь ты лидер.", reply_markup=get_main_kb(message.chat.type), parse_mode="HTML")

# --- ВСТУПЛЕНИЕ В КЛАН ---
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

@dp.message(F.text.lower().startswith("вступить "))
async def join_request(message: Message):
    uid = message.from_user.id
    clan_name = message.text[9:].strip()
    
    async with aiosqlite.connect(DB_PATH) as db:
        # 1. Проверяем, не в клане ли уже игрок
        async with db.execute("SELECT clan_id FROM users WHERE id = ?", (uid,)) as cur:
            if (await cur.fetchone())[0]:
                return await message.answer("❌ Ты уже состоишь в клане!")
                
        # 2. Ищем клан
        async with db.execute("SELECT id, owner_id, name FROM clans WHERE name = ?", (clan_name,)) as cur:
            clan_data = await cur.fetchone()
            
        if not clan_data:
            return await message.answer(f"❌ Клан «{clan_name}» не найден.")
            
        clan_id, owner_id, c_name = clan_data

        # 3. Проверяем количество участников (лимит 10)
        async with db.execute("SELECT COUNT(id) FROM users WHERE clan_id = ?", (clan_id,)) as cur:
            count = (await cur.fetchone())[0]
            if count >= 10:
                return await message.answer("❌ В этом клане уже достигнут лимит участников (10/10).")

        # 4. Создаем заявку в базе
        try:
            await db.execute("INSERT INTO clan_requests (user_id, clan_id) VALUES (?, ?)", (uid, clan_id))
            await db.commit()
        except aiosqlite.IntegrityError:
            return await message.answer("⏳ Ты уже отправил заявку в этот клан. Жди ответа лидера.")

        # 5. Уведомляем лидера
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Принять", callback_data=f"clan_accept:{uid}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"clan_decline:{uid}")
            ]
        ])
        
        try:
            await bot.send_message(
                owner_id, 
                f"🔔 <b>Новая заявка в клан!</b>\nИгрок {message.from_user.full_name} хочет вступить в твой клан «{c_name}».",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            await message.answer(f"✅ Заявка в клан <b>{c_name}</b> отправлена лидеру!", parse_mode="HTML")
        except Exception:
            await message.answer("❌ Не удалось отправить уведомление лидеру (возможно, бот у него заблокирован).")

@dp.callback_query(F.data.startswith("clan_accept:"))
async def accept_member(callback: CallbackQuery):
    applicant_id = int(callback.data.split(":")[1])
    leader_id = callback.from_user.id
    
    async with aiosqlite.connect(DB_PATH) as db:
        # Узнаем ID клана лидера
        async with db.execute("SELECT id FROM clans WHERE owner_id = ?", (leader_id,)) as cur:
            clan_data = await cur.fetchone()
            if not clan_data: return
            clan_id = clan_data[0]

        # Проверяем лимит еще раз (на случай, если пока лидер думал, кто-то другой зашел)
        async with db.execute("SELECT COUNT(id) FROM users WHERE clan_id = ?", (clan_id,)) as cur:
            if (await cur.fetchone())[0] >= 10:
                return await callback.answer("❌ Лимит участников (10) уже исчерпан!", show_alert=True)

        # Добавляем игрока в клан и удаляем заявку
        await db.execute("UPDATE users SET clan_id = ? WHERE id = ?", (clan_id, applicant_id))
        await db.execute("DELETE FROM clan_requests WHERE user_id = ?", (applicant_id,))
        await db.commit()

    await callback.message.edit_text("✅ Ты принял нового участника!")
    try:
        await bot.send_message(applicant_id, "🎉 Твоя заявка в клан была одобрена! Добро пожаловать.")
    except: pass

@dp.callback_query(F.data.startswith("clan_decline:"))
async def decline_member(callback: CallbackQuery):
    applicant_id = int(callback.data.split(":")[1])
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM clan_requests WHERE user_id = ?", (applicant_id,))
        await db.commit()

    await callback.message.edit_text("❌ Ты отклонил заявку.")
    try:
        await bot.send_message(applicant_id, "😔 Твоя заявка в клан была отклонена лидером.")
    except: pass

# --- ПОПОЛНЕНИЕ КАЗНЫ И ВЫХОД ---
@dp.message(F.text.lower().startswith("в казну "))
async def donate_to_clan(message: Message):
    try:
        amount = int(message.text.split()[2])
        if amount <= 0: return
    except:
        return
        
    uid = message.from_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT balance, clan_id FROM users WHERE id = ?", (uid,)) as cur:
            user_data = await cur.fetchone()
            
        if not user_data[1]:
            return await message.answer("❌ Ты не состоишь в клане!")
        if user_data[0] < amount:
            return await message.answer("❌ Недостаточно Угадаек на балансе.")
            
        # Переводим деньги
        await db.execute("UPDATE users SET balance = balance - ? WHERE id = ?", (amount, uid))
        await db.execute("UPDATE clans SET balance = balance + ? WHERE id = ?", (amount, user_data[1]))
        await db.commit()
        
    await message.answer(f"💰 Ты пожертвовал <b>{fmt(amount)}</b> Угадаек в казну клана!", parse_mode="HTML")

@dp.message(F.text.lower().startswith("из казны "))
async def withdraw_from_clan(message: Message):
    try:
        # Команда состоит из 3 слов: "из" [0], "казны" [1], "сумма" [2]
        amount = int(message.text.split()[2])
        if amount <= 0: return
    except:
        return await message.answer("❓ Правильный формат: <code>из казны 1000</code>", parse_mode="HTML")
        
    uid = message.from_user.id
    
    async with aiosqlite.connect(DB_PATH) as db:
        # 1. Узнаем, в каком клане игрок
        async with db.execute("SELECT clan_id FROM users WHERE id = ?", (uid,)) as cur:
            user_data = await cur.fetchone()
            
        if not user_data or not user_data[0]:
            return await message.answer("❌ Ты не состоишь в клане!")
            
        clan_id = user_data[0]
        
        # 2. Узнаем, кто лидер и сколько денег в казне
        async with db.execute("SELECT owner_id, balance FROM clans WHERE id = ?", (clan_id,)) as cur:
            clan_data = await cur.fetchone()
            
        if not clan_data:
            return
            
        owner_id, clan_balance = clan_data
        
        # 3. Проверки прав и баланса
        if uid != owner_id:
            return await message.answer("❌ Только <b>Лидер</b> может брать деньги из казны!", parse_mode="HTML")
            
        if clan_balance < amount:
            return await message.answer(f"❌ В казне недостаточно средств! Доступно: <b>{fmt(clan_balance)}</b>", parse_mode="HTML")
            
        # 4. Переводим деньги из клана лидеру
        await db.execute("UPDATE clans SET balance = balance - ? WHERE id = ?", (amount, clan_id))
        await db.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (amount, uid))
        await db.commit()
        
    await message.answer(f"👑 Ты вывел <b>{fmt(amount)}</b> Угадаек из казны клана в свой карман!", parse_mode="HTML")

@dp.message(F.text.lower() == "покинуть клан")
async def leave_clan(message: Message):
    uid = message.from_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT clan_id FROM users WHERE id = ?", (uid,)) as cur:
            c_id = (await cur.fetchone())[0]
            
        if not c_id: return
        
        async with db.execute("SELECT owner_id FROM clans WHERE id = ?", (c_id,)) as cur:
            owner_id = (await cur.fetchone())[0]
            
        if uid == owner_id:
            return await message.answer("👑 Лидер не может просто так покинуть клан! (Функция роспуска клана в разработке)")
            
        await db.execute("UPDATE users SET clan_id = NULL WHERE id = ?", (uid,))
        await db.commit()
        
    await message.answer("🚪 Ты покинул клан.")

@dp.callback_query(F.data == "clan_top")
async def show_clan_top(callback: CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        query = "SELECT name, balance FROM clans ORDER BY balance DESC LIMIT 5"
        async with db.execute(query) as cur:
            top_clans = await cur.fetchall()
    
    text = "🏆 <b>ТОП-5 БОГАТЕЙШИХ КЛАНОВ</b>\n\n"
    for i, (name, bal) in enumerate(top_clans, 1):
        text += f"{i}. 🛡 <b>{name}</b> — {fmt(bal)} Угадаек\n"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="clan_main")]])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data == "clan_members")
async def clan_members_list(callback: CallbackQuery):
    uid = callback.from_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        # Получаем clan_id игрока
        async with db.execute("SELECT clan_id FROM users WHERE id = ?", (uid,)) as cur:
            cid = (await cur.fetchone())[0]
        
        # Получаем список всех членов клана
        async with db.execute("SELECT id, name FROM users WHERE clan_id = ?", (cid,)) as cur:
            members = await cur.fetchall()
            
        # Узнаем, кто лидер
        async with db.execute("SELECT owner_id FROM clans WHERE id = ?", (cid,)) as cur:
            owner_id = (await cur.fetchone())[0]

    text = "👥 <b>Участники клана:</b>\n\n"
    buttons = []
    
    for m_id, m_name in members:
        role = "👑" if m_id == owner_id else "👤"
        text += f"{role} {m_name} (ID: {m_id})\n"
        
        # Если смотрит лидер, добавляем кнопки управления для каждого (кроме него самого)
        if uid == owner_id and m_id != owner_id:
            buttons.append([
                InlineKeyboardButton(text=f"❌ Выгнать {m_name}", callback_data=f"kick_{m_id}"),
                InlineKeyboardButton(text=f"👑 Передать", callback_data=f"transfer_{m_id}")
            ])

    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="clan_main")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


#----------------------------Магазин улучшений (Logic)-----------------------
@dp.callback_query(F.data == "clan_upgrades")
async def clan_upgrades_menu(callback: CallbackQuery):
    uid = callback.from_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, balance, multiplier, level, owner_id FROM clans WHERE owner_id = ?", (uid,)) as cur:
            clan = await cur.fetchone()
        
        if not clan:
            return await callback.answer("❌ Только лидер может заходить в магазин!", show_alert=True)
        
        cid, balance, mult, lvl, owner = clan
        upgrade_cost = lvl * 50000 # Цена растет с уровнем

        text = (
            f"🛒 <b>Магазин улучшений</b>\n\n"
            f"Текущий уровень: <b>{lvl}</b>\n"
            f"Множитель выигрыша: <b>x{mult}</b>\n\n"
            f"🔹 <b>Улучшение: Удачливый клан</b>\n"
            f"Дает +0.1 к каждому выигрышу в рулетке всем участникам.\n"
            f"💰 Стоимость: <b>{fmt(upgrade_cost)}</b> из казны."
        )
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"✅ Купить (Ур. {lvl+1})", callback_data=f"buy_upgrade_luck")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="clan_main")]
        ])
        
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data == "buy_upgrade_luck")
async def buy_upgrade(callback: CallbackQuery):
    uid = callback.from_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, balance, level FROM clans WHERE owner_id = ?", (uid,)) as cur:
            clan = await cur.fetchone()
        
        cid, balance, lvl = clan
        cost = lvl * 50000
        
        if balance < cost:
            return await callback.answer("❌ В казне недостаточно средств!", show_alert=True)
        
        # Списываем деньги и повышаем уровень/множитель
        await db.execute("UPDATE clans SET balance = balance - ?, level = level + 1, multiplier = multiplier + 0.1 WHERE id = ?", (cost, cid))
        await db.commit()
        
        await callback.answer("🎉 Улучшение куплено! Весь клан стал удачливее.", show_alert=True)
        await clan_upgrades_menu(callback) # Обновляем меню

# --- РУЛЕТКА ---
def is_valid_bet_format(m: Message):
    if not m.text: return False
    parts = m.text.lower().split()
    if len(parts) < 2: return False # Должно быть хотя бы 2 слова (сумма + ставка)
    
    first_word = parts[0]
    if not (first_word.isdigit() or first_word in ["все", "всё"]):
        return False
        
    return True

@dp.message(is_valid_bet_format)
async def take_bet(message: Message):
    if message.chat.type == "private":
        return await message.answer("🎰 В рулетку можно играть только в группах! Добавь меня в чат с друзьями.")
    parts = message.text.split()
    if len(parts) < 2:
        return 

    try:
        raw_targets = [t.lower() for t in parts[1:]]
        valid_targets = []
        invalid_targets = []
        
        for t in raw_targets:
            if t in ["к", "кр", "красное", "ч", "чр", "черное", "чет", "нечет"]:
                valid_targets.append(t)
            elif t.isdigit() and 0 <= int(t) <= 36:
                valid_targets.append(t)
            elif "-" in t:
                try:
                    low, high = map(int, t.split("-"))
                    if 0 <= low <= 36 and 0 <= high <= 36 and low < high:
                        valid_targets.append(t)
                    else:
                        invalid_targets.append(t)
                except:
                    invalid_targets.append(t)
            else:
                invalid_targets.append(t)
                
        if invalid_targets:
            return await message.answer(f"❌ Ошибка в купоне!\nЯ не понимаю эти ставки: **{', '.join(invalid_targets)}**\n\nРазрешены: числа (0-36), цвета (к, ч), чет/нечет и диапазоны (например 1-18).", parse_mode="Markdown")
        
        targets = valid_targets
        count = len(targets)

        uid = message.from_user.id
        user_name = message.from_user.full_name
        res = await get_user(uid, user_name)
        bal = res[0]
        
        first_word = parts[0].lower() 

        if first_word in ["все", "всё"]:
            amount = bal // count  
            if amount <= 0:
                return await message.answer("❌ Твоего баланса не хватит!")
        else:
            amount = int(first_word)
            if amount <= 0: return

        total_needed = amount * count
        if bal < total_needed:
            return await message.answer(f"❌ Не хватает Угадаек!\nВаш баланс: {fmt(bal)}\nНужно: {fmt(total_needed)}")

        cid = message.chat.id
        if cid not in pending_bets:
            pending_bets[cid] = []
        
        pending_bets[cid].append({
            "user_id": uid, 
            "name": message.from_user.first_name, 
            "amount": amount, 
            "targets": targets
        })
        
        await update_balance(uid, -total_needed)
        
        report = f"✅ Ставок принято: {count}\n"
        if first_word in ["все", "всё"]:
            report += f"🔥 **ВА-БАНК!**\n"
        
        report += f"💸 Потрачено: {fmt(total_needed)}\n\n📊 **Ваш купон:**\n"
        for t in targets:
            report += f"• {fmt(amount)} ➔ {t}\n"
            
        await message.answer(report, parse_mode="Markdown")
        
    except Exception as e:
        logging.error(f"Ошибка в ставке: {e}")

@dp.message(F.text.lower() == "go")
@dp.message(F.text.lower() == "го")
async def spin(message: Message):
    if message.chat.type == "private":
        return await message.answer("🎰 В рулетку можно играть только в группах!")
    
    cid = message.chat.id
    if cid not in pending_bets or not pending_bets[cid]:
        return await message.answer("🎰 Ставок пока нет!")

    # 1. Крутим колесо
    res_num = random.randint(0, 36)
    
    # Открываем соединение с БД для записи истории и проверки кланов
    async with aiosqlite.connect(DB_PATH) as db:
        # Сохраняем в историю
        await db.execute("INSERT INTO history (number) VALUES (?)", (res_num,))
        await db.commit()

        # Определяем цвет для заголовка
        red_numbers = [1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]
        if res_num == 0:
            header_color = "🟢 ЗЕРО"
            res_color_key = "зеро"
        elif res_num in red_numbers:
            header_color = "🔴 КРАСНОЕ"
            res_color_key = "к"
        else:
            header_color = "⚫ ЧЁРНОЕ"
            res_color_key = "ч"

        header_text = f"🎰 {header_color} {res_num}\n\n"
        user_reports = []

        # 2. Обрабатываем ставки каждого игрока
        for bet in pending_bets[cid]:
            uid = bet['user_id']
            name = bet['name']
            amount = bet['amount']
            targets = bet['targets']
            
            # --- НОВАЯ ЛОГИКА: Получаем клановый множитель игрока ---
            query = "SELECT multiplier FROM clans WHERE id = (SELECT clan_id FROM users WHERE id = ?)"
            async with db.execute(query, (uid,)) as cur:
                row = await cur.fetchone()
                clan_mult = row[0] if row else 1.0 # Если нет клана, множитель 1.0
            
            total_won = 0
            target_lines = []
            
            for t in targets:
                is_win = False
                mult = 0
                
                if t.isdigit() and int(t) == res_num:
                    is_win, mult = True, 36
                elif t in ["к", "кр", "красное"] and res_color_key == "к":
                    is_win, mult = True, 2
                elif t in ["ч", "чр", "черное"] and res_color_key == "ч":
                    is_win, mult = True, 2
                elif t == "чет" and res_num != 0 and res_num % 2 == 0:
                    is_win, mult = True, 2
                elif t == "нечет" and res_num % 2 != 0:
                    is_win, mult = True, 2
                elif "-" in t:
                    low, high = map(int, t.split("-"))
                    if low <= res_num <= high:
                        is_win, mult = True, 2

                if is_win:
                    # ПРИМЕНЯЕМ КЛАНОВЫЙ МНОЖИТЕЛЬ
                    current_win = int(amount * mult * clan_mult) 
                    total_won += current_win
                    target_lines.append(f"✅ {fmt(amount)} ➔ {t}")
                else:
                    target_lines.append(f"❌ {fmt(amount)} ➔ {t}")

            # Рассчитываем чистый итог (сколько выиграл минус сколько поставил)
            total_spent = amount * len(targets)
            profit_loss = total_won - total_spent
            
            if total_won > 0:
                await update_balance(uid, total_won)

            user_block = f"👤 {name}:\n" + "\n".join(target_lines)
            
            # Если множитель больше 1, добавляем пометку о бонусе
            sign = "+" if profit_loss > 0 else ""
            bonus_text = f" (x{clan_mult} 💎)" if clan_mult > 1.0 else ""
            user_block += f"\n💰 Итог: {sign}{fmt(profit_loss)}{bonus_text}"
            
            user_reports.append(user_block)

    # 3. Собираем всё сообщение и отправляем
    final_text = header_text + "\n\n".join(user_reports)
    pending_bets[cid] = []
    
    await message.answer(final_text, parse_mode="HTML")

@dp.message(F.text.lower() == "лог")
async def show_history(message: Message):
    async with aiosqlite.connect(DB_PATH) as db:
        # Достаем 10 последних записей
        async with db.execute("SELECT number FROM history ORDER BY rowid DESC LIMIT 10") as cursor:
            rows = await cursor.fetchall()

    if not rows:
        return await message.answer("📜 История игр пока пуста.")

    red_numbers = [1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]
    history_lines = []

    for i, (num,) in enumerate(rows, 1):
        if num == 0:
            color_circle = "🟢"
            color_name = "ЗЕРО"
        elif num in red_numbers:
            color_circle = "🔴"
            color_name = "КРАСНОЕ"
        else:
            color_circle = "⚫"
            color_name = "ЧЁРНОЕ"
        
        history_lines.append(f"{i}. 🎰 {color_circle} {color_name} {num}")

    res_text = "📜 <b>История:</b>\n\n" + "\n".join(history_lines)
    await message.answer(res_text, parse_mode="HTML")

# --- ИГРА: ДУЭЛЬ ---
@dp.message(F.text.lower().startswith("дуэль ") | F.text.lower().startswith("дуель "), F.reply_to_message)
async def start_duel(message: Message):
    if message.chat.type == "private":
        return await message.answer("❌ Дуэли возможны только в группах!")

    try:
        parts = message.text.split()
        if len(parts) < 2: return
        
        amount = int(parts[1])
        if amount <= 0: return
        
        challenger = message.from_user 
        victim = message.reply_to_message.from_user 
        
        if challenger.id == victim.id:
            return await message.answer("🤔 Самострел запрещен! Выбери другого оппонента.")
        if victim.is_bot:
            return await message.answer("🤖 Боты бессмертны, с ними нет смысла стреляться.")

        res_c = await get_user(challenger.id, challenger.full_name)
        c_bal = res_c[0]
        
        res_v = await get_user(victim.id, victim.full_name)
        v_bal = res_v[0]

        if c_bal < amount:
            return await message.answer(f"❌ У тебя не хватает {fmt(amount)} Угадаек!")
        if v_bal < amount:
            return await message.answer(f"❌ У {victim.first_name} маловато денег для такой дуэли.")

        cid = message.chat.id
        if cid not in pending_duels:
            pending_duels[cid] = {}
            
        pending_duels[cid][victim.id] = {
            "challenger_id": challenger.id,
            "challenger_name": challenger.first_name,
            "amount": amount
        }

        kb = ReplyKeyboardMarkup(keyboard=[
            [KeyboardButton(text="🤝 Принять дуэль")]
        ], resize_keyboard=True, one_time_keyboard=True)

        await message.answer(
            f"🔫 <b>{challenger.first_name}</b> вызывает на дуэль <b>{victim.first_name}</b>!\n"
            f"💰 Ставка: <b>{fmt(amount)}</b> Угадаек.\n\n"
            f"<i>{victim.first_name}, ты принимаешь вызов?</i>",
            reply_markup=kb, parse_mode="HTML"
        )
    except Exception as e:
        logging.error(f"Ошибка дуэли: {e}")

@dp.message(F.text == "🤝 Принять дуэль")
async def accept_duel(message: Message):
    if message.chat.type == "private": return
    
    cid = message.chat.id
    vid = message.from_user.id 
    
    if cid not in pending_duels or vid not in pending_duels[cid]:
        return 
        
    duel = pending_duels[cid].pop(vid) 
    amount = duel["amount"]
    cid_challenger = duel["challenger_id"]
    c_name = duel["challenger_name"]
    v_name = message.from_user.first_name
    
    res_c = await get_user(cid_challenger, c_name)
    c_bal = res_c[0]
    
    res_v = await get_user(vid, v_name)
    v_bal = res_v[0]
    
    if c_bal < amount or v_bal < amount:
        return await message.answer("❌ Дуэль сорвалась: у кого-то закончились деньги!", reply_markup=get_main_kb(message.chat.type))
        
    await update_balance(cid_challenger, -amount)
    await update_balance(vid, -amount)
    
    winner_is_challenger = random.choice([True, False])
    total_win = amount * 2
    
    if winner_is_challenger:
        await update_balance(cid_challenger, total_win)
        winner_name, loser_name = c_name, v_name
    else:
        await update_balance(vid, total_win)
        winner_name, loser_name = v_name, c_name

    await message.answer(
        f"💥 ПАХ!\n\n🏆 <b>{winner_name}</b> оказался быстрее и застрелил <b>{loser_name}</b>!\n"
        f"💰 Весь банк в размере <b>{fmt(total_win)}</b> Угадаек уходит победителю!",
        parse_mode="HTML", reply_markup=get_main_kb(message.chat.type)
    )


# --- АДМИН-ЧИТ: ОБНУЛЕНИЕ ТАЙМЕРОВ ---
@dp.message(lambda m: m.text and m.text.lower().startswith("обнулить"))
async def admin_reset(message: Message):
    logging.info(f"Команда 'обнулить' от ID: {message.from_user.id}")

    if message.from_user.id != ADMIN_ID:
        return 

    target_user = message.reply_to_message.from_user if message.reply_to_message else message.from_user
    
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""UPDATE users SET 
                           last_steal = NULL, 
                           shame_mark = NULL, 
                           last_bonus = NULL 
                           WHERE id = ?""", (target_user.id,))
            await db.commit()
        
        await message.answer(f"🪄 **Магия!** Таймеры для {target_user.first_name} сброшены.")
    except Exception as e:
        logging.error(f"Ошибка при обнулении: {e}")
        await message.answer("❌ Произошла ошибка в базе данных.")

# --- АДМИН-КОМАНДЫ (ИСПРАВЛЕННЫЕ) ---

@dp.message(F.reply_to_message, F.text.lower().startswith("+предмет"), lambda m: m.from_user.id == ADMIN_ID)
async def admin_give_item(message: Message):
    parts = message.text.split()
    try:
        item_name = parts[1]
        amount = int(parts[2]) if len(parts) > 2 else 1
        target_id = message.reply_to_message.from_user.id
        target_name = message.reply_to_message.from_user.first_name

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO inventory (user_id, item_name, amount) 
                VALUES (?, ?, ?) 
                ON CONFLICT(user_id, item_name) DO UPDATE SET amount = amount + ?
            """, (target_id, item_name, amount, amount))
            await db.commit()
        
        await message.answer(f"🪄 Админ выдал <b>{target_name}</b> предмет: <b>{item_name}</b> ({amount} шт.)", parse_mode="HTML")
    except Exception as e:
        await message.answer("❌ Ошибка. Пример: <code>+предмет Клевер 5</code>")


@dp.message(F.reply_to_message, F.text.lower().startswith("-предмет"), lambda m: m.from_user.id == ADMIN_ID)
async def admin_take_item(message: Message):
    parts = message.text.split()
    try:
        item_name = parts[1]
        amount = int(parts[2]) if len(parts) > 2 else 1
        target_id = message.reply_to_message.from_user.id
        
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                UPDATE inventory SET amount = MAX(0, amount - ?) 
                WHERE user_id = ? AND item_name = ?
            """, (amount, target_id, item_name))
            await db.commit()
        
        await message.answer(f"🧹 Админ изъял у игрока предмет: <b>{item_name}</b> ({amount} шт.)", parse_mode="HTML")
    except:
        await message.answer("❌ Ошибка. Пример: <code>-предмет Шар 1</code>")



# Стало:
@dp.message(F.reply_to_message, lambda m: m.from_user.id == ADMIN_ID)
async def admin_balance_change(message: Message):
    if message.text.startswith(("+", "-")) and "предмет" not in message.text.lower():
        try:
            val = int(message.text.replace(" ", ""))
            await update_balance(message.reply_to_message.from_user.id, val)
            await message.answer(f"👑 Изменено на {fmt(val)}")
        except: pass




# --- ЗАПУСК ---
async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Бот выключен")
