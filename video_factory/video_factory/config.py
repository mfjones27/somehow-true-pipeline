from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    # Trusted local application configuration; never taken from a request.
    root: Path = PROJECT_ROOT
    ffmpeg: str = "/usr/bin/ffmpeg"
    ffprobe: str = "/usr/bin/ffprobe"
    font_regular: str = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    font_bold: str = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    max_audio_bytes: int = 64 * 1024 * 1024
    max_jobs: int = 100
    max_storage_bytes: int = 2 * 1024**3
    min_free_bytes: int = 512 * 1024**2
    render_timeout_seconds: int = 600

    @property
    def assets(self) -> Path:
        return self.root / "assets"

    @property
    def jobs(self) -> Path:
        return self.root / "jobs"

