import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy import Column, BigInteger, Integer, String, DateTime
import datetime

# Берем ссылку на базу от Railway
DATABASE_URL = os.getenv("DATABASE_URL").replace("postgresql://", "postgresql+asyncpg://")

engine = create_async_engine(DATABASE_URL)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = 'users'
    tg_id = Column(BigInteger, primary_key=True)
    balance = Column(Integer, default=1000)
    wins = Column(Integer, default=0)
    username = Column(String, default="Игрок")


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

class RouletteLog(Base):
    __tablename__ = 'roulette_history'
    id = Column(Integer, primary_key=True)
    number = Column(Integer)
    color = Column(String)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)

