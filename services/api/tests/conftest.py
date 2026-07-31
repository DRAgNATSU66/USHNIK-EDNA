import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, MagicMock, patch

from app.main import create_app
from app.auth.jwt import create_access_token
from app.models.user import UserRole
import app.db.mongo as _mongo_module


def _make_mock_collection():
    coll = MagicMock()
    coll.find_one = AsyncMock(return_value=None)
    coll.insert_one = AsyncMock(return_value=MagicMock(inserted_id="mock"))
    coll.insert_many = AsyncMock()
    coll.update_one = AsyncMock(return_value=MagicMock(matched_count=1))
    coll.update_many = AsyncMock(return_value=MagicMock(matched_count=0))
    coll.find = MagicMock(return_value=_AsyncCursor([]))
    coll.aggregate = MagicMock(return_value=_AsyncCursor([]))
    return coll


class _MockDb:
    """Fake AsyncIOMotorDatabase that returns a mock collection for any key."""
    def __getitem__(self, key):
        return _make_mock_collection()


class _AsyncCursor:
    def __init__(self, items):
        self._items = list(items)

    def skip(self, n):
        return self

    def limit(self, n):
        return self

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._items:
            return self._items.pop(0)
        raise StopAsyncIteration


@pytest.fixture
def app_instance():
    return create_app()


@pytest_asyncio.fixture
async def client(app_instance):
    """Test client with MongoDB module-level _db patched to a mock."""
    mock_db = _MockDb()
    mock_client = MagicMock()

    with patch.object(_mongo_module, "_db", mock_db), \
         patch.object(_mongo_module, "_client", mock_client):
        async with AsyncClient(
            transport=ASGITransport(app=app_instance), base_url="http://test"
        ) as ac:
            # Prevent real lifespan DB connection during tests
            yield ac


@pytest.fixture
def researcher_token():
    return create_access_token(
        "usr_test_001",
        {"email": "test@example.com", "role": UserRole.researcher, "name": "Test User"},
    )


@pytest.fixture
def admin_token():
    return create_access_token(
        "usr_admin_001",
        {"email": "admin@example.com", "role": UserRole.admin, "name": "Admin User"},
    )


@pytest.fixture
def curator_token():
    return create_access_token(
        "usr_curator_001",
        {"email": "curator@example.com", "role": UserRole.curator, "name": "Curator User"},
    )
