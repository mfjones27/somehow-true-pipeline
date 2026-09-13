"""Small PCM-WAV-only asset boundary, with directory-relative no-follow opens."""

import os
import stat
import wave
from pathlib import Path

from .config import Settings
from .errors import FactoryError


def snapshot_audio(relative_path: str, destination: Path, settings: Settings,
                   expected_duration: float) -> dict:
    """Copy a regular file through safe file descriptors; never follow symlinks.

    Each component is opened under the asset root with O_NOFOLLOW. The final
    descriptor remains the same even if another local process renames a path.
    Only this snapshot is handed to ffmpeg.
    """
    parts = relative_path.split("/")
    if any(part in ("", ".", "..") for part in parts) or relative_path.startswith("/"):
        raise FactoryError("Narration must be a safe asset-root-relative path")
    root_fd = None
    file_fd = None
    try:
        root_fd = os.open(settings.assets, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        for part in parts[:-1]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                              dir_fd=root_fd)
            os.close(root_fd)
            root_fd = next_fd
        file_fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                          dir_fd=root_fd)
        metadata = os.fstat(file_fd)
        if not stat.S_ISREG(metadata.st_mode):
            raise FactoryError("Narration must be a regular file")
        if metadata.st_size > settings.max_audio_bytes:
            raise FactoryError("Narration exceeds the 64 MiB input limit")
        with os.fdopen(file_fd, "rb") as source:
            file_fd = None
            with destination.open("xb") as target:
                # Bound the copy even if a local writer grows the source during reading.
                remaining = settings.max_audio_bytes + 1
                while remaining:
                    block = source.read(min(1024 * 1024, remaining))
                    if not block:
                        break
                    target.write(block)
                    remaining -= len(block)
                if target.tell() > settings.max_audio_bytes:
                    raise FactoryError("Narration exceeds the 64 MiB input limit")
        with wave.open(str(destination), "rb") as audio:
            if (audio.getcomptype() != "NONE" or audio.getnchannels() not in (1, 2)
                    or audio.getsampwidth() not in (2, 3, 4)
                    or not 22050 <= audio.getframerate() <= 96000):
                raise FactoryError("Use mono/stereo 16/24/32-bit PCM WAV at 22.05–96 kHz")
            duration = audio.getnframes() / audio.getframerate()
            if abs(duration - expected_duration) > 0.05:
                raise FactoryError("Audio duration must match manifest within 0.05 seconds")
            # Check declared PCM data is actually present, not just a plausible header.
            expected_bytes = audio.getnframes() * audio.getnchannels() * audio.getsampwidth()
            if len(audio.readframes(audio.getnframes())) != expected_bytes:
                raise FactoryError("Narration WAV is truncated")
            return {
                "duration": duration, "channels": audio.getnchannels(),
                "sample_rate": audio.getframerate(), "sample_width": audio.getsampwidth(),
            }
    except FactoryError:
        raise
    except (OSError, wave.Error, EOFError) as exc:
        raise FactoryError("Narration is missing, unsafe, or not a supported PCM WAV") from exc
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if root_fd is not None:
            os.close(root_fd)
