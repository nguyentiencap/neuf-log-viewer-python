"""
Tests for neuf_log_viewer_cli.py (Python port of neuf-log-viewer-cli.js).

TDD: these tests were written before the CLI implementation.
They define the complete expected behaviour of the CLI.

Mirrors: neuf-log-viewer-cli.js test coverage
"""

import asyncio
import io
import os
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# Bootstrap: ensure python-port root is importable
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_PYTHON_PORT = os.path.dirname(_HERE)
if _PYTHON_PORT not in sys.path:
    sys.path.insert(0, _PYTHON_PORT)

from neuf_log_viewer_cli import (
    parse_args,
    build_filters,
    expand_comma_separated,
    is_valid_timestamp,
    validate_options,
    format_text,
    format_compact,
    levenshtein_distance,
    suggest_option_name,
)


# ---------------------------------------------------------------------------
# Helper: run a coroutine synchronously inside a test
# ---------------------------------------------------------------------------
def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ===========================================================================
# parse_args
# ===========================================================================
class TestParseArgs(unittest.TestCase):

    def test_returns_command_folder_and_options(self):
        result = parse_args(['cli', 'filter', '/logs/folder'])
        self.assertEqual(result['command'], 'filter')
        self.assertEqual(result['folder'], '/logs/folder')
        self.assertEqual(result['options'], {})

    def test_parses_string_option(self):
        result = parse_args(['cli', 'filter', '/logs', '--search', 'Error'])
        self.assertEqual(result['options']['search'], 'Error')

    def test_accumulates_repeated_option_into_list(self):
        result = parse_args(['cli', 'filter', '/logs', '--device', 'd1', '--device', 'd2'])
        self.assertEqual(result['options']['device'], ['d1', 'd2'])

    def test_boolean_flag_without_value(self):
        result = parse_args(['cli', 'filter', '/logs', '--help'])
        self.assertTrue(result['options']['help'])

    def test_defaults_to_help_when_no_command(self):
        result = parse_args(['cli'])
        self.assertEqual(result['command'], 'help')

    def test_folder_is_none_when_second_arg_is_option(self):
        result = parse_args(['cli', 'filter', '--help'])
        self.assertIsNone(result['folder'])

    def test_parses_multiple_different_options(self):
        result = parse_args([
            'cli', 'filter', '/logs',
            '--level', 'ERROR',
            '--search', 'exception',
            '--page', '2',
            '--page-size', '50',
        ])
        opts = result['options']
        self.assertEqual(opts['level'], 'ERROR')
        self.assertEqual(opts['search'], 'exception')
        self.assertEqual(opts['page'], '2')
        self.assertEqual(opts['page-size'], '50')

    def test_presets_command(self):
        result = parse_args(['cli', 'presets', '/logs'])
        self.assertEqual(result['command'], 'presets')
        self.assertEqual(result['folder'], '/logs')


# ===========================================================================
# expand_comma_separated
# ===========================================================================
class TestExpandCommaSeparated(unittest.TestCase):

    def test_splits_single_string_by_comma(self):
        self.assertEqual(expand_comma_separated('a,b,c'), ['a', 'b', 'c'])

    def test_returns_list_unchanged_if_no_comma(self):
        self.assertEqual(expand_comma_separated('device1'), ['device1'])

    def test_flattens_list_of_comma_strings(self):
        self.assertEqual(
            expand_comma_separated(['p1,p2', 'p3']),
            ['p1', 'p2', 'p3']
        )

    def test_returns_empty_list_for_none(self):
        self.assertEqual(expand_comma_separated(None), [])

    def test_strips_whitespace_around_values(self):
        self.assertEqual(expand_comma_separated('a , b , c'), ['a', 'b', 'c'])

    def test_filters_empty_strings(self):
        self.assertEqual(expand_comma_separated('a,,b'), ['a', 'b'])


# ===========================================================================
# build_filters
# ===========================================================================
class TestBuildFilters(unittest.TestCase):

    def test_empty_options_return_empty_filters(self):
        self.assertEqual(build_filters({}), {})

    def test_device_becomes_device_include(self):
        filters = build_filters({'device': 'dev1'})
        self.assertEqual(filters['deviceInclude'], ['dev1'])

    def test_level_becomes_log_level_include_uppercased(self):
        filters = build_filters({'level': 'error'})
        self.assertEqual(filters['logLevelInclude'], ['ERROR'])

    def test_component_becomes_component_include(self):
        filters = build_filters({'component': 'com.example'})
        self.assertEqual(filters['componentInclude'], ['com.example'])

    def test_exclude_component_becomes_component_exclude(self):
        filters = build_filters({'exclude-component': 'com.noise'})
        self.assertEqual(filters['componentExclude'], ['com.noise'])

    def test_search_is_preserved(self):
        filters = build_filters({'search': 'Exception'})
        self.assertEqual(filters['search'], 'Exception')

    def test_time_from_and_time_to_are_preserved(self):
        filters = build_filters({'time-from': '2026.01.01 00:00:00', 'time-to': '2026.12.31 23:59:59'})
        self.assertEqual(filters['timeFrom'], '2026.01.01 00:00:00')
        self.assertEqual(filters['timeTo'], '2026.12.31 23:59:59')

    def test_context_is_parsed_to_int(self):
        filters = build_filters({'context': '5'})
        self.assertEqual(filters['contextLines'], 5)

    def test_preset_is_expanded_as_list(self):
        filters = build_filters({'preset': 'p1,p2'})
        self.assertEqual(filters['preset'], ['p1', 'p2'])

    def test_comma_separated_device_is_expanded(self):
        filters = build_filters({'device': 'd1,d2,d3'})
        self.assertEqual(filters['deviceInclude'], ['d1', 'd2', 'd3'])

    def test_repeated_level_is_combined(self):
        filters = build_filters({'level': ['ERROR', 'WARN']})
        self.assertIn('ERROR', filters['logLevelInclude'])
        self.assertIn('WARN', filters['logLevelInclude'])


# ===========================================================================
# is_valid_timestamp
# ===========================================================================
class TestIsValidTimestamp(unittest.TestCase):

    def test_valid_format(self):
        self.assertTrue(is_valid_timestamp('2026.05.08 10:30:00'))

    def test_invalid_separator(self):
        self.assertFalse(is_valid_timestamp('2026-05-08 10:30:00'))

    def test_missing_seconds(self):
        self.assertFalse(is_valid_timestamp('2026.05.08 10:30'))

    def test_none_is_invalid(self):
        self.assertFalse(is_valid_timestamp(None))

    def test_empty_string_is_invalid(self):
        self.assertFalse(is_valid_timestamp(''))

    def test_timestamp_with_milliseconds_is_invalid(self):
        # CLI only accepts second-precision timestamps
        self.assertFalse(is_valid_timestamp('2026.05.08 10:30:00.123'))


# ===========================================================================
# levenshtein_distance / suggest_option_name
# ===========================================================================
class TestLevenshteinDistance(unittest.TestCase):

    def test_identical_strings_return_zero(self):
        self.assertEqual(levenshtein_distance('search', 'search'), 0)

    def test_single_substitution(self):
        self.assertEqual(levenshtein_distance('search', 'serach'), 2)

    def test_completely_different_strings(self):
        self.assertGreater(levenshtein_distance('abc', 'xyz'), 0)


class TestSuggestOptionName(unittest.TestCase):

    def test_suggests_search_for_serach(self):
        self.assertEqual(suggest_option_name('searh'), 'search')

    def test_suggests_device_for_deviec(self):
        self.assertEqual(suggest_option_name('devce'), 'device')

    def test_returns_none_for_completely_unknown_option(self):
        self.assertIsNone(suggest_option_name('zzzzzzzzz'))


# ===========================================================================
# validate_options
# ===========================================================================
class TestValidateOptions(unittest.TestCase):

    def test_valid_options_do_not_raise(self):
        # Should not raise SystemExit
        try:
            validate_options('filter', {'level': 'ERROR', 'format': 'text', 'page': '1', 'page-size': '100'})
        except SystemExit:
            self.fail("validate_options raised SystemExit for valid options")

    def test_unknown_option_writes_to_stderr_and_exits(self):
        with self.assertRaises(SystemExit) as ctx:
            with patch('sys.stderr', new_callable=io.StringIO) as mock_err:
                validate_options('filter', {'unknownflag': 'value'})
        self.assertNotEqual(ctx.exception.code, 0)

    def test_invalid_log_level_exits(self):
        with self.assertRaises(SystemExit):
            validate_options('filter', {'level': 'VERBOSE'})

    def test_invalid_format_exits(self):
        with self.assertRaises(SystemExit):
            validate_options('filter', {'format': 'xml'})

    def test_invalid_timestamp_time_from_exits(self):
        with self.assertRaises(SystemExit):
            validate_options('filter', {'time-from': '2026-05-08 10:30:00'})

    def test_invalid_page_exits(self):
        with self.assertRaises(SystemExit):
            validate_options('filter', {'page': 'abc'})

    def test_invalid_page_size_exits(self):
        with self.assertRaises(SystemExit):
            validate_options('filter', {'page-size': '-1'})

    def test_invalid_context_exits(self):
        with self.assertRaises(SystemExit):
            validate_options('filter', {'context': 'abc'})


# ===========================================================================
# format_text / format_compact
# ===========================================================================
class TestFormatText(unittest.TestCase):

    def _make_log(self, **kwargs):
        base = {
            'filename': 'NEUF-test.log',
            'timestamp': '2026.04.08 10:00:00.000',
            'log_level': 'INFO',
            'thread_name': 'main',
            'device_id': 'Device1',
            'component_name': 'com.example',
            'message': 'Test message',
        }
        base.update(kwargs)
        return base

    def test_includes_all_fields(self):
        log = self._make_log()
        line = format_text(log)
        self.assertIn('[INFO]', line)
        self.assertIn('<Device1>', line)
        self.assertIn('(com.example)', line)
        self.assertIn('Test message', line)
        self.assertIn('NEUF-test.log', line)

    def test_no_device_id(self):
        log = self._make_log(device_id=None)
        line = format_text(log)
        self.assertNotIn('<', line)

    def test_no_component_name(self):
        log = self._make_log(component_name=None)
        line = format_text(log)
        self.assertNotIn('(', line)


class TestFormatCompact(unittest.TestCase):

    def _make_log(self, **kwargs):
        base = {
            'filename': 'NEUF-test.log',
            'timestamp': '2026.04.08 10:00:00.000',
            'log_level': 'ERROR',
            'thread_name': 'main',
            'device_id': 'Device1',
            'component_name': 'com.example',
            'message': 'Compact message',
        }
        base.update(kwargs)
        return base

    def test_includes_timestamp_level_component_message(self):
        log = self._make_log()
        line = format_compact(log)
        self.assertIn('[ERROR]', line)
        self.assertIn('(com.example)', line)
        self.assertIn('Compact message', line)

    def test_does_not_include_device_or_thread(self):
        log = self._make_log()
        line = format_compact(log)
        self.assertNotIn('<Device1>', line)
        self.assertNotIn('main', line)


# ===========================================================================
# Integration: cmd_presets and cmd_filter via mocked NEUFLogService
# ===========================================================================
class TestCmdPresets(unittest.IsolatedAsyncioTestCase):
    """Test cmdPresets command with mocked service."""

    async def test_outputs_presets_to_stdout(self):
        from neuf_log_viewer_cli import cmd_presets

        mock_service = MagicMock()
        mock_service.is_database_scanned.return_value = True
        mock_service.initialize = AsyncMock()
        mock_service.get_preset_suggestions = AsyncMock(return_value={
            'success': True,
            'suggestions': [
                {'id': 'preset_1', 'label': 'Preset One', 'description': 'Preset One'},
                {'id': 'preset_2', 'label': 'Preset Two', 'description': 'Different description'},
            ]
        })

        out = io.StringIO()
        with patch('sys.stdout', out):
            await cmd_presets('/fake/folder', {}, mock_service)

        output = out.getvalue()
        self.assertIn('preset_1', output)
        self.assertIn('Preset One', output)
        self.assertIn('preset_2', output)

    async def test_outputs_no_presets_message_when_empty(self):
        from neuf_log_viewer_cli import cmd_presets

        mock_service = MagicMock()
        mock_service.is_database_scanned.return_value = True
        mock_service.initialize = AsyncMock()
        mock_service.get_preset_suggestions = AsyncMock(return_value={
            'success': True,
            'suggestions': []
        })

        out = io.StringIO()
        with patch('sys.stdout', out):
            await cmd_presets('/fake/folder', {}, mock_service)

        self.assertIn('No presets', out.getvalue())


class TestCmdFilter(unittest.IsolatedAsyncioTestCase):
    """Test cmd_filter command with mocked service."""

    def _make_service(self, logs=None, total=None):
        if logs is None:
            logs = [
                {
                    'id': 1,
                    'filename': 'NEUF-test.log',
                    'timestamp': '2026.04.08 10:00:00.000',
                    'log_level': 'ERROR',
                    'thread_name': 'main',
                    'device_id': 'Dev1',
                    'component_name': 'com.example',
                    'message': 'Test error message',
                }
            ]
        if total is None:
            total = len(logs)

        mock_service = MagicMock()
        mock_service.is_database_scanned.return_value = True
        mock_service.initialize = AsyncMock()
        mock_service.normalize_filters = MagicMock(side_effect=lambda f: f)
        mock_service.apply_preset = AsyncMock()
        mock_service.filter_logs = AsyncMock(return_value={
            'success': True,
            'logs': logs,
            'total': total,
            'page': 1,
            'pageSize': 200,
            'totalPages': 1,
            'outputTable': 'filter_abc',
        })
        return mock_service

    async def test_outputs_text_format_by_default(self):
        from neuf_log_viewer_cli import cmd_filter

        svc = self._make_service()
        out = io.StringIO()
        with patch('sys.stdout', out):
            await cmd_filter('/fake/folder', {}, svc)

        output = out.getvalue()
        self.assertIn('[ERROR]', output)
        self.assertIn('Test error message', output)

    async def test_outputs_json_format(self):
        from neuf_log_viewer_cli import cmd_filter
        import json

        svc = self._make_service()
        out = io.StringIO()
        with patch('sys.stdout', out):
            await cmd_filter('/fake/folder', {'format': 'json'}, svc)

        parsed = json.loads(out.getvalue())
        self.assertIn('logs', parsed)
        self.assertEqual(len(parsed['logs']), 1)
        self.assertEqual(parsed['logs'][0]['log_level'], 'ERROR')

    async def test_outputs_compact_format(self):
        from neuf_log_viewer_cli import cmd_filter

        svc = self._make_service()
        out = io.StringIO()
        with patch('sys.stdout', out):
            await cmd_filter('/fake/folder', {'format': 'compact'}, svc)

        output = out.getvalue()
        self.assertIn('[ERROR]', output)
        # compact does NOT include thread/device
        self.assertNotIn('<Dev1>', output)

    async def test_pagination_info_printed(self):
        from neuf_log_viewer_cli import cmd_filter

        logs = [
            {
                'id': i,
                'filename': 'NEUF.log',
                'timestamp': '2026.04.08 10:00:00.000',
                'log_level': 'INFO',
                'thread_name': 'main',
                'device_id': None,
                'component_name': None,
                'message': f'Message {i}',
            }
            for i in range(5)
        ]
        mock_service = MagicMock()
        mock_service.is_database_scanned.return_value = True
        mock_service.initialize = AsyncMock()
        mock_service.normalize_filters = MagicMock(side_effect=lambda f: f)
        mock_service.apply_preset = AsyncMock()
        mock_service.filter_logs = AsyncMock(return_value={
            'success': True,
            'logs': logs,
            'total': 10,  # more than one page
            'page': 1,
            'pageSize': 5,
            'totalPages': 2,
            'outputTable': 'filter_xyz',
        })

        out = io.StringIO()
        with patch('sys.stdout', out):
            await cmd_filter('/fake/folder', {'page-size': '5'}, mock_service)

        self.assertIn('Page 1/2', out.getvalue())


class TestEnsureDatabase(unittest.IsolatedAsyncioTestCase):
    """Test ensure_database scans when DB doesn't exist."""

    async def test_scans_when_not_yet_indexed(self):
        from neuf_log_viewer_cli import ensure_database

        mock_service = MagicMock()
        mock_service.is_database_scanned.return_value = False
        mock_service.scan_logs = AsyncMock(return_value={
            'success': True,
            'data': {'totalLogs': 100, 'filesScanned': 2}
        })

        err = io.StringIO()
        with patch('sys.stderr', err):
            await ensure_database('/fake/folder', mock_service)

        mock_service.scan_logs.assert_called_once_with('/fake/folder')
        self.assertIn('Indexed', err.getvalue())

    async def test_skips_scan_when_already_indexed(self):
        from neuf_log_viewer_cli import ensure_database

        mock_service = MagicMock()
        mock_service.is_database_scanned.return_value = True
        mock_service.scan_logs = AsyncMock()

        await ensure_database('/fake/folder', mock_service)
        mock_service.scan_logs.assert_not_called()


if __name__ == '__main__':
    unittest.main()
