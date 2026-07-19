from __future__ import annotations

import os

from hq_ocr_bridge.process_lifetime import (
    OWNER_PID_ENV,
    start_owner_watchdog_from_env,
    start_parent_watchdog,
    start_process_exit_watchdog,
)


def _immediate_thread(**options):
    class ImmediateThread:
        @staticmethod
        def start():
            options["target"]()

    assert options["daemon"] is True
    return ImmediateThread()


def test_owner_watchdog_exits_after_its_electron_process():
    waited: list[int] = []
    exit_codes: list[int] = []

    started = start_owner_watchdog_from_env(
        {OWNER_PID_ENV: "2468"},
        platform="nt",
        waiter=lambda process_id: waited.append(process_id) or True,
        exit_process=exit_codes.append,
        thread_factory=_immediate_thread,
    )

    assert started is True
    assert waited == [2468]
    assert exit_codes == [0]


def test_owner_watchdog_ignores_missing_or_invalid_process_ids():
    assert start_owner_watchdog_from_env({}) is False
    assert start_owner_watchdog_from_env({OWNER_PID_ENV: "not-a-pid"}) is False
    assert start_owner_watchdog_from_env({OWNER_PID_ENV: "-20"}) is False


def test_watchdog_does_not_exit_when_process_cannot_be_observed():
    exit_codes: list[int] = []

    started = start_process_exit_watchdog(
        3579,
        platform="nt",
        waiter=lambda _process_id: False,
        exit_process=exit_codes.append,
        thread_factory=_immediate_thread,
    )

    assert started is True
    assert exit_codes == []


def test_watchdog_fails_closed_when_waiting_raises():
    exit_codes: list[int] = []

    def failed_waiter(_process_id):
        raise OSError("cannot observe owner")

    started = start_process_exit_watchdog(
        3580,
        platform="nt",
        waiter=failed_waiter,
        exit_process=exit_codes.append,
        thread_factory=_immediate_thread,
    )

    assert started is True
    assert exit_codes == [1]


def test_worker_watchdog_uses_its_bridge_parent_pid():
    waited: list[int] = []

    started = start_parent_watchdog(
        parent_pid=4680,
        platform="nt",
        waiter=lambda process_id: waited.append(process_id) or False,
        exit_process=lambda _code: None,
        thread_factory=_immediate_thread,
    )

    assert started is True
    assert waited == [4680]


def test_watchdog_is_disabled_outside_windows():
    assert start_process_exit_watchdog(5791, platform="posix") is False


def test_watchdog_refuses_to_observe_its_own_pid():
    assert start_process_exit_watchdog(os.getpid(), platform="nt") is False
