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

GroupingAlgorithm (ABC)
    group(items, key_fn, **kwargs) -> List[Any]
        Deduplicate / annotate a list of items.

    build_dictionary(items, key_fn, **kwargs) -> List[DictionaryEntry]
        Return repeated patterns sorted by repeat_count DESC.

    export_dictionary(items, key_fn, output_path, **kwargs) -> None
        Call build_dictionary and serialise the result as a JSON file.
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
from dataclasses import asdict, dataclass
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
# GroupingAlgorithm
# ---------------------------------------------------------------------------

class GroupingAlgorithm(ABC):
    """
    Abstract base class for grouping/deduplication algorithms.

    Concrete subclasses must implement `group` and `build_dictionary`.
    `export_dictionary` is provided as a non-abstract convenience method.
    """

    @abstractmethod
    def group(
        self,
        items: List[Any],
        key_fn: Callable[[Any], str],
        **kwargs,
    ) -> List[Any]:
        """
        Deduplicate / annotate a list of items.

        @param items:   Any list of items.
        @param key_fn:  item -> str fingerprint extractor.
        @returns:       Processed list (duplicates removed or collapsed).
        """

    @abstractmethod
    def build_dictionary(
        self,
        items: List[Any],
        key_fn: Callable[[Any], str],
        **kwargs,
    ) -> List[DictionaryEntry]:
        """
        Identify all repeated patterns in *items* and return them as a sorted
        list of DictionaryEntry objects.

        Entries are sorted by repeat_count DESC.

        @param items:   Any list of items.
        @param key_fn:  item -> str fingerprint extractor.
        @returns:       List of DictionaryEntry, sorted by repeat_count DESC.
        """

    def export_dictionary(
        self,
        items: List[Any],
        key_fn: Callable[[Any], str],
        output_path: str,
        **kwargs,
    ) -> None:
        """
        Build the pattern dictionary and write it to *output_path* as JSON.

        The file will contain a JSON array of objects:
          [{"entry_id": "key_1-2", "key_sequence": [...], "repeat_count": N}, ...]

        @param items:       Any list of items.
        @param key_fn:      item -> str fingerprint extractor.
        @param output_path: Destination path for the .json file.
        """
        entries = self.build_dictionary(items, key_fn, **kwargs)
        data = [e.to_dict() for e in entries]
        with open(output_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
