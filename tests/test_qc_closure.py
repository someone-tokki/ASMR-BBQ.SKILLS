from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from apply_qc_decisions import apply_items
from review_qc_report import normalize_report
from validate_qc_closure import validate_items


SRT_JA = """1
00:00:00,000 --> 00:00:02,000
先生、聞こえる？

2
00:00:02,000 --> 00:00:04,000
もっと近くに来て。

3
00:00:04,000 --> 00:00:06,000
これはただの息遣い。
"""

SRT_ZH = """1
00:00:00,000 --> 00:00:02,000
先生，听得见吗？

2
00:00:02,000 --> 00:00:04,000
再靠近一点。

3
00:00:04,000 --> 00:00:06,000
这是普通的呼吸声。
"""


class QcClosureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.asr_dir = root / "asr"
        self.zh_dir = root / "zh"
        self.asr_dir.mkdir()
        self.zh_dir.mkdir()
        (self.asr_dir / "track.ja.asr.srt").write_text(SRT_JA, encoding="utf-8")
        (self.zh_dir / "track.zh.srt").write_text(SRT_ZH, encoding="utf-8")
        self.report = {
            "track.ja.asr.srt": [
                {"i": 1, "problem": "称呼错译", "suggest": "老师，听得见吗？"},
                {"i": 2, "problem": "标点不自然", "suggest": "再靠近一点。"},
                {"i": 3, "problem": "ASR 幻觉，可能不是真台词", "suggest": "[持续呼吸声]"},
            ]
        }

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def expected_items(self) -> list[dict]:
        return [item.__dict__ for item in normalize_report(self.report, asr_dir=self.asr_dir, zh_dir=self.zh_dir)]

    def closed_items(self) -> list[dict]:
        items = self.expected_items()
        items[0].update(
            decision="accept",
            replacement="老师，听得见吗？",
            decision_reason="台本对应句保留老师称呼。",
            evidence_level="script_confirmed",
            evidence_summary="台本原文与当前日文一致，确认先生应保留为老师。",
        )
        items[1].update(
            decision="reject",
            decision_reason="当前标点和停顿已自然，QC 建议未带来实际改动。",
            evidence_level="ja_context_confirmed",
            evidence_summary="相邻字幕语气连续。",
        )
        items[2].update(
            decision="defer",
            decision_reason="无台本且 ASR 不能证明这是纯音效。",
            evidence_level="insufficient",
            evidence_summary="需要听感确认。",
            review_required=True,
            review_method="audio_review",
        )
        return items

    def test_normalization_has_stable_id_category_and_context(self) -> None:
        first = self.expected_items()
        second = self.expected_items()
        self.assertEqual([item["issue_id"] for item in first], [item["issue_id"] for item in second])
        self.assertEqual(first[0]["category"], "role_tone")
        self.assertEqual(first[2]["category"], "hallucination")
        self.assertEqual(first[1]["context_before"][0]["i"], 1)
        self.assertEqual(first[1]["context_after"][0]["i"], 3)

    def test_closure_accepts_evidence_rejects_and_defers(self) -> None:
        report, passed = validate_items(self.expected_items(), self.closed_items())
        self.assertTrue(passed)
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["summary"]["ready_to_apply"], 1)
        self.assertEqual(report["summary"]["deferred"], 1)
        self.assertEqual(report["manual_review_items"][0]["index"], 3)

    def test_closure_rejects_missing_or_insufficient_acceptance(self) -> None:
        items = self.closed_items()
        items[0]["evidence_level"] = "insufficient"
        report, passed = validate_items(self.expected_items(), items[:-1])
        self.assertFalse(passed)
        self.assertEqual(report["summary"]["unresolved"], 1)
        self.assertIn("lacks sufficient source evidence", " ".join(report["errors"]))

    def test_closure_rejects_defer_without_review_method(self) -> None:
        items = self.closed_items()
        items[2]["review_method"] = ""
        report, passed = validate_items(self.expected_items(), items)
        self.assertFalse(passed)
        self.assertIn("Deferred item has no review_method", " ".join(report["errors"]))

    def test_closure_rejects_duplicate_decision_entries(self) -> None:
        items = self.closed_items()
        items.append(dict(items[0]))
        report, passed = validate_items(self.expected_items(), items)
        self.assertFalse(passed)
        self.assertIn("Duplicate decision item", " ".join(report["errors"]))

    def test_apply_only_changes_closure_approved_target(self) -> None:
        reviewed = self.closed_items()
        closure, passed = validate_items(self.expected_items(), reviewed)
        self.assertTrue(passed)
        allowances = {item["issue_id"]: item for item in closure["items"]}
        results, failures = apply_items(
            reviewed,
            zh_dir=self.zh_dir,
            closure_allowances=allowances,
            apply=True,
            allow_stale=False,
            backup_dir=self.zh_dir / "backup",
        )
        self.assertEqual(failures, 0)
        self.assertIn("applied", [result.status for result in results])
        updated = (self.zh_dir / "track.zh.srt").read_text(encoding="utf-8")
        self.assertIn("老师，听得见吗？", updated)
        self.assertIn("再靠近一点。", updated)
        self.assertIn("这是普通的呼吸声。", updated)
        self.assertTrue((self.zh_dir / "backup" / "track.zh.srt").exists())

    def test_unchanged_acceptance_is_not_counted_as_a_repair(self) -> None:
        reviewed = self.closed_items()
        reviewed[1].update(
            decision="accept",
            replacement="再靠近一点。",
            decision_reason="仅确认现有句子已经符合建议。",
            evidence_level="ja_context_confirmed",
            evidence_summary="日文与相邻字幕上下文支持当前表达。",
        )
        closure, passed = validate_items(self.expected_items(), reviewed)
        self.assertTrue(passed)
        allowances = {item["issue_id"]: item for item in closure["items"]}
        results, failures = apply_items(
            reviewed,
            zh_dir=self.zh_dir,
            closure_allowances=allowances,
            apply=True,
            allow_stale=False,
            backup_dir=None,
        )
        self.assertEqual(failures, 0)
        self.assertIn("already_correct", [result.status for result in results])
        self.assertNotIn("applied", [result.status for result in results if result.index == 2])

    def test_apply_rejects_replacement_changed_after_closure(self) -> None:
        reviewed = self.closed_items()
        closure, passed = validate_items(self.expected_items(), reviewed)
        self.assertTrue(passed)
        reviewed[0]["replacement"] = "老师，今天很开心。"
        allowances = {item["issue_id"]: item for item in closure["items"]}
        results, failures = apply_items(
            reviewed,
            zh_dir=self.zh_dir,
            closure_allowances=allowances,
            apply=False,
            allow_stale=False,
            backup_dir=None,
        )
        self.assertEqual(failures, 1)
        self.assertIn("does not match", results[0].message)

    def test_high_risk_rewrite_without_source_anchor_is_deferred(self) -> None:
        items = self.closed_items()
        items[2].update(
            decision="accept",
            replacement="[持续呼吸声]",
            decision_reason="想让字幕更自然。",
            evidence_level="ja_context_confirmed",
            evidence_summary="语境大致像呼吸。",
            review_required=False,
            review_method="",
        )
        report, passed = validate_items(self.expected_items(), items)
        self.assertTrue(passed)
        third = next(item for item in report["items"] if item["index"] == 3)
        self.assertEqual(third["effective_decision"], "defer")
        self.assertFalse(third["apply_allowed"])


if __name__ == "__main__":
    unittest.main()
