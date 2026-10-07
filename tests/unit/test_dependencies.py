import pytest
from fastapi import HTTPException

from app.config import settings
from app.deps.auth import verify_api_key


async def test_valid_api_key_is_accepted() -> None:
    await verify_api_key(settings.auth.api_key.get_secret_value())


@pytest.mark.parametrize("api_key", [None, "", "wrong-key", "ключ"])
async def test_invalid_api_key_is_rejected(api_key: str | None) -> None:
    with pytest.raises(HTTPException) as error:
        await verify_api_key(api_key)

    assert error.value.status_code == 401
