"""
Test Suite for Database Filter Module (Python port of test/database-filter.test.js)
Tests DatabaseService.execute_filter_step() with an in-memory SQLite database.
"""
import sys
import sqlite3
import calendar
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.database import DatabaseWrapper, DatabaseService
from src.log_parser import LogParserService, log_parser_service


def utc_ts(year, month, day, hour, minute, second):
    """Return Unix seconds for the given UTC datetime (month is 1-based)."""
    return int(calendar.timegm((year, month, day, hour, minute, second, 0, 0, 0)))


def get_time_bucket(ts):
    return log_parser_service.get_time_bucket(ts)


# ── Seed data mirrors SEED_LOGS from test/database-filter.test.js ─────────────
SEED_LOGS = [
    {'filename': 'app.log', 'timestamp': '2026.04.28 09:00:00.000', 'threadName': 'main', 'deviceId': 'DEV001', 'componentName': 'com.example', 'logLevel': 'ERROR', 'message': 'Connection failed'},
    {'filename': 'app.log', 'timestamp': '2026.04.28 09:01:00.000', 'threadName': 'main', 'deviceId': 'DEV001', 'componentName': 'com.example', 'logLevel': 'WARN',  'message': 'Retrying connection'},
    {'filename': 'app.log', 'timestamp': '2026.04.28 09:02:00.000', 'threadName': 'http', 'deviceId': 'DEV002', 'componentName': 'com.http',    'logLevel': 'INFO',  'message': 'Request received'},
    {'filename': 'app.log', 'timestamp': '2026.04.28 09:03:00.000', 'threadName': 'http', 'deviceId': 'DEV002', 'componentName': 'com.http',    'logLevel': 'ERROR', 'message': 'Request failed'},
    {'filename': 'sys.log', 'timestamp': '2026.04.28 10:00:00.000', 'threadName': 'sys',  'deviceId': 'DEV003', 'componentName': 'com.sys',     'logLevel': 'INFO',  'message': 'System startup'},
    {'filename': 'sys.log', 'timestamp': '2026.04.28 10:01:00.000', 'threadName': 'sys',  'deviceId': 'DEV003', 'componentName': 'com.sys',     'logLevel': 'DEBUG', 'message': 'Loaded config'},
]


def build_database_service(rows):
    """
    Build an in-memory DatabaseService seeded with the given rows.
    Equivalent to buildDatabaseService(SQL, rows) in the JS test.
    """
    conn = sqlite3.connect(':memory:')
    wrapper = DatabaseWrapper(conn)
    service = DatabaseService(wrapper)
    service.init_database()
    if rows:
        rows_with_bucket = [
            {**r, 'timeBucket': get_time_bucket(r['timestamp'])}
            for r in rows
        ]
        insert_stmt = service.prepare_insert()
        insert_many = service.create_batch_insert(insert_stmt)
        insert_many(rows_with_bucket)
    return service


# ============================================================================
# basic include filter
# ============================================================================
class TestExecuteFilterStepBasicInclude(unittest.TestCase):
    def test_log_level_include_error_keeps_only_error_rows(self):
        svc = build_database_service(SEED_LOGS)
        result = svc.execute_filter_step({'logLevelInclude': ['ERROR']}, 'logs', 'filter_step_1')
        self.assertEqual(result['count'], 2)

    def test_device_include_dev001_keeps_dev001_rows(self):
        svc = build_database_service(SEED_LOGS)
        result = svc.execute_filter_step({'deviceInclude': ['DEV001']}, 'logs', 'filter_step_1')
        self.assertEqual(result['count'], 2)

    def test_no_filters_keeps_all_rows(self):
        svc = build_database_service(SEED_LOGS)
        result = svc.execute_filter_step({}, 'logs', 'filter_step_1')
        self.assertEqual(result['count'], len(SEED_LOGS))


# ============================================================================
# exclude filter
# ============================================================================
class TestExecuteFilterStepExclude(unittest.TestCase):
    def test_log_level_exclude_debug_removes_debug_rows(self):
        svc = build_database_service(SEED_LOGS)
        result = svc.execute_filter_step({'logLevelExclude': ['DEBUG']}, 'logs', 'filter_step_1')
        self.assertEqual(result['count'], 5)

    def test_filename_exclude_sys_log_removes_sys_log_rows(self):
        svc = build_database_service(SEED_LOGS)
        result = svc.execute_filter_step({'filenameExclude': ['sys.log']}, 'logs', 'filter_step_1')
        self.assertEqual(result['count'], 4)


# ============================================================================
# chained steps (inputTable from previous step)
# ============================================================================
class TestExecuteFilterStepChained(unittest.TestCase):
    def test_step1_error_then_step2_dev001(self):
        svc = build_database_service(SEED_LOGS)
        step1 = svc.execute_filter_step({'logLevelInclude': ['ERROR']}, 'logs', 'filter_step_1')
        self.assertEqual(step1['count'], 2)
        step2 = svc.execute_filter_step({'deviceInclude': ['DEV001']}, 'filter_step_1', 'filter_step_2')
        self.assertEqual(step2['count'], 1)

    def test_three_chained_steps_filename_level_device(self):
        svc = build_database_service(SEED_LOGS)
        svc.execute_filter_step({'filenameInclude': ['app.log']}, 'logs', 'filter_step_1')
        svc.execute_filter_step({'logLevelInclude': ['ERROR']}, 'filter_step_1', 'filter_step_2')
        step3 = svc.execute_filter_step({'deviceInclude': ['DEV002']}, 'filter_step_2', 'filter_step_3')
        self.assertEqual(step3['count'], 1)

    def test_output_table_recreated_when_same_name_reused(self):
        svc = build_database_service(SEED_LOGS)
        svc.execute_filter_step({'logLevelInclude': ['ERROR']}, 'logs', 'filter_step_1')
        result = svc.execute_filter_step({'logLevelInclude': ['INFO']}, 'logs', 'filter_step_1')
        self.assertEqual(result['count'], 2)


# ============================================================================
# search filter
# ============================================================================
class TestExecuteFilterStepSearch(unittest.TestCase):
    def test_search_connection_keeps_matching_rows(self):
        svc = build_database_service(SEED_LOGS)
        result = svc.execute_filter_step({'search': 'Connection'}, 'logs', 'filter_step_1')
        self.assertEqual(result['count'], 2)

    def test_step1_error_then_step2_search_failed(self):
        svc = build_database_service(SEED_LOGS)
        svc.execute_filter_step({'logLevelInclude': ['ERROR']}, 'logs', 'filter_step_1')
        step2 = svc.execute_filter_step({'search': 'failed'}, 'filter_step_1', 'filter_step_2')
        self.assertEqual(step2['count'], 2)


# ============================================================================
# empty result
# ============================================================================
class TestExecuteFilterStepEmptyResult(unittest.TestCase):
    def test_impossible_filter_produces_empty_output(self):
        svc = build_database_service(SEED_LOGS)
        result = svc.execute_filter_step({'deviceInclude': ['DEV_NONEXISTENT']}, 'logs', 'filter_step_1')
        self.assertEqual(result['count'], 0)

    def test_step_chained_from_empty_table_produces_empty_output(self):
        svc = build_database_service(SEED_LOGS)
        svc.execute_filter_step({'deviceInclude': ['NONE']}, 'logs', 'filter_step_1')
        result = svc.execute_filter_step({}, 'filter_step_1', 'filter_step_2')
        self.assertEqual(result['count'], 0)


# ============================================================================
# contextLines
# ============================================================================
class TestExecuteFilterStepContextLines(unittest.TestCase):
    def test_context_lines_1_includes_1_row_before_and_after_each_match(self):
        svc = build_database_service(SEED_LOGS)
        result = svc.execute_filter_step(
            {'search': 'Connection', 'contextLines': 1},
            'logs', 'filter_step_1'
        )
        self.assertEqual(result['count'], 4)

    def test_context_lines_0_behaves_same_as_plain_search(self):
        svc = build_database_service(SEED_LOGS)
        result = svc.execute_filter_step(
            {'search': 'Connection', 'contextLines': 0},
            'logs', 'filter_step_1'
        )
        self.assertEqual(result['count'], 2)

    def test_context_lines_2_matches_at_ids_10_and_17_produce_15_rows(self):
        rows = [
            {
                'filename': 'app.log',
                'timestamp': f'2026.04.28 09:{str(i).zfill(2)}:00.000',
                'threadName': 'main',
                'deviceId': 'DEV001',
                'componentName': 'com.example',
                'logLevel': 'INFO',
                'message': 'TARGET message' if i in (9, 16) else f'Normal message {i}'
            }
            for i in range(20)
        ]
        svc = build_database_service(rows)
        result = svc.execute_filter_step(
            {'search': 'TARGET', 'contextLines': 2},
            'logs', 'filter_step_1'
        )
        self.assertEqual(result['count'], 15)

    def test_context_lines_2_overlapping_ranges_deduplicate_correctly(self):
        rows = [
            {
                'filename': 'app.log',
                'timestamp': f'2026.04.28 09:{str(i).zfill(2)}:00.000',
                'threadName': 'main',
                'deviceId': 'DEV001',
                'componentName': 'com.example',
                'logLevel': 'INFO',
                'message': 'TARGET message' if i in (9, 11) else f'Normal message {i}'
            }
            for i in range(20)
        ]
        svc = build_database_service(rows)
        result = svc.execute_filter_step(
            {'search': 'TARGET', 'contextLines': 2},
            'logs', 'filter_step_1'
        )
        self.assertEqual(result['count'], 11)

    def test_context_lines_with_other_filters(self):
        svc = build_database_service(SEED_LOGS)
        result = svc.execute_filter_step(
            {'filenameInclude': ['app.log'], 'search': 'failed', 'contextLines': 1},
            'logs', 'filter_step_1'
        )
        self.assertEqual(result['count'], 5)


# ============================================================================
# regex search
# ============================================================================
class TestExecuteFilterStepRegex(unittest.TestCase):
    def test_search_regex_basic_pattern(self):
        svc = build_database_service(SEED_LOGS)
        result = svc.execute_filter_step(
            {'search': 'conn.*failed', 'searchRegex': True},
            'logs', 'filter_step_1'
        )
        self.assertEqual(result['count'], 1)

    def test_search_regex_alternation_pattern(self):
        svc = build_database_service(SEED_LOGS)
        result = svc.execute_filter_step(
            {'search': 'Connection failed|startup', 'searchRegex': True},
            'logs', 'filter_step_1'
        )
        self.assertEqual(result['count'], 2)

    def test_search_regex_case_insensitive_by_default(self):
        svc = build_database_service(SEED_LOGS)
        result = svc.execute_filter_step(
            {'search': 'CONNECTION FAILED', 'searchRegex': True},
            'logs', 'filter_step_1'
        )
        self.assertEqual(result['count'], 1)

    def test_search_regex_anchor_matches_start_of_message(self):
        svc = build_database_service(SEED_LOGS)
        result = svc.execute_filter_step(
            {'search': '^System', 'searchRegex': True},
            'logs', 'filter_step_1'
        )
        self.assertEqual(result['count'], 1)

    def test_search_regex_invalid_pattern_returns_0_without_throwing(self):
        svc = build_database_service(SEED_LOGS)
        result = svc.execute_filter_step(
            {'search': '[invalid(regex', 'searchRegex': True},
            'logs', 'filter_step_1'
        )
        self.assertEqual(result['count'], 0)

    def test_search_regex_false_falls_back_to_like_search(self):
        svc = build_database_service(SEED_LOGS)
        result = svc.execute_filter_step(
            {'search': 'Connection', 'searchRegex': False},
            'logs', 'filter_step_1'
        )
        self.assertEqual(result['count'], 2)


# ============================================================================
# time range (timeFrom / timeTo)
# ============================================================================
class TestExecuteFilterStepTimeRange(unittest.TestCase):
    def test_time_from_filters_out_earlier_rows(self):
        svc = build_database_service(SEED_LOGS)
        result = svc.execute_filter_step(
            {'timeFrom': get_time_bucket('2026.04.28 09:02:00.000')},
            'logs', 'filter_step_1'
        )
        self.assertEqual(result['count'], 4)

    def test_time_to_filters_out_later_rows(self):
        svc = build_database_service(SEED_LOGS)
        result = svc.execute_filter_step(
            {'timeTo': get_time_bucket('2026.04.28 09:01:00.000')},
            'logs', 'filter_step_1'
        )
        self.assertEqual(result['count'], 2)

    def test_time_from_and_time_to_keeps_only_rows_in_range(self):
        svc = build_database_service(SEED_LOGS)
        result = svc.execute_filter_step(
            {
                'timeFrom': get_time_bucket('2026.04.28 09:01:00.000'),
                'timeTo':   get_time_bucket('2026.04.28 09:03:00.000'),
            },
            'logs', 'filter_step_1'
        )
        self.assertEqual(result['count'], 3)

    def test_time_range_with_no_matching_rows_returns_0(self):
        svc = build_database_service(SEED_LOGS)
        result = svc.execute_filter_step(
            {
                'timeFrom': get_time_bucket('2026.04.28 11:00:00.000'),
                'timeTo':   get_time_bucket('2026.04.28 11:59:00.000'),
            },
            'logs', 'filter_step_1'
        )
        self.assertEqual(result['count'], 0)

    def test_time_range_combined_with_log_level_include_narrows_correctly(self):
        svc = build_database_service(SEED_LOGS)
        result = svc.execute_filter_step(
            {
                'timeFrom': get_time_bucket('2026.04.28 09:00:00.000'),
                'timeTo':   get_time_bucket('2026.04.28 09:03:00.000'),
                'logLevelInclude': ['ERROR'],
            },
            'logs', 'filter_step_1'
        )
        self.assertEqual(result['count'], 2)

    def test_time_from_as_string_filters_correctly(self):
        svc = build_database_service(SEED_LOGS)
        result = svc.execute_filter_step(
            {'timeFrom': '2026.04.28 09:02:00.000'},
            'logs', 'filter_step_1'
        )
        self.assertEqual(result['count'], 4)

    def test_time_to_as_string_filters_correctly(self):
        svc = build_database_service(SEED_LOGS)
        result = svc.execute_filter_step(
            {'timeTo': '2026.04.28 09:01:00.000'},
            'logs', 'filter_step_1'
        )
        self.assertEqual(result['count'], 2)

    def test_time_from_and_time_to_as_strings_work_together(self):
        svc = build_database_service(SEED_LOGS)
        result = svc.execute_filter_step(
            {
                'timeFrom': '2026.04.28 09:01:00.000',
                'timeTo':   '2026.04.28 09:03:00.000',
            },
            'logs', 'filter_step_1'
        )
        self.assertEqual(result['count'], 3)


if __name__ == '__main__':
    unittest.main()
