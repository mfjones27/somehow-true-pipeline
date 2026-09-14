"""Somehow True desktop window. Starts the local API and opens the React UI."""
from __future__ import annotations

import os
import sys
import threading
import time
import urllib.request
from pathlib import Path

os.environ["DESKTOP_MODE"] = "true"
os.environ["PIPELINE_ENABLED"] = "true"
os.environ.setdefault("SOMEHOW_TRUE_PORT", "8765")

APP_ID = "SomehowTrue.Studio"
WINDOW_TITLE = "Somehow True"

if sys.platform == "win32":
    import ctypes
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)

if getattr(sys, "frozen", False):
    os.environ.setdefault("SOMEHOW_TRUE_ROOT", str(Path(sys.executable).resolve().parent))

from providers.env import ROOT, load_env

load_env()

PORT = int(os.environ.get("SOMEHOW_TRUE_PORT", "8765"))
HOST = "127.0.0.1"
URL = f"http://{HOST}:{PORT}"
_SERVER_ERROR: list[BaseException] = []


def _focus_existing() -> bool:
    if sys.platform != "win32":
        return False
    import ctypes
    hwnd = ctypes.windll.user32.FindWindowW(None, WINDOW_TITLE)
    if not hwnd:
        return False
    ctypes.windll.user32.ShowWindow(hwnd, 9)
    ctypes.windll.user32.SetForegroundWindow(hwnd)
    return True


def _studio_alive() -> bool:
    try:
        with urllib.request.urlopen(f"{URL}/health", timeout=0.6) as resp:
            return resp.status == 200
    except Exception:
        return False


def _already_running() -> bool:
    if sys.platform != "win32":
        return False
    import ctypes
    ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\SomehowTrue.Studio")
    return ctypes.GetLastError() == 183


def _wait_for_server(timeout: float = 25) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _SERVER_ERROR:
            raise _SERVER_ERROR[0]
        try:
            with urllib.request.urlopen(f"{URL}/health", timeout=1) as resp:
                if resp.status == 200:
                    return
        except Exception:
            time.sleep(0.15)
    raise RuntimeError(f"Studio did not start on {URL}")


def _run_server() -> None:
    try:
        import uvicorn
        from app import app

        uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
    except Exception as exc:
        _SERVER_ERROR.append(exc)
        log = ROOT / "pipeline_output" / "studio-server.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(f"{type(exc).__name__}: {exc}", encoding="utf-8")


def _set_window_app_id(hwnd: int, relaunch: str, icon: str) -> None:
    """Make this window group with the pinned Somehow True icon."""
    import ctypes
    from ctypes import HRESULT, POINTER, Structure, byref, c_ubyte, c_uint16, c_uint32, c_ushort, c_void_p, c_wchar_p

    ole32 = ctypes.oledll.ole32
    shell32 = ctypes.windll.shell32

    class GUID(Structure):
        _fields_ = [
            ("Data1", c_uint32),
            ("Data2", c_uint16),
            ("Data3", c_uint16),
            ("Data4", c_ubyte * 8),
        ]

    class PROPERTYKEY(Structure):
        _fields_ = [("fmtid", GUID), ("pid", c_uint32)]

    class PROPVARIANT(Structure):
        _fields_ = [
            ("vt", c_ushort),
            ("wReserved1", c_ushort),
            ("wReserved2", c_ushort),
            ("wReserved3", c_ushort),
            ("pszVal", c_wchar_p),
        ]

    iid = GUID()
    ole32.IIDFromString("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}", byref(iid))
    fmt = GUID()
    ole32.IIDFromString("{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}", byref(fmt))

    store = c_void_p()
    getter = shell32.SHGetPropertyStoreForWindow
    getter.argtypes = [c_void_p, POINTER(GUID), POINTER(c_void_p)]
    getter.restype = HRESULT
    if getter(hwnd, byref(iid), byref(store)) != 0 or not store.value:
        return

    class Vtbl(Structure):
        _fields_ = [
            ("QueryInterface", c_void_p),
            ("AddRef", c_void_p),
            ("Release", ctypes.WINFUNCTYPE(c_uint32, c_void_p)),
            ("GetCount", c_void_p),
            ("GetAt", c_void_p),
            ("GetValue", c_void_p),
            ("SetValue", ctypes.WINFUNCTYPE(HRESULT, c_void_p, POINTER(PROPERTYKEY), POINTER(PROPVARIANT))),
            ("Commit", ctypes.WINFUNCTYPE(HRESULT, c_void_p)),
        ]

    class Store(Structure):
        _fields_ = [("lpVtbl", POINTER(Vtbl))]

    ps = ctypes.cast(store, POINTER(Store))
    vtbl = ps.contents.lpVtbl.contents
    values = {
        5: APP_ID,
        2: f'"{relaunch}"',
        4: WINDOW_TITLE,
        3: icon,
    }
    for pid, value in values.items():
        if not value:
            continue
        key = PROPERTYKEY()
        key.fmtid = fmt
        key.pid = pid
        variant = PROPVARIANT()
        variant.vt = 31
        variant.pszVal = value
        vtbl.SetValue(store, byref(key), byref(variant))
    vtbl.Commit(store)
    vtbl.Release(store)


def _claim_taskbar(window) -> None:
    if sys.platform != "win32":
        return
    import ctypes

    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    hwnd = ctypes.windll.user32.FindWindowW(None, WINDOW_TITLE)
    if not hwnd:
        try:
            hwnd = int(window.native.Handle.ToInt64())
        except Exception:
            return
    exe = next(
        (path for path in (ROOT / "Somehow True.exe", ROOT / "SomehowTrue.exe") if path.exists()),
        Path(sys.executable),
    )
    icon = str(ROOT / "ui" / "icon.ico")
    try:
        _set_window_app_id(hwnd, str(exe), icon)
    except Exception:
        pass


def main() -> int:
    try:
        if _studio_alive() and _focus_existing():
            return 0
        if _already_running() and _focus_existing():
            return 0
        threading.Thread(target=_run_server, daemon=True).start()
        _wait_for_server()
        if _SERVER_ERROR:
            raise _SERVER_ERROR[0]
        import webview

        icon = ROOT / "ui" / "icon.ico"
        webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
        window = webview.create_window(
            WINDOW_TITLE,
            URL,
            width=1440,
            height=920,
            min_size=(960, 680),
            background_color="#0b0907",
            text_select=True,
        )
        window.events.shown += lambda *_args: _claim_taskbar(window)
        webview.start(icon=str(icon) if icon.exists() else None)
        return 0
    except Exception as exc:
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, str(exc), WINDOW_TITLE, 0x10)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
