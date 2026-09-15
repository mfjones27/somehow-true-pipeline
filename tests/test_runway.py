"""Locked Runway model, prompt quality, and clip file checks."""
import tempfile
import unittest
from pathlib import Path

from providers.runway import (
    HARD_BANS,
    RUNWAY_MODEL,
    RUNWAY_RATIO,
    clip_file_issues,
    clip_prompt,
    lock_runway_config,
    prepare_prompt,
    prompt_problems,
    text_to_video_request,
    utf16_units,
    weak_prompts,
)


DETAILED = (
    "35mm locked-off medium close-up of a brass marine chronometer on a teak chart table, "
    "the second hand ticking as afternoon sidelight from a porthole slides across engraved numerals. "
    "Camera slowly pushes in two feet over eight seconds. Warm tungsten fill from a desk lamp at camera left, "
    "cool window light on the right, shallow depth of field, dust in the beam. "
    "Keep the lower third empty for captions. No on-screen text, logos, or faces."
)


def _clip(size=90_000) -> Path:
    handle = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    handle.write(b"0" * size)
    handle.close()
    return Path(handle.name)


class RunwayLockTest(unittest.TestCase):
    def test_force_overwrites_old_config(self):
        config = lock_runway_config({"runway_model": "gen4.5", "runway_ratio": "720:1280"})
        self.assertEqual(config["runway_model"], "seedance2_5")
        self.assertEqual(config["runway_ratio"], "1080:1920")
        self.assertIs(config["runway_audio"], False)

    def test_text_to_video_request_is_seedance_1080p_silent(self):
        request = text_to_video_request(DETAILED, 8)
        self.assertEqual(request["model"], RUNWAY_MODEL)
        self.assertEqual(request["model"], "seedance2_5")
        self.assertEqual(request["ratio"], RUNWAY_RATIO)
        self.assertEqual(request["duration"], 8)
        self.assertIs(request["audio"], False)
        self.assertGreater(len(request["promptText"]), 400)

    def test_duration_clamps_to_model_limits(self):
        self.assertEqual(text_to_video_request(DETAILED, 2)["duration"], 4)
        self.assertEqual(text_to_video_request(DETAILED, 40)["duration"], 15)


class PromptQualityTest(unittest.TestCase):
    def test_short_generic_prompt_is_rejected(self):
        issues = prompt_problems("Portrait cinematic shot of a fictional town.")
        self.assertTrue(issues)

    def test_detailed_prompt_passes(self):
        self.assertEqual(prompt_problems(prepare_prompt(DETAILED)), [])

    def test_weak_prompts_flags_index(self):
        flagged = weak_prompts(["a town", DETAILED])
        self.assertEqual(flagged[0][0], 0)

    def test_prepare_prompt_appends_bans(self):
        text = prepare_prompt(
            "35mm close-up of a rusted buoy chain under overcast north-sea light, "
            "camera dolly along the links, wet metal catching a cold highlight, "
            "barnacles and orange rust flakes, lower third empty."
        )
        self.assertIn("No on-screen text", text)
        self.assertIn("No on-screen text", HARD_BANS)

    def test_clip_prompt_respects_utf16_budget(self):
        text = clip_prompt("w" * 20_000)
        self.assertLessEqual(utf16_units(text), 14_000)


class ClipFileIssuesTest(unittest.TestCase):
    def tearDown(self):
        for path in getattr(self, "_temps", []):
            path.unlink(missing_ok=True)

    def test_720p_is_rejected_when_1080_required(self):
        path = _clip()
        self._temps = [path]
        probe = {
            "streams": [{"codec_type": "video", "width": 720, "height": 1280, "duration": "8.0"}],
            "format": {"duration": "8.0"},
        }
        issues = clip_file_issues(path, probe, 8, require_1080=True)
        self.assertTrue(any("720x1280" in issue for issue in issues))

    def test_1080p_probe_is_clean(self):
        path = _clip()
        self._temps = [path]
        probe = {
            "streams": [{"codec_type": "video", "width": 1080, "height": 1920, "duration": "8.02"}],
            "format": {"duration": "8.02"},
        }
        self.assertEqual(clip_file_issues(path, probe, 8, require_1080=True), [])


if __name__ == "__main__":
    unittest.main()
