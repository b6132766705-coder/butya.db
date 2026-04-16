Сейчас создам исправленный код. Вот основные баги, которые я нашёл и исправлю:

1. **Отсутствует файл database.py** с моделями и настройкой БД
2. **Проблемы с async сессиями** - неправильная работа с контекстным менеджером
3. **Parse mode** - "Markdown" может вызывать проблемы с экранированием
4. **Обработка ошибок** - отсутствует в критических местах
Action: file_editor create /app/backend/telegram_bot/database.py --file-text "import os
from sqlalchemy import Column, Integer, BigInteger, String, DateTime, func
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base

# Получаем URL базы данных из переменных окружения
DATABASE_URL = os.getenv(\"DATABASE_URL\", \"postgresql+asyncpg://user:password@localhost:5432/roulette_bot\")

# Преобразуем URL для asyncpg если нужно
if DATABASE_URL.startswith(\"postgresql://\"):
    DATABASE_URL = DATABASE_URL.replace(\"postgresql://\", \"postgresql+asyncpg://\", 1)

# Создаём асинхронный движок
engine = create_async_engine(DATABASE_URL, echo=False)

# Фабрика сессий
async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)

Base = declarative_base()


class User(Base):
    __tablename__ = \"users\"

    tg_id = Column(BigInteger, primary_key=True)
    username = Column(String(255), nullable=True)
    balance = Column(Integer, default=1000)  # Начальный баланс
    wins = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())


class RouletteLog(Base):
    __tablename__ = \"roulette_logs\"

    id = Column(Integer, primary_key=True, autoincrement=True)
    number = Column(Integer, nullable=False)
    color = Column(String(50), nullable=False)
    created_at = Column(DateTime, server_default=func.now())


async def init_db():
    \"\"\"Инициализация базы данных - создание таблиц\"\"\"
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
"
Observation: Create successful: /app/backend/telegram_bot/database.py
