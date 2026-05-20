"""
Test Suite for Log File Scanner Module (Python port, mirroring test/log-file-scanner pattern)
Tests all methods of LogFileScannerService.
"""
import sys
import os
import asyncio
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.log_file_scanner import LogFileScannerService
from src.log_parser import LogParserService


def _make_scanner():
    return LogFileScannerService(LogParserService())


# ============================================================================
# find_neuf_log_files
# ============================================================================
class TestFindNeufLogFiles(unittest.TestCase):
    def test_returns_matching_neuf_log_files_sorted(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Create matching and non-matching files
            for name in ['NEUF-b.log', 'NEUF-a.log', 'other.log', 'neuf-c.log']:
                open(os.path.join(tmp, name), 'w').close()
            scanner = _make_scanner()
            result = scanner.find_neuf_log_files(tmp)
            basenames = [os.path.basename(p) for p in result]
            self.assertIn('NEUF-a.log', basenames)
            self.assertIn('NEUF-b.log', basenames)
            self.assertIn('neuf-c.log', basenames)
            self.assertNotIn('other.log', basenames)
            # Result must be sorted
            self.assertEqual(result, sorted(result))

    def test_returns_empty_list_when_no_matching_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, 'app.log'), 'w').close()
            scanner = _make_scanner()
            result = scanner.find_neuf_log_files(tmp)
            self.assertEqual(result, [])

    def test_returns_only_top_level_files_not_subdirectory(self):
        with tempfile.TemporaryDirectory() as tmp:
            sub = os.path.join(tmp, 'subdir')
            os.makedirs(sub)
            # File in subdir should NOT be returned
            open(os.path.join(sub, 'NEUF-sub.log'), 'w').close()
            # File at top level should be returned
            open(os.path.join(tmp, 'NEUF-top.log'), 'w').close()
            scanner = _make_scanner()
            result = scanner.find_neuf_log_files(tmp)
            basenames = [os.path.basename(p) for p in result]
            self.assertIn('NEUF-top.log', basenames)
            self.assertNotIn('NEUF-sub.log', basenames)

    def test_handles_empty_directory_gracefully(self):
        with tempfile.TemporaryDirectory() as tmp:
            scanner = _make_scanner()
            result = scanner.find_neuf_log_files(tmp)
            self.assertEqual(result, [])

    def test_returns_full_absolute_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, 'NEUF-test.log'), 'w').close()
            scanner = _make_scanner()
            result = scanner.find_neuf_log_files(tmp)
            self.assertEqual(len(result), 1)
            self.assertTrue(os.path.isabs(result[0]))


# ============================================================================
# parse_files
# ============================================================================
class TestParseFiles(unittest.TestCase):
    VALID_LINES = '\n'.join([
        '2026.04.08 10:00:00.000 [INFO] Thread-1: <Dev001> (com.example.Service) Message one',
        '2026.04.08 10:00:01.000 [ERROR] Thread-2: <Dev002> (com.example.Controller) Error here',
        '2026.04.08 10:00:02.000 [DEBUG] Worker-3: Debug info',
    ])

    def test_parse_files_returns_total_entries_and_file_stats(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, 'NEUF-main.log'), 'w') as f:
                f.write(self.VALID_LINES)
            scanner = _make_scanner()
            batches = []
            result = asyncio.run(
                scanner.parse_files(tmp, lambda b: batches.append(b))
            )
            self.assertIn('totalEntries', result)
            self.assertIn('fileStats', result)
            self.assertEqual(result['totalEntries'], 3)
            self.assertEqual(len(result['fileStats']), 1)
            self.assertEqual(result['fileStats'][0]['entries'], 3)

    def test_parse_files_delivers_batches_via_callback(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, 'NEUF-main.log'), 'w') as f:
                f.write(self.VALID_LINES)
            scanner = _make_scanner()
            batches = []
            asyncio.run(scanner.parse_files(tmp, lambda b: batches.append(b)))
            total_from_batches = sum(len(b) for b in batches)
            self.assertGreater(total_from_batches, 0)

    def test_parse_files_returns_zero_entries_when_no_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            scanner = _make_scanner()
            result = asyncio.run(
                scanner.parse_files(tmp, lambda b: None)
            )
            self.assertEqual(result['totalEntries'], 0)
            self.assertEqual(result['fileStats'], [])

    def test_parse_files_handles_multiline_log_entry(self):
        multiline = (
            '2026.04.08 10:00:00.000 [ERROR] Thread-1: Exception occurred\n'
            '    at com.example.Class.method(Class.java:42)\n'
            '    at com.example.Other.run(Other.java:10)\n'
            '2026.04.08 10:00:01.000 [INFO] Thread-1: Recovery done\n'
        )
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, 'NEUF-multi.log'), 'w') as f:
                f.write(multiline)
            scanner = _make_scanner()
            result = asyncio.run(
                scanner.parse_files(tmp, lambda b: None)
            )
            # Two log entries (the stack trace is part of the first entry)
            self.assertEqual(result['totalEntries'], 2)

    def test_parse_files_uses_precomputed_files_list_when_provided(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = os.path.join(tmp, 'NEUF-provided.log')
            with open(log_path, 'w') as f:
                f.write(self.VALID_LINES)
            scanner = _make_scanner()
            result = asyncio.run(
                scanner.parse_files(tmp, lambda b: None, precomputed_files=[log_path])
            )
            self.assertEqual(result['totalEntries'], 3)

    def test_parse_files_file_stats_include_filename_lines_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, 'NEUF-stats.log'), 'w') as f:
                f.write(self.VALID_LINES)
            scanner = _make_scanner()
            result = asyncio.run(
                scanner.parse_files(tmp, lambda b: None)
            )
            stat = result['fileStats'][0]
            self.assertIn('filename', stat)
            self.assertIn('lines', stat)
            self.assertIn('entries', stat)

    def test_parse_files_parsed_log_has_required_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, 'NEUF-keys.log'), 'w') as f:
                f.write(self.VALID_LINES)
            scanner = _make_scanner()
            all_logs = []
            asyncio.run(scanner.parse_files(tmp, lambda b: all_logs.extend(b)))
            self.assertGreater(len(all_logs), 0)
            required_keys = {'filename', 'timestamp', 'timeBucket', 'logLevel',
                             'threadName', 'message'}
            for log in all_logs:
                self.assertTrue(required_keys.issubset(log.keys()))


if __name__ == '__main__':
    unittest.main()
