"""Caption lines stay inside the 1080x1920 safe area."""
import unittest

from providers.captions import (
    CAPTION_MAX_WIDTH,
    CAPTION_POS_X,
    fit_caption_phrases,
    lock_caption_style,
    measure_text,
    scale_font_to_fit,
)
from produce_video import _group_phrases


FONT = r"C:\Windows\Fonts\arialbd.ttf"


class CaptionFitTest(unittest.TestCase):
    def test_lock_centers_and_widens_safe_box(self):
        config = lock_caption_style({
            "caption_style": {"pos_x": 485, "max_width_px": 780, "active_word_color": "&H87E2C5&"},
        })
        self.assertEqual(config["caption_style"]["pos_x"], CAPTION_POS_X)
        self.assertEqual(config["caption_style"]["pos_x"], 540)
        self.assertEqual(config["caption_style"]["max_width_px"], CAPTION_MAX_WIDTH)
        self.assertEqual(config["caption_style"]["active_word_color"], "&H87E2C5")

    def test_long_phrase_is_split_to_fit(self):
        phrases = fit_caption_phrases(
            ["previously uncharted volcanoes and sprawling lava fields"],
            FONT,
            66,
        )
        self.assertGreater(len(phrases), 1)
        for phrase in phrases:
            self.assertLessEqual(len(phrase.split()), 3)
            self.assertLessEqual(measure_text(phrase, FONT, 66), CAPTION_MAX_WIDTH)

    def test_short_phrase_stays_together(self):
        phrases = fit_caption_phrases(["Cave of Crystals"], FONT, 66)
        self.assertEqual(phrases, ["Cave of Crystals"])

    def test_single_long_word_shrinks_font(self):
        word = "electroencephalographically"
        size = scale_font_to_fit(word, FONT, 66)
        self.assertLessEqual(measure_text(word, FONT, size), CAPTION_MAX_WIDTH)

    def test_group_phrases_does_not_glue_leftovers(self):
        phrases = _group_phrases("one two three four five.", [])
        self.assertIn("four five.", phrases)
        self.assertTrue(all(len(p.split()) <= 3 for p in phrases))


if __name__ == "__main__":
    unittest.main()
