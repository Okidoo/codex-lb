from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import cast

import aiohttp
from cryptography.fernet import InvalidToken
from pydantic import ValidationError

from app.core.auth import (
    DEFAULT_EMAIL,
    DEFAULT_PLAN,
    claims_from_auth,
    generate_unique_account_id,
    parse_auth_json,
    token_expiry_epoch_ms,
)
from app.core.auth.api_key_cache import get_api_key_cache
from app.core.cache.invalidation import NAMESPACE_API_KEY, get_cache_invalidation_poller
from app.core.clients.account_http import invalidate_account_client
from app.core.clients.account_proxy_probe import (
    ProbeReason,
    ProbeResult,
    ProxyProbeError,
    probe_account_proxy,
)
from app.core.clients.http import lease_http_session
from app.core.config.settings import get_settings
from app.core.crypto import TokenEncryptor
from app.core.plan_types import coerce_account_plan_type
from app.core.utils.time import naive_utc_to_epoch, to_utc_naive, utcnow
from app.db.models import Account, AccountStatus
from app.modules.accounts.auth_manager import AuthManager
from app.modules.accounts.mappers import build_account_summaries, build_account_usage_trends
from app.modules.accounts.repository import AccountsRepository, _RotatedTokens
from app.modules.accounts.schemas import (
    AccountAdditionalQuota,
    AccountAdditionalWindow,
    AccountAuthExportResponse,
    AccountAuthExportTokens,
    AccountExportResponse,
    AccountImportResponse,
    AccountOpenCodeAuthExportAccount,
    AccountOpenCodeAuthExportResponse,
    AccountProbeResponse,
    AccountProxyInput,
    AccountProxySummary,
    AccountRequestUsage,
    AccountSummary,
    AccountTrendsResponse,
    CodexAuthJson,
    CodexAuthTokens,
    OpenCodeAuthJson,
    OpenCodeOAuthAuth,
)
from app.modules.limit_warmup.repository import LimitWarmupRepository
from app.modules.proxy.account_cache import get_account_selection_cache
from app.modules.usage.additional_quota_keys import get_additional_display_label_for_quota_key
from app.modules.usage.repository import AdditionalUsageRepository, UsageRepository
from app.modules.usage.updater import AdditionalUsageRepositoryPort, UsageUpdater

logger = logging.getLogger(__name__)

_SPARKLINE_DAYS = 7
_DETAIL_BUCKET_SECONDS = 3600  # 1h → 168 points

DEFAULT_PROBE_MODEL = "gpt-5.5"
PROBE_REQUEST_TIMEOUT_SECONDS = 30.0
PROBE_CONNECT_TIMEOUT_SECONDS = 10.0
# Network/upstream failure sentinel for ``probe_status_code`` — kept as ``0`` so
# the value is distinguishable from any real HTTP status the upstream might
# return.
PROBE_NETWORK_FAILURE_STATUS = 0


class InvalidAuthJsonError(Exception):
    pass


class AccountNotFoundError(Exception):
    """Raised by ``AccountsService`` when the target account does not exist."""

    def __init__(self, account_id: str) -> None:
        self.account_id = account_id
        super().__init__(f"Account not found: {account_id}")


class ProxyPasswordUnrecoverableError(Exception):
    """The stored proxy password could not be decrypted.

    Raised by ``set_account_proxy`` when the operator does not provide a
    new password and the existing encrypted password fails to decrypt
    (most commonly because the Fernet encryption key has been rotated
    since the password was stored). The API layer maps this to HTTP 422
    with ``error.code=proxy_password_unrecoverable`` so the dashboard
    can render an actionable "please re-enter the password" message
    instead of a raw 500.
    """

    def __init__(self) -> None:
        super().__init__("Stored proxy password cannot be decrypted; please re-enter it")


class AccountCredentialsUnrecoverableError(Exception):
    """The account's stored OAuth refresh token could not be decrypted.

    Same Fernet-key-rotation scenario as
    :class:`ProxyPasswordUnrecoverableError`, but for the refresh token.
    Unlike the password case, there is NO dashboard widget to "re-enter"
    a refresh token — the operator must re-run the OAuth flow / re-
    import the account's auth.json. The API layer maps this to HTTP
    422 with ``error.code=account_credentials_unrecoverable`` so the
    dashboard can prompt the operator for the right recovery action.
    """

    def __init__(self, account_id: str) -> None:
        self.account_id = account_id
        super().__init__(f"Account {account_id!r} credentials cannot be decrypted; please re-import the account")


_PASSWORD_UNSET = object()


class AccountNotProbableError(Exception):
    """Raised when an account is in a status that disallows probing."""


class AccountsService:
    def __init__(
        self,
        repo: AccountsRepository,
        usage_repo: UsageRepository | None = None,
        additional_usage_repo: AdditionalUsageRepository | AdditionalUsageRepositoryPort | None = None,
        limit_warmup_repo: LimitWarmupRepository | None = None,
        auth_manager: AuthManager | None = None,
    ) -> None:
        self._repo = repo
        self._usage_repo = usage_repo
        self._additional_usage_repo = additional_usage_repo
        self._limit_warmup_repo = limit_warmup_repo
        self._usage_updater = UsageUpdater(usage_repo, repo, additional_usage_repo) if usage_repo else None
        self._encryptor = TokenEncryptor()
        self._auth_manager = auth_manager

    async def list_accounts(self) -> list[AccountSummary]:
        accounts = await self._repo.list_accounts()
        if not accounts:
            return []
        account_ids = [account.id for account in accounts]
        account_id_set = set(account_ids)
        primary_usage = await self._usage_repo.latest_by_account(window="primary") if self._usage_repo else {}
        secondary_usage = await self._usage_repo.latest_by_account(window="secondary") if self._usage_repo else {}
        request_usage_rows = await self._repo.list_request_usage_summary_by_account(account_ids)
        limit_warmups_by_account = (
            await self._limit_warmup_repo.latest_by_account(account_ids) if self._limit_warmup_repo else {}
        )
        request_usage_by_account = {
            account_id: AccountRequestUsage(
                request_count=row.request_count,
                total_tokens=row.total_tokens,
                cached_input_tokens=row.cached_input_tokens,
                total_cost_usd=row.total_cost_usd,
            )
            for account_id, row in request_usage_rows.items()
        }
        additional_quotas_by_account: dict[str, list[AccountAdditionalQuota]] = {}
        additional_usage_repo = cast(AdditionalUsageRepository | None, self._additional_usage_repo)
        if additional_usage_repo:
            quota_keys = await additional_usage_repo.list_quota_keys(account_ids=account_ids)
            for quota_key in quota_keys:
                primary_entries = await additional_usage_repo.latest_by_account(quota_key, "primary")
                secondary_entries = await additional_usage_repo.latest_by_account(quota_key, "secondary")
                for account_id in (set(primary_entries) | set(secondary_entries)) & account_id_set:
                    primary_entry = primary_entries.get(account_id)
                    secondary_entry = secondary_entries.get(account_id)
                    reference_entry = primary_entry or secondary_entry
                    if reference_entry is None:
                        continue
                    additional_quotas_by_account.setdefault(account_id, []).append(
                        AccountAdditionalQuota(
                            quota_key=quota_key,
                            limit_name=reference_entry.limit_name,
                            metered_feature=reference_entry.metered_feature,
                            display_label=get_additional_display_label_for_quota_key(quota_key)
                            or reference_entry.limit_name,
                            primary_window=AccountAdditionalWindow(
                                used_percent=primary_entry.used_percent,
                                reset_at=primary_entry.reset_at,
                                window_minutes=primary_entry.window_minutes,
                            )
                            if primary_entry is not None
                            else None,
                            secondary_window=AccountAdditionalWindow(
                                used_percent=secondary_entry.used_percent,
                                reset_at=secondary_entry.reset_at,
                                window_minutes=secondary_entry.window_minutes,
                            )
                            if secondary_entry is not None
                            else None,
                        )
                    )
        for account_quota_list in additional_quotas_by_account.values():
            account_quota_list.sort(key=lambda quota: quota.display_label or quota.quota_key or quota.limit_name)

        return build_account_summaries(
            accounts=accounts,
            primary_usage=primary_usage,
            secondary_usage=secondary_usage,
            request_usage_by_account=request_usage_by_account,
            additional_quotas_by_account=additional_quotas_by_account,
            limit_warmups_by_account=limit_warmups_by_account,
            encryptor=self._encryptor,
        )

    async def get_account_trends(self, account_id: str) -> AccountTrendsResponse | None:
        account = await self._repo.get_by_id(account_id)
        if not account or not self._usage_repo:
            return None
        now = utcnow()
        since = now - timedelta(days=_SPARKLINE_DAYS)
        since_epoch = naive_utc_to_epoch(since)
        bucket_count = (_SPARKLINE_DAYS * 24 * 3600) // _DETAIL_BUCKET_SECONDS
        buckets = await self._usage_repo.trends_by_bucket(
            since=since,
            bucket_seconds=_DETAIL_BUCKET_SECONDS,
            account_id=account_id,
        )
        trends = build_account_usage_trends(buckets, since_epoch, _DETAIL_BUCKET_SECONDS, bucket_count)
        trend = trends.get(account_id)
        return AccountTrendsResponse(
            account_id=account_id,
            primary=trend.primary if trend else [],
            secondary=trend.secondary if trend else [],
            secondary_scheduled=trend.secondary_scheduled if trend else [],
        )

    async def export_opencode_auth(self, account_id: str) -> AccountOpenCodeAuthExportResponse | None:
        account = await self._repo.get_by_id(account_id)
        if account is None:
            return None

        access_token = self._encryptor.decrypt(account.access_token_encrypted)
        refresh_token = self._encryptor.decrypt(account.refresh_token_encrypted)
        expires = token_expiry_epoch_ms(access_token) or 0
        return AccountOpenCodeAuthExportResponse(
            filename=_opencode_auth_export_filename(account),
            account=AccountOpenCodeAuthExportAccount(
                account_id=account.id,
                chatgpt_account_id=account.chatgpt_account_id,
                email=account.email,
            ),
            auth_json=OpenCodeAuthJson(
                openai=OpenCodeOAuthAuth(
                    refresh=refresh_token,
                    access=access_token,
                    expires=expires,
                    account_id=account.chatgpt_account_id,
                ),
            ),
        )

    async def export_auth(self, account_id: str) -> AccountAuthExportResponse | None:
        account = await self._repo.get_by_id(account_id)
        if account is None:
            return None

        access_token = self._encryptor.decrypt(account.access_token_encrypted)
        refresh_token = self._encryptor.decrypt(account.refresh_token_encrypted)
        id_token = self._encryptor.decrypt(account.id_token_encrypted)
        expires = token_expiry_epoch_ms(access_token) or 0

        tokens = AccountAuthExportTokens(
            id_token=id_token,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at_ms=expires,
        )

        codex_auth_json = CodexAuthJson(
            auth_mode="chatgpt",
            openai_api_key=None,
            tokens=CodexAuthTokens(
                id_token=id_token,
                access_token=access_token,
                refresh_token=refresh_token,
                account_id=account.chatgpt_account_id,
            ),
            last_refresh=account.last_refresh.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z",
        )

        opencode_auth_json = OpenCodeAuthJson(
            openai=OpenCodeOAuthAuth(
                refresh=refresh_token,
                access=access_token,
                expires=expires,
                account_id=account.chatgpt_account_id,
            ),
        )

        return AccountAuthExportResponse(
            filename=_opencode_auth_export_filename(account),
            account=AccountOpenCodeAuthExportAccount(
                account_id=account.id,
                chatgpt_account_id=account.chatgpt_account_id,
                email=account.email,
            ),
            tokens=tokens,
            codex_auth_json=codex_auth_json,
            opencode_auth_json=opencode_auth_json,
        )

    async def import_account(
        self,
        raw: bytes,
        *,
        proxy_payload: AccountProxyInput | None = None,
    ) -> AccountImportResponse:
        try:
            auth = parse_auth_json(raw)
        except (json.JSONDecodeError, ValidationError, UnicodeDecodeError, TypeError) as exc:
            raise InvalidAuthJsonError("Invalid auth.json payload") from exc
        claims = claims_from_auth(auth)

        email = claims.email or DEFAULT_EMAIL
        raw_account_id = claims.account_id
        account_id = generate_unique_account_id(raw_account_id, email, claims.workspace_id)
        plan_type = coerce_account_plan_type(claims.plan_type, DEFAULT_PLAN)
        last_refresh = to_utc_naive(auth.last_refresh_at) if auth.last_refresh_at else utcnow()

        account = Account(
            id=account_id,
            chatgpt_account_id=raw_account_id,
            email=email,
            workspace_id=claims.workspace_id,
            workspace_label=claims.workspace_label,
            seat_type=claims.seat_type,
            plan_type=plan_type,
            access_token_encrypted=self._encryptor.encrypt(auth.tokens.access_token),
            refresh_token_encrypted=self._encryptor.encrypt(auth.tokens.refresh_token),
            id_token_encrypted=self._encryptor.encrypt(auth.tokens.id_token),
            last_refresh=last_refresh,
            status=AccountStatus.ACTIVE,
            deactivation_reason=None,
        )

        saved = await self.persist_account_with_optional_proxy(
            account,
            proxy_payload=proxy_payload,
            refresh_token=auth.tokens.refresh_token,
        )
        if self._usage_repo and self._usage_updater:
            latest_usage = await self._usage_repo.latest_by_account(window="primary")
            await self._usage_updater.refresh_accounts([saved], latest_usage)
        get_account_selection_cache().invalidate()
        return AccountImportResponse(
            account_id=saved.id,
            email=saved.email,
            workspace_id=saved.workspace_id,
            workspace_label=saved.workspace_label,
            seat_type=saved.seat_type,
            plan_type=saved.plan_type,
            status=saved.status,
        )

    async def persist_account_with_optional_proxy(
        self,
        account: Account,
        *,
        proxy_payload: AccountProxyInput | None,
        refresh_token: str,
        before_upsert: Callable[[], Awaitable[None]] | None = None,
    ) -> Account:
        """Atomically probe optional proxy, persist account, refresh caches.

        Shared by the import and OAuth add-account flows so the
        probe / upsert / invalidate / usage-refresh sequence does not
        drift between them. The caller MUST have already populated
        ``account`` with identity + (encrypted) token fields; the
        plaintext ``refresh_token`` is only needed to drive the proxy
        probe when ``proxy_payload`` is provided.
        """

        if proxy_payload is not None:
            # Lock the final account_id before probing so proxy fields and
            # rotated tokens are applied to the same row that will be saved.
            account.id = await self._repo.preview_import_account_id(account.id, account.email)
            await self._probe_and_apply_proxy_payload(
                account,
                refresh_token=refresh_token,
                proxy_payload=proxy_payload,
            )

        if before_upsert is not None:
            await before_upsert()
        saved = await self._repo.upsert(
            account,
            include_proxy_fields=proxy_payload is not None,
        )
        if proxy_payload is not None:
            await invalidate_account_client(saved.id)
        if self._usage_repo and self._usage_updater:
            latest_usage = await self._usage_repo.latest_by_account(window="primary")
            await self._usage_updater.refresh_accounts([saved], latest_usage)
        get_account_selection_cache().invalidate()
        return saved

    async def reauthenticate_account_with_optional_proxy(
        self,
        account_id: str,
        account: Account,
        *,
        proxy_payload: AccountProxyInput | None,
        refresh_token: str,
        before_update: Callable[[], Awaitable[None]] | None = None,
    ) -> Account:
        """Re-authenticate an exact target account and optionally refresh its proxy.

        Unlike imports/add-account OAuth, reauth is identity-targeted: duplicate
        mode must never redirect this write into a ``__copy`` account.
        """

        if proxy_payload is not None:
            await self._probe_and_apply_proxy_payload(
                account,
                refresh_token=refresh_token,
                proxy_payload=proxy_payload,
            )

        if before_update is not None:
            await before_update()
        saved = await self._repo.reauthenticate_account(
            account_id,
            account,
            include_proxy_fields=proxy_payload is not None,
        )
        if saved is None:
            raise AccountNotFoundError(account_id)
        await invalidate_account_client(saved.id)
        if self._usage_repo and self._usage_updater:
            latest_usage = await self._usage_repo.latest_by_account(window="primary")
            await self._usage_updater.refresh_accounts([saved], latest_usage)
        get_account_selection_cache().invalidate()
        return saved

    async def _probe_and_apply_proxy_payload(
        self,
        account: Account,
        *,
        refresh_token: str,
        proxy_payload: AccountProxyInput,
    ) -> None:
        result, rotated_tokens = await self._probe_proxy_payload(
            refresh_token=refresh_token,
            payload=proxy_payload,
        )
        account.access_token_encrypted = rotated_tokens.access_token_encrypted
        account.refresh_token_encrypted = rotated_tokens.refresh_token_encrypted
        account.id_token_encrypted = rotated_tokens.id_token_encrypted
        account.last_refresh = rotated_tokens.last_refresh
        account.proxy_host = proxy_payload.host
        account.proxy_port = proxy_payload.port
        account.proxy_username = proxy_payload.username
        account.proxy_password_encrypted = (
            self._encryptor.encrypt(proxy_payload.password)
            if proxy_payload.password is not None and not proxy_payload.clear_password
            else None
        )
        account.proxy_remote_dns = proxy_payload.remote_dns
        account.proxy_label = proxy_payload.label
        account.proxy_last_validated_at = result.checked_at

    async def reactivate_account(self, account_id: str) -> bool:
        result = await self._repo.update_status(account_id, AccountStatus.ACTIVE, None, None, blocked_at=None)
        if result:
            # Drop any cached per-account client + reset the proxy-failure
            # window so a freshly-reactivated account does not inherit the
            # stale failure timestamps that triggered its prior deactivation.
            await invalidate_account_client(account_id)
            get_account_selection_cache().invalidate()
        return result

    async def pause_account(self, account_id: str) -> bool:
        result = await self._repo.update_status(account_id, AccountStatus.PAUSED, None, None, blocked_at=None)
        if result:
            get_account_selection_cache().invalidate()
        return result

    async def set_limit_warmup_enabled(self, account_id: str, enabled: bool) -> bool:
        return await self._repo.update_limit_warmup_enabled(account_id, enabled)

    async def delete_account(self, account_id: str, *, delete_history: bool = False) -> bool:
        result = await self._repo.delete(account_id, delete_history=delete_history)
        if result:
            # Drop the cached per-account egress session and reset the
            # runtime proxy-failure tracker for the deleted account so
            # nothing leaks into the next account that happens to take
            # this id back (rare, but generated_unique_account_id can
            # collide on aggressive id reuse).
            await invalidate_account_client(account_id)
            get_account_selection_cache().invalidate()
            get_api_key_cache().clear()
            poller = get_cache_invalidation_poller()
            if poller is not None:
                await poller.bump(NAMESPACE_API_KEY)
        return result

    async def set_account_alias(self, account_id: str, alias: str | None) -> bool:
        normalized = alias.strip() if isinstance(alias, str) else None
        if normalized == "":
            normalized = None
        return await self._repo.update_alias(account_id, normalized)

    async def export_account(self, account_id: str) -> AccountExportResponse | None:
        account = await self._repo.get_by_id(account_id)
        if not account:
            return None
        access_token = self._encryptor.decrypt(account.access_token_encrypted)
        refresh_token = self._encryptor.decrypt(account.refresh_token_encrypted)
        id_token = self._encryptor.decrypt(account.id_token_encrypted)
        auth_json = {
            "auth_mode": "chatgpt",
            "OPENAI_API_KEY": None,
            "tokens": {
                "id_token": id_token,
                "access_token": access_token,
                "refresh_token": refresh_token,
                "account_id": account.chatgpt_account_id,
            },
            "last_refresh": account.last_refresh.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z",
        }
        return AccountExportResponse(
            account_id=account.id,
            email=account.email,
            workspace_id=account.workspace_id,
            workspace_label=account.workspace_label,
            seat_type=account.seat_type,
            plan_type=account.plan_type,
            status=account.status.value,
            auth_json=json.dumps(auth_json, indent=2),
        )

    async def get_account_proxy(self, account_id: str) -> AccountProxySummary | None:
        """Return the public proxy summary for an account, or ``None``.

        ``None`` covers both "account does not exist" and "account has no
        proxy configured" — callers that need to distinguish them should
        check ``get_by_id`` separately.
        """

        record = await self._repo.get_proxy_config(account_id)
        if record is None:
            return None
        return AccountProxySummary(
            host=record.host,
            port=record.port,
            username=record.username,
            has_password=record.password_encrypted is not None,
            remote_dns=record.remote_dns,
            label=record.label,
            last_validated_at=record.last_validated_at,
        )

    async def set_account_proxy(
        self,
        account_id: str,
        payload: AccountProxyInput,
    ) -> AccountProxySummary:
        """Probe the proposed proxy and persist it on success.

        The probe performs a real OAuth refresh through the proposed
        ``ProxyConnector`` against the configured ``auth_base_url`` (defaults
        to ``https://auth.openai.com``). Only an ``ok`` outcome reaches
        the database; any other outcome raises :class:`ProxyProbeError`.

        Password handling: omitted ``payload.password`` reuses the
        existing password by default. Explicit ``password: null`` or
        ``clear_password`` clears the stored secret.
        """

        account = await self._repo.get_by_id(account_id)
        if account is None:
            raise AccountNotFoundError(account_id)

        existing = await self._repo.get_proxy_config(account_id)

        password_field_was_sent = "password" in payload.model_fields_set
        clear_password = payload.clear_password or (password_field_was_sent and payload.password is None)
        if clear_password:
            password_plain = None
        elif payload.password is not None:
            password_plain: str | None = payload.password
        elif existing is not None and existing.password_encrypted is not None:
            try:
                password_plain = self._encryptor.decrypt(existing.password_encrypted)
            except InvalidToken as exc:
                # The encryption key has been rotated since the password
                # was stored. Without the original key we cannot recover
                # the plaintext, so the only path forward is for the
                # operator to re-enter it. Surface a typed envelope so
                # the dashboard can render an actionable message instead
                # of a raw 500.
                raise ProxyPasswordUnrecoverableError() from exc
        else:
            password_plain = None

        try:
            refresh_token = self._encryptor.decrypt(account.refresh_token_encrypted)
        except InvalidToken as exc:
            # Same Fernet-key-rotation scenario as the password decrypt
            # above, but for the OAuth refresh token. Without the
            # original key we cannot recover the plaintext, and there
            # is no operator-visible way to "re-enter" a refresh
            # token (it can only be re-obtained by re-running the
            # OAuth flow / re-importing auth.json). Surface a typed
            # envelope so the dashboard can render an actionable
            # message instead of a raw 500.
            raise AccountCredentialsUnrecoverableError(account_id) from exc
        result, rotated_tokens = await self._probe_proxy_payload(
            refresh_token=refresh_token,
            payload=payload,
            password_plain=password_plain,
        )

        # Refresh-token rotation safety. The probe just performed a real
        # OAuth refresh through the proposed proxy; if the upstream
        # rotated the refresh token, the response payload contains the
        # new tokens. We MUST persist them atomically with the proxy
        # config — otherwise the previously stored refresh token is now
        # stale and the next real refresh will fail with ``invalid_grant``.
        password_encrypted = self._encryptor.encrypt(password_plain) if password_plain is not None else None
        updated = await self._repo.update_proxy(
            account_id,
            host=payload.host,
            port=payload.port,
            username=payload.username,
            password_encrypted=password_encrypted,
            remote_dns=payload.remote_dns,
            label=payload.label,
            last_validated_at=result.checked_at,
            rotated_tokens=rotated_tokens,
        )
        if not updated:
            raise AccountNotFoundError(account_id)
        await self._reactivate_after_proxy_repair(account_id)
        # Drop any cached per-account ClientSession so subsequent leases
        # rebuild against the new (or revalidated) configuration.
        await invalidate_account_client(account_id)
        get_account_selection_cache().invalidate()

        logging.getLogger(__name__).info(
            "Proxy config updated account_id=%s host=%s port=%d",
            account_id,
            payload.host,
            payload.port,
        )

        return AccountProxySummary(
            host=payload.host,
            port=payload.port,
            username=payload.username,
            has_password=password_encrypted is not None,
            remote_dns=payload.remote_dns,
            label=payload.label,
            last_validated_at=result.checked_at,
        )

    async def _probe_proxy_payload(
        self,
        *,
        refresh_token: str,
        payload: AccountProxyInput,
        password_plain: str | None | object = _PASSWORD_UNSET,
    ) -> tuple[ProbeResult, _RotatedTokens]:
        probe_password = payload.password if password_plain is _PASSWORD_UNSET else cast(str | None, password_plain)
        result: ProbeResult = await probe_account_proxy(
            host=payload.host,
            port=payload.port,
            username=payload.username,
            password=probe_password,
            remote_dns=payload.remote_dns,
            refresh_token=refresh_token,
        )
        if not result.ok:
            raise ProxyProbeError(result.reason, result.detail)
        tokens = result.tokens
        if not (tokens and tokens.access_token and tokens.refresh_token and tokens.id_token):
            raise ProxyProbeError(
                ProbeReason.INVALID_RESPONSE,
                "OAuth refresh succeeded but token payload was incomplete",
            )
        return result, _RotatedTokens(
            access_token_encrypted=self._encryptor.encrypt(tokens.access_token),
            refresh_token_encrypted=self._encryptor.encrypt(tokens.refresh_token),
            id_token_encrypted=self._encryptor.encrypt(tokens.id_token),
            last_refresh=utcnow(),
        )

    async def clear_account_proxy(self, account_id: str) -> bool:
        """Remove the proxy configuration on an account (idempotent for empty).

        Returns ``True`` if the row was modified (either a proxy was
        configured and is now cleared OR no proxy was configured — both
        leave the row in the canonical no-proxy state). Returns ``False``
        only when the account does not exist.
        """

        cleared = await self._repo.clear_proxy(account_id)
        if cleared:
            await self._reactivate_after_proxy_repair(account_id)
            await invalidate_account_client(account_id)
            get_account_selection_cache().invalidate()
        return cleared

    async def _reactivate_after_proxy_repair(self, account_id: str) -> None:
        """Bring proxy-failure-deactivated accounts back after operator repair."""

        await self._repo.update_status_if_current(
            account_id,
            AccountStatus.ACTIVE,
            deactivation_reason=None,
            expected_status=AccountStatus.DEACTIVATED,
            expected_deactivation_reason="proxy_unreachable",
        )

    async def probe_account(
        self,
        account_id: str,
        model: str | None = None,
    ) -> AccountProbeResponse | None:
        """Send a minimal upstream ``responses.create`` pinned to one account.

        Bypasses load-balancer scoring so an operator can wake the upstream
        rate-limiter for a stuck account (see upstream issues #676 / #677).
        Triggers an immediate usage refresh after the probe and returns the
        before/after snapshot so the operator can see whether the upstream
        state changed.
        """
        account = await self._repo.get_by_id(account_id)
        if account is None:
            return None
        if account.status in (AccountStatus.PAUSED, AccountStatus.DEACTIVATED):
            raise AccountNotProbableError(f"Account is {account.status.value} and cannot be probed")

        primary_before, secondary_before = await self._latest_usage_percents(account_id)
        status_before = account.status.value

        probe_account = account
        if self._auth_manager is not None:
            probe_account = await self._auth_manager.ensure_fresh(account, force=False)

        access_token = self._encryptor.decrypt(probe_account.access_token_encrypted)
        probe_model = model or DEFAULT_PROBE_MODEL
        probe_status = await self._send_probe_request(
            access_token=access_token,
            chatgpt_account_id=probe_account.chatgpt_account_id,
            model=probe_model,
        )

        if self._usage_repo and self._usage_updater:
            await self._usage_updater.force_refresh(probe_account)
            get_account_selection_cache().invalidate()

        refreshed = await self._repo.get_by_id(account_id) or account
        primary_after, secondary_after = await self._latest_usage_percents(account_id)

        return AccountProbeResponse(
            status="probed",
            account_id=account_id,
            probe_status_code=probe_status,
            primary_used_percent_before=primary_before,
            primary_used_percent_after=primary_after,
            secondary_used_percent_before=secondary_before,
            secondary_used_percent_after=secondary_after,
            account_status_before=status_before,
            account_status_after=refreshed.status.value,
        )

    async def _latest_usage_percents(self, account_id: str) -> tuple[float | None, float | None]:
        if self._usage_repo is None:
            return None, None
        primary_entry = await self._usage_repo.latest_entry_for_account(account_id, window="primary")
        secondary_entry = await self._usage_repo.latest_entry_for_account(account_id, window="secondary")
        return (
            primary_entry.used_percent if primary_entry is not None else None,
            secondary_entry.used_percent if secondary_entry is not None else None,
        )

    async def _send_probe_request(
        self,
        *,
        access_token: str,
        chatgpt_account_id: str | None,
        model: str,
    ) -> int:
        settings = get_settings()
        base = settings.upstream_base_url.rstrip("/")
        if "/backend-api" not in base:
            base = f"{base}/backend-api"
        url = f"{base}/codex/responses"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "text/event-stream",
            "Content-Type": "application/json",
        }
        if chatgpt_account_id and not chatgpt_account_id.startswith(("email_", "local_")):
            headers["chatgpt-account-id"] = chatgpt_account_id
        body = {
            "model": model,
            "instructions": "Respond with a single dot.",
            "input": [
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": "."}],
                }
            ],
            "max_output_tokens": 1,
            "stream": True,
            "store": False,
        }
        timeout = aiohttp.ClientTimeout(
            total=PROBE_REQUEST_TIMEOUT_SECONDS,
            sock_connect=PROBE_CONNECT_TIMEOUT_SECONDS,
        )
        try:
            async with lease_http_session() as session:
                async with session.post(url, headers=headers, json=body, timeout=timeout) as resp:
                    # Initiating the request is enough to wake the upstream
                    # rate-limiter; we do not consume the SSE body.
                    return resp.status
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            logger.warning(
                "Probe upstream request failed account=%s error=%s",
                chatgpt_account_id,
                exc,
            )
            return PROBE_NETWORK_FAILURE_STATUS


def _opencode_auth_export_filename(account: Account) -> str:
    source = account.email or account.id
    safe = "".join(char if char.isalnum() or char in "._-" else "-" for char in source).strip("-._")
    return f"opencode-auth-{safe or account.id}.json"
