from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from ..config import get_settings

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None


async def connect_mongo() -> None:
    global _client, _db
    settings = get_settings()
    _client = AsyncIOMotorClient(settings.mongodb_uri)
    _db = _client[settings.mongodb_db]
    # Verify connection
    await _client.admin.command("ping")


async def close_mongo() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None


def get_db() -> AsyncIOMotorDatabase:
    if _db is None:
        raise RuntimeError("MongoDB not connected. Call connect_mongo() first.")
    return _db
