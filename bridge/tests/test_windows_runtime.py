from __future__ import annotations

from hq_ocr_bridge import windows_runtime


def test_runtime_preload_is_skipped_outside_frozen_windows():
    loaded: list[str] = []

    warning = windows_runtime.preload_frozen_torch_runtime(
        platform_name="posix",
        frozen=True,
        bundle_dir="/bundle",
        load_library=lambda path: loaded.append(path),
    )

    assert warning == ""
    assert loaded == []


def test_runtime_preload_loads_c10_before_application_import(monkeypatch, tmp_path):
    torch_lib_dir = tmp_path / "torch" / "lib"
    torch_lib_dir.mkdir(parents=True)
    c10_path = torch_lib_dir / "c10.dll"
    c10_path.write_bytes(b"test")
    loaded: list[str] = []
    searched: list[str] = []
    directory_handle = object()
    monkeypatch.setattr(windows_runtime, "_DLL_DIRECTORY_HANDLES", [])

    warning = windows_runtime.preload_frozen_torch_runtime(
        platform_name="nt",
        frozen=True,
        bundle_dir=str(tmp_path),
        add_dll_directory=lambda path: searched.append(path) or directory_handle,
        load_library=lambda path: loaded.append(path),
    )

    assert warning == ""
    assert searched == [str(torch_lib_dir)]
    assert loaded == [str(c10_path)]
    assert windows_runtime._DLL_DIRECTORY_HANDLES == [directory_handle]


def test_runtime_preload_reports_dll_error_without_stopping_other_engines(tmp_path):
    torch_lib_dir = tmp_path / "torch" / "lib"
    torch_lib_dir.mkdir(parents=True)
    c10_path = torch_lib_dir / "c10.dll"
    c10_path.write_bytes(b"test")

    def fail_to_load(_path: str):
        raise OSError("broken runtime")

    warning = windows_runtime.preload_frozen_torch_runtime(
        platform_name="nt",
        frozen=True,
        bundle_dir=str(tmp_path),
        add_dll_directory=lambda _path: None,
        load_library=fail_to_load,
    )

    assert warning == "Torch runtime preload failed: broken runtime"
