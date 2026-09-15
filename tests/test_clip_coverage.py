"""Narration vs Runway clip coverage planning."""
import unittest

from providers.clip_coverage import (
    COVERAGE_SLACK_SECONDS,
    fill_clip_durations,
    hold_prompt,
    plan_scene_coverage,
)
from providers.runway import PROMPT_MAX_UNITS, utf16_units


class FillDurationsTest(unittest.TestCase):
    def test_no_gap(self):
        self.assertEqual(fill_clip_durations(0), [])
        self.assertEqual(fill_clip_durations(-1), [])

    def test_rounds_up_to_runway_minimum(self):
        self.assertEqual(fill_clip_durations(0.4), [4])
        self.assertEqual(fill_clip_durations(1), [4])

    def test_single_clip_under_max(self):
        self.assertEqual(fill_clip_durations(8.2), [9])
        self.assertEqual(fill_clip_durations(10), [10])

    def test_splits_beyond_max(self):
        self.assertEqual(fill_clip_durations(11), [11])
        self.assertEqual(fill_clip_durations(16), [15, 4])
        self.assertEqual(fill_clip_durations(20), [15, 5])
        self.assertEqual(fill_clip_durations(30), [15, 15])


class PlanCoverageTest(unittest.TestCase):
    def test_already_covers(self):
        prompts = ["a", "b"]
        durations = [10, 10]
        out_p, out_d = plan_scene_coverage(prompts, durations, 19.9)
        self.assertEqual(out_p, ["a", "b"])
        self.assertEqual(out_d, [10, 10])

    def test_grows_existing_scenes_from_the_end(self):
        prompts = ["open", "middle", "close"]
        _, durations = plan_scene_coverage(prompts, [5, 8, 5], 23)
        self.assertEqual(durations, [5, 8, 10])
        self.assertEqual(len(prompts), 3)

    def test_fct023_grows_existing_scenes_instead_of_a_seventh(self):
        """FCT-023: 50s of planned clips vs 58.56s narration."""
        prompts = [f"scene {i}" for i in range(6)]
        planned, durations = plan_scene_coverage(prompts, [10, 10, 5, 8, 8, 9], 58.56)
        self.assertEqual(len(planned), 6)
        self.assertGreaterEqual(sum(durations), 58.56 - COVERAGE_SLACK_SECONDS)
        self.assertEqual(durations, [10, 10, 5, 8, 11, 15])

    def test_adds_fill_clip_when_six_max_clips_are_not_enough(self):
        prompts = [f"scene {i}" for i in range(6)]
        planned, durations = plan_scene_coverage(prompts, [15] * 6, 96.2)
        self.assertEqual(durations[:6], [15] * 6)
        self.assertEqual(durations[6:], [7])
        self.assertEqual(len(planned), 7)
        self.assertIn("Almost still", planned[-1])
        self.assertTrue(planned[-1].startswith("scene 5."))

    def test_pads_missing_durations(self):
        _, durations = plan_scene_coverage(["a", "b", "c"], [8], 10)
        self.assertEqual(len(durations), 3)

    def test_clamps_too_short_durations(self):
        _, durations = plan_scene_coverage(["a", "b"], [2, 2], 8)
        self.assertTrue(all(d >= 4 for d in durations))

    def test_hold_prompt_stays_within_runway_limit(self):
        text = hold_prompt("word " * 4000)
        self.assertLessEqual(utf16_units(text), PROMPT_MAX_UNITS)


if __name__ == "__main__":
    unittest.main()
