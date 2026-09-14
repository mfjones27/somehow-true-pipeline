"""Windows exe entry. Hosts the studio in this process so the taskbar pin groups."""
from __future__ import annotations

import importlib.util
import os
import sys
import traceback
from pathlib import Path


def _message(title: str, text: str, error: bool = True) -> None:
    if sys.platform != "win32":
        print(text)
        return
    import ctypes
    ctypes.windll.user32.MessageBoxW(None, text, title, 0x10 if error else 0x40)


def repo_root() -> Path:
    here = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    for candidate in (here, here.parent):
        if (candidate / "desktop.py").exists() and (candidate / "daily_pipeline.py").exists():
            return candidate
    raise FileNotFoundError(
        "This shortcut is not in the pipeline folder.\n"
        f"Looked in:\n{here}\n{here.parent}\n\n"
        "Pin SomehowTrue.exe from the somehow-true-pipeline folder."
    )


def _attach_venv(root: Path) -> None:
    sys.path.insert(0, str(root))
    venv = root / ".venv"
    scripts = venv / "Scripts"
    site_packages = venv / "Lib" / "site-packages"
    extras = [p for p in (scripts, venv / "DLLs", venv / "Library" / "bin") if p.exists()]
    if extras:
        os.environ["PATH"] = os.pathsep.join(str(p) for p in extras) + os.pathsep + os.environ.get("PATH", "")
    if hasattr(os, "add_dll_directory"):
        for folder in extras:
            os.add_dll_directory(str(folder))
    if site_packages.exists():
        sys.path.insert(0, str(site_packages))
        import site
        site.addsitedir(str(site_packages))


def _run_studio(root: Path) -> int:
    os.chdir(root)
    os.environ["SOMEHOW_TRUE_ROOT"] = str(root)
    _attach_venv(root)
    path = root / "desktop.py"
    spec = importlib.util.spec_from_file_location("somehow_true_desktop", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return int(module.main() or 0)


def main() -> int:
    try:
        return _run_studio(repo_root())
    except Exception:
        _message("Somehow True", traceback.format_exc()[-1500:])
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
