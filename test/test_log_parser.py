"""
Test Suite for Log Parser Module (Python port of test/log-parser.test.js)
Tests all methods of LogParserService.
"""
import sys
import calendar
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.log_parser import LogParserService

parser = LogParserService()


def utc_ts(year, month, day, hour, minute, second):
    """Return Unix seconds for the given UTC datetime (month is 1-based)."""
    return int(calendar.timegm((year, month, day, hour, minute, second, 0, 0, 0)))


# ============================================================================
# normalizeComponentName
# ============================================================================
class TestNormalizeComponentName(unittest.TestCase):
    def test_full_package_path(self):
        self.assertEqual(parser.normalize_component_name('com.example.package.ClassName'), 'com.example.package')

    def test_simple_class_name_without_package(self):
        self.assertEqual(parser.normalize_component_name('ClassName'), 'ClassName')

    def test_java_colon_format(self):
        self.assertEqual(parser.normalize_component_name('java:133'), 'java:133')

    def test_single_level_package(self):
        self.assertEqual(parser.normalize_component_name('com.ClassName'), 'com')

    def test_deep_package_path(self):
        self.assertEqual(
            parser.normalize_component_name('com.nuance.docimg.dws.core.impl.DeviceManager'),
            'com.nuance.docimg.dws.core.impl'
        )

    def test_null_input(self):
        self.assertIsNone(parser.normalize_component_name(None))

    def test_empty_string(self):
        self.assertIsNone(parser.normalize_component_name(''))

    def test_dot_at_start(self):
        self.assertEqual(parser.normalize_component_name('.ClassName'), '.ClassName')

    def test_historical_session_manager_java_format(self):
        self.assertEqual(
            parser.normalize_component_name('HistoricalSessionManager.java:273'),
            'HistoricalSessionManager'
        )


# ============================================================================
# normalizeThreadName
# ============================================================================
class TestNormalizeThreadName(unittest.TestCase):
    def test_thread_with_number(self):
        self.assertEqual(parser.normalize_thread_name('Thread-123'), 'Thread')

    def test_thread_with_multiple_dashes(self):
        self.assertEqual(parser.normalize_thread_name('Worker-Thread-456'), 'Worker-Thread')

    def test_thread_without_number(self):
        self.assertEqual(parser.normalize_thread_name('MainThread'), 'MainThread')

    def test_null_input(self):
        self.assertEqual(parser.normalize_thread_name(None), 'unknown')

    def test_empty_string(self):
        self.assertEqual(parser.normalize_thread_name(''), 'unknown')


# ============================================================================
# getTimeBucket
# ============================================================================
class TestGetTimeBucket(unittest.TestCase):
    def test_first_half_hour(self):
        expected = utc_ts(2026, 4, 8, 14, 15, 30)
        self.assertEqual(parser.get_time_bucket('2026.04.08 14:15:30.123'), expected)

    def test_second_half_hour(self):
        expected = utc_ts(2026, 4, 8, 14, 45, 30)
        self.assertEqual(parser.get_time_bucket('2026.04.08 14:45:30.123'), expected)

    def test_exactly_00_minutes(self):
        expected = utc_ts(2026, 4, 8, 14, 0, 0)
        self.assertEqual(parser.get_time_bucket('2026.04.08 14:00:00.000'), expected)

    def test_exactly_30_minutes(self):
        expected = utc_ts(2026, 4, 8, 14, 30, 0)
        self.assertEqual(parser.get_time_bucket('2026.04.08 14:30:00.000'), expected)

    def test_minute_29_boundary(self):
        expected = utc_ts(2026, 4, 8, 14, 29, 59)
        self.assertEqual(parser.get_time_bucket('2026.04.08 14:29:59.999'), expected)

    def test_minute_59_boundary(self):
        expected = utc_ts(2026, 4, 8, 14, 59, 59)
        self.assertEqual(parser.get_time_bucket('2026.04.08 14:59:59.999'), expected)

    def test_invalid_timestamp_format(self):
        self.assertIsNone(parser.get_time_bucket('invalid-timestamp'))

    def test_null_input(self):
        self.assertIsNone(parser.get_time_bucket(None))


# ============================================================================
# formatLogEntry
# ============================================================================
class TestFormatLogEntry(unittest.TestCase):
    def test_complete_log_object(self):
        log = {
            'filename': 'test.log',
            'timestamp': '2026.04.08 14:30:45.123',
            'log_level': 'INFO',
            'thread_name': 'Thread-1',
            'device_id': 'Device123',
            'component_name': 'com.example.Component',
            'message': 'Test message'
        }
        result = parser.format_log_entry(log)
        self.assertEqual(
            result['formattedLog'],
            '(test.log) 2026.04.08 14:30:45.123 [INFO] Thread-1: <Device123> (com.example.Component) Test message'
        )

    def test_log_object_without_device_id(self):
        log = {
            'filename': 'test.log',
            'timestamp': '2026.04.08 14:30:45.123',
            'log_level': 'INFO',
            'thread_name': 'Thread-1',
            'device_id': None,
            'component_name': 'com.example.Component',
            'message': 'Test message'
        }
        result = parser.format_log_entry(log)
        self.assertEqual(
            result['formattedLog'],
            '(test.log) 2026.04.08 14:30:45.123 [INFO] Thread-1: (com.example.Component) Test message'
        )

    def test_log_object_without_component_name(self):
        log = {
            'filename': 'test.log',
            'timestamp': '2026.04.08 14:30:45.123',
            'log_level': 'INFO',
            'thread_name': 'Thread-1',
            'device_id': 'Device123',
            'component_name': None,
            'message': 'Test message'
        }
        result = parser.format_log_entry(log)
        self.assertEqual(
            result['formattedLog'],
            '(test.log) 2026.04.08 14:30:45.123 [INFO] Thread-1: <Device123> Test message'
        )

    def test_minimal_log_object(self):
        log = {
            'filename': 'test.log',
            'timestamp': '2026.04.08 14:30:45.123',
            'log_level': 'INFO',
            'thread_name': 'Thread-1',
            'device_id': None,
            'component_name': None,
            'message': 'Test message'
        }
        result = parser.format_log_entry(log)
        self.assertEqual(
            result['formattedLog'],
            '(test.log) 2026.04.08 14:30:45.123 [INFO] Thread-1: Test message'
        )


# ============================================================================
# detectLogLineStart
# ============================================================================
class TestDetectLogLineStart(unittest.TestCase):
    def test_valid_log_line_returns_timestamp_and_time_bucket(self):
        line = '2026.04.08 14:30:45.123 [INFO] Thread-1: Test message'
        result = parser.detect_log_line_start(line)
        self.assertIsNotNone(result)
        self.assertEqual(result['timestamp'], '2026.04.08 14:30:45.123')
        self.assertEqual(result['timeBucket'], utc_ts(2026, 4, 8, 14, 30, 45))

    def test_continuation_line_returns_none(self):
        self.assertIsNone(parser.detect_log_line_start('  at com.example.Class.method(Class.java:42)'))

    def test_empty_line_returns_none(self):
        self.assertIsNone(parser.detect_log_line_start(''))

    def test_plain_text_without_timestamp_returns_none(self):
        self.assertIsNone(parser.detect_log_line_start('Some random text without timestamp'))


# ============================================================================
# parseLine
# ============================================================================
class TestParseLine(unittest.TestCase):
    def test_complete_log_line_with_all_fields(self):
        line = '2026.04.08 14:30:45.123 [INFO] class com.example.MyClass: Thread-1: <Device123> (com.example.package.Component) Test message'
        result = parser.parse_line(line, 'NEUF-test.log')
        self.assertEqual(result, {
            'filename': 'NEUF-test.log',
            'timestamp': '2026.04.08 14:30:45.123',
            'timeBucket': utc_ts(2026, 4, 8, 14, 30, 45),
            'logLevel': 'INFO',
            'threadName': 'Thread',
            'deviceId': 'Device123',
            'componentName': 'com.example.package',
            'message': 'Test message'
        })

    def test_log_line_without_device_id_and_component_name(self):
        line = '2026.04.08 14:30:45.123 [WARN] MainThread: Simple warning'
        result = parser.parse_line(line, 'NEUF-test.log')
        self.assertEqual(result, {
            'filename': 'NEUF-test.log',
            'timestamp': '2026.04.08 14:30:45.123',
            'timeBucket': utc_ts(2026, 4, 8, 14, 30, 45),
            'logLevel': 'WARN',
            'threadName': 'MainThread',
            'deviceId': None,
            'componentName': None,
            'message': 'Simple warning'
        })

    def test_log_line_without_class_name(self):
        line = '2026.04.08 14:30:45.123 [INFO] Thread-1: <Device123> (com.example.Component) Test message'
        result = parser.parse_line(line, 'NEUF-test.log')
        self.assertEqual(result['logLevel'], 'INFO')
        self.assertEqual(result['threadName'], 'Thread')
        self.assertEqual(result['deviceId'], 'Device123')
        self.assertEqual(result['componentName'], 'com.example')
        self.assertEqual(result['message'], 'Test message')

    def test_minimal_log_line(self):
        line = '2026.04.08 14:30:45.123 [ERROR] Worker-123: Error occurred'
        result = parser.parse_line(line, 'test.log')
        self.assertEqual(result, {
            'filename': 'test.log',
            'timestamp': '2026.04.08 14:30:45.123',
            'timeBucket': utc_ts(2026, 4, 8, 14, 30, 45),
            'logLevel': 'ERROR',
            'threadName': 'Worker',
            'deviceId': None,
            'componentName': None,
            'message': 'Error occurred'
        })

    def test_continuation_line_returns_none(self):
        self.assertIsNone(parser.parse_line('  at com.example.Class.method(Class.java:42)', 'test.log'))

    def test_empty_line_returns_none(self):
        self.assertIsNone(parser.parse_line('', 'test.log'))

    def test_plain_text_without_timestamp_returns_none(self):
        self.assertIsNone(parser.parse_line('Some random text without timestamp', 'test.log'))


if __name__ == '__main__':
    unittest.main()
