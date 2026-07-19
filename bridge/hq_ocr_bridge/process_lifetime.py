from __future__ import annotations

from collections.abc import Callable, Mapping
import ctypes
from ctypes import wintypes
import os
import threading
from typing import Any


OWNER_PID_ENV = "HQ_OCR_OWNER_PID"
_SYNCHRONIZE = 0x00100000
_WAIT_OBJECT_0 = 0x00000000
_WAIT_FAILED = 0xFFFFFFFF
_INFINITE = 0xFFFFFFFF
_ERROR_INVALID_PARAMETER = 87
_MAX_WINDOWS_PID = 0xFFFFFFFF


def start_owner_watchdog_from_env(
    env: Mapping[str, str] | None = None,
    **watchdog_options: Any,
) -> bool:
    values = os.environ if env is None else env
    owner_pid = _positive_pid(values.get(OWNER_PID_ENV))
    if owner_pid is None:
        return False
    return start_process_exit_watchdog(owner_pid, **watchdog_options)


def start_parent_watchdog(
    parent_pid: int | None = None,
    **watchdog_options: Any,
) -> bool:
    watched_pid = os.getppid() if parent_pid is None else parent_pid
    return start_process_exit_watchdog(watched_pid, **watchdog_options)


def start_process_exit_watchdog(
    process_id: int,
    *,
    platform: str = os.name,
    waiter: Callable[[int], bool] | None = None,
    exit_process: Callable[[int], None] = os._exit,
    thread_factory: Callable[..., Any] = threading.Thread,
) -> bool:
    watched_pid = _positive_pid(process_id)
    if platform != "nt" or watched_pid is None or watched_pid == os.getpid():
        return False

    wait_for_exit = waiter or _wait_for_windows_process_exit

    def watch() -> None:
        try:
            owner_exited = wait_for_exit(watched_pid)
        except Exception:
            exit_process(1)
            return
        if owner_exited:
            exit_process(0)

    thread = thread_factory(
        target=watch,
        name=f"process-watchdog-{watched_pid}",
        daemon=True,
    )
    thread.start()
    return True


def _wait_for_windows_process_exit(process_id: int) -> bool:
    if os.name != "nt":
        return False

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    open_process = kernel32.OpenProcess
    open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    open_process.restype = wintypes.HANDLE
    wait_for_single_object = kernel32.WaitForSingleObject
    wait_for_single_object.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    wait_for_single_object.restype = wintypes.DWORD
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL

    process_handle = open_process(_SYNCHRONIZE, False, process_id)
    if not process_handle:
        error_code = ctypes.get_last_error()
        if error_code == _ERROR_INVALID_PARAMETER:
            return True
        raise ctypes.WinError(error_code)
    try:
        result = wait_for_single_object(process_handle, _INFINITE)
        if result == _WAIT_FAILED:
            raise ctypes.WinError(ctypes.get_last_error())
        return result == _WAIT_OBJECT_0
    finally:
        close_handle(process_handle)


def _positive_pid(value: object) -> int | None:
    try:
        process_id = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    if process_id <= 0 or process_id > _MAX_WINDOWS_PID:
        return None
    return process_id
