"""
RE-PAIR Grouping Module

Implements the RE-PAIR (Recursive Pairing) compression-inspired grouping
algorithm as a concrete GroupingAlgorithm subclass.

Algorithm overview
------------------
RE-PAIR repeatedly finds the most-frequent adjacent pair of symbols, replaces
all non-overlapping occurrences with a fresh rule symbol, and records the rule.
The process terminates when no pair appears more than once.

Dictionary generation
---------------------
Each rule R_i -> (left, right) is expanded recursively to its full sequence of
original tokens (the "concat pairs" step described in the issue).  Rules are
exposed as DictionaryEntry objects where:

    entry_id     = "key_{startLine}-{endLine}"  (1-indexed, first occurrence
                   of the expanded pattern in the original input)
    key_sequence = fully-expanded list of original keys
    repeat_count = frequency of the pair when the rule was created

Entries are sorted by repeat_count DESC.

Grouping behaviour
------------------
group() runs RE-PAIR and removes all items that belong to a repeated pattern
after the first occurrence (similar to LZ77 filter_duplicate=True behaviour).

Public API
----------
RePairGroupingAlgorithm
    .group(items, key_fn, **kwargs)              -> List[Any]
    .build_dictionary(items, key_fn, **kwargs)   -> List[DictionaryEntry]
    .export_dictionary(items, key_fn, path, ...) -> None  (inherited)
"""

import heapq
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from .grouping_interface import DictionaryEntry, GroupingAlgorithm


# ---------------------------------------------------------------------------
# _expand_symbol — public for unit tests
# ---------------------------------------------------------------------------

def _expand_symbol(
    sym: Any,
    rules: List[Tuple[Any, Any, int]],
) -> List[str]:
    """
    Recursively expand *sym* to its original key tokens.

    Terminal symbols (str) expand to [sym].
    Rule symbols (int rule_id) expand recursively: expand(left) + expand(right).
    """
    if isinstance(sym, str):
        return [sym]
    left, right, _ = rules[sym]
    return _expand_symbol(left, rules) + _expand_symbol(right, rules)


# ---------------------------------------------------------------------------
# Efficient RE-PAIR engine
# ---------------------------------------------------------------------------
#
# Data structures
# ---------------
# Working sequence  — doubly-linked list (parallel arrays: val, prv, nxt, act)
# orig_start[i]     — leftmost original index covered by node i
# orig_end[i]       — rightmost original index covered by node i
# Pair index        — pair_occ: pair -> set of starting-node indices
# Best-pair heap    — max-heap (negated counts) for O(log n) extraction
#
# For each rule R_k created at working-sequence position i (merging i and j):
#   original range of that occurrence = [orig_start[i], orig_end[j]]
#   (captured BEFORE the merge updates orig_end[i])
#
# The first occurrence (smallest orig_start) is kept; all others are added
# to `drop_ranges`.  This avoids any post-hoc O(patterns × n) scan.

def _run_repair(
    keys: List[str],
) -> Tuple[
    List[Tuple[Any, Any, int]],  # rules
    List[Any],                    # final_seq
    List[int],                    # rule_first_pos  (0-indexed, per rule)
    List[Tuple[int, int]],        # drop_ranges     [(start, end_inclusive), ...]
]:
    """
    Run RE-PAIR on *keys*.

    Returns
    -------
    rules           : list of (left_sym, right_sym, freq_at_creation)
    final_seq       : compressed sequence
    rule_first_pos  : for each rule R_k, the 0-indexed original start position
                      of its leftmost (first) occurrence in *keys*
    drop_ranges     : list of (start, end_inclusive) in 0-indexed original
                      coordinates, one range per non-first occurrence of each rule
    """
    n = len(keys)
    if n == 0:
        return [], [], [], []
    if n == 1:
        return [], list(keys), [], []

    # --- doubly-linked list ---
    val: List[Any]  = list(keys)
    prv: List[int]  = [-1] + list(range(n - 1))
    nxt: List[int]  = list(range(1, n)) + [-1]
    act: List[bool] = [True] * n

    # Original range of each living node.
    orig_start: List[int] = list(range(n))
    orig_end:   List[int] = list(range(n))

    # --- pair occurrence sets ---
    pair_occ: Dict[Tuple, set] = defaultdict(set)
    for i in range(n - 1):
        pair_occ[(keys[i], keys[i + 1])].add(i)

    # --- max-heap: (-count, seq_id, pair) ---
    _seq: List[int] = [0]

    heap: List[Tuple[int, int, Any]] = []
    for pair, positions in pair_occ.items():
        heapq.heappush(heap, (-len(positions), _seq[0], pair))
        _seq[0] += 1

    rules:          List[Tuple[Any, Any, int]] = []
    rule_first_pos: List[int]                  = []
    drop_ranges:    List[Tuple[int, int]]      = []

    def _push(pair: Tuple) -> None:
        c = len(pair_occ.get(pair, ()))
        if c >= 2:
            heapq.heappush(heap, (-c, _seq[0], pair))
            _seq[0] += 1

    while heap:
        neg_count, _sid, best_pair = heapq.heappop(heap)
        actual = len(pair_occ.get(best_pair, ()))
        if actual < 2:
            continue
        if actual != -neg_count:
            _push(best_pair)
            continue

        rule_id    = len(rules)
        best_count = actual
        rules.append((best_pair[0], best_pair[1], best_count))

        positions = list(pair_occ.pop(best_pair))

        # Sort by orig_start to put the first (leftmost) occurrence first.
        positions.sort(key=lambda idx: orig_start[idx])
        first_orig = -1

        for i in positions:
            if not act[i]:
                continue

            j = nxt[i]
            if j == -1 or not act[j]:
                continue
            if val[i] != best_pair[0] or val[j] != best_pair[1]:
                continue

            # Capture range BEFORE merge
            r_start = orig_start[i]
            r_end   = orig_end[j]

            if first_orig == -1:
                first_orig = r_start   # first occurrence → keep
            else:
                drop_ranges.append((r_start, r_end))  # duplicate → drop

            right_nbr = nxt[j]
            left_nbr  = prv[i]

            # --- remove stale pairs from index ---
            if left_nbr != -1 and act[left_nbr]:
                old = (val[left_nbr], best_pair[0])
                pair_occ[old].discard(left_nbr)
                if not pair_occ[old]:
                    del pair_occ[old]

            if right_nbr != -1 and act[right_nbr]:
                old = (best_pair[1], val[right_nbr])
                pair_occ[old].discard(j)
                if not pair_occ[old]:
                    del pair_occ[old]

            # --- merge: keep i, deactivate j ---
            val[i]      = rule_id
            act[j]      = False
            orig_end[i] = r_end          # i now covers up to j's original end
            nxt[i]      = right_nbr
            if right_nbr != -1:
                prv[right_nbr] = i

            # --- register new pairs ---
            if left_nbr != -1 and act[left_nbr]:
                new_pair = (val[left_nbr], rule_id)
                pair_occ[new_pair].add(left_nbr)
                _push(new_pair)

            if right_nbr != -1 and act[right_nbr]:
                new_pair = (rule_id, val[right_nbr])
                pair_occ[new_pair].add(i)
                _push(new_pair)

        rule_first_pos.append(first_orig if first_orig != -1 else 0)

    # --- reconstruct final sequence ---
    final: List[Any] = []
    i = 0
    while i < n and not act[i]:
        i += 1
    while i != -1 and i < n:
        final.append(val[i])
        i = nxt[i]

    return rules, final, rule_first_pos, drop_ranges


# ---------------------------------------------------------------------------
# RePairGroupingAlgorithm
# ---------------------------------------------------------------------------

class RePairGroupingAlgorithm(GroupingAlgorithm):
    """
    GroupingAlgorithm implementation using the RE-PAIR algorithm.

    build_dictionary() returns one DictionaryEntry per RE-PAIR rule with
    key_sequence fully expanded to original tokens.

    group() removes items that are part of a repeated pattern after its
    first occurrence, using the drop-range information emitted directly
    by _run_repair (O(n + total_replacements), no post-hoc scan).
    """

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _expand_all(
        rules: List[Tuple[Any, Any, int]],
    ) -> List[List[str]]:
        """Return fully-expanded token list for every rule."""
        expanded: List[List[str]] = []
        for left, right, _ in rules:
            exp = _expand_symbol(left, rules) + _expand_symbol(right, rules)
            expanded.append(exp)
        return expanded

    # ------------------------------------------------------------------
    # GroupingAlgorithm interface
    # ------------------------------------------------------------------

    def group(
        self,
        items: List[Any],
        key_fn: Callable[[Any], str],
        **kwargs,
    ) -> List[Any]:
        """
        Remove items that belong to a repeated pattern after its first
        occurrence, using RE-PAIR to identify the repeated patterns.

        The first occurrence of every repeated block is kept; all
        subsequent copies are dropped.  Drop ranges are collected in O(n)
        directly during the RE-PAIR run — no post-hoc scan over the input.
        """
        if not items:
            return []

        keys  = [key_fn(item) for item in items]
        _rules, _final, _rfp, drop_ranges = _run_repair(keys)
        if not drop_ranges:
            return list(items)

        keep = bytearray(b'\x01' * len(keys))   # 1 = keep, 0 = drop
        for (start, end) in drop_ranges:
            keep[start: end + 1] = b'\x00' * (end - start + 1)

        return [item for idx, item in enumerate(items) if keep[idx]]

    def build_dictionary(
        self,
        items: List[Any],
        key_fn: Callable[[Any], str],
        **kwargs,
    ) -> List[DictionaryEntry]:
        """
        Run RE-PAIR and return one DictionaryEntry per rule, sorted by
        repeat_count DESC.

        Each rule is fully expanded (recursively substituted) so that
        key_sequence contains only original token keys — never rule ids.

        entry_id is derived from rule_first_pos returned by _run_repair
        (no additional scan of the original input is needed).
        """
        if not items:
            return []

        keys = [key_fn(item) for item in items]
        rules, _final, rule_first_pos, _dr = _run_repair(keys)
        if not rules:
            return []

        expanded_rules = self._expand_all(rules)
        entries: List[DictionaryEntry] = []

        for rule_idx, ((left, right, freq), exp) in enumerate(
            zip(rules, expanded_rules)
        ):
            first_0    = rule_first_pos[rule_idx]   # 0-indexed start
            start_line = first_0 + 1                # 1-indexed
            end_line   = first_0 + len(exp)         # 1-indexed inclusive

            entries.append(DictionaryEntry(
                entry_id     = f"key_{start_line}-{end_line}",
                key_sequence = tuple(exp),
                repeat_count = freq,
            ))

        entries.sort(key=lambda e: e.repeat_count, reverse=True)
        return entries
