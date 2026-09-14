"""ffmpeg SIGTERM with a finished file is treated as success."""
import unittest
from types import SimpleNamespace
from pathlib import Path

from produce_video import ffmpeg_output_path, ffmpeg_terminated_cleanly


class FfmpegExitTests(unittest.TestCase):
    def test_output_path_is_last_non_flag(self):
        path = ffmpeg_output_path(["-i", "a.mp4", "-c:v", "libx264", "out.mp4"])
        self.assertEqual(path, Path("out.mp4"))

    def test_signal_15_in_stderr_is_clean(self):
        result = SimpleNamespace(returncode=255, stderr="Exiting normally, received signal 15.\n")
        self.assertTrue(ffmpeg_terminated_cleanly(result))

    def test_normal_failure_is_not_clean(self):
        result = SimpleNamespace(returncode=1, stderr="Error opening input")
        self.assertFalse(ffmpeg_terminated_cleanly(result))


if __name__ == "__main__":
    unittest.main()
