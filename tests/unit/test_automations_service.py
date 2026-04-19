from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.modules.automations.service import (
    AutomationValidationError,
    _resolve_effective_status,
    compute_latest_due_slot_utc,
    compute_next_run_utc,
    normalize_schedule_days,
    normalize_schedule_time,
    parse_schedule_time_hhmm,
    validate_timezone,
)

pytestmark = pytest.mark.unit


def test_parse_schedule_time_hhmm_accepts_valid_value() -> None:
    assert parse_schedule_time_hhmm("05:00") == (5, 0)
    assert parse_schedule_time_hhmm("23:59") == (23, 59)


def test_parse_schedule_time_hhmm_rejects_invalid_value() -> None:
    with pytest.raises(AutomationValidationError):
        parse_schedule_time_hhmm("5:00")
    with pytest.raises(AutomationValidationError):
        parse_schedule_time_hhmm("24:01")
    with pytest.raises(AutomationValidationError):
        parse_schedule_time_hhmm("aa:bb")


def test_normalize_schedule_time_zero_pads_valid_values() -> None:
    assert normalize_schedule_time("05:00") == "05:00"
    assert normalize_schedule_time(" 23:09 ") == "23:09"


def test_compute_next_run_utc_respects_timezone_and_dst() -> None:
    # Before spring DST transition day in Europe/Warsaw.
    before_dst_now = datetime(2026, 3, 28, 3, 30)
    before_dst_next = compute_next_run_utc(
        before_dst_now,
        schedule_time="05:00",
        timezone_name="Europe/Warsaw",
        schedule_days=["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
    )
    assert before_dst_next == datetime(2026, 3, 28, 4, 0)

    # After DST jump, 05:00 local equals 03:00 UTC.
    after_dst_now = datetime(2026, 3, 29, 3, 30)
    after_dst_next = compute_next_run_utc(
        after_dst_now,
        schedule_time="05:00",
        timezone_name="Europe/Warsaw",
        schedule_days=["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
    )
    assert after_dst_next == datetime(2026, 3, 30, 3, 0)


def test_compute_latest_due_slot_utc_returns_most_recent_slot() -> None:
    now_utc = datetime(2026, 3, 29, 3, 30)
    latest_due = compute_latest_due_slot_utc(
        now_utc,
        schedule_time="05:00",
        timezone_name="Europe/Warsaw",
        schedule_days=["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
    )
    assert latest_due == datetime(2026, 3, 29, 3, 0)


def test_compute_next_run_utc_respects_selected_weekdays() -> None:
    now_utc = datetime(2026, 4, 14, 10, 0)  # Tuesday
    next_run = compute_next_run_utc(
        now_utc,
        schedule_time="09:00",
        timezone_name="UTC",
        schedule_days=["mon", "wed"],
    )
    assert next_run == datetime(2026, 4, 15, 9, 0)  # Wednesday


def test_compute_latest_due_slot_utc_respects_selected_weekdays() -> None:
    now_utc = datetime(2026, 4, 14, 10, 0)  # Tuesday
    latest_due = compute_latest_due_slot_utc(
        now_utc,
        schedule_time="09:00",
        timezone_name="UTC",
        schedule_days=["mon", "wed"],
    )
    assert latest_due == datetime(2026, 4, 13, 9, 0)  # Monday


def test_normalize_schedule_days_rejects_invalid_entries() -> None:
    with pytest.raises(AutomationValidationError):
        normalize_schedule_days(["mon", "invalid-day"])


def test_validate_timezone_accepts_server_default() -> None:
    assert validate_timezone("server_default") == "server_default"
    assert validate_timezone("Server default") == "server_default"
    assert validate_timezone("default") == "server_default"


def test_compute_next_run_utc_accepts_server_default_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TZ", "UTC")
    now_utc = datetime(2026, 4, 14, 10, 0)
    next_run = compute_next_run_utc(
        now_utc,
        schedule_time="11:00",
        timezone_name="server_default",
        schedule_days=["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
    )
    assert next_run == datetime(2026, 4, 14, 11, 0)


def test_resolve_effective_status_stays_running_when_accounts_are_still_running() -> None:
    now_utc = datetime(2026, 4, 19, 2, 45, 0)
    status = _resolve_effective_status(
        pending_accounts=2,
        completed_accounts=0,
        success_count=0,
        failed_count=0,
        partial_count=0,
        running_count=2,
        fallback_status="running",
        now_utc=now_utc,
        window_end_utc=now_utc - timedelta(seconds=1),
    )
    assert status == "running"
