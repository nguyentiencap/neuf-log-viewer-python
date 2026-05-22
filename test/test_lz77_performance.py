"""
Performance Test Suite for lz77_grouping.py

Measures execution time of group_similar_lines() under:
  - all_unique:      no duplicates   (worst-case: emitted_starts always grows, zero matches)
  - high_repeat:     small alphabet  (many candidates per key → deep match expansion)
  - block_repeat:    chunked blocks  (realistic log-file pattern)
  - random_mixed:    random keys     (average case)

Sizes tested: 10_000 and 100_000 items.

Run with:
    python -m pytest test/test_lz77_performance.py -v -s
  or standalone:
    python test/test_lz77_performance.py
"""

import sys
import time
import random
import string
import unittest
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.lz77_grouping import group_similar_lines

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def key_fn(item: str) -> str:
    return item


def drop_dup(item, dup_pos, match_start, match_len):
    return None


def _measure(label: str, items: List[str], min_match: int = 1) -> float:
    """Run group_similar_lines, print timing, return elapsed seconds."""
    t0     = time.perf_counter()
    result = group_similar_lines(items, key_fn, drop_dup, min_match=min_match)
    elapsed = time.perf_counter() - t0
    kept    = len(result)
    ratio   = kept / len(items) * 100
    print(
        f"  [{label}]  n={len(items):>7,}  "
        f"kept={kept:>7,} ({ratio:5.1f}%)  "
        f"time={elapsed*1000:8.1f} ms"
    )
    return elapsed


# ---------------------------------------------------------------------------
# Scenario builders
# ---------------------------------------------------------------------------

def make_all_unique(n: int) -> List[str]:
    """Every item is unique → no matches ever fired."""
    return [f"key_{i:07d}" for i in range(n)]


def make_high_repeat(n: int, alphabet_size: int = 4) -> List[str]:
    """
    Very small alphabet (default 4 symbols).
    emitted_starts for each key will accumulate hundreds of positions
    → stresses the inner candidate-expansion loop.
    """
    alphabet = [chr(ord("A") + i) for i in range(alphabet_size)]
    rng      = random.Random(42)
    return [rng.choice(alphabet) for _ in range(n)]


def make_block_repeat(n: int, block_size: int = 50, num_unique_blocks: int = 20) -> List[str]:
    """
    Simulate a log file: a fixed pool of unique blocks, repeated in sequence.
    E.g. block_size=50, num_unique_blocks=20 → 1000-item cycle repeated n//1000 times.
    """
    rng  = random.Random(0)
    pool = [
        [f"L{b:03d}_{l:03d}" for l in range(block_size)]
        for b in range(num_unique_blocks)
    ]
    flat: List[str] = []
    while len(flat) < n:
        blk = rng.choice(pool)
        flat.extend(blk)
    return flat[:n]


def make_random_mixed(n: int, vocab_size: int = 500) -> List[str]:
    """
    Medium vocabulary — realistic mix of hits and misses.
    """
    rng   = random.Random(7)
    vocab = [f"msg_{i:04d}" for i in range(vocab_size)]
    return [rng.choice(vocab) for _ in range(n)]


def make_worst_case_candidates(n: int) -> List[str]:
    """
    Worst case for _find_longest_match: ONE single key repeated n times.
    emitted_starts["A"] grows to O(n), and for each new position we iterate
    over ALL previous positions trying to extend the match.
    After the first match the rest is consumed, so it collapses quickly,
    but this stresses the first match search.
    """
    return ["A"] * n


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

SIZES = [10_000, 100_000]
THRESHOLD_MS = {
    10_000:  2_000,   # must finish in < 2 s
    100_000: 30_000,  # must finish in < 30 s
}


class TestLZ77Performance10k(unittest.TestCase):
    N = 10_000

    def _assert_fast(self, elapsed: float):
        limit = THRESHOLD_MS[self.N] / 1_000
        self.assertLess(
            elapsed, limit,
            f"Exceeded time limit: {elapsed*1000:.0f} ms > {THRESHOLD_MS[self.N]} ms",
        )

    def test_all_unique(self):
        print(f"\n--- n={self.N:,} ---")
        elapsed = _measure("all_unique      ", make_all_unique(self.N))
        self._assert_fast(elapsed)

    def test_high_repeat_alphabet4(self):
        elapsed = _measure("high_repeat(a=4)", make_high_repeat(self.N, alphabet_size=4))
        self._assert_fast(elapsed)

    def test_high_repeat_alphabet26(self):
        elapsed = _measure("high_repeat(a=26)", make_high_repeat(self.N, alphabet_size=26))
        self._assert_fast(elapsed)

    def test_block_repeat(self):
        elapsed = _measure("block_repeat    ", make_block_repeat(self.N))
        self._assert_fast(elapsed)

    def test_random_mixed(self):
        elapsed = _measure("random_mixed    ", make_random_mixed(self.N))
        self._assert_fast(elapsed)

    def test_single_key_all_same(self):
        elapsed = _measure("all_same(A*n)   ", make_worst_case_candidates(self.N))
        self._assert_fast(elapsed)

    def test_min_match_3_block_repeat(self):
        elapsed = _measure("block(min_m=3)  ", make_block_repeat(self.N), min_match=3)
        self._assert_fast(elapsed)


class TestLZ77Performance100k(unittest.TestCase):
    N = 100_000

    def _assert_fast(self, elapsed: float):
        limit = THRESHOLD_MS[self.N] / 1_000
        self.assertLess(
            elapsed, limit,
            f"Exceeded time limit: {elapsed*1000:.0f} ms > {THRESHOLD_MS[self.N]} ms",
        )

    def test_all_unique(self):
        print(f"\n--- n={self.N:,} ---")
        elapsed = _measure("all_unique      ", make_all_unique(self.N))
        self._assert_fast(elapsed)

    def test_high_repeat_alphabet4(self):
        elapsed = _measure("high_repeat(a=4)", make_high_repeat(self.N, alphabet_size=4))
        self._assert_fast(elapsed)

    def test_high_repeat_alphabet26(self):
        elapsed = _measure("high_repeat(a=26)", make_high_repeat(self.N, alphabet_size=26))
        self._assert_fast(elapsed)

    def test_block_repeat(self):
        elapsed = _measure("block_repeat    ", make_block_repeat(self.N))
        self._assert_fast(elapsed)

    def test_random_mixed(self):
        elapsed = _measure("random_mixed    ", make_random_mixed(self.N))
        self._assert_fast(elapsed)

    def test_single_key_all_same(self):
        elapsed = _measure("all_same(A*n)   ", make_worst_case_candidates(self.N))
        self._assert_fast(elapsed)

    def test_min_match_3_block_repeat(self):
        elapsed = _measure("block(min_m=3)  ", make_block_repeat(self.N), min_match=3)
        self._assert_fast(elapsed)


# ---------------------------------------------------------------------------
# Standalone runner — prints a compact summary table
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    scenarios = [
        ("all_unique",        make_all_unique),
        ("high_repeat(a=4)",  lambda n: make_high_repeat(n, alphabet_size=4)),
        ("high_repeat(a=26)", lambda n: make_high_repeat(n, alphabet_size=26)),
        ("block_repeat",      make_block_repeat),
        ("random_mixed",      make_random_mixed),
        ("all_same",          make_worst_case_candidates),
    ]

    print("\n" + "=" * 72)
    print(f"  {'Scenario':<22}  {'n':>8}  {'kept':>8}  {'ratio':>7}  {'time':>10}")
    print("=" * 72)

    for name, builder in scenarios:
        for n in SIZES:
            data    = builder(n)
            t0      = time.perf_counter()
            result  = group_similar_lines(data, key_fn, drop_dup)
            elapsed = time.perf_counter() - t0
            kept    = len(result)
            ratio   = kept / n * 100
            print(
                f"  {name:<22}  {n:>8,}  {kept:>8,}  {ratio:>6.1f}%"
                f"  {elapsed*1000:>8.1f} ms"
            )
    print("=" * 72)
