"""
Generic Grouping Interface Module

Defines the abstract base class for all grouping/deduplication algorithms.

Public API
----------
DictionaryEntry
    Immutable value object representing one repeated-pattern entry.

    entry_id     : str   — "key_{startLine}-{endLine}" (1-indexed, inclusive)
    key_sequence : List[str]  — fully-expanded sequence of original keys
    repeat_count : int   — how many times the pattern was found repeated

GroupingResult
    Combined result returned by group().

    deduplicated : List[Any]            — items with duplicates removed/collapsed
    dictionary   : List[DictionaryEntry] — repeated patterns sorted by repeat_count DESC

GroupingAlgorithm (ABC)
    group(items, key_fn, **kwargs) -> GroupingResult
        Deduplicate / annotate a list of items and build the pattern dictionary
        in a single pass, returning both as a GroupingResult.

    export_dictionary(items, key_fn, output_path, **kwargs) -> None
        Call group() and serialise the dictionary part as a JSON file.
        JSON schema:
        [
          {
            "entry_id":     "key_1-3",
            "key_sequence": ["A", "B", "C"],
            "repeat_count": 5
          },
          ...
        ]
        Entries are sorted by repeat_count DESC.
"""

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable, List


# ---------------------------------------------------------------------------
# DictionaryEntry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DictionaryEntry:
    """
    A single entry in the grouping dictionary.

    entry_id      — unique identifier: "key_{startLine}-{endLine}" (1-indexed)
    key_sequence  — fully-expanded list of original-key tokens forming the pattern
    repeat_count  — number of times this pattern was found repeated in the input
    """
    entry_id:     str
    key_sequence: tuple          # immutable; serialised as list
    repeat_count: int

    def to_dict(self) -> dict:
        return {
            "entry_id":     self.entry_id,
            "key_sequence": list(self.key_sequence),
            "repeat_count": self.repeat_count,
        }


# ---------------------------------------------------------------------------
# GroupingResult
# ---------------------------------------------------------------------------

@dataclass
class GroupingResult:
    """
    Combined result returned by GroupingAlgorithm.group().

    deduplicated — items with duplicates removed or collapsed
    dictionary   — repeated patterns sorted by repeat_count DESC
    """
    deduplicated: List[Any]
    dictionary:   List[DictionaryEntry]


# ---------------------------------------------------------------------------
# GroupingAlgorithm
# ---------------------------------------------------------------------------

class GroupingAlgorithm(ABC):
    """
    Abstract base class for grouping/deduplication algorithms.

    Concrete subclasses must implement `group`, which returns a GroupingResult
    containing both the deduplicated item list and the pattern dictionary in
    a single pass.

    `export_dictionary` is provided as a non-abstract convenience method.
    """

    @abstractmethod
    def group(
        self,
        items: List[Any],
        key_fn: Callable[[Any], str],
        **kwargs,
    ) -> GroupingResult:
        """
        Deduplicate / annotate a list of items and build the pattern dictionary.

        @param items:   Any list of items.
        @param key_fn:  item -> str fingerprint extractor.
        @returns:       GroupingResult with deduplicated items and dictionary.
        """

    def export_dictionary(
        self,
        items: List[Any],
        key_fn: Callable[[Any], str],
        output_path: str,
        **kwargs,
    ) -> None:
        """
        Run group() and write the dictionary part to *output_path* as JSON.

        The file will contain a JSON array of objects:
          [{"entry_id": "key_1-2", "key_sequence": [...], "repeat_count": N}, ...]

        @param items:       Any list of items.
        @param key_fn:      item -> str fingerprint extractor.
        @param output_path: Destination path for the .json file.
        """
        result = self.group(items, key_fn, **kwargs)
        data = [e.to_dict() for e in result.dictionary]
        with open(output_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
