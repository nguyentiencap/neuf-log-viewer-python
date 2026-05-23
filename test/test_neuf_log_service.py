"""
Test Suite for NEUF Log Service Module (Python port of test/neuf-log-service.test.js)
Tests all methods of NEUFLogService.
"""
import sys
import os
import asyncio
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.neuf_log_service import NEUFLogService
from src.database import compute_hash_lo_hi

mock_logger = lambda *_: None
log_service = NEUFLogService(mock_logger)


LOG_CONTENT = '\n'.join([
    '2026.04.08 10:00:00.000 [INFO] Thread-1: <Device001> (com.example.service) Test message 1',
    '2026.04.08 10:00:01.000 [ERROR] Thread-2: <Device002> (com.example.controller) Test error message',
    '2026.04.08 10:00:02.000 [DEBUG] Thread-1: <Device001> (com.example.service) Debug message',
    '2026.04.08 10:00:03.000 [WARN] Thread-3: <Device003> (com.example.util) Warning message',
    '2026.04.08 10:00:04.000 [INFO] Thread-1: <Device001> (com.example.service) Another info message',
])


def _create_test_database():
    """Create a temp folder with a NEUF-*.log file and scan it.  Returns paths dict."""
    test_folder = tempfile.mkdtemp(prefix='neuf-filter-test-')
    db_dir = os.path.join(test_folder, 'log-filter-db')
    db_path = os.path.join(db_dir, 'neuf-logs.db')
    log_file = os.path.join(test_folder, 'NEUF-test.log')
    with open(log_file, 'w') as f:
        f.write(LOG_CONTENT)
    asyncio.run(log_service.scan_logs(test_folder))
    return {'testFolder': test_folder, 'dbPath': db_path, 'logFilePath': log_file}


def _cleanup_test_database(paths):
    import shutil
    shutil.rmtree(paths['testFolder'], ignore_errors=True)


# ============================================================================
# get_db_path
# ============================================================================
class TestGetDbPath(unittest.TestCase):
    def test_returns_correct_database_path_structure(self):
        result = log_service.get_db_path('/test/logs')
        self.assertIn('logFolderPath', result)
        self.assertIn('dbPath', result)
        self.assertIn('dbDir', result)
        self.assertTrue(result['dbPath'].endswith(
            os.path.join('log-filter-db', 'neuf-logs.db')
        ))

    def test_resolves_relative_paths_to_absolute(self):
        result = log_service.get_db_path('./logs')
        self.assertTrue(os.path.isabs(result['logFolderPath']))

    def test_database_directory_is_inside_log_folder(self):
        result = log_service.get_db_path('/test/logs')
        self.assertTrue(result['dbDir'].startswith(result['logFolderPath']))

    def test_database_file_is_named_neuf_logs_db(self):
        result = log_service.get_db_path('/test/logs')
        self.assertEqual(os.path.basename(result['dbPath']), 'neuf-logs.db')

    def test_handles_paths_with_spaces(self):
        result = log_service.get_db_path('/path/with spaces/logs')
        self.assertGreater(len(result['dbPath']), 0)

    def test_multiple_get_db_path_calls_do_not_interfere(self):
        p1 = log_service.get_db_path('/test/path1')
        p2 = log_service.get_db_path('/test/path2')
        p3 = log_service.get_db_path('/test/path1')
        self.assertEqual(p1['dbPath'], p3['dbPath'])
        self.assertNotEqual(p1['dbPath'], p2['dbPath'])


# ============================================================================
# is_database_scanned
# ============================================================================
class TestIsDatabaseScanned(unittest.TestCase):
    def test_returns_false_for_non_existent_database(self):
        self.assertFalse(log_service.is_database_scanned('/non/existent/path'))

    def test_returns_false_for_none_input(self):
        self.assertFalse(log_service.is_database_scanned(None))

    def test_returns_false_for_empty_string(self):
        self.assertFalse(log_service.is_database_scanned(''))


# ============================================================================
# _create_database_service
# ============================================================================
class TestCreateDatabaseService(unittest.TestCase):
    def test_returns_db_and_database_service_objects(self):
        import sqlite3
        conn = sqlite3.connect(':memory:')
        result = log_service._create_database_service(conn)
        self.assertIn('db', result)
        self.assertIn('databaseService', result)


# ============================================================================
# clear_database
# ============================================================================
class TestClearDatabase(unittest.TestCase):
    def test_returns_success_when_database_does_not_exist(self):
        result = log_service.clear_database('/non/existent/path')
        self.assertTrue(result['success'])
        self.assertIn('message', result)
        self.assertIn('dbPath', result)

    def test_handles_non_existent_paths_gracefully(self):
        result = log_service.clear_database('/absolutely/non/existent/path/12345xyz')
        self.assertTrue(result['success'])
        self.assertIn('message', result)

    def test_deletes_existing_database_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_dir = os.path.join(tmp, 'log-filter-db')
            os.makedirs(db_dir)
            db_path = os.path.join(db_dir, 'neuf-logs.db')
            with open(db_path, 'w') as f:
                f.write('')
            result = log_service.clear_database(tmp)
            self.assertTrue(result['success'])
            self.assertFalse(os.path.exists(db_path))


# ============================================================================
# Constructor
# ============================================================================
class TestConstructor(unittest.TestCase):
    def test_accepts_logger_parameter(self):
        custom_logger = lambda msg: None
        service = NEUFLogService(custom_logger)
        self.assertIsNotNone(service.parser_service)
        self.assertIsNotNone(service.logger)
        # Verify the injected logger is actually used by an operation
        # (operation must succeed without errors; get_db_path raises until implemented)
        result = service.get_db_path('/test/logs')
        self.assertIn('dbPath', result)

    def test_uses_default_logger_when_not_provided(self):
        service = NEUFLogService()
        self.assertTrue(callable(service.logger))
        # Logger must be exercised by a real operation
        result = service.get_db_path('/test/logs')
        self.assertIn('dbDir', result)


# ============================================================================
# load_database error handling
# ============================================================================
class TestLoadDatabaseErrorHandling(unittest.TestCase):
    def test_throws_error_when_database_not_found(self):
        with self.assertRaises(Exception) as ctx:
            asyncio.run(log_service.load_database('/non/existent/path'))
        self.assertIn('not found', str(ctx.exception).lower())


# ============================================================================
# scan_logs return structure
# ============================================================================
class TestScanLogs(unittest.TestCase):
    def test_returns_correct_structure_when_database_already_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_dir = os.path.join(tmp, 'log-filter-db')
            os.makedirs(db_dir)
            db_path = os.path.join(db_dir, 'neuf-logs.db')
            with open(db_path, 'w') as f:
                f.write('')
            result = asyncio.run(log_service.scan_logs(tmp))
            self.assertTrue(result['success'])
            self.assertIn('message', result)
            self.assertIn('data', result)
            self.assertTrue(result['data']['alreadyScanned'])

    def test_raises_no_neuf_log_files_found_for_empty_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(Exception) as ctx:
                asyncio.run(log_service.scan_logs(tmp))
            self.assertRegex(str(ctx.exception), r'No NEUF log files found in:')

    def test_error_message_mentions_naming_requirement(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(Exception) as ctx:
                asyncio.run(log_service.scan_logs(tmp))
            self.assertRegex(str(ctx.exception), r'NEUF-\*\.log')

    def test_raises_could_not_parse_when_log_file_has_no_valid_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, 'NEUF-test.log'), 'w') as f:
                f.write('This is not a valid NEUF log line\nNeither is this\n')
            with self.assertRaises(Exception) as ctx:
                asyncio.run(log_service.scan_logs(tmp))
            self.assertRegex(str(ctx.exception), r'NEUF-\*\.log file\(s\).*could not parse')

    def test_could_not_parse_error_includes_file_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, 'NEUF-a.log'), 'w') as f:
                f.write('not valid\n')
            with open(os.path.join(tmp, 'NEUF-b.log'), 'w') as f:
                f.write('also not valid\n')
            with self.assertRaises(Exception) as ctx:
                asyncio.run(log_service.scan_logs(tmp))
            self.assertRegex(str(ctx.exception), r'Found 2 NEUF-\*\.log file\(s\)')

    def test_clear_db_file_removes_stale_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_dir = os.path.join(tmp, 'log-filter-db')
            os.makedirs(db_dir)
            db_path = os.path.join(db_dir, 'neuf-logs.db')
            with open(db_path, 'w') as f:
                f.write('stale')
            log_service._clear_db_file(db_path, tmp)
            self.assertFalse(os.path.exists(db_path))

    def test_db_file_removed_when_neuf_log_has_no_valid_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_dir = os.path.join(tmp, 'log-filter-db')
            os.makedirs(db_dir)
            with open(os.path.join(tmp, 'NEUF-test.log'), 'w') as f:
                f.write('not a valid log line\n')
            db_path = os.path.join(db_dir, 'neuf-logs.db')
            with self.assertRaises(Exception) as ctx:
                asyncio.run(log_service.scan_logs(tmp))
            self.assertRegex(str(ctx.exception), r'could not parse')
            self.assertFalse(os.path.exists(db_path))


# ============================================================================
# Service integration
# ============================================================================
class TestServiceIntegration(unittest.TestCase):
    def test_parser_service_is_injected_with_required_methods(self):
        # Methods must be callable AND must produce valid output (not just exist)
        self.assertEqual(
            log_service.parser_service.normalize_thread_name('Thread-123'),
            'Thread'
        )
        self.assertEqual(
            log_service.parser_service.normalize_component_name('com.example.Class'),
            'com.example'
        )

    def test_no_instance_state_stored_between_operations(self):
        s1 = NEUFLogService(mock_logger)
        s2 = NEUFLogService(mock_logger)
        p1 = s1.get_db_path('/test/path1')
        p2 = s2.get_db_path('/test/path2')
        self.assertNotEqual(p1['dbPath'], p2['dbPath'])


# ============================================================================
# filter_logs and get_filter_options with real database
# ============================================================================
class TestFilterLogsAndGetFilterOptions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.paths = _create_test_database()

    @classmethod
    def tearDownClass(cls):
        _cleanup_test_database(cls.paths)

    def test_filter_logs_returns_all_logs_with_empty_filters(self):
        result = asyncio.run(log_service.filter_logs(
            self.paths['testFolder'], {}, {'page': 1, 'pageSize': 100}
        ))
        self.assertTrue(result['success'])
        self.assertIsInstance(result['logs'], list)
        self.assertIsInstance(result['total'], int)
        self.assertEqual(result['page'], 1)
        self.assertEqual(result['pageSize'], 100)
        self.assertEqual(len(result['logs']), 5)

    def test_filter_logs_filters_by_log_level(self):
        result = asyncio.run(log_service.filter_logs(
            self.paths['testFolder'],
            {'logLevelInclude': ['ERROR']},
            {'page': 1, 'pageSize': 100}
        ))
        self.assertTrue(all(log['log_level'] == 'ERROR' for log in result['logs']))
        self.assertEqual(len(result['logs']), 1)

    def test_filter_logs_filters_by_device_id(self):
        result = asyncio.run(log_service.filter_logs(
            self.paths['testFolder'],
            {'deviceInclude': ['Device001']},
            {'page': 1, 'pageSize': 100}
        ))
        self.assertTrue(all(log['device_id'] == 'Device001' for log in result['logs']))
        self.assertEqual(len(result['logs']), 3)

    def test_filter_logs_pagination_works_correctly(self):
        r1 = asyncio.run(log_service.filter_logs(
            self.paths['testFolder'], {}, {'page': 1, 'pageSize': 2}
        ))
        r2 = asyncio.run(log_service.filter_logs(
            self.paths['testFolder'], {}, {'page': 2, 'pageSize': 2}
        ))
        self.assertEqual(len(r1['logs']), 2)
        self.assertEqual(len(r2['logs']), 2)
        self.assertEqual(r1['totalPages'], 3)
        self.assertNotEqual(r1['logs'][0]['id'], r2['logs'][0]['id'])

    def test_get_filter_options_returns_available_filter_options(self):
        result = asyncio.run(log_service.get_filter_options(self.paths['testFolder']))
        self.assertTrue(result['success'])
        self.assertIn('data', result)
        self.assertIsInstance(result['data']['logLevels'], list)
        self.assertIsInstance(result['data']['devices'], list)
        self.assertIsInstance(result['data']['threads'], list)
        self.assertIsInstance(result['data']['components'], list)

    def test_get_filter_options_returns_correct_log_levels(self):
        result = asyncio.run(log_service.get_filter_options(self.paths['testFolder']))
        levels = [l['log_level'] for l in result['data']['logLevels']]
        self.assertIn('INFO', levels)
        self.assertIn('ERROR', levels)
        self.assertIn('DEBUG', levels)
        self.assertIn('WARN', levels)

    def test_get_filter_options_returns_correct_device_ids(self):
        result = asyncio.run(log_service.get_filter_options(self.paths['testFolder']))
        devices = [d['device_id'] for d in result['data']['devices']]
        self.assertIn('Device001', devices)
        self.assertIn('Device002', devices)
        self.assertIn('Device003', devices)
        self.assertEqual(len(result['data']['devices']), 3)


class TestApplyDedupFilter(unittest.TestCase):
    def _log(self, idx, message, hash_pair):
        return {
            'id': idx,
            'filename': 'NEUF-test.log',
            'timestamp': f'2026.04.08 10:00:0{idx}.000',
            'thread_name': 'Thread-1',
            'device_id': 'Device001',
            'component_name': 'com.example',
            'log_level': 'INFO',
            'message': message,
            'hash_lo': hash_pair[0] if hash_pair else None,
            'hash_hi': hash_pair[1] if hash_pair else None,
        }

    def test_none_mode_returns_logs_unchanged(self):
        hash_pair = compute_hash_lo_hi('Device001', 'com.example', 'same')
        logs = [self._log(1, 'same', hash_pair), self._log(2, 'same', hash_pair)]
        result = log_service.apply_dedup_filter(logs, 'none')
        self.assertEqual(result, logs)

    def test_skip_mode_drops_duplicate_rows(self):
        hash_pair = compute_hash_lo_hi('Device001', 'com.example', 'same')
        logs = [self._log(1, 'same', hash_pair), self._log(2, 'same', hash_pair)]
        result = log_service.apply_dedup_filter(logs, 'skip')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['id'], 1)

    def test_annotate_mode_marks_duplicate_rows(self):
        hash_pair = compute_hash_lo_hi('Device001', 'com.example', 'same')
        logs = [self._log(1, 'same', hash_pair), self._log(2, 'same', hash_pair)]
        result = log_service.apply_dedup_filter(logs, 'annotate')
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['message'], 'same')
        self.assertIn('Giống dòng 1', result[1]['message'])

    def test_missing_hash_rows_are_not_grouped(self):
        logs = [self._log(1, 'same', None), self._log(2, 'same', None)]
        result = log_service.apply_dedup_filter(logs, 'skip')
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['message'], 'same')
        self.assertEqual(result[1]['message'], 'same')


if __name__ == '__main__':
    unittest.main()
