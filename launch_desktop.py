"""Windows exe entry. Starts the studio with visible errors if something is missing."""
from __future__ import annotations

import os
import shutil
import subprocess
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


def python_bin(root: Path) -> str:
    candidates: list[Path] = [
        root / ".venv" / "Scripts" / "python.exe",
        Path(r"C:\Python314\python.exe"),
        Path(r"C:\Python313\python.exe"),
        Path(r"C:\Python312\python.exe"),
    ]
    if not getattr(sys, "frozen", False):
        candidates.insert(0, Path(sys.executable))
    which = shutil.which("python")
    if which:
        candidates.append(Path(which))
    for path in candidates:
        if path and path.exists() and path.name.lower() != "somehowtrue.exe":
            return str(path)
    raise FileNotFoundError(
        "Python was not found. Install Python 3 and retry.\n"
        "The taskbar pin launches Python, which then opens the studio."
    )


def main() -> int:
    try:
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("SomehowTrue.Studio")
        root = repo_root()
        os.chdir(root)
        py = python_bin(root)
        log_path = root / "pipeline_output" / "studio-launch.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        creation = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0  # type: ignore[attr-defined]
        with log_path.open("w", encoding="utf-8") as log:
            log.write(f"root={root}\npython={py}\nexe={sys.executable}\n")
            log.flush()
            proc = subprocess.Popen(
                [py, "-u", str(root / "desktop.py")],
                cwd=str(root),
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=creation,
            )
            code = proc.wait()
        if code != 0:
            detail = log_path.read_text(encoding="utf-8", errors="replace")[-1500:]
            _message("Somehow True", f"Studio exited ({code}).\n\n{detail}")
            return code
        return 0
    except Exception:
        _message("Somehow True", traceback.format_exc()[-1500:])
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
