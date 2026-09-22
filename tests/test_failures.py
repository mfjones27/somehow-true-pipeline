"""Human-readable job failure lines."""
import unittest

from providers.failures import extract_failure


class ExtractFailureTest(unittest.TestCase):
    def test_prefers_error_prefix(self):
        log = "STEP 1\nRuntimeError: hidden\nERROR: Narration.wav is missing\nPipeline FAILED for FCT-027"
        self.assertEqual(extract_failure(log), "Narration.wav is missing")

    def test_uses_traceback_exception(self):
        log = """
Traceback (most recent call last):
  File "produce_video.py", line 1, in <module>
    run()
RuntimeError: RUNWAY_API_KEY is missing
Pipeline FAILED for FCT-027
"""
        self.assertEqual(extract_failure(log), "RuntimeError: RUNWAY_API_KEY is missing")

    def test_empty_log(self):
        self.assertIn("no log", extract_failure("").lower())


if __name__ == "__main__":
    unittest.main()
