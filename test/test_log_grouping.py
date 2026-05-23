"""
Test Suite for log_grouping.py — NEUF log deduplication wrapper.

Tests: group_neuf_logs (delegates to LZ77 engine in lz77_grouping.py)
Key = device_id + component_name + message  (timestamp / log_level ignored).
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.log_grouping import group_neuf_logs


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def make_line(
    device_id="DEV001",
    component_name="com.example.Foo",
    message="Hello World",
    filename="NEUF-test.log",
    timestamp="2026.05.11 10:00:00.000",
    log_level="DEBUG",
    thread_name="Thread",
):
    return {
        "filename": filename,
        "timestamp": timestamp,
        "log_level": log_level,
        "thread_name": thread_name,
        "device_id": device_id,
        "component_name": component_name,
        "message": message,
    }


# ---------------------------------------------------------------------------
# Key correctness: device_id + component_name + message
# ---------------------------------------------------------------------------

class TestNeufKeyBehavior(unittest.TestCase):
    """Verify that the key is built from the right fields."""

    def test_different_device_ids_not_grouped(self):
        lines = [make_line(device_id="D1", message="Same"),
                 make_line(device_id="D2", message="Same")]
        self.assertEqual(len(group_neuf_logs(lines, filter_duplicate=True)), 2)

    def test_different_component_names_not_grouped(self):
        lines = [make_line(component_name="com.alpha", message="Same"),
                 make_line(component_name="com.beta",  message="Same")]
        self.assertEqual(len(group_neuf_logs(lines, filter_duplicate=True)), 2)

    def test_different_timestamps_are_still_grouped(self):
        """timestamp is not part of the key — same device+component+message groups."""
        lines = [
            make_line(message="M", timestamp="10:00"),
            make_line(message="M", timestamp="10:01"),
        ]
        result = group_neuf_logs(lines, filter_duplicate=True)
        self.assertEqual(len(result), 1)

    def test_different_log_levels_still_grouped(self):
        lines = [
            make_line(message="M", log_level="INFO"),
            make_line(message="M", log_level="DEBUG"),
        ]
        result = group_neuf_logs(lines, filter_duplicate=True)
        self.assertEqual(len(result), 1)

    def test_none_device_id_handled(self):
        lines = [make_line(device_id=None, message="M"),
                 make_line(device_id=None, message="M")]
        result = group_neuf_logs(lines, filter_duplicate=True)
        self.assertEqual(len(result), 1)

    def test_none_component_name_handled(self):
        lines = [make_line(component_name=None, message="M"),
                 make_line(component_name=None, message="M")]
        result = group_neuf_logs(lines, filter_duplicate=True)
        self.assertEqual(len(result), 1)


# ---------------------------------------------------------------------------
# filter_duplicate=True
# ---------------------------------------------------------------------------

class TestGroupNeufLogsFilterTrue(unittest.TestCase):

    def test_single_line_duplicate_removed(self):
        lines = [make_line(message="A"), make_line(message="B"),
                 make_line(message="A"), make_line(message="B")]
        result = group_neuf_logs(lines, filter_duplicate=True)
        msgs   = [r["message"] for r in result]
        self.assertEqual(msgs.count("A"), 1)
        self.assertEqual(msgs.count("B"), 1)

    def test_two_line_block_duplicate_removed(self):
        lines = [make_line(message=m) for m in ["A", "B", "C", "A", "B", "D"]]
        result = group_neuf_logs(lines, filter_duplicate=True)
        msgs   = [r["message"] for r in result]
        self.assertEqual(len(result), 4)
        self.assertIn("C", msgs)
        self.assertIn("D", msgs)

    def test_abc_block_collapse(self):
        lines  = [make_line(message=m) for m in ["A", "B", "C", "A", "B", "C", "A", "B"]]
        result = group_neuf_logs(lines, filter_duplicate=True)
        self.assertEqual([r["message"] for r in result], ["A", "B", "C"])

    def test_all_unique_unchanged(self):
        lines  = [make_line(message=f"Unique {i}") for i in range(5)]
        result = group_neuf_logs(lines, filter_duplicate=True)
        self.assertEqual(len(result), 5)

    def test_three_identical_collapse_to_one(self):
        lines  = [make_line(message="X") for _ in range(3)]
        result = group_neuf_logs(lines, filter_duplicate=True)
        self.assertEqual(len(result), 1)

    def test_empty_input_returns_empty(self):
        self.assertEqual(group_neuf_logs([], filter_duplicate=True), [])

    def test_single_line_unchanged(self):
        lines  = [make_line(message="Only")]
        result = group_neuf_logs(lines, filter_duplicate=True)
        self.assertEqual(result[0]["message"], "Only")


# ---------------------------------------------------------------------------
# filter_duplicate=False  (annotation mode)
# ---------------------------------------------------------------------------

class TestGroupNeufLogsFilterFalse(unittest.TestCase):

    def test_single_line_dup_annotation_format(self):
        lines = [make_line(message="A"), make_line(message="A")]
        result = group_neuf_logs(lines, filter_duplicate=False)
        self.assertEqual(result[0]["message"], "A")
        self.assertIn("Same as line", result[1]["message"])
        self.assertIn("1", result[1]["message"])

    def test_two_line_block_annotation_contains_range(self):
        lines  = [make_line(message=m) for m in ["A", "B", "C", "A", "B", "D"]]
        result = group_neuf_logs(lines, filter_duplicate=False)
        msg    = result[3]["message"]
        self.assertIn("Same as line", msg)
        self.assertIn("1", msg)
        self.assertIn("2", msg)

    def test_two_line_block_collapses_to_one_annotation(self):
        lines = [make_line(message=m) for m in ["A", "B", "C", "A", "B", "D"]]
        result = group_neuf_logs(lines, filter_duplicate=False)
        # [A, B, C, annotation, D] = 5 lines
        self.assertEqual(len(result), 5)

    def test_abc_block_collapse_to_two_annotations(self):
        """[A,B,C,A,B,C,A,B] → [A, B, C, ann(1-3), ann(1-2)]"""
        lines  = [make_line(message=m) for m in ["A", "B", "C", "A", "B", "C", "A", "B"]]
        result = group_neuf_logs(lines, filter_duplicate=False)
        self.assertEqual(len(result), 5)
        self.assertEqual(result[0]["message"], "A")
        self.assertEqual(result[1]["message"], "B")
        self.assertEqual(result[2]["message"], "C")
        msg3 = result[3]["message"]
        self.assertIn("Same as line", msg3)
        self.assertIn("1", msg3)
        self.assertIn("3", msg3)
        msg4 = result[4]["message"]
        self.assertIn("Same as line", msg4)
        self.assertIn("1", msg4)
        self.assertIn("2", msg4)

    def test_annotation_preserves_metadata_of_duplicate_line(self):
        """Non-message fields of the annotation line come from the dup line itself."""
        lines = [
            make_line(message="MSG", filename="NEUF-a.log", timestamp="10:00"),
            make_line(message="MSG", filename="NEUF-a.log", timestamp="10:01"),
        ]
        result = group_neuf_logs(lines, filter_duplicate=False)
        ann = result[1]
        self.assertEqual(ann["filename"],  "NEUF-a.log")
        self.assertEqual(ann["timestamp"], "10:01")
        self.assertIn("Same as line", ann["message"])

    def test_first_occurrence_message_unchanged(self):
        lines = [make_line(message="X"), make_line(message="X")]
        result = group_neuf_logs(lines, filter_duplicate=False)
        self.assertEqual(result[0]["message"], "X")

    def test_three_identical_produces_two_annotations(self):
        lines  = [make_line(message="X") for _ in range(3)]
        result = group_neuf_logs(lines, filter_duplicate=False)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["message"], "X")
        self.assertIn("Same as line", result[1]["message"])
        self.assertIn("Same as line", result[2]["message"])


# ---------------------------------------------------------------------------
# Field preservation
# ---------------------------------------------------------------------------

class TestGroupNeufLogsFieldPreservation(unittest.TestCase):

    def test_surviving_line_keeps_all_fields(self):
        lines = [
            make_line(device_id="D1", component_name="C1", message="M",
                      filename="NEUF-a.log", log_level="INFO"),
            make_line(device_id="D1", component_name="C1", message="M",
                      filename="NEUF-a.log", log_level="INFO"),
        ]
        result = group_neuf_logs(lines, filter_duplicate=True)
        r = result[0]
        self.assertEqual(r["filename"],       "NEUF-a.log")
        self.assertEqual(r["log_level"],      "INFO")
        self.assertEqual(r["device_id"],      "D1")
        self.assertEqual(r["component_name"], "C1")


# ---------------------------------------------------------------------------
# min_match parameter
# ---------------------------------------------------------------------------

class TestGroupNeufLogsMinMatch(unittest.TestCase):

    def test_min_match_2_ignores_single_line_duplicates(self):
        """Single-line dup should NOT trigger when min_match=2."""
        lines = [make_line(message="A"), make_line(message="B"),
                 make_line(message="A")]
        result = group_neuf_logs(lines, filter_duplicate=True, min_match=2)
        self.assertEqual(len(result), 3)

    def test_min_match_2_triggers_on_two_line_block(self):
        lines  = [make_line(message=m) for m in ["A", "B", "A", "B"]]
        result = group_neuf_logs(lines, filter_duplicate=True, min_match=2)
        self.assertEqual(len(result), 2)


if __name__ == "__main__":
    unittest.main()
