"""
Workflow Grouping Module

Implements workflow pattern mining using Drain3 (template extraction) + PrefixSpan
(sequence pattern mining) to detect multi-step workflow patterns across logs.

Handles parameter variance (e.g. COM-1 vs COM-2 as same pattern) and tolerates noise
(up to max_gap non-matching logs between workflow steps).

Public API
----------
WorkflowGroupingConfig
    Configuration for Drain3 template mining and PrefixSpan sequence mining.

WorkflowGroupingAlgorithm
    Concrete GroupingAlgorithm implementation for workflow-based deduplication.
"""

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Tuple

from drain3.template_miner import TemplateMiner
from drain3.template_miner_config import TemplateMinerConfig
from drain3.masking import MaskingInstruction

from .grouping_interface import DictionaryEntry, GroupingAlgorithm, GroupingResult


# ---------------------------------------------------------------------------
# WorkflowGroupingConfig
# ---------------------------------------------------------------------------

@dataclass
class WorkflowGroupingConfig:
    """Configuration for workflow pattern mining."""

    # ── Drain3 normalization ──────────────────────────────────────────────
    drain_sim_th: float = 0.5
    # Similarity threshold for grouping log messages into the same template.
    # Range 0.0–1.0. Lower = more aggressive grouping (more <*> placeholders).
    # Raise if templates are over-merged; lower if too many distinct templates.

    drain_depth: int = 4
    # Parse-tree depth. Deeper = finer-grained template discrimination.

    drain_max_children: int = 100
    # Max children per tree node. Limits memory on very diverse logs.

    parametrize_numeric_tokens: bool = True
    # Replace bare numbers with <*> automatically before template matching.

    # ── PrefixSpan sequence mining ────────────────────────────────────────
    min_support: int = 2
    # Minimum occurrences for a workflow to be reported.
    # Lower = more patterns but more noise; 2 is the minimum meaningful value.

    max_gap: int = 3
    # Maximum number of non-matching ("noise") logs allowed between
    # two consecutive workflow steps. Increase for noisier logs.

    min_workflow_len: int = 6
    # Minimum number of steps (meaningful log lines) in a reportable workflow.

    max_workflow_len: int = 25
    # Maximum steps per workflow. Prevents combinatorial explosion.

    max_samples_per_workflow: int = 5
    # How many example occurrences to store per discovered workflow.

    # ── Prefix filtering ─────────────────────────────────────────────────
    min_meaningful_prefix_len: int = 3
    # Templates whose meaningful content (after stripping leading <*>) is
    # shorter than this are excluded from sequence mining.


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _create_miner(config: WorkflowGroupingConfig) -> TemplateMiner:
    """Create a Drain3 template miner with standard masking rules."""
    template_config = TemplateMinerConfig()
    template_config.drain_sim_th = config.drain_sim_th
    template_config.drain_depth = config.drain_depth
    template_config.drain_max_children = config.drain_max_children
    template_config.parametrize_numeric_tokens = config.parametrize_numeric_tokens

    # Standard masking rules for IP, HEX, UUID
    template_config.masking_instructions = [
        MaskingInstruction(r'((\d{1,3}\.){3}\d{1,3})', 'IP'),
        MaskingInstruction(r'(0x[0-9a-fA-F]+)', 'HEX'),
        MaskingInstruction(
            r'([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})',
            'UUID'
        ),
    ]

    return TemplateMiner(config=template_config)


def _extract_meaningful_prefix(template: str, min_len: int) -> str | None:
    """
    Extract meaningful prefix from template.

    Strips leading <*> tokens and returns None if result is too short or
    all tokens are <*>.

    Examples:
      "<*> exit" → "exit" (if min_len <= 4)
      "<*> <*> is null" → "is null" (if min_len <= 7)
      "<*>" → None (not meaningful)
    """
    if not template:
        return None

    tokens = template.split()
    if not tokens:
        return None

    start_idx = 0
    while start_idx < len(tokens) and tokens[start_idx] == '<*>':
        start_idx += 1

    if start_idx >= len(tokens):
        return None

    meaningful = ' '.join(tokens[start_idx:])

    if len(meaningful) < min_len:
        return None

    return meaningful


def _extract_params(items: List[Any], log_indices: List[int]) -> Dict[str, List[str]]:
    """
    Extract key parameters from a sequence of logs.

    Returns dict with:
      job_ids: list of unique job IDs (e.g., "4", "6")
      trans_ids: list of unique transaction IDs
      node_ids: list of unique node IDs
    """
    params = {
        'job_ids': [],
        'trans_ids': [],
        'node_ids': [],
    }

    for idx in log_indices:
        if idx >= len(items):
            continue

        msg = items[idx].get('message', '')
        if not msg:
            continue

        # Extract job IDs (job:N pattern)
        job_matches = re.findall(r'job:(\d+)', msg)
        params['job_ids'].extend(job_matches)

        # Extract transaction IDs (Transaction\\DIGITS)
        trans_matches = re.findall(r'Transaction\\\\(\d+)', msg)
        params['trans_ids'].extend(trans_matches)

        # Extract node IDs (nDIGITS pattern)
        node_matches = re.findall(r'(n\d+)', msg)
        params['node_ids'].extend(node_matches)

    # Deduplicate and keep only first few
    params['job_ids'] = list(dict.fromkeys(params['job_ids']))[:3]
    params['trans_ids'] = list(dict.fromkeys(params['trans_ids']))[:2]
    params['node_ids'] = list(dict.fromkeys(params['node_ids']))[:2]

    return params


def _build_compact_desc(workflow_id: str, params: Dict[str, List[str]]) -> str:
    """
    Build compact workflow description.

    Example: "W0001 | job:4,6 | trans:3050334596 | node:n1761796701"
    """
    parts = [workflow_id]

    if params['job_ids']:
        parts.append("job:" + ','.join(params['job_ids']))

    if params['trans_ids']:
        parts.append("trans:" + ','.join(params['trans_ids']))

    if params['node_ids']:
        parts.append("node:" + ','.join(params['node_ids']))

    return ' | '.join(parts)


def _mine_sequences(
    log_to_prefix: Dict[int, str],
    thread_logs: Dict[str, List[int]],
    config: WorkflowGroupingConfig,
) -> List[Dict]:
    """
    Mine sequential patterns using PrefixSpan-like algorithm.

    Returns list of workflows, each with:
      sequence: tuple of meaningful prefixes
      occurrences: list of {thread, log_indices}
    """
    import time
    t_mine = time.time()
    seq_counts = Counter()
    seq_samples = defaultdict(list)

    print(f'[EXPORT] [Mining] Processing {len(thread_logs)} threads...', flush=True)
    thread_sequence_stats = {}  # Debug: track per-thread stats

    for thread_num, (thread_id, log_indices) in enumerate(thread_logs.items()):
        if thread_num > 0 and thread_num % max(1, len(thread_logs) // 5) == 0:
            print(f'[EXPORT] [Mining] Processed {thread_num}/{len(thread_logs)} threads...', flush=True)

        # Get meaningful prefixes for this thread
        prefixes = []
        indices = []
        for idx in log_indices:
            if idx in log_to_prefix:
                prefixes.append(log_to_prefix[idx])
                indices.append(idx)

        if len(prefixes) < config.min_workflow_len:
            continue

        thread_seqs_before = len(seq_counts)

        # Mine sequences with gap tolerance
        for seq_len in range(config.min_workflow_len, min(config.max_workflow_len + 1, len(prefixes) + 1)):
            for start in range(len(prefixes) - seq_len + 1):
                seq_items = []
                seq_indices = []
                pos = start

                for item_idx in range(seq_len):
                    if pos >= len(prefixes):
                        break

                    found = False
                    for gap in range(config.max_gap + 1):
                        if pos + gap < len(prefixes):
                            seq_items.append(prefixes[pos + gap])
                            seq_indices.append(indices[pos + gap])
                            pos = pos + gap + 1
                            found = True
                            break

                    if not found:
                        break

                if len(seq_items) == seq_len:
                    seq = tuple(seq_items)
                    seq_counts[seq] += 1

                    if len(seq_samples[seq]) < config.max_samples_per_workflow:
                        seq_samples[seq].append({
                            'thread': thread_id,
                            'log_indices': seq_indices
                        })

        thread_seqs_after = len(seq_counts)
        thread_sequence_stats[thread_id] = {
            'meaningful_logs': len(prefixes),
            'new_sequences': thread_seqs_after - thread_seqs_before
        }

    # Debug: show per-thread stats for top 5 threads
    print(f'[EXPORT] [Mining] Debug - Per-thread sequence generation:', flush=True)
    sorted_threads = sorted(thread_sequence_stats.items(), key=lambda x: x[1]['new_sequences'], reverse=True)
    for i, (thread_id, stats) in enumerate(sorted_threads[:5]):
        print(f'  Thread {i+1}: {thread_id} → {stats["meaningful_logs"]} logs → {stats["new_sequences"]:,} sequences', flush=True)

    frequent_seqs = [
        {
            'sequence': seq,
            'support': count,
            'occurrences': seq_samples[seq]
        }
        for seq, count in seq_counts.most_common()
        if count >= config.min_support
    ]

    elapsed_mine = (time.time() - t_mine) * 1000
    print(f'[EXPORT] [Mining] Done - found {len(seq_counts):,} total sequences, {len(frequent_seqs):,} frequent patterns ({elapsed_mine:.0f}ms)', flush=True)

    return frequent_seqs


# ---------------------------------------------------------------------------
# WorkflowGroupingAlgorithm
# ---------------------------------------------------------------------------

class WorkflowGroupingAlgorithm(GroupingAlgorithm):
    """
    Workflow-based deduplication algorithm.

    Uses Drain3 for template normalization and PrefixSpan for multi-step
    workflow discovery. Handles parameter variance and gap tolerance.
    """

    def __init__(self, config: WorkflowGroupingConfig = None):
        self.config = config or WorkflowGroupingConfig()

    def group(
        self,
        items: List[Any],
        key_fn: Callable[[Any], str],
        **kwargs,
    ) -> GroupingResult:
        """
        Group items into workflow patterns and deduplicate.

        Returns GroupingResult with deduplicated items and pattern dictionary.
        Also attaches _wf_first_occ_indices to track canonical occurrences.
        """
        import time

        # Step 1: Extract messages and run Drain3
        t_msgs = time.time()
        messages = [key_fn(item) for item in items]
        print(f'[EXPORT] [Drain3] Extracting templates from {len(messages)} messages...', flush=True)

        miner = _create_miner(self.config)
        log_to_template = {}
        log_to_prefix = {}

        progress_interval = max(1000, len(messages) // 10)  # Log every ~10%
        for idx, msg in enumerate(messages):
            if idx > 0 and idx % progress_interval == 0:
                print(f'[EXPORT] [Drain3] Processed {idx:,}/{len(messages):,} messages...', flush=True)

            result = miner.add_log_message(msg)
            cluster_id = result['cluster_id']
            if cluster_id is not None:
                cluster = miner.drain.id_to_cluster[cluster_id]
                template = cluster.get_template()
                log_to_template[idx] = template

                # Extract meaningful prefix
                prefix = _extract_meaningful_prefix(template, self.config.min_meaningful_prefix_len)
                if prefix:
                    log_to_prefix[idx] = prefix

        elapsed_ms = (time.time() - t_msgs) * 1000
        print(f'[EXPORT] [Drain3] Done - extracted {len(log_to_template):,} templates ({elapsed_ms:.0f}ms)', flush=True)

        # Step 2: Group logs by thread
        print(f'[EXPORT] [Threading] Grouping logs by thread...', flush=True)
        thread_logs = defaultdict(list)
        for idx, item in enumerate(items):
            thread_name = item.get('thread_name', 'default')
            thread_logs[thread_name].append(idx)
        print(f'[EXPORT] [Threading] Found {len(thread_logs)} threads', flush=True)

        # Step 3: Mine workflows
        print(f'[EXPORT] [Mining] Starting workflow sequence mining from {len(log_to_prefix):,} meaningful logs...', flush=True)
        workflows = _mine_sequences(log_to_prefix, thread_logs, self.config)

        # Step 4: Build deduplicated list and pattern dictionary
        t_build = time.time()
        print(f'[EXPORT] [Building] Processing {len(workflows):,} workflows...', flush=True)
        deduplicated = []
        dictionary = []
        skip_set = set()
        wf_first_occ_indices = {}

        # Track which items are annotations (to skip actual occurrences)
        annotation_ranges = {}  # (start, end) -> wf_idx

        for wf_idx, workflow in enumerate(workflows):
            if wf_idx > 0 and wf_idx % max(1, len(workflows) // 10) == 0:
                print(f'[EXPORT] [Building] Processed {wf_idx:,}/{len(workflows):,} workflows...', flush=True)
            seq = workflow['sequence']
            occurrences = workflow['occurrences']

            if not occurrences:
                continue

            # Sort occurrences by first log index
            sorted_occurrences = sorted(occurrences, key=lambda x: x['log_indices'][0])

            # First occurrence is canonical, keep it
            canonical = sorted_occurrences[0]
            canonical_indices = canonical['log_indices']
            wf_first_occ_indices[wf_idx] = canonical_indices

            # Build dictionary entry
            workflow_id = f'W{wf_idx + 1:04d}'
            key_sequence = tuple(seq)
            repeat_count = len(occurrences)
            occurrences_1indexed = tuple(
                sorted([idx + 1 for occ in sorted_occurrences for idx, _ in enumerate(items) if idx == occ['log_indices'][0]])
            )

            dictionary.append(DictionaryEntry(
                rule_id=wf_idx,
                entry_id=workflow_id,
                key_sequence=key_sequence,
                repeat_count=repeat_count,
                occurrences=occurrences_1indexed,
            ))

            # Mark duplicates for removal
            for dup_idx, dup_occ in enumerate(sorted_occurrences[1:], start=1):
                dup_indices = dup_occ['log_indices']
                start_idx = dup_indices[0]
                end_idx = dup_indices[-1]

                # Extract params from logs for compact description
                params = _extract_params(items, dup_indices)
                compact_desc = _build_compact_desc(workflow_id, params)

                # Create annotation sentinel
                start_ts = items[start_idx].get('timestamp', '')
                end_ts = items[end_idx].get('timestamp', '')

                # Copy fields from first log in duplicate group (but exclude message to avoid duplication)
                annotation_item = dict(items[start_idx])
                annotation_item.pop('message', None)  # Remove message to prevent duplication
                annotation_item.update({
                    '_is_annotation': True,
                    '_workflow_compact_desc': compact_desc,
                    '_chunks': [(wf_idx, canonical_indices[0], len(dup_indices))],
                    '_match_len': len(dup_indices),
                    '_wf_start_ts': start_ts,
                    '_wf_end_ts': end_ts,
                })

                annotation_ranges[(start_idx, end_idx)] = (wf_idx, annotation_item)

                # Mark all indices in this duplicate for skipping
                for skip_idx in dup_indices:
                    skip_set.add(skip_idx)

        # Step 5: Build deduplicated list
        print(f'[EXPORT] [Building] Constructing deduplicated log list...', flush=True)
        i = 0
        while i < len(items):
            # Check if this position starts an annotation
            found_annotation = False
            for (start_idx, end_idx), (_, annotation_item) in annotation_ranges.items():
                if i == start_idx:
                    deduplicated.append(annotation_item)
                    i = end_idx + 1
                    found_annotation = True
                    break

            if not found_annotation:
                if i not in skip_set:
                    deduplicated.append(dict(items[i]))
                i += 1

        # Sort dictionary by repeat_count DESC
        dictionary.sort(key=lambda e: e.repeat_count, reverse=True)

        elapsed_build = (time.time() - t_build) * 1000
        print(f'[EXPORT] [Building] Done - {len(deduplicated):,} deduplicated logs, {len(dictionary):,} patterns ({elapsed_build:.0f}ms)', flush=True)

        # Create result and attach first occurrence indices
        result = GroupingResult(deduplicated, dictionary)
        result._wf_first_occ_indices = wf_first_occ_indices

        return result
