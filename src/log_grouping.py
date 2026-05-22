"""
NEUF Log Grouping Module
Deduplication / annotation for NEUF log-row dicts.

Delegates to the generic LZ77 engine in lz77_grouping.py.

Key = device_id + component_name + message  (timestamp / log_level ignored).

Public API
----------
group_neuf_logs(lines, filter_duplicate, min_match) -> List[dict]
    filter_duplicate=True  : duplicate blocks removed entirely.
    filter_duplicate=False : each duplicate block collapsed to 1 annotation line.
                             "Giống dòng {j+1}"          (block length = 1)
                             "Giống dòng {j+1}-{j+L}"    (block length > 1)
"""

from typing import List, Optional

from .lz77_grouping import group_similar_lines

_SEP = "\x00"


# ---------------------------------------------------------------------------
# Key function
# ---------------------------------------------------------------------------

def _neuf_log_key_fn(line: dict) -> str:
    """Fingerprint a NEUF log row: device_id + component_name + message."""
    device    = line.get("device_id")      or ""
    component = line.get("component_name") or ""
    message   = line.get("message")        or ""
    return f"{device}{_SEP}{component}{_SEP}{message}"


# ---------------------------------------------------------------------------
# on_duplicate factory
# ---------------------------------------------------------------------------

def _make_neuf_on_duplicate(filter_duplicate: bool):
    """
    Build the on_duplicate callback for NEUF log rows.

    filter_duplicate=True  : return None  → drop entire block.
    filter_duplicate=False : return a modified copy of the first line with
                             message replaced by an annotation string.
    """
    def on_duplicate(item: dict, dup_pos: int, match_start: int, match_len: int):
        if filter_duplicate:
            return None
        modified = dict(item)
        if match_len == 1:
            modified["message"] = f"Same as line {match_start + 1}"
        else:
            modified["message"] = f"Same as line {match_start + 1}-{match_start + match_len}"
        return modified

    return on_duplicate


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def group_neuf_logs(
    lines: List[dict],
    filter_duplicate: bool = True,
    min_match: int = 1,
) -> List[dict]:
    """
    Deduplicate / annotate NEUF log-row dicts using LZ77 greedy scan.

    @param lines:            List of NEUF log-row dicts.
    @param filter_duplicate: True  = remove duplicate blocks.
                             False = collapse each duplicate block to 1 annotation line.
    @param min_match:        Minimum block length to trigger grouping (default 1).
    @returns:                Processed list of log-row dicts.
    """
    return group_similar_lines(
        items        = lines,
        key_fn       = _neuf_log_key_fn,
        on_duplicate = _make_neuf_on_duplicate(filter_duplicate),
        min_match    = min_match,
    )
