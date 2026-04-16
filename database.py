from sqlalchemy import Column, Integer, BigInteger, String, create_url
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
import os

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_async_engine(DATABASE_URL)
async_session = async_sessionmaker(engine, expire_on_commit=False)
Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    tg_id = Column(BigInteger, primary_key=True)
    balance = Column(Integer, default=1000)
    wins = Column(Integer, default=0)
    username = Column(String, default="Игрок") # Колонка для имен

class RouletteLog(Base):
    __tablename__ = 'roulette_log'
    id = Column(Integer, primary_key=True)
    number = Column(Integer)
    color = Column(String)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
