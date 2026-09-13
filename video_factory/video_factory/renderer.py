"""Fixed-argument local encoder and technical output checks. No shell execution."""

import json
import math
import subprocess
import threading
import time
from pathlib import Path

from .config import Settings
from .errors import RenderError
from .graphics import FPS, HEIGHT, WIDTH, FramePainter
from .models import Manifest


def probe_output(path: Path, duration: float, settings: Settings) -> dict:
    try:
        result = subprocess.run(
            [settings.ffprobe, "-v", "error", "-protocol_whitelist", "file",
             "-f", "mov", "-show_streams", "-show_format", "-of", "json", str(path)],
            check=True, capture_output=True, timeout=20,
        )
        info = json.loads(result.stdout)
        videos = [s for s in info["streams"] if s["codec_type"] == "video"]
        audios = [s for s in info["streams"] if s["codec_type"] == "audio"]
        video, audio = videos[0], audios[0]
        measured = float(info["format"]["duration"])
        if not (
            len(videos) == len(audios) == 1
            and video["codec_name"] == "h264" and audio["codec_name"] == "aac"
            and video["width"] == WIDTH and video["height"] == HEIGHT
            and video["pix_fmt"] == "yuv420p" and video["r_frame_rate"] == "30/1"
            and math.isfinite(measured) and abs(measured - duration) <= 0.1
            and abs(float(audio["duration"]) - duration) <= 0.1
        ):
            raise ValueError("Unexpected encoded format or duration")
        return {"duration": measured, "width": WIDTH, "height": HEIGHT,
                "fps": FPS, "video_codec": "h264", "audio_codec": "aac",
                "pixel_format": "yuv420p", "bytes": path.stat().st_size}
    except (subprocess.SubprocessError, OSError, KeyError, IndexError, ValueError) as exc:
        raise RenderError("Encoded output did not pass technical validation") from exc


def encode(manifest: Manifest, audio_path: Path, output_path: Path,
           painter: FramePainter, settings: Settings) -> dict:
    partial = output_path.with_suffix(".partial.mp4")
    log_path = output_path.parent / "ffmpeg.log"
    frames = math.ceil(manifest.duration * FPS)
    command = [
        settings.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-n",
        "-threads", "2", "-filter_threads", "1", "-filter_complex_threads", "1",
        "-f", "rawvideo", "-pixel_format", "rgb24",
        "-video_size", f"{WIDTH}x{HEIGHT}", "-framerate", str(FPS),
        "-protocol_whitelist", "pipe", "-i", "pipe:0",
        "-protocol_whitelist", "file", "-f", "wav", "-i", str(audio_path),
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "libx264", "-threads", "2", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-af", "apad", "-t", f"{manifest.duration:.6f}",
        "-map_metadata", "-1", "-movflags", "+faststart",
        "-fs", str(128 * 1024**2), "-f", "mp4", str(partial),
    ]
    process = None
    timer = None
    started = time.monotonic()
    try:
        with log_path.open("xb") as log:
            process = subprocess.Popen(command, stdin=subprocess.PIPE,
                                       stdout=subprocess.DEVNULL, stderr=log)
            timer = threading.Timer(settings.render_timeout_seconds, process.kill)
            timer.daemon = True
            timer.start()
            for frame in range(frames):
                if time.monotonic() - started > settings.render_timeout_seconds:
                    raise RenderError("Local rendering time limit exceeded")
                process.stdin.write(painter.frame(frame / FPS).tobytes())
            process.stdin.close()
            process.wait(timeout=max(1, settings.render_timeout_seconds
                                     - (time.monotonic() - started)))
            if process.returncode:
                raise RenderError("Encoder failed; inspect the local ffmpeg.log")
        technical = probe_output(partial, manifest.duration, settings)
        partial.replace(output_path)
        painter.frame(min(1, manifest.duration / 2)).save(output_path.parent / "preview.png")
        return technical
    except RenderError:
        raise
    except (OSError, subprocess.SubprocessError) as exc:
        raise RenderError("Encoder unavailable, interrupted, or unable to write output") from exc
    finally:
        if timer:
            timer.cancel()
        if process:
            if process.poll() is None:
                process.kill()
            if process.stdin and not process.stdin.closed:
                try:
                    process.stdin.close()
                except OSError:
                    pass
            process.wait()
