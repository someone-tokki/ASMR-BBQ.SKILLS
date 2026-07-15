from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from check_preflight import load_profile, validate
from preflight_gate import enforce_preflight
from render_preflight_questionnaire import REQUIRED_ITEMS, render


class PreflightGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source = self.root / "RJ000000"
        self.source.mkdir()
        (self.source / "track.mp3").write_bytes(b"placeholder")
        self.questionnaire = self.root / "preflight_questionnaire.md"
        self.questionnaire.write_text(render(self.root, self.source, {}, {}, {}), encoding="utf-8")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def profile(self) -> dict:
        content = self.questionnaire.read_text(encoding="utf-8")
        return {
            "confirmed": True,
            "confirmation_source": "explicit_user",
            "preflight_questions_presented": True,
            "preflight_questionnaire": {
                "path": self.questionnaire.as_posix(),
                "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            },
            "confirmed_items": ["scope", "quality_mode", "asr", "translate", "qc", "output_format"],
            "quality_mode": "standard",
            "output_format": "vtt",
            "scope": "all",
            "audio_scope_summary": "one MP3",
            "asr_audio_preparation": {"wav_only_choice_required": False},
            "stages": {
                "asr": {"backend": "local-asr-api", "model": "large-v3"},
                "translate": {"backend": "openai-compatible", "base_url": "http://127.0.0.1:8000/v1", "model": "translator"},
                "qc": {"backend": "openai-compatible", "base_url": "http://127.0.0.1:8000/v1", "model": "qc"},
            },
        }

    def test_rendered_questionnaire_has_all_required_items(self) -> None:
        content = self.questionnaire.read_text(encoding="utf-8")
        for item in REQUIRED_ITEMS:
            self.assertIn(item, content)
        self.assertIn("## 7.", content)

    def test_valid_questionnaire_allows_preflight(self) -> None:
        self.assertEqual(validate(self.profile(), "asr"), [])

    def test_relative_questionnaire_path_resolves_from_project_root(self) -> None:
        profile = self.profile()
        profile["preflight_questionnaire"]["path"] = "preflight_questionnaire.md"
        (self.root / "run_profile.json").write_text(json.dumps(profile), encoding="utf-8")
        self.assertEqual(validate(load_profile(self.root), "translate"), [])

    def test_changed_questionnaire_blocks_preflight(self) -> None:
        profile = self.profile()
        self.questionnaire.write_text(self.questionnaire.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8")
        self.assertIn("preflight_questionnaire changed after user confirmation; render and confirm it again", validate(profile, "asr"))

    def test_missing_project_root_is_not_silently_allowed(self) -> None:
        with self.assertRaises(SystemExit):
            enforce_preflight(argparse.Namespace(project_root=""), "asr")


if __name__ == "__main__":
    unittest.main()
