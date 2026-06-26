from __future__ import annotations

import pytest

from app.core.crypto import TokenEncryptor
from app.db.models import AccountProvider, ZaiCredential
from app.db.session import SessionLocal

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_zai_account_create_list_delete_stores_encrypted_credential(async_client, db_setup):
    api_key = "test-key-id.test-secret"

    created = await async_client.post(
        "/api/accounts/zai",
        json={"apiKey": api_key, "label": "GLM slot"},
    )

    assert created.status_code == 200
    created_payload = created.json()
    account_id = created_payload["accountId"]
    assert created_payload["provider"] == "zai"
    assert created_payload["planType"] == "zai"
    assert created_payload["label"] == "GLM slot"

    listed = await async_client.get("/api/accounts")
    assert listed.status_code == 200
    account = next(item for item in listed.json()["accounts"] if item["accountId"] == account_id)
    assert account["provider"] == AccountProvider.ZAI.value
    assert account["planType"] == "zai"
    assert account["displayName"] == "GLM slot"

    async with SessionLocal() as session:
        credential = await session.get(ZaiCredential, account_id)
        assert credential is not None
        assert credential.api_key_encrypted != api_key
        assert credential.api_key_hash
        assert TokenEncryptor().decrypt(credential.api_key_encrypted) == api_key

    deleted = await async_client.delete(f"/api/accounts/{account_id}")
    assert deleted.status_code == 200

    async with SessionLocal() as session:
        assert await session.get(ZaiCredential, account_id) is None

