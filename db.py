from motor.motor_asyncio import AsyncIOMotorClient
import redis.asyncio as aioredis
from dotenv import load_dotenv
import os

load_dotenv()

mongo = AsyncIOMotorClient(os.getenv("MONGO_URL"))
db    = mongo[os.getenv("MONGO_DB", "test")]
cache = aioredis.from_url(os.getenv("REDIS_URL"))
