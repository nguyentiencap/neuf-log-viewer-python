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
