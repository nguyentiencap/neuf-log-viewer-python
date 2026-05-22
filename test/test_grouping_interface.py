"""
Test Suite for the generic GroupingAlgorithm interface.

Tests both concrete implementations (LZ77GroupingAlgorithm and
RePairGroupingAlgorithm) through the shared interface, covering:
  - group()            — returns GroupingResult with deduplicated items and dict
  - export_dictionary()— JSON serialisation
  - Performance        — 10 000 and 100 000 items
"""

import json
import sys
import time
import tempfile
import random
import unittest
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.grouping_interface import DictionaryEntry, GroupingAlgorithm, GroupingResult
from src.lz77_grouping   import LZ77GroupingAlgorithm
from src.repair_grouping import RePairGroupingAlgorithm


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def items(keys: List[str]):
    return [{"k": k} for k in keys]


def key_fn(item: dict) -> str:
    return item["k"]


IMPLEMENTATIONS = [
    ("LZ77",    LZ77GroupingAlgorithm),
    ("RE-PAIR", RePairGroupingAlgorithm),
]


# ---------------------------------------------------------------------------
# DictionaryEntry unit tests
# ---------------------------------------------------------------------------

class TestDictionaryEntry(unittest.TestCase):

    def test_to_dict_fields(self):
        e = DictionaryEntry(
            entry_id     = "key_1-3",
            key_sequence = ("A", "B", "C"),
            repeat_count = 5,
            occurrences  = (1, 4),
        )
        d = e.to_dict()
        self.assertEqual(d["entry_id"],     "key_1-3")
        self.assertEqual(d["key_sequence"], ["A", "B", "C"])
        self.assertEqual(d["repeat_count"], 5)
        self.assertEqual(d["occurrences"],  [1, 4])

    def test_immutable(self):
        e = DictionaryEntry("key_1-1", ("X",), 2)
        with self.assertRaises(Exception):
            e.entry_id = "key_2-2"   # frozen dataclass

    def test_key_sequence_serialises_as_list(self):
        e = DictionaryEntry("key_1-2", ("P", "Q"), 3)
        self.assertIsInstance(e.to_dict()["key_sequence"], list)

    def test_occurrences_serialises_as_list(self):
        e = DictionaryEntry("key_1-2", ("P", "Q"), 3, (1, 5))
        self.assertIsInstance(e.to_dict()["occurrences"], list)
        self.assertEqual(e.to_dict()["occurrences"], [1, 5])

    def test_occurrences_defaults_to_empty(self):
        e = DictionaryEntry("key_1-1", ("X",), 2)
        self.assertEqual(e.occurrences, ())


# ---------------------------------------------------------------------------
# Interface contract tests (run against every implementation)
# ---------------------------------------------------------------------------

class _InterfaceContractMixin:
    """
    Mixin that tests the GroupingAlgorithm contract.
    Subclasses must set `self.alg` to a concrete instance.
    """

    # --- group() returns a GroupingResult ---

    def test_group_is_grouping_algorithm(self):
        self.assertIsInstance(self.alg, GroupingAlgorithm)

    def test_group_returns_grouping_result(self):
        result = self.alg.group([], key_fn)
        self.assertIsInstance(result, GroupingResult)

    def test_group_empty_returns_empty(self):
        result = self.alg.group([], key_fn)
        self.assertEqual(result.deduplicated, [])
        self.assertEqual(result.dictionary, [])

    def test_group_all_unique_unchanged(self):
        its    = items(["X", "Y", "Z"])
        result = self.alg.group(its, key_fn)
        self.assertEqual(len(result.deduplicated), 3)

    def test_group_removes_duplicates(self):
        its    = items(["A", "B", "A", "B"])
        result = self.alg.group(its, key_fn)
        keys   = [r["k"] for r in result.deduplicated]
        self.assertEqual(keys.count("A"), 1)
        self.assertEqual(keys.count("B"), 1)

    def test_group_single_item(self):
        its    = items(["Z"])
        result = self.alg.group(its, key_fn)
        self.assertEqual(len(result.deduplicated), 1)

    # --- dictionary field ---

    def test_dict_empty_returns_empty(self):
        result = self.alg.group([], key_fn)
        self.assertEqual(result.dictionary, [])

    def test_dict_all_unique_returns_empty(self):
        its    = items(["X", "Y", "Z"])
        result = self.alg.group(its, key_fn)
        self.assertEqual(result.dictionary, [])

    def test_dict_returns_dict_entries(self):
        its    = items(["A", "B", "A", "B"])
        result = self.alg.group(its, key_fn)
        self.assertGreater(len(result.dictionary), 0)
        for e in result.dictionary:
            self.assertIsInstance(e, DictionaryEntry)

    def test_dict_sorted_desc_by_repeat_count(self):
        # [A,B,C, A,B,C, A,B,C] — ABC repeats 2×; A repeats 2×; etc.
        its    = items(["A", "B", "C"] * 3)
        result = self.alg.group(its, key_fn)
        counts = [e.repeat_count for e in result.dictionary]
        self.assertEqual(counts, sorted(counts, reverse=True))

    def test_dict_entry_id_format(self):
        its    = items(["A", "B", "A", "B"])
        result = self.alg.group(its, key_fn)
        for e in result.dictionary:
            self.assertTrue(
                e.entry_id.startswith("key_"),
                f"entry_id '{e.entry_id}' does not start with 'key_'",
            )
            parts = e.entry_id[4:].split("-")
            self.assertEqual(len(parts), 2)
            self.assertTrue(parts[0].isdigit())
            self.assertTrue(parts[1].isdigit())
            self.assertLessEqual(int(parts[0]), int(parts[1]))

    def test_dict_key_sequence_nonempty(self):
        its    = items(["A", "B", "A", "B"])
        result = self.alg.group(its, key_fn)
        for e in result.dictionary:
            self.assertGreater(len(e.key_sequence), 0)

    def test_dict_key_sequence_contains_original_keys(self):
        orig_keys = {"A", "B", "C"}
        its       = items(["A", "B", "C", "A", "B", "C"])
        result    = self.alg.group(its, key_fn)
        for e in result.dictionary:
            for sym in e.key_sequence:
                self.assertIn(sym, orig_keys)

    def test_dict_repeat_count_at_least_2(self):
        its    = items(["A", "B", "A", "B"])
        result = self.alg.group(its, key_fn)
        for e in result.dictionary:
            self.assertGreaterEqual(e.repeat_count, 2)

    def test_dict_occurrences_nonempty(self):
        its    = items(["A", "B", "A", "B"])
        result = self.alg.group(its, key_fn)
        for e in result.dictionary:
            self.assertGreater(len(e.occurrences), 0)

    def test_dict_occurrences_length_matches_repeat_count(self):
        its    = items(["A", "B", "A", "B"])
        result = self.alg.group(its, key_fn)
        for e in result.dictionary:
            self.assertEqual(len(e.occurrences), e.repeat_count)

    def test_dict_occurrences_sorted_ascending(self):
        its    = items(["A", "B", "C", "A", "B", "C"])
        result = self.alg.group(its, key_fn)
        for e in result.dictionary:
            self.assertEqual(list(e.occurrences), sorted(e.occurrences))

    def test_dict_occurrences_are_1indexed(self):
        its    = items(["A", "B", "A", "B"])
        result = self.alg.group(its, key_fn)
        for e in result.dictionary:
            for pos in e.occurrences:
                self.assertGreaterEqual(pos, 1)

    # --- export_dictionary() ---

    def test_export_creates_valid_json(self):
        its = items(["A", "B", "A", "B"])
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            self.alg.export_dictionary(its, key_fn, path)
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            self.assertIsInstance(data, list)
        finally:
            import os
            os.unlink(path)

    def test_export_json_schema(self):
        its = items(["A", "B", "A", "B"])
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            self.alg.export_dictionary(its, key_fn, path)
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            for obj in data:
                self.assertIn("entry_id",     obj)
                self.assertIn("key_sequence", obj)
                self.assertIn("repeat_count", obj)
                self.assertIn("occurrences",  obj)
                self.assertIsInstance(obj["entry_id"],     str)
                self.assertIsInstance(obj["key_sequence"], list)
                self.assertIsInstance(obj["repeat_count"], int)
                self.assertIsInstance(obj["occurrences"],  list)
        finally:
            import os
            os.unlink(path)

    def test_export_empty_items_creates_empty_json_array(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            self.alg.export_dictionary([], key_fn, path)
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            self.assertEqual(data, [])
        finally:
            import os
            os.unlink(path)

    def test_export_sorted_desc_in_json(self):
        its = items(["A", "B", "C"] * 4 + ["X", "Y"] * 2)
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            self.alg.export_dictionary(its, key_fn, path)
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            counts = [obj["repeat_count"] for obj in data]
            self.assertEqual(counts, sorted(counts, reverse=True))
        finally:
            import os
            os.unlink(path)


# ---------------------------------------------------------------------------
# Concrete test classes — one per implementation
# ---------------------------------------------------------------------------

class TestLZ77Interface(_InterfaceContractMixin, unittest.TestCase):
    def setUp(self):
        self.alg = LZ77GroupingAlgorithm()


class TestRePairInterface(_InterfaceContractMixin, unittest.TestCase):
    def setUp(self):
        self.alg = RePairGroupingAlgorithm()


# ---------------------------------------------------------------------------
# Performance tests — 10 000 and 100 000 items
# ---------------------------------------------------------------------------

PERF_SIZES     = [10_000, 100_000]
PERF_LIMIT_MS  = {10_000: 2_000, 100_000: 60_000}


def _make_block_repeat(n: int, block_size: int = 20, num_blocks: int = 10) -> List[str]:
    rng  = random.Random(0)
    pool = [[f"L{b:02d}_{l:02d}" for l in range(block_size)] for b in range(num_blocks)]
    flat: List[str] = []
    while len(flat) < n:
        flat.extend(rng.choice(pool))
    return flat[:n]


def _make_all_unique(n: int) -> List[str]:
    return [f"key_{i:07d}" for i in range(n)]


def _measure_group(alg: GroupingAlgorithm, keys: List[str]) -> float:
    its = [{"k": k} for k in keys]
    t0  = time.perf_counter()
    alg.group(its, key_fn)
    return time.perf_counter() - t0


class TestLZ77Performance10k(unittest.TestCase):
    N   = 10_000
    ALG = LZ77GroupingAlgorithm

    def _limit(self) -> float:
        return PERF_LIMIT_MS[self.N] / 1_000

    def test_group_block_repeat(self):
        elapsed = _measure_group(self.ALG(), _make_block_repeat(self.N))
        self.assertLess(elapsed, self._limit())

    def test_group_all_unique(self):
        elapsed = _measure_group(self.ALG(), _make_all_unique(self.N))
        self.assertLess(elapsed, self._limit())


class TestLZ77Performance100k(TestLZ77Performance10k):
    N   = 100_000
    ALG = LZ77GroupingAlgorithm


class TestRePairPerformance10k(unittest.TestCase):
    N   = 10_000
    ALG = RePairGroupingAlgorithm

    def _limit(self) -> float:
        return PERF_LIMIT_MS[self.N] / 1_000

    def test_group_block_repeat(self):
        elapsed = _measure_group(self.ALG(), _make_block_repeat(self.N))
        self.assertLess(elapsed, self._limit())

    def test_group_all_unique(self):
        elapsed = _measure_group(self.ALG(), _make_all_unique(self.N))
        self.assertLess(elapsed, self._limit())


class TestRePairPerformance100k(TestRePairPerformance10k):
    N   = 100_000
    ALG = RePairGroupingAlgorithm


if __name__ == "__main__":
    unittest.main()
