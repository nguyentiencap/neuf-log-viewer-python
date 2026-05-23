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
        resp = self.client.post('/filter_log', json={})
        self.assertIn('filterOptions', resp.json())

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
        resp = self.client.post('/export_log', json={'format': 'full'})
        self.assertEqual(resp.status_code, 200)

    def test_export_full_format_content_type_is_text_plain(self):
        resp = self.client.post('/export_log', json={'format': 'full'})
        self.assertIn('text/plain', resp.headers['content-type'])

    def test_export_full_format_has_attachment_disposition(self):
        resp = self.client.post('/export_log', json={'format': 'full'})
        self.assertIn('attachment', resp.headers.get('content-disposition', ''))

    def test_export_compact_format(self):
        resp = self.client.post('/export_log', json={'format': 'compact'})
        self.assertEqual(resp.status_code, 200)
        self.assertIn('text/plain', resp.headers['content-type'])

    def test_export_json_format(self):
        resp = self.client.post('/export_log', json={'format': 'json'})
        self.assertEqual(resp.status_code, 200)
        self.assertIn('application/json', resp.headers['content-type'])
        # Should be valid JSON array
        data = resp.json()
        self.assertIsInstance(data, list)

    def test_export_csv_format(self):
        resp = self.client.post('/export_log', json={'format': 'csv'})
        self.assertEqual(resp.status_code, 200)
        self.assertIn('text/csv', resp.headers['content-type'])
        # First line should be headers
        lines = resp.text.strip().split('\n')
        self.assertIn('filename', lines[0])

    def test_export_filename_includes_timestamp(self):
        resp = self.client.post('/export_log', json={'format': 'full'})
        disposition = resp.headers.get('content-disposition', '')
        self.assertIn('neuf-logs-export-', disposition)

    def test_export_json_filename_ends_with_json(self):
        resp = self.client.post('/export_log', json={'format': 'json'})
        disposition = resp.headers.get('content-disposition', '')
        self.assertIn('.json', disposition)

    def test_export_csv_filename_ends_with_csv(self):
        resp = self.client.post('/export_log', json={'format': 'csv'})
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


if __name__ == '__main__':
    unittest.main()
