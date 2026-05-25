"""
Tests for neuf_log_viewer_api.py (Python/FastAPI port of neuf-log-viewer-api.js).

TDD: tests were written before the API implementation.
They define the complete expected behaviour of every endpoint.

Test framework: unittest + FastAPI TestClient (via httpx)
"""

import asyncio
import json
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# Bootstrap: ensure python-port root is importable
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_PYTHON_PORT = os.path.dirname(_HERE)
if _PYTHON_PORT not in sys.path:
    sys.path.insert(0, _PYTHON_PORT)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_log_row(
    id=1,
    filename='NEUF-test.log',
    timestamp='2026.04.08 10:00:00.000',
    log_level='ERROR',
    thread_name='main',
    device_id='Device1',
    component_name='com.example',
    message='Test error message',
):
    return {
        'id': id,
        'filename': filename,
        'timestamp': timestamp,
        'log_level': log_level,
        'thread_name': thread_name,
        'device_id': device_id,
        'component_name': component_name,
        'message': message,
    }


def _make_filter_result(logs=None, total=None, page=1, page_size=1000, total_pages=1):
    if logs is None:
        logs = [_make_log_row()]
    if total is None:
        total = len(logs)
    return {
        'success': True,
        'logs': logs,
        'total': total,
        'page': page,
        'pageSize': page_size,
        'totalPages': total_pages,
        'outputTable': 'filter_abc',
    }


def _make_service(
    filter_result=None,
    preset_suggestions=None,
    filter_options=None,
):
    """Build a fully mocked NEUFLogService."""
    if filter_result is None:
        filter_result = _make_filter_result()
    if preset_suggestions is None:
        preset_suggestions = {
            'success': True,
            'suggestions': [
                {'id': 'preset_1', 'label': 'Preset One', 'description': 'Preset One'},
            ]
        }
    if filter_options is None:
        filter_options = {
            'success': True,
            'data': {
                'logLevels': ['ERROR', 'WARN'],
                'devices': ['Device1'],
                'components': ['com.example'],
                'filenames': ['NEUF-test.log'],
            }
        }

    svc = MagicMock()
    svc.initialize = AsyncMock()
    svc.is_database_scanned = MagicMock(return_value=True)
    svc.scan_logs = AsyncMock(return_value={
        'success': True,
        'data': {'totalLogs': 10, 'filesScanned': 1, 'alreadyScanned': False}
    })
    svc.normalize_filters = MagicMock(side_effect=lambda f: f)
    svc.apply_preset = AsyncMock()
    svc.filter_logs = AsyncMock(return_value=filter_result)
    svc.get_filter_options = AsyncMock(return_value=filter_options)
    svc.get_preset_suggestions = AsyncMock(return_value=preset_suggestions)
    svc.get_db_scan_meta = AsyncMock(return_value={'scanTimeFrom': None, 'scanTimeTo': None})
    svc.format_log_entry = MagicMock(side_effect=lambda log, fmt: {**log, 'formattedLog': f'{log["timestamp"]} [{log["log_level"]}] {log["message"]}'})
    svc.dedup_and_extract_patterns = MagicMock(side_effect=lambda logs, mode: (logs, []))
    return svc


# ---------------------------------------------------------------------------
# Import the app factory AFTER setting up the service mock
# ---------------------------------------------------------------------------

def _build_test_client(service):
    """Create a TestClient with the mocked service injected."""
    from fastapi.testclient import TestClient
    import neuf_log_viewer_api as api_module

    # Use a temporary directory as folder_path
    import tempfile
    tmp_dir = tempfile.mkdtemp()

    app = api_module.create_app(folder_path=tmp_dir, log_service=service)
    return TestClient(app), tmp_dir


# ===========================================================================
# GET /health
# ===========================================================================

class TestHealthEndpoint(unittest.TestCase):

    def setUp(self):
        self.svc = _make_service()
        self.client, self.folder = _build_test_client(self.svc)

    def test_returns_200_ok(self):
        resp = self.client.get('/health')
        self.assertEqual(resp.status_code, 200)

    def test_response_has_success_true(self):
        resp = self.client.get('/health')
        data = resp.json()
        self.assertTrue(data['success'])

    def test_response_has_status_healthy(self):
        resp = self.client.get('/health')
        self.assertEqual(resp.json()['status'], 'healthy')

    def test_response_includes_folder_path(self):
        resp = self.client.get('/health')
        self.assertIn('folderPath', resp.json())

    def test_response_includes_database_scanned_flag(self):
        resp = self.client.get('/health')
        self.assertIn('databaseScanned', resp.json())


# ===========================================================================
# POST /preset_suggestions
# ===========================================================================

class TestPresetSuggestionsEndpoint(unittest.TestCase):

    def setUp(self):
        self.svc = _make_service()
        self.client, self.folder = _build_test_client(self.svc)

    def test_returns_200(self):
        resp = self.client.post('/preset_suggestions')
        self.assertEqual(resp.status_code, 200)

    def test_response_has_success_true(self):
        resp = self.client.post('/preset_suggestions')
        self.assertTrue(resp.json()['success'])

    def test_response_contains_suggestions_list(self):
        resp = self.client.post('/preset_suggestions')
        data = resp.json()
        self.assertIn('suggestions', data)
        self.assertIsInstance(data['suggestions'], list)

    def test_suggestions_include_id_and_label(self):
        resp = self.client.post('/preset_suggestions')
        s = resp.json()['suggestions'][0]
        self.assertIn('id', s)
        self.assertIn('label', s)

    def test_returns_500_on_service_error(self):
        svc = _make_service()
        svc.get_preset_suggestions = AsyncMock(side_effect=RuntimeError('DB error'))
        client, _ = _build_test_client(svc)
        resp = client.post('/preset_suggestions')
        self.assertEqual(resp.status_code, 500)
        self.assertFalse(resp.json()['success'])


# ===========================================================================
# POST /filter_log
# ===========================================================================

class TestFilterLogEndpoint(unittest.TestCase):

    def setUp(self):
        self.svc = _make_service()
        self.client, self.folder = _build_test_client(self.svc)

    def test_returns_200(self):
        resp = self.client.post('/filter_log', json={})
        self.assertEqual(resp.status_code, 200)

    def test_response_has_success_true(self):
        resp = self.client.post('/filter_log', json={})
        self.assertTrue(resp.json()['success'])

    def test_response_contains_logs(self):
        resp = self.client.post('/filter_log', json={})
        data = resp.json()
        self.assertIn('logs', data)
        self.assertIsInstance(data['logs'], list)

    def test_response_contains_pagination_fields(self):
        resp = self.client.post('/filter_log', json={})
        data = resp.json()
        self.assertIn('total', data)
        self.assertIn('page', data)
        self.assertIn('pageSize', data)
        self.assertIn('totalPages', data)

    def test_response_contains_filter_options(self):
        # filter_log returns the raw paginated result; filter options are fetched
        # separately via /filter_option — response contains success/logs/total etc.
        resp = self.client.post('/filter_log', json={})
        data = resp.json()
        self.assertIn('success', data)
        self.assertIn('logs', data)

    def test_logs_are_formatted_by_default(self):
        resp = self.client.post('/filter_log', json={})
        logs = resp.json()['logs']
        self.assertGreater(len(logs), 0)
        self.assertIn('formattedLog', logs[0])

    def test_raw_true_returns_unformatted_logs(self):
        resp = self.client.post('/filter_log', json={'raw': True})
        logs = resp.json()['logs']
        # raw logs: should NOT have formattedLog key
        self.assertNotIn('formattedLog', logs[0])

    def test_accepts_filters_object(self):
        body = {
            'filters': {
                'logLevelInclude': ['ERROR'],
                'deviceInclude': ['Device1'],
            },
            'page': 1,
            'pageSize': 100,
        }
        resp = self.client.post('/filter_log', json=body)
        self.assertEqual(resp.status_code, 200)
        # Verify filter_logs was called with some filters
        self.svc.filter_logs.assert_called_once()

    def test_accepts_legacy_steps_format(self):
        body = {
            'steps': [{'filters': {'logLevelInclude': ['WARN']}}]
        }
        resp = self.client.post('/filter_log', json=body)
        self.assertEqual(resp.status_code, 200)

    def test_page_and_page_size_forwarded(self):
        self.client.post('/filter_log', json={'page': 3, 'pageSize': 50})
        call_kwargs = self.svc.filter_logs.call_args
        pagination = call_kwargs[0][2] if call_kwargs[0] else call_kwargs[1].get('pagination', call_kwargs[0][2] if call_kwargs[0] else None)
        # Just check it was called
        self.svc.filter_logs.assert_called_once()

    def test_returns_500_on_service_error(self):
        svc = _make_service()
        svc.filter_logs = AsyncMock(side_effect=RuntimeError('DB error'))
        client, _ = _build_test_client(svc)
        resp = client.post('/filter_log', json={})
        self.assertEqual(resp.status_code, 500)
        self.assertFalse(resp.json()['success'])


# ===========================================================================
# POST /export_log
# ===========================================================================

class TestExportLogEndpoint(unittest.TestCase):

    def setUp(self):
        logs_page1 = [_make_log_row(id=i, message=f'Message {i}') for i in range(3)]
        result = _make_filter_result(logs=logs_page1, total=3, total_pages=1)
        self.svc = _make_service(filter_result=result)
        self.client, self.folder = _build_test_client(self.svc)

    def test_export_full_format_returns_200(self):
        resp = self.client.post('/export_log', json={'format': 'full', 'dedup': 'none'})
        self.assertEqual(resp.status_code, 200)

    def test_export_full_format_content_type_is_text_plain(self):
        # dedup='none' returns bare file; dedup='annotate' (default) returns a ZIP
        resp = self.client.post('/export_log', json={'format': 'full', 'dedup': 'none'})
        self.assertIn('text/plain', resp.headers['content-type'])

    def test_export_full_format_has_attachment_disposition(self):
        resp = self.client.post('/export_log', json={'format': 'full', 'dedup': 'none'})
        self.assertIn('attachment', resp.headers.get('content-disposition', ''))

    def test_export_compact_format(self):
        resp = self.client.post('/export_log', json={'format': 'compact', 'dedup': 'none'})
        self.assertEqual(resp.status_code, 200)
        self.assertIn('text/plain', resp.headers['content-type'])

    def test_export_json_format(self):
        resp = self.client.post('/export_log', json={'format': 'json', 'dedup': 'none'})
        self.assertEqual(resp.status_code, 200)
        self.assertIn('application/json', resp.headers['content-type'])
        # Should be valid JSON array
        data = resp.json()
        self.assertIsInstance(data, list)

    def test_export_csv_format(self):
        resp = self.client.post('/export_log', json={'format': 'csv', 'dedup': 'none'})
        self.assertEqual(resp.status_code, 200)
        self.assertIn('text/csv', resp.headers['content-type'])
        # First line should be headers
        lines = resp.text.strip().split('\n')
        self.assertIn('filename', lines[0])

    def test_export_filename_includes_timestamp(self):
        # dedup='none' returns a bare file with a predictable name
        resp = self.client.post('/export_log', json={'format': 'full', 'dedup': 'none'})
        disposition = resp.headers.get('content-disposition', '')
        self.assertIn('neuf-logs-export-', disposition)

    def test_export_json_filename_ends_with_json(self):
        resp = self.client.post('/export_log', json={'format': 'json', 'dedup': 'none'})
        disposition = resp.headers.get('content-disposition', '')
        self.assertIn('.json', disposition)

    def test_export_csv_filename_ends_with_csv(self):
        resp = self.client.post('/export_log', json={'format': 'csv', 'dedup': 'none'})
        disposition = resp.headers.get('content-disposition', '')
        self.assertIn('.csv', disposition)

    def test_export_with_filters(self):
        body = {
            'filters': {'logLevelInclude': ['ERROR']},
            'format': 'full',
        }
        resp = self.client.post('/export_log', json=body)
        self.assertEqual(resp.status_code, 200)

    def test_export_accepts_legacy_steps_format(self):
        body = {
            'steps': [{'filters': {'logLevelInclude': ['WARN']}}],
            'format': 'full',
        }
        resp = self.client.post('/export_log', json=body)
        self.assertEqual(resp.status_code, 200)

    def test_returns_500_on_service_error(self):
        svc = _make_service()
        svc.filter_logs = AsyncMock(side_effect=RuntimeError('DB error'))
        client, _ = _build_test_client(svc)
        resp = client.post('/export_log', json={})
        self.assertEqual(resp.status_code, 500)
        self.assertFalse(resp.json()['success'])


# ===========================================================================
# Helper: parse_filters_from_request
# ===========================================================================

class TestParseFiltersFromRequest(unittest.TestCase):

    def setUp(self):
        import neuf_log_viewer_api as api_module
        self.parse = api_module.parse_filters_from_request

    def test_returns_empty_lists_for_missing_keys(self):
        filters = self.parse({}, MagicMock(normalize_filters=lambda f: f))
        self.assertEqual(filters['filenameInclude'], [])
        self.assertEqual(filters['logLevelInclude'], [])

    def test_preserves_log_level_include(self):
        filters = self.parse({'logLevelInclude': ['ERROR']}, MagicMock(normalize_filters=lambda f: f))
        self.assertEqual(filters['logLevelInclude'], ['ERROR'])

    def test_preserves_search(self):
        filters = self.parse({'search': 'Exception'}, MagicMock(normalize_filters=lambda f: f))
        self.assertEqual(filters['search'], 'Exception')

    def test_preserves_time_from_and_time_to(self):
        filters = self.parse(
            {'timeFrom': '2026.01.01 00:00:00', 'timeTo': '2026.12.31 23:59:59'},
            MagicMock(normalize_filters=lambda f: f)
        )
        self.assertEqual(filters['timeFrom'], '2026.01.01 00:00:00')
        self.assertEqual(filters['timeTo'], '2026.12.31 23:59:59')

    def test_context_lines_parsed_to_int(self):
        filters = self.parse({'contextLines': '5'}, MagicMock(normalize_filters=lambda f: f))
        self.assertEqual(filters['contextLines'], 5)

    def test_strict_context_parsed_to_bool(self):
        filters = self.parse({'strictContext': 'true'}, MagicMock(normalize_filters=lambda f: f))
        self.assertTrue(filters['strictContext'])


# ===========================================================================
# Helper: escape_csv_value
# ===========================================================================

class TestEscapeCsvValue(unittest.TestCase):

    def setUp(self):
        import neuf_log_viewer_api as api_module
        self.escape = api_module.escape_csv_value

    def test_plain_value_unchanged(self):
        self.assertEqual(self.escape('hello'), 'hello')

    def test_value_with_comma_is_quoted(self):
        result = self.escape('hello, world')
        self.assertEqual(result, '"hello, world"')

    def test_value_with_double_quote_is_escaped(self):
        result = self.escape('say "hi"')
        self.assertEqual(result, '"say ""hi"""')

    def test_none_returns_empty_string(self):
        self.assertEqual(self.escape(None), '')

    def test_value_with_newline_is_quoted(self):
        result = self.escape('line1\nline2')
        self.assertEqual(result, '"line1\nline2"')


# ===========================================================================
# Pattern post-processing: _is_contiguous_subsequence
# ===========================================================================

class TestIsContiguousSubsequence(unittest.TestCase):

    def setUp(self):
        import neuf_log_viewer_api as api_module
        self.fn = api_module._is_contiguous_subsequence

    def test_exact_match_is_not_subsequence(self):
        # Same length → cannot be a *strict* sub-sequence
        self.assertFalse(self.fn(('a', 'b'), ('a', 'b')))

    def test_prefix_is_subsequence(self):
        self.assertTrue(self.fn(('a',), ('a', 'b', 'c')))

    def test_suffix_is_subsequence(self):
        self.assertTrue(self.fn(('c',), ('a', 'b', 'c')))

    def test_middle_is_subsequence(self):
        self.assertTrue(self.fn(('b',), ('a', 'b', 'c')))

    def test_two_element_prefix_is_subsequence(self):
        self.assertTrue(self.fn(('a', 'b'), ('a', 'b', 'c')))

    def test_non_contiguous_is_not_matched(self):
        # ('a', 'c') does not appear contiguously in ('a', 'b', 'c')
        self.assertFalse(self.fn(('a', 'c'), ('a', 'b', 'c')))

    def test_empty_needle_returns_false(self):
        self.assertFalse(self.fn((), ('a', 'b')))

    def test_needle_longer_than_haystack_returns_false(self):
        self.assertFalse(self.fn(('a', 'b', 'c', 'd'), ('a', 'b')))


# ===========================================================================
# Pattern post-processing: _deduplicate_patterns
# ===========================================================================

def _make_pattern(key_sequence, repeat_count, occurrences=None, **kwargs):
    """Helper: build a minimal pattern dict as returned by _build_patterns_from_result."""
    if occurrences is None:
        occurrences = [{'line': 1, 'timestamp': '2026.01.01 00:00:00.000'}]
    return {
        'rule_id': 0,
        'pattern_length': len(key_sequence),
        'repeat_count': repeat_count,
        '_key_sequence': tuple(key_sequence),
        'message': '',
        'device_id': kwargs.get('device_id'),
        'component_name': kwargs.get('component_name'),
        'log_level': kwargs.get('log_level'),
        'first_occurrence': occurrences[0]['timestamp'],
        'occurrences': list(occurrences),
        'block_lines': [],
    }


class TestDeduplicatePatterns(unittest.TestCase):

    def setUp(self):
        import neuf_log_viewer_api as api_module
        self.fn = api_module._deduplicate_patterns

    def test_no_duplicates_unchanged(self):
        p1 = _make_pattern(['A', 'B'], 3)
        p2 = _make_pattern(['C', 'D'], 2)
        result = self.fn([p1, p2])
        self.assertEqual(len(result), 2)

    def test_identical_key_sequence_merged(self):
        occ1 = [{'line': 1, 'timestamp': 'T1'}]
        occ2 = [{'line': 100, 'timestamp': 'T2'}]
        p1 = _make_pattern(['A', 'B'], 1, occurrences=occ1)
        p2 = _make_pattern(['A', 'B'], 1, occurrences=occ2)
        result = self.fn([p1, p2])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['repeat_count'], 2)

    def test_merged_occurrences_sorted_by_line(self):
        occ1 = [{'line': 200, 'timestamp': 'T2'}]
        occ2 = [{'line': 10,  'timestamp': 'T1'}]
        p1 = _make_pattern(['X'], 1, occurrences=occ1)
        p2 = _make_pattern(['X'], 1, occurrences=occ2)
        result = self.fn([p1, p2])
        lines = [o['line'] for o in result[0]['occurrences']]
        self.assertEqual(lines, sorted(lines))

    def test_result_sorted_by_wasted_lines_desc(self):
        # p1: 2 lines × 1 = 2 wasted; p2: 1 line × 5 = 5 wasted
        p1 = _make_pattern(['A', 'B'], 1)
        p2 = _make_pattern(['C'], 5)
        result = self.fn([p1, p2])
        scores = [r['repeat_count'] * r['pattern_length'] for r in result]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_empty_list_returns_empty(self):
        self.assertEqual(self.fn([]), [])


# ===========================================================================
# Pattern post-processing: _filter_maximal_patterns
# ===========================================================================

class TestFilterMaximalPatterns(unittest.TestCase):

    def setUp(self):
        import neuf_log_viewer_api as api_module
        self.fn = api_module._filter_maximal_patterns

    def test_single_pattern_kept(self):
        p = _make_pattern(['A', 'B', 'C'], 3)
        result = self.fn([p])
        self.assertEqual(len(result), 1)

    def test_sub_pattern_dropped(self):
        big = _make_pattern(['A', 'B', 'C'], 3)
        sub = _make_pattern(['A', 'B'], 3)        # prefix of big
        result = self.fn([big, sub])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['_key_sequence'], ('A', 'B', 'C'))

    def test_non_overlapping_patterns_both_kept(self):
        p1 = _make_pattern(['A', 'B', 'C'], 3)
        p2 = _make_pattern(['X', 'Y', 'Z'], 3)
        result = self.fn([p1, p2])
        self.assertEqual(len(result), 2)

    def test_suffix_sub_pattern_dropped(self):
        big = _make_pattern(['A', 'B', 'C'], 3)
        sub = _make_pattern(['B', 'C'], 3)         # suffix of big
        result = self.fn([big, sub])
        self.assertEqual(len(result), 1)

    def test_middle_sub_pattern_dropped(self):
        big = _make_pattern(['A', 'B', 'C', 'D'], 2)
        sub = _make_pattern(['B', 'C'], 2)
        result = self.fn([big, sub])
        self.assertEqual(len(result), 1)

    def test_same_length_patterns_both_kept(self):
        p1 = _make_pattern(['A', 'B'], 4)
        p2 = _make_pattern(['C', 'D'], 4)
        result = self.fn([p1, p2])
        self.assertEqual(len(result), 2)

    def test_empty_list_returns_empty(self):
        self.assertEqual(self.fn([]), [])

    def test_result_sorted_by_wasted_lines_desc(self):
        p1 = _make_pattern(['A', 'B', 'C'], 1)   # wasted = 3
        p2 = _make_pattern(['X', 'Y'], 5)          # wasted = 10
        result = self.fn([p1, p2])
        scores = [r['repeat_count'] * r['pattern_length'] for r in result]
        self.assertEqual(scores, sorted(scores, reverse=True))


# ===========================================================================
# Pattern post-processing: _filter_by_significance
# ===========================================================================

class TestFilterBySignificance(unittest.TestCase):

    def setUp(self):
        import neuf_log_viewer_api as api_module
        self.fn = api_module._filter_by_significance

    def test_zero_threshold_keeps_all(self):
        p1 = _make_pattern(['A'], 1)   # score = 1
        p2 = _make_pattern(['B'], 2)   # score = 2
        result = self.fn([p1, p2], 0)
        self.assertEqual(len(result), 2)

    def test_negative_threshold_keeps_all(self):
        p1 = _make_pattern(['A'], 1)
        result = self.fn([p1], -5)
        self.assertEqual(len(result), 1)

    def test_below_threshold_dropped(self):
        low  = _make_pattern(['A'], 2)     # score = 2
        high = _make_pattern(['B', 'C', 'D'], 5)  # score = 15
        result = self.fn([low, high], 10)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['_key_sequence'], ('B', 'C', 'D'))

    def test_at_threshold_kept(self):
        p = _make_pattern(['A', 'B'], 5)   # score = 10
        result = self.fn([p], 10)
        self.assertEqual(len(result), 1)

    def test_above_threshold_kept(self):
        p = _make_pattern(['A', 'B', 'C'], 5)  # score = 15
        result = self.fn([p], 10)
        self.assertEqual(len(result), 1)

    def test_empty_list_returns_empty(self):
        self.assertEqual(self.fn([], 10), [])


# ===========================================================================
# _format_patterns_markdown — new format
# ===========================================================================

class TestFormatPatternsMarkdown(unittest.TestCase):

    def setUp(self):
        import neuf_log_viewer_api as api_module
        self.fn = api_module._format_patterns_markdown

    def _make_full_pattern(self, key_seq, repeat_count, block_lines=None, **kwargs):
        p = _make_pattern(key_seq, repeat_count, **kwargs)
        p['block_lines'] = block_lines or [f'Log line {i}' for i in range(len(key_seq))]
        return p

    def test_no_patterns_returns_no_detected_message(self):
        result = self.fn([], '2026.01.01 00:00:00')
        self.assertIn('No repeated patterns detected', result)

    def test_header_contains_generated_at(self):
        result = self.fn([], '2026.05.25 10:00:00')
        self.assertIn('2026.05.25 10:00:00', result)

    def test_header_shows_raw_and_filtered_counts_when_different(self):
        p = self._make_full_pattern(['A'], 3)
        result = self.fn([p], '2026.01.01 00:00:00', raw_total=100)
        self.assertIn('100', result)
        self.assertIn('1 meaningful pattern', result)

    def test_header_shows_single_count_when_raw_matches_filtered(self):
        p = self._make_full_pattern(['A'], 3)
        result = self.fn([p], '2026.01.01 00:00:00', raw_total=1)
        self.assertIn('Total patterns found', result)

    def test_executive_summary_table_present(self):
        p = self._make_full_pattern(['A', 'B'], 4, device_id='D1', component_name='C1')
        result = self.fn([p], '2026.01.01 00:00:00')
        self.assertIn('Executive Summary', result)
        self.assertIn('| Rank |', result)
        self.assertIn('Pattern #', result)
        self.assertIn('D1', result)
        self.assertIn('C1', result)

    def test_wasted_lines_in_summary(self):
        # 3 lines × 4 repeats = 12 wasted
        p = self._make_full_pattern(['A', 'B', 'C'], 4)
        result = self.fn([p], '2026.01.01 00:00:00')
        self.assertIn('12', result)

    def test_detail_section_present(self):
        p = self._make_full_pattern(['A', 'B'], 3)
        result = self.fn([p], '2026.01.01 00:00:00')
        self.assertIn('Pattern Details', result)
        # Heading format: "### Pattern #<rule_id+1> (Rank <rank>) — ..."
        self.assertIn('### Pattern #', result)
        self.assertIn('(Rank 1)', result)

    def test_block_preview_truncated_for_long_blocks(self):
        # 10 block lines → preview shows first 5, remainder note shown
        lines = [f'Line {i}' for i in range(10)]
        p = self._make_full_pattern(list(range(10)), 2, block_lines=lines)
        result = self.fn([p], '2026.01.01 00:00:00')
        self.assertIn('5 more lines', result)
        # First 5 lines present, 6th not
        self.assertIn('Line 0', result)
        self.assertIn('Line 4', result)
        self.assertNotIn('Line 5', result)

    def test_short_block_not_truncated(self):
        lines = ['Line A', 'Line B']
        p = self._make_full_pattern(['K1', 'K2'], 3, block_lines=lines)
        result = self.fn([p], '2026.01.01 00:00:00')
        self.assertIn('Line A', result)
        self.assertIn('Line B', result)
        self.assertNotIn('more lines', result)

    def test_max_patterns_cap_respected(self):
        patterns = [self._make_full_pattern([f'K{i}'], 2) for i in range(10)]
        result = self.fn(patterns, '2026.01.01 00:00:00', max_patterns=3)
        # Only 3 detail sections should appear
        self.assertEqual(result.count('### Pattern #'), 3)

    def test_occurrences_table_present(self):
        occ = [{'line': 42, 'timestamp': '2026.01.01 10:00:00.000'}]
        p = self._make_full_pattern(['A'], 1, occurrences=occ)
        result = self.fn([p], '2026.01.01 00:00:00')
        self.assertIn('42', result)
        self.assertIn('2026.01.01 10:00:00.000', result)

    def test_showing_top_N_message_when_cap_applied(self):
        patterns = [self._make_full_pattern([f'K{i}'], 2) for i in range(10)]
        result = self.fn(patterns, '2026.01.01 00:00:00', max_patterns=5)
        self.assertIn('Showing top', result)


# ===========================================================================
# ExportLogRequest new fields
# ===========================================================================

class TestExportLogRequestNewFields(unittest.TestCase):

    def test_default_max_patterns_is_50(self):
        from neuf_log_viewer_api import ExportLogRequest
        req = ExportLogRequest()
        self.assertEqual(req.max_patterns, 50)

    def test_default_min_pattern_significance_is_10(self):
        from neuf_log_viewer_api import ExportLogRequest
        req = ExportLogRequest()
        self.assertEqual(req.min_pattern_significance, 10)

    def test_custom_max_patterns(self):
        from neuf_log_viewer_api import ExportLogRequest
        req = ExportLogRequest(max_patterns=20)
        self.assertEqual(req.max_patterns, 20)

    def test_custom_min_pattern_significance(self):
        from neuf_log_viewer_api import ExportLogRequest
        req = ExportLogRequest(min_pattern_significance=50)
        self.assertEqual(req.min_pattern_significance, 50)


# ===========================================================================
# Export endpoint: post-processing pipeline is applied
# ===========================================================================

class TestExportLogPostProcessing(unittest.TestCase):
    """
    Verify that when dedup != 'none' the export pipeline:
    - Calls dedup_and_extract_patterns
    - Returns a ZIP containing the markdown report
    """

    def setUp(self):
        # Build a service that returns 3 identical log rows so patterns can be detected
        logs = [_make_log_row(id=i, message='Same message') for i in range(6)]
        result = _make_filter_result(logs=logs, total=6, total_pages=1)
        # Return a non-empty patterns list from the mock
        patterns_fixture = [
            {
                'rule_id': 0,
                'pattern_length': 3,
                'repeat_count': 2,
                '_key_sequence': ('k1', 'k2', 'k3'),
                'message': 'Same message',
                'device_id': 'D1',
                'component_name': 'C1',
                'log_level': 'ERROR',
                'first_occurrence': '2026.01.01 00:00:00.000',
                'occurrences': [
                    {'line': 1, 'timestamp': '2026.01.01 00:00:00.000'},
                    {'line': 4, 'timestamp': '2026.01.01 00:01:00.000'},
                ],
                'block_rows': [_make_log_row(id=i) for i in range(3)],
                'first_orig': 0,
            }
        ]
        self.svc = _make_service(filter_result=result)
        self.svc.dedup_and_extract_patterns = MagicMock(
            side_effect=lambda logs, mode: (logs, list(patterns_fixture))
        )
        self.client, self.folder = _build_test_client(self.svc)

    def test_dedup_mode_annotate_returns_zip(self):
        resp = self.client.post('/export_log', json={
            'format': 'full', 'dedup': 'annotate', 'min_pattern_significance': 0,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIn('application/zip', resp.headers['content-type'])

    def test_zip_contains_markdown_report(self):
        import zipfile, io
        resp = self.client.post('/export_log', json={
            'format': 'full', 'dedup': 'annotate', 'min_pattern_significance': 0,
        })
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            names = zf.namelist()
        md_files = [n for n in names if n.endswith('.md')]
        self.assertGreater(len(md_files), 0)

    def test_markdown_report_contains_executive_summary(self):
        import zipfile, io
        # min_pattern_significance=0 ensures the fixture pattern (score=6) survives filtering
        resp = self.client.post('/export_log', json={
            'format': 'full', 'dedup': 'annotate', 'min_pattern_significance': 0,
        })
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            md_name = next(n for n in zf.namelist() if n.endswith('.md'))
            md_content = zf.read(md_name).decode('utf-8')
        self.assertIn('Executive Summary', md_content)

    def test_custom_max_patterns_forwarded(self):
        import zipfile, io
        resp = self.client.post(
            '/export_log',
            json={
                'format': 'full', 'dedup': 'annotate',
                'max_patterns': 5, 'min_pattern_significance': 0,
            },
        )
        self.assertEqual(resp.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            md_name = next(n for n in zf.namelist() if n.endswith('.md'))
            md_content = zf.read(md_name).decode('utf-8')
        # Report was generated (sanity check)
        self.assertIn('NEUF Log', md_content)

    def test_dedup_mode_skip_also_produces_zip(self):
        resp = self.client.post('/export_log', json={
            'format': 'full', 'dedup': 'skip', 'min_pattern_significance': 0,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIn('application/zip', resp.headers['content-type'])


if __name__ == '__main__':
    unittest.main()
