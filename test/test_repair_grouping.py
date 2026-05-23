"""
Test Suite for repair_grouping.py — RE-PAIR grouping algorithm.

Covers:
  - group()            — returns GroupingResult with deduplicated items and dict
  - export_dictionary()— JSON output via inherited method
  - Performance        — 10 000 and 100 000 items
"""

import sys
import time
import random
import unittest
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.grouping_interface import DictionaryEntry
from src.repair_grouping    import RePairGroupingAlgorithm, _expand_symbol


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def items(keys: List[str]):
    return [{"k": k} for k in keys]


def key_fn(item: dict) -> str:
    return item["k"]


# ---------------------------------------------------------------------------
# _expand_symbol unit tests
# ---------------------------------------------------------------------------

class TestExpandSymbol(unittest.TestCase):

    def test_terminal_string(self):
        self.assertEqual(_expand_symbol("A", []), ["A"])

    def test_rule_id_two_terminals(self):
        rules = [("A", "B", 3)]
        self.assertEqual(_expand_symbol(0, rules), ["A", "B"])

    def test_rule_id_nested(self):
        # rule 0: A,B  rule 1: 0,C  => expand(1) = [A,B,C]
        rules = [("A", "B", 3), (0, "C", 2)]
        self.assertEqual(_expand_symbol(1, rules), ["A", "B", "C"])

    def test_rule_id_deeply_nested(self):
        # rule 0: A,B  rule 1: 0,C  rule 2: 1,D => expand(2) = [A,B,C,D]
        rules = [("A", "B", 3), (0, "C", 2), (1, "D", 1)]
        self.assertEqual(_expand_symbol(2, rules), ["A", "B", "C", "D"])


# ---------------------------------------------------------------------------
# group() — basic behaviour
# ---------------------------------------------------------------------------

class TestRePairGroup(unittest.TestCase):

    alg = RePairGroupingAlgorithm()

    def test_empty_input(self):
        result = self.alg.group([], key_fn)
        self.assertEqual(result.deduplicated, [])

    def test_all_unique_unchanged(self):
        its    = items(["X", "Y", "Z"])
        result = self.alg.group(its, key_fn)
        self.assertEqual(len(result.deduplicated), 3)

    def test_single_item(self):
        its    = items(["A"])
        result = self.alg.group(its, key_fn)
        self.assertEqual(len(result.deduplicated), 1)

    def test_simple_duplicate_removed(self):
        its    = items(["A", "B", "A", "B"])
        result = self.alg.group(its, key_fn)
        keys   = [r["k"] for r in result.deduplicated]
        self.assertEqual(keys.count("A"), 1)
        self.assertEqual(keys.count("B"), 1)

    def test_three_repeating_block(self):
        its    = items(["A", "B", "C", "A", "B", "C", "A", "B", "C"])
        result = self.alg.group(its, key_fn)
        keys   = [r["k"] for r in result.deduplicated]
        # All three letters kept but duplicates removed
        self.assertEqual(keys.count("A"), 1)
        self.assertEqual(keys.count("B"), 1)
        self.assertEqual(keys.count("C"), 1)

    def test_first_occurrence_kept(self):
        its    = items(["P", "Q", "P", "Q"])
        result = self.alg.group(its, key_fn)
        self.assertEqual(result.deduplicated[0]["k"], "P")
        self.assertEqual(result.deduplicated[1]["k"], "Q")

    def test_unique_mixed_with_repeats(self):
        its    = items(["A", "B", "X", "A", "B", "Y"])
        result = self.alg.group(its, key_fn)
        keys   = [r["k"] for r in result.deduplicated]
        self.assertIn("X", keys)
        self.assertIn("Y", keys)
        self.assertEqual(keys.count("A"), 1)
        self.assertEqual(keys.count("B"), 1)


# ---------------------------------------------------------------------------
# dictionary field — entries and expansion
# ---------------------------------------------------------------------------

class TestRePairBuildDictionary(unittest.TestCase):

    alg = RePairGroupingAlgorithm()

    def test_empty_input_returns_empty(self):
        result = self.alg.group([], key_fn)
        self.assertEqual(result.dictionary, [])

    def test_all_unique_returns_empty(self):
        its    = items(["X", "Y", "Z"])
        result = self.alg.group(its, key_fn)
        self.assertEqual(result.dictionary, [])

    def test_returns_dict_entry_objects(self):
        its    = items(["A", "B", "A", "B"])
        result = self.alg.group(its, key_fn)
        for e in result.dictionary:
            self.assertIsInstance(e, DictionaryEntry)

    def test_sorted_by_repeat_count_desc(self):
        its    = items(["A", "B", "C"] * 4)
        result = self.alg.group(its, key_fn)
        counts = [e.repeat_count for e in result.dictionary]
        self.assertEqual(counts, sorted(counts, reverse=True))

    def test_entry_id_format(self):
        its    = items(["A", "B", "A", "B"])
        result = self.alg.group(its, key_fn)
        for e in result.dictionary:
            self.assertTrue(e.entry_id.startswith("key_"))
            parts = e.entry_id[4:].split("-")
            self.assertEqual(len(parts), 2)
            s, end = int(parts[0]), int(parts[1])
            self.assertGreaterEqual(s, 1)
            self.assertLessEqual(s, end)

    def test_key_sequence_contains_only_original_tokens(self):
        its    = items(["A", "B", "C", "A", "B", "C"])
        result = self.alg.group(its, key_fn)
        for e in result.dictionary:
            for sym in e.key_sequence:
                self.assertIsInstance(sym, str)
                self.assertIn(sym, {"A", "B", "C"})

    def test_two_token_rule_expanded(self):
        # [A,B] appears 3 times → rule R0 = A,B
        its    = items(["A", "B"] * 3)
        result = self.alg.group(its, key_fn)
        seqs   = [list(e.key_sequence) for e in result.dictionary]
        self.assertIn(["A", "B"], seqs)

    def test_nested_rule_fully_expanded(self):
        # [A,B,C] appears multiple times → inner rule [A,B] found first,
        # then outer rule [R0,C]; outer must expand to [A,B,C]
        its    = items(["A", "B", "C"] * 4)
        result = self.alg.group(its, key_fn)
        seqs   = [list(e.key_sequence) for e in result.dictionary]
        self.assertIn(["A", "B", "C"], seqs)

    def test_repeat_count_at_least_2(self):
        its    = items(["A", "B"] * 3)
        result = self.alg.group(its, key_fn)
        for e in result.dictionary:
            self.assertGreaterEqual(e.repeat_count, 2)

    def test_occurrences_nonempty(self):
        its    = items(["A", "B"] * 3)
        result = self.alg.group(its, key_fn)
        for e in result.dictionary:
            self.assertGreater(len(e.occurrences), 0)

    def test_occurrences_sorted_ascending(self):
        its    = items(["A", "B", "C"] * 4)
        result = self.alg.group(its, key_fn)
        for e in result.dictionary:
            self.assertEqual(list(e.occurrences), sorted(e.occurrences))

    def test_occurrences_are_1indexed(self):
        its    = items(["A", "B", "A", "B"])
        result = self.alg.group(its, key_fn)
        for e in result.dictionary:
            for pos in e.occurrences:
                self.assertGreaterEqual(pos, 1)

    def test_occurrences_first_position_matches_entry_id(self):
        # [A,B] first at position 1 → entry_id key_1-2, occurrences[0] == 1
        its    = items(["A", "B", "C", "A", "B"])
        result = self.alg.group(its, key_fn)
        ab_entry = next((e for e in result.dictionary if list(e.key_sequence) == ["A", "B"]), None)
        self.assertIsNotNone(ab_entry)
        self.assertEqual(ab_entry.occurrences[0], 1)

    def test_entry_id_1indexed_first_occurrence(self):
        # [A,B] first appears at positions 0-1 → entry_id key_1-2
        its    = items(["A", "B", "C", "A", "B"])
        result = self.alg.group(its, key_fn)
        ab_entry = next((e for e in result.dictionary if list(e.key_sequence) == ["A", "B"]), None)
        self.assertIsNotNone(ab_entry)
        self.assertEqual(ab_entry.entry_id, "key_1-2")


# ---------------------------------------------------------------------------
# Performance — 10 000 items
# ---------------------------------------------------------------------------

THRESHOLD_MS = {10_000: 2_000, 100_000: 60_000}


def _make_block_repeat(n: int, block_size: int = 20, num_blocks: int = 10) -> List[str]:
    rng  = random.Random(0)
    pool = [[f"L{b:02d}_{l:02d}" for l in range(block_size)] for b in range(num_blocks)]
    flat: List[str] = []
    while len(flat) < n:
        flat.extend(rng.choice(pool))
    return flat[:n]


def _make_all_unique(n: int) -> List[str]:
    return [f"key_{i:07d}" for i in range(n)]


def _make_random_mixed(n: int, vocab: int = 500) -> List[str]:
    rng   = random.Random(7)
    vocab_list = [f"msg_{i:04d}" for i in range(vocab)]
    return [rng.choice(vocab_list) for _ in range(n)]


class TestRePairPerformance10k(unittest.TestCase):
    N = 10_000

    def _assert_fast(self, elapsed: float):
        limit = THRESHOLD_MS[self.N] / 1_000
        self.assertLess(
            elapsed, limit,
            f"Exceeded limit: {elapsed*1000:.0f} ms > {THRESHOLD_MS[self.N]} ms",
        )

    def _run_group(self, keys: List[str]) -> float:
        its = [{"k": k} for k in keys]
        alg = RePairGroupingAlgorithm()
        t0  = time.perf_counter()
        alg.group(its, key_fn)
        return time.perf_counter() - t0

    def test_group_block_repeat(self):
        self._assert_fast(self._run_group(_make_block_repeat(self.N)))

    def test_group_all_unique(self):
        self._assert_fast(self._run_group(_make_all_unique(self.N)))

    def test_group_random_mixed(self):
        self._assert_fast(self._run_group(_make_random_mixed(self.N)))


class TestRePairPerformance100k(TestRePairPerformance10k):
    N = 100_000


if __name__ == "__main__":
    unittest.main()
