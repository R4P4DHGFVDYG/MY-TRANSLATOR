from __future__ import annotations

import ctypes
import os
import sys
from collections.abc import Callable
from typing import Any


_DLL_DIRECTORY_HANDLES: list[Any] = []


def preload_frozen_torch_runtime(
    *,
    platform_name: str | None = None,
    frozen: bool | None = None,
    bundle_dir: str | None = None,
    file_exists: Callable[[str], bool] | None = None,
    add_dll_directory: Callable[[str], Any] | None = None,
    load_library: Callable[[str], Any] | None = None,
) -> str:
    """Load c10 before Paddle/PaddleX in a frozen Windows process."""
    current_platform = os.name if platform_name is None else platform_name
    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    if current_platform != "nt" or not is_frozen:
        return ""

    bundle_root = str(getattr(sys, "_MEIPASS", "")) if bundle_dir is None else bundle_dir
    if not bundle_root:
        return ""

    torch_lib_dir = os.path.join(bundle_root, "torch", "lib")
    c10_path = os.path.join(torch_lib_dir, "c10.dll")
    exists = os.path.isfile if file_exists is None else file_exists
    if not exists(c10_path):
        return ""

    add_directory = (
        getattr(os, "add_dll_directory", None)
        if add_dll_directory is None
        else add_dll_directory
    )
    loader = ctypes.CDLL if load_library is None else load_library
    try:
        if callable(add_directory):
            handle = add_directory(torch_lib_dir)
            if handle is not None:
                # Windows removes the search path when this handle is collected.
                _DLL_DIRECTORY_HANDLES.append(handle)
        loader(c10_path)
    except OSError as exc:
        return f"Torch runtime preload failed: {exc}"
    return ""
