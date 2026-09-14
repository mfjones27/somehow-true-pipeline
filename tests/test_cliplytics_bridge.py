"""Cliplytics → Somehow True CONTENT.csv importer."""
from __future__ import annotations

import csv
import json
import unittest
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from import_cliplytics import main
from providers.cliplytics_bridge import (
    CONTENT_COLUMNS,
    IMPORT_STATUS,
    build_core_fact,
    import_items,
    item_to_row,
    load_items,
    next_cliplytics_id,
    parse_payload,
    prefer_sidecars,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "cliplytics"
SIDECAR = FIXTURES / "tiktok_ready" / "compound-interest-trap.json"
RESULTS = FIXTURES / "results" / "video_results.json"


def _seed_csv(path: Path, extra_rows: list[dict[str, str]] | None = None) -> None:
    rows = extra_rows or []
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CONTENT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


class SidecarMappingTest(unittest.TestCase):
    def test_tiktok_ready_sidecar_maps_to_row(self):
        data = json.loads(SIDECAR.read_text(encoding="utf-8"))
        item = parse_payload(data, SIDECAR, "tiktok_ready")[0]
        row = item_to_row(item, "CLX-001", "2026-09-14 00:00:00")
        self.assertEqual(row["id"], "CLX-001")
        self.assertEqual(row["topic"], "Why most people never actually see compound interest")
        self.assertEqual(row["category"], "finance")
        self.assertEqual(
            row["hook"],
            "Everyone quotes compound interest. Almost nobody lasts long enough for it to matter.",
        )
        self.assertIn("Source URL: https://www.tiktok.com/@moneymentor/video/7123456789012345678", row["core_fact"])
        self.assertIn("Cliplytics id: tt-7123456789012345678", row["core_fact"])
        self.assertIn("not independently verified", row["core_fact"])
        self.assertIn("Everyone quotes compound interest", row["script"])
        self.assertIn("Treat the numbers as a prompt to check", row["script"])
        self.assertEqual(row["script_version"], "1")
        self.assertEqual(row["status"], IMPORT_STATUS)
        self.assertEqual(row["duration_seconds"], "28.5")
        self.assertEqual(row["fingerprint"], item.fingerprint)
        self.assertTrue(row["fingerprint"])


class ResultsMappingTest(unittest.TestCase):
    def test_video_result_maps_to_row(self):
        data = json.loads(RESULTS.read_text(encoding="utf-8"))
        item = parse_payload(data, RESULTS, "results")[0]
        row = item_to_row(item, "CLX-002", "2026-09-14 00:00:00")
        self.assertEqual(row["topic"][:40], "A short claims grocery prices doubled wh")
        self.assertEqual(row["category"], "economy")
        self.assertEqual(
            row["hook"],
            "This inflation chart will shock you. #inflation #economy",
        )
        self.assertEqual(row["script"], "")
        self.assertEqual(row["script_version"], "0")
        core = build_core_fact(item)
        self.assertIn("Cliplytics analysis summary (unverified):", core)
        self.assertIn("Creator asserts grocery prices doubled.", core)
        self.assertIn("https://www.youtube.com/watch?v=dQwFinanceExample", core)
        self.assertNotIn("grocery prices doubled while wages stayed flat, and that is true", core.lower())


class DuplicateAndDryRunTest(unittest.TestCase):
    def test_duplicate_source_is_skipped(self):
        items, skipped_load = load_items([(SIDECAR, "tiktok_ready")])
        self.assertEqual(skipped_load, [])
        with TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "CONTENT.csv"
            first = import_items(items, csv_path, now="2026-09-14 00:00:00")
            self.assertEqual(len(first.imported), 1)
            self.assertEqual(first.imported[0]["id"], "CLX-001")
            second = import_items(items, csv_path, now="2026-09-14 00:00:01")
            self.assertEqual(second.imported, [])
            self.assertEqual(len(second.skipped), 1)
            self.assertEqual(second.skipped[0].reason, "duplicate")
            rows = _read_csv(csv_path)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["id"], "CLX-001")

    def test_dry_run_does_not_write_csv_or_config(self):
        items, _ = load_items([(SIDECAR, "tiktok_ready")])
        with TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "CONTENT.csv"
            imports_root = Path(tmp) / "imports"
            _seed_csv(csv_path)
            result = import_items(
                items,
                csv_path,
                dry_run=True,
                write_config=True,
                imports_root=imports_root,
                now="2026-09-14 00:00:00",
            )
            self.assertEqual(len(result.imported), 1)
            self.assertEqual(result.imported[0]["id"], "CLX-001")
            self.assertEqual(_read_csv(csv_path), [])
            self.assertFalse(imports_root.exists())
            self.assertEqual(result.configs, [])

    def test_write_config_emits_produce_json(self):
        items, _ = load_items([(SIDECAR, "tiktok_ready")])
        with TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "CONTENT.csv"
            imports_root = Path(tmp) / "imports"
            result = import_items(
                items,
                csv_path,
                write_config=True,
                imports_root=imports_root,
                now="2026-09-14 00:00:00",
            )
            config_path = imports_root / "CLX-001" / "config.json"
            self.assertEqual(result.configs, [config_path])
            config = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(config["content_id"], "CLX-001")
            self.assertIn("compound interest", config["title"].lower())
            self.assertEqual(
                config["sources"],
                ["https://www.tiktok.com/@moneymentor/video/7123456789012345678"],
            )
            self.assertTrue(config["scene_prompts"])
            self.assertEqual(len(config["scene_durations"]), len(config["scene_prompts"]))
            self.assertIn("unverified", config["description"].lower())

    def test_auto_prefers_sidecar_over_results_duplicate(self):
        sidecar_items, _ = load_items([(SIDECAR, "tiktok_ready")])
        # Same URL as the sidecar, presented as a VideoResult.
        duplicate_result = {
            "id": "tt-7123456789012345678",
            "url": "https://www.tiktok.com/@moneymentor/video/7123456789012345678",
            "platform": "tiktok",
            "metadata": {
                "id": "tt-7123456789012345678",
                "url": "https://www.tiktok.com/@moneymentor/video/7123456789012345678",
                "caption": "weaker caption",
                "hashtags": ["finance"],
            },
            "analysis": {"summary": "weaker summary", "topics": [], "key_takeaways": []},
            "script": None,
            "error": None,
        }
        result_item = parse_payload(duplicate_result, Path("results/dup.json"), "results")[0]
        chosen, skipped = prefer_sidecars(sidecar_items + [result_item])
        self.assertEqual(len(chosen), 1)
        self.assertEqual(chosen[0].source_kind, "tiktok_ready")
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0].reason, "duplicate")

    def test_clx_ids_do_not_follow_fct_sequence(self):
        rows = [{"id": "FCT-023", "fingerprint": "abc"}]
        self.assertEqual(next_cliplytics_id(rows), "CLX-001")
        rows.append({"id": "CLX-001"})
        self.assertEqual(next_cliplytics_id(rows), "CLX-002")


class CliTest(unittest.TestCase):
    def test_help_exits_zero(self):
        with patch("sys.stdout", new=StringIO()), self.assertRaises(SystemExit) as caught:
            main(["--help"])
        self.assertEqual(caught.exception.code, 0)

    def test_cli_dry_run_from_input_file(self):
        with TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "CONTENT.csv"
            _seed_csv(csv_path, [{"id": "FCT-001", **{k: "" for k in CONTENT_COLUMNS if k != "id"}}])
            with patch("sys.stdout", new=StringIO()):
                code = main(
                    [
                        "--input",
                        str(SIDECAR),
                        "--csv",
                        str(csv_path),
                        "--dry-run",
                        "--source",
                        "tiktok_ready",
                    ]
                )
            self.assertEqual(code, 0)
            rows = _read_csv(csv_path)
            self.assertEqual([row["id"] for row in rows], ["FCT-001"])

    def test_cli_imports_unique_sidecar_and_result(self):
        with TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "CONTENT.csv"
            _seed_csv(csv_path)
            with patch("sys.stdout", new=StringIO()):
                code = main(
                    [
                        "--cliplytics-dir",
                        str(FIXTURES),
                        "--csv",
                        str(csv_path),
                    ]
                )
            self.assertEqual(code, 0)
            ids = [row["id"] for row in _read_csv(csv_path)]
            self.assertEqual(ids, ["CLX-001", "CLX-002"])


if __name__ == "__main__":
    unittest.main()
