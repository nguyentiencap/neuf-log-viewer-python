"""
Test Suite for lz77_grouping.py — generic LZ77 deduplication engine.

Tests: group_similar_lines, _find_longest_match, _build_window_keys, build_key_dict
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.lz77_grouping import (
    group_similar_lines,
    _find_longest_match,
    _build_window_keys,
    build_key_dict,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def items(keys):
    """Build plain dicts {k: key} for generic testing."""
    return [{"k": key, "idx": i} for i, key in enumerate(keys)]

def key_fn(item):
    return item["k"]

def drop_dup(item, dup_pos, match_start, match_len):
    return None

def replace_dup(item, dup_pos, match_start, match_len):
    r = dict(item)
    r["k"] = f"[dup@{match_start}+{match_len}]"
    return r


# ---------------------------------------------------------------------------
# _find_longest_match
# ---------------------------------------------------------------------------

class TestFindLongestMatch(unittest.TestCase):

    def test_no_candidates_returns_none(self):
        self.assertIsNone(_find_longest_match(["A", "B"], 1, {}))

    def test_exact_single_match_returns_length_1(self):
        emitted = {"A": [0]}
        result  = _find_longest_match(["A", "B", "A"], 2, emitted)
        self.assertEqual(result, (0, 1))

    def test_longer_match_preferred(self):
        # keys[2:4] == keys[0:2] == ["A","B"]
        emitted = {"A": [0]}
        result  = _find_longest_match(["A", "B", "A", "B"], 2, emitted)
        self.assertIsNotNone(result)
        self.assertEqual(result[1], 2)

    def test_overlapping_source_not_used(self):
        # pos=1, candidate j=0; j+length must stay < pos=1
        # so only length=1 is possible (keys[1]==keys[0]=="A"), but j+1 == pos → forbidden
        emitted = {"A": [0]}
        result  = _find_longest_match(["A", "A"], 1, emitted)
        # j=0, j+0 < 1 → ok, j+1 < 1 → False → length=1 is allowed
        self.assertIsNotNone(result)
        self.assertEqual(result[1], 1)

    def test_no_match_returns_none(self):
        emitted = {"X": [0]}
        self.assertIsNone(_find_longest_match(["X", "Y", "Z"], 2, emitted))


# ---------------------------------------------------------------------------
# _build_window_keys
# ---------------------------------------------------------------------------

class TestBuildWindowKeys(unittest.TestCase):

    def test_window1_identity(self):
        self.assertEqual(_build_window_keys(["A", "B", "C"], 1), ["A", "B", "C"])

    def test_window2_length(self):
        self.assertEqual(len(_build_window_keys(["A", "B", "C", "D"], 2)), 3)

    def test_window2_content(self):
        result = _build_window_keys(["A", "B", "C"], 2)
        self.assertIn("A", result[0])
        self.assertIn("B", result[0])
        self.assertIn("B", result[1])
        self.assertIn("C", result[1])

    def test_window_larger_than_n_returns_empty(self):
        self.assertEqual(_build_window_keys(["A", "B"], 3), [])

    def test_window_equal_n_returns_one_element(self):
        self.assertEqual(len(_build_window_keys(["A", "B", "C"], 3)), 1)


# ---------------------------------------------------------------------------
# build_key_dict
# ---------------------------------------------------------------------------

class TestBuildKeyDict(unittest.TestCase):

    def test_returns_only_duplicate_keys(self):
        kd = build_key_dict(["A", "B", "A", "C"], set(range(4)))
        self.assertIn("A", kd)
        self.assertNotIn("B", kd)
        self.assertNotIn("C", kd)

    def test_index_lists_are_correct(self):
        kd = build_key_dict(["X", "X", "X"], set(range(3)))
        self.assertEqual(sorted(kd["X"]), [0, 1, 2])

    def test_active_filter_excludes_inactive(self):
        kd = build_key_dict(["A", "A", "A"], {0, 2})
        self.assertNotIn(1, kd["A"])

    def test_all_unique_returns_empty(self):
        self.assertEqual(build_key_dict(["A", "B", "C"], set(range(3))), {})

    def test_empty_input_returns_empty(self):
        self.assertEqual(build_key_dict([], set()), {})

    def test_single_active_instance_not_duplicate(self):
        # key "A" at index 0 and 1, but only 0 active
        self.assertNotIn("A", build_key_dict(["A", "A"], {0}))


# ---------------------------------------------------------------------------
# group_similar_lines — basic behavior
# ---------------------------------------------------------------------------

class TestGroupSimilarLinesBasic(unittest.TestCase):

    def test_empty_input_returns_empty(self):
        self.assertEqual(group_similar_lines([], key_fn, drop_dup), [])

    def test_all_unique_unchanged(self):
        its    = items(["X", "Y", "Z"])
        result = group_similar_lines(its, key_fn, drop_dup)
        self.assertEqual(len(result), 3)

    def test_on_duplicate_none_removes_block(self):
        its    = items(["A", "B", "A"])
        result = group_similar_lines(its, key_fn, drop_dup)
        self.assertEqual([r["k"] for r in result], ["A", "B"])

    def test_on_duplicate_replacement_inserted(self):
        its    = items(["A", "B", "A"])
        result = group_similar_lines(its, key_fn, replace_dup)
        self.assertEqual(result[0]["k"], "A")
        self.assertEqual(result[1]["k"], "B")
        self.assertIn("dup", result[2]["k"])

    def test_on_duplicate_receives_correct_arguments(self):
        its      = items(["P", "Q", "P", "Q"])
        captured = []

        def capture(item, dup_pos, match_start, match_len):
            captured.append((dup_pos, match_start, match_len))
            return None

        group_similar_lines(its, key_fn, capture)
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0], (2, 0, 2))   # block [P,Q] at pos 2, source 0, len 2

    def test_three_identical_filter_drops_all_but_first(self):
        its    = items(["X", "X", "X"])
        result = group_similar_lines(its, key_fn, drop_dup)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["k"], "X")

    def test_three_identical_replace_gives_three_items(self):
        its    = items(["X", "X", "X"])
        result = group_similar_lines(its, key_fn, replace_dup)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["k"], "X")
        self.assertIn("dup", result[1]["k"])
        self.assertIn("dup", result[2]["k"])


# ---------------------------------------------------------------------------
# group_similar_lines — block detection
# ---------------------------------------------------------------------------

class TestGroupSimilarLinesBlockDetection(unittest.TestCase):

    def test_two_line_block_detected(self):
        """[A,B,C,A,B,D] — block [A,B] at index 3-4 matches block at 0-1."""
        its    = items(["A", "B", "C", "A", "B", "D"])
        result = group_similar_lines(its, key_fn, drop_dup)
        keys   = [r["k"] for r in result]
        self.assertIn("C", keys)
        self.assertIn("D", keys)
        self.assertEqual(keys.count("A"), 1)
        self.assertEqual(keys.count("B"), 1)

    def test_two_line_block_replace_length(self):
        its      = items(["A", "B", "C", "A", "B", "D"])
        captured = []

        def cap(item, dp, ms, ml):
            captured.append(ml)
            return None

        group_similar_lines(its, key_fn, cap)
        self.assertIn(2, captured)   # block length 2 detected

    def test_abc_block_collapse(self):
        """[A,B,C,A,B,C,A,B] — expected drops: block 3-5, block 6-7."""
        its    = items(["A", "B", "C", "A", "B", "C", "A", "B"])
        result = group_similar_lines(its, key_fn, drop_dup)
        keys   = [r["k"] for r in result]
        self.assertEqual(keys, ["A", "B", "C"])

    def test_abc_block_replace_produces_two_annotations(self):
        its      = items(["A", "B", "C", "A", "B", "C", "A", "B"])
        captured = []

        def cap(item, dp, ms, ml):
            captured.append((dp, ms, ml))
            r = dict(item)
            r["k"] = f"ann({ms},{ml})"
            return r

        result = group_similar_lines(its, key_fn, cap)
        # 3 originals + 2 annotations = 5
        self.assertEqual(len(result), 5)
        self.assertEqual(captured[0][2], 3)   # first annotation: block length 3
        self.assertEqual(captured[1][2], 2)   # second annotation: block length 2


# ---------------------------------------------------------------------------
# group_similar_lines — min_match
# ---------------------------------------------------------------------------

class TestGroupSimilarLinesMinMatch(unittest.TestCase):

    def test_min_match_2_ignores_single_line_duplicates(self):
        """Single-line dup [A] should NOT trigger when min_match=2."""
        its      = items(["A", "B", "A"])
        captured = []

        def cap(item, dp, ms, ml):
            captured.append(ml)
            return None

        result = group_similar_lines(its, key_fn, cap, min_match=2)
        # Block length is 1 < min_match=2 → not triggered
        self.assertEqual(len(captured), 0)
        self.assertEqual(len(result), 3)

    def test_min_match_2_triggers_on_two_line_block(self):
        """Two-line block [A,B] repeat should trigger when min_match=2."""
        its    = items(["A", "B", "A", "B"])
        result = group_similar_lines(its, key_fn, drop_dup, min_match=2)
        self.assertEqual(len(result), 2)
