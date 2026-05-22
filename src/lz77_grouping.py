"""
LZ77 Grouping Module
Generic LZ77-inspired duplicate-block detection for any sequence of items.

Public API
----------
group_similar_lines(items, key_fn, on_duplicate, min_match) -> List[Any]
    Single-pass greedy deduplication engine.

    key_fn(item) -> str
        Extracts a comparable fingerprint from each item.

    on_duplicate(item, dup_pos, match_start, match_len) -> item | None
        Called for the FIRST item of each duplicate block.
        Return None  : drop the entire block.
        Return item  : use as replacement for first line; rest of block dropped.

    min_match : int (default 1)
        Minimum block length to trigger on_duplicate.

LZ77GroupingAlgorithm
    GroupingAlgorithm subclass that wraps group_similar_lines.
    group() runs deduplication and collects the pattern dictionary in one pass,
    returning a GroupingResult with both deduplicated items and dictionary.

Internal helpers (exported for testability)
-------------------------------------------
_find_longest_match(keys, pos, emitted_starts) -> (start, length) | None
    LZ77 core: find the longest prefix of keys[pos:] seen before pos.

_build_window_keys(base_keys, window) -> List[str]
    Sliding-window key joiner — for unit tests only.

build_key_dict(window_keys, active_indices) -> Dict[str, List[int]]
    Group duplicate keys by index — for unit tests only.
"""

from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from .grouping_interface import DictionaryEntry, GroupingAlgorithm, GroupingResult

_SEP = "\x00"


# ---------------------------------------------------------------------------
# _find_longest_match
# ---------------------------------------------------------------------------

def _find_longest_match(
    keys: List[str],
    pos: int,
    emitted_starts: Dict[str, List[int]],
) -> Optional[Tuple[int, int]]:
    """
    Find the longest sequence starting at `pos` that has appeared entirely
    before `pos` (non-overlapping), restricted to positions in `emitted_starts`.

    @param keys:           Full list of per-item fingerprints.
    @param pos:            Current scan position.
    @param emitted_starts: key -> [positions of kept items with that key].
    @returns:              (match_start, match_length) or None.
    """
    n          = len(keys)
    candidates = emitted_starts.get(keys[pos], [])

    if not candidates:
        return None

    best_start  = -1
    best_length = 0

    for j in candidates:
        length = 0
        while (
            pos + length < n
            and j + length < pos          # source block must fully precede pos
            and keys[pos + length] == keys[j + length]
        ):
            length += 1

        if length > best_length:
            best_length = length
            best_start  = j

    return (best_start, best_length) if best_length > 0 else None


# ---------------------------------------------------------------------------
# _build_window_keys  (test utility)
# ---------------------------------------------------------------------------

def _build_window_keys(base_keys: List[str], window: int) -> List[str]:
    """
    Join `window` consecutive base_keys into composite keys.
    Result length = len(base_keys) - window + 1.
    """
    n = len(base_keys)
    if window > n:
        return []
    return [_SEP.join(base_keys[i: i + window]) for i in range(n - window + 1)]


# ---------------------------------------------------------------------------
# build_key_dict  (test utility)
# ---------------------------------------------------------------------------

def build_key_dict(
    window_keys: List[str],
    active_indices: Set[int],
) -> Dict[str, List[int]]:
    """
    Map each key to the list of active indices that share it.
    Only keys with 2+ active occurrences are returned.
    """
    mapping: Dict[str, List[int]] = {}
    for idx, key in enumerate(window_keys):
        if idx in active_indices:
            mapping.setdefault(key, []).append(idx)
    return {k: v for k, v in mapping.items() if len(v) >= 2}


# ---------------------------------------------------------------------------
# group_similar_lines  — main entry point
# ---------------------------------------------------------------------------

def group_similar_lines(
    items: List[Any],
    key_fn: Callable[[Any], str],
    on_duplicate: Callable[[Any, int, int, int], Optional[Any]],
    min_match: int = 1,
) -> List[Any]:
    """
    Generic LZ77-inspired deduplication for any sequence of items.

    Single left-to-right pass:
      1. Compute keys via key_fn.
      2. Track emitted_starts: positions of items actually kept in the output.
      3. For each unhandled position i:
         - Find longest match before i using _find_longest_match.
         - No match (or length < min_match): emit item as-is, register key.
         - Match of length L at position j:
             Call on_duplicate(items[i], i, j, L).
             If result is not None → emit it (replaces first line of block).
             i .. i+L-1 are all marked handled and NOT registered as emitted.
      4. Return result list.

    @param items:         Any list of items.
    @param key_fn:        item -> str fingerprint for comparison.
    @param on_duplicate:  (item, dup_pos, match_start, match_len) -> item | None
    @param min_match:     Minimum match length to trigger grouping (default 1).
    @returns:             Deduplicated/annotated list.
    """
    if not items:
        return []

    n    = len(items)
    keys = [key_fn(item) for item in items]

    handled:        Set[int]              = set()
    emitted_starts: Dict[str, List[int]] = {}
    result:         List[Any]            = []

    for i in range(n):
        if i in handled:
            continue

        match = _find_longest_match(keys, i, emitted_starts)

        if match is None or match[1] < min_match:
            result.append(items[i])
            emitted_starts.setdefault(keys[i], []).append(i)
        else:
            match_start, match_len = match
            replacement = on_duplicate(items[i], i, match_start, match_len)
            if replacement is not None:
                result.append(replacement)
            for offset in range(match_len):
                handled.add(i + offset)

    return result


# ---------------------------------------------------------------------------
# LZ77GroupingAlgorithm — GroupingAlgorithm adapter
# ---------------------------------------------------------------------------

class LZ77GroupingAlgorithm(GroupingAlgorithm):
    """
    GroupingAlgorithm implementation backed by the LZ77-inspired engine.

    group() parameters (via **kwargs):
        on_duplicate : Callable[[Any, int, int, int], Optional[Any]]
            Called for the first item of each duplicate block.
            Return None to drop the block; return an item to insert a replacement.
            Defaults to dropping duplicates (return None).
        min_match : int (default 1)
            Minimum block length to trigger on_duplicate.
    """

    def group(
        self,
        items: List[Any],
        key_fn: Callable[[Any], str],
        on_duplicate: Optional[Callable[[Any, int, int, int], Optional[Any]]] = None,
        min_match: int = 1,
        **kwargs,
    ) -> GroupingResult:
        """
        Deduplicate items and collect the pattern dictionary in a single pass.

        Returns a GroupingResult containing both the deduplicated item list
        and the pattern dictionary (sorted by repeat_count DESC).
        """
        if not items:
            return GroupingResult(deduplicated=[], dictionary=[])

        keys    = [key_fn(item) for item in items]
        counts: Dict[Tuple[str, ...], int] = {}

        def _default_on_duplicate(item, dup_pos, match_start, match_len):
            return None

        effective_on_duplicate = on_duplicate if on_duplicate is not None else _default_on_duplicate

        def _collecting_on_duplicate(item, dup_pos, match_start, match_len):
            block = tuple(keys[match_start: match_start + match_len])
            counts[block] = counts.get(block, 0) + 1
            return effective_on_duplicate(item, dup_pos, match_start, match_len)

        deduplicated = group_similar_lines(
            items        = items,
            key_fn       = key_fn,
            on_duplicate = _collecting_on_duplicate,
            min_match    = min_match,
        )

        entries: List[DictionaryEntry] = []
        seen: Set[Tuple[str, ...]] = set()

        for block, count in counts.items():
            if block in seen:
                continue
            seen.add(block)
            plen = len(block)
            start_line = 1
            for i in range(len(keys) - plen + 1):
                if tuple(keys[i: i + plen]) == block:
                    start_line = i + 1      # 1-indexed
                    break
            end_line = start_line + plen - 1
            entries.append(DictionaryEntry(
                entry_id     = f"key_{start_line}-{end_line}",
                key_sequence = block,
                repeat_count = count + 1,   # +1 for the original occurrence
            ))

        entries.sort(key=lambda e: e.repeat_count, reverse=True)
        return GroupingResult(deduplicated=deduplicated, dictionary=entries)
