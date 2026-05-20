"""
Test Suite for Preset Service Module (Python port of test/preset.test.js)
Tests all static methods of PresetService.
"""
import sys
import os
import json
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.preset import PresetService


# ============================================================================
# PresetService.apply_preset
# ============================================================================
class TestApplyPreset(unittest.TestCase):
    def test_no_op_when_filters_has_no_preset_field(self):
        filters = {'logLevelInclude': ['ERROR']}
        PresetService.apply_preset(filters, {})
        self.assertEqual(filters, {'logLevelInclude': ['ERROR']})

    def test_no_op_when_preset_is_empty_string(self):
        filters = {'preset': ''}
        PresetService.apply_preset(filters, {})
        self.assertEqual(list(filters.keys()), ['preset'])

    def test_no_op_when_preset_is_empty_list(self):
        filters = {'preset': []}
        PresetService.apply_preset(filters, {})
        self.assertEqual(list(filters.keys()), ['preset'])

    def test_time_range_intersection_both_have_time_from_to(self):
        presets = {
            'afternoon': {
                'id': 'afternoon',
                'label': 'Afternoon',
                'description': 'Afternoon preset',
                'filters': {
                    'timeFrom': '2026.04.28 12:00:00',
                    'timeTo':   '2026.04.28 18:00:00'
                }
            }
        }
        filters = {
            'preset': 'afternoon',
            'timeFrom': '2026.04.28 13:00:00',
            'timeTo':   '2026.04.28 17:00:00'
        }
        PresetService.apply_preset(filters, presets)
        # larger timeFrom (13:00 > 12:00) and smaller timeTo (17:00 < 18:00)
        self.assertEqual(filters['timeFrom'], '2026.04.28 13:00:00')
        self.assertEqual(filters['timeTo'], '2026.04.28 17:00:00')

    def test_time_range_preset_wider_than_user_range(self):
        presets = {
            'wide_range': {
                'id': 'wide_range',
                'filters': {
                    'timeFrom': '2026.04.28 06:00:00',
                    'timeTo':   '2026.04.28 22:00:00'
                }
            }
        }
        filters = {
            'preset': 'wide_range',
            'timeFrom': '2026.04.28 10:00:00',
            'timeTo':   '2026.04.28 15:00:00'
        }
        PresetService.apply_preset(filters, presets)
        # User range is narrower, should remain unchanged
        self.assertEqual(filters['timeFrom'], '2026.04.28 10:00:00')
        self.assertEqual(filters['timeTo'], '2026.04.28 15:00:00')

    def test_time_range_preset_narrower_than_user_range(self):
        presets = {
            'narrow_range': {
                'id': 'narrow_range',
                'filters': {
                    'timeFrom': '2026.04.28 10:00:00',
                    'timeTo':   '2026.04.28 15:00:00'
                }
            }
        }
        filters = {
            'preset': 'narrow_range',
            'timeFrom': '2026.04.28 06:00:00',
            'timeTo':   '2026.04.28 22:00:00'
        }
        PresetService.apply_preset(filters, presets)
        # Preset range is narrower, should be applied
        self.assertEqual(filters['timeFrom'], '2026.04.28 10:00:00')
        self.assertEqual(filters['timeTo'], '2026.04.28 15:00:00')

    def test_time_range_only_preset_has_time_from_to(self):
        presets = {
            'with_time': {
                'id': 'with_time',
                'filters': {
                    'timeFrom': '2026.04.28 12:00:00',
                    'timeTo':   '2026.04.28 18:00:00'
                }
            }
        }
        filters = {'preset': 'with_time'}
        PresetService.apply_preset(filters, presets)
        self.assertEqual(filters['timeFrom'], '2026.04.28 12:00:00')
        self.assertEqual(filters['timeTo'], '2026.04.28 18:00:00')

    def test_time_range_only_user_has_time_from_to(self):
        presets = {
            'without_time': {
                'id': 'without_time',
                'filters': {'logLevelInclude': ['ERROR']}
            }
        }
        filters = {
            'preset': 'without_time',
            'timeFrom': '2026.04.28 10:00:00',
            'timeTo':   '2026.04.28 20:00:00'
        }
        PresetService.apply_preset(filters, presets)
        self.assertEqual(filters['timeFrom'], '2026.04.28 10:00:00')
        self.assertEqual(filters['timeTo'], '2026.04.28 20:00:00')
        self.assertEqual(filters['logLevelInclude'], ['ERROR'])

    def test_time_range_only_preset_has_time_from(self):
        presets = {
            'from_only': {
                'id': 'from_only',
                'filters': {'timeFrom': '2026.04.28 12:00:00'}
            }
        }
        filters = {
            'preset': 'from_only',
            'timeFrom': '2026.04.28 10:00:00',
            'timeTo':   '2026.04.28 20:00:00'
        }
        PresetService.apply_preset(filters, presets)
        # Should take larger timeFrom
        self.assertEqual(filters['timeFrom'], '2026.04.28 12:00:00')
        self.assertEqual(filters['timeTo'], '2026.04.28 20:00:00')

    def test_time_range_numeric_unix_second_timestamps(self):
        import calendar
        date_from = int(calendar.timegm((2026, 4, 28, 12, 0, 0, 0, 0, 0)))
        date_to   = int(calendar.timegm((2026, 4, 28, 18, 0, 0, 0, 0, 0)))
        user_from = int(calendar.timegm((2026, 4, 28, 13, 0, 0, 0, 0, 0)))
        user_to   = int(calendar.timegm((2026, 4, 28, 17, 0, 0, 0, 0, 0)))
        presets = {
            'unix_time': {
                'id': 'unix_time',
                'filters': {'timeFrom': date_from, 'timeTo': date_to}
            }
        }
        filters = {'preset': 'unix_time', 'timeFrom': user_from, 'timeTo': user_to}
        PresetService.apply_preset(filters, presets)
        self.assertEqual(filters['timeFrom'], user_from)
        self.assertEqual(filters['timeTo'], user_to)

    def test_time_range_multiple_presets_with_overlapping_ranges(self):
        presets = {
            'morning': {
                'id': 'morning',
                'description': 'Morning',
                'filters': {
                    'timeFrom': '2026.04.28 06:00:00',
                    'timeTo':   '2026.04.28 12:00:00'
                }
            },
            'business_hours': {
                'id': 'business_hours',
                'description': 'Business hours',
                'filters': {
                    'timeFrom': '2026.04.28 09:00:00',
                    'timeTo':   '2026.04.28 17:00:00'
                }
            }
        }
        filters = {
            'preset': ['morning', 'business_hours'],
            'timeFrom': '2026.04.28 08:00:00',
            'timeTo':   '2026.04.28 15:00:00'
        }
        PresetService.apply_preset(filters, presets)
        # max(6:00, 9:00, 8:00) = 9:00; min(12:00, 17:00, 15:00) = 12:00
        self.assertEqual(filters['timeFrom'], '2026.04.28 09:00:00')
        self.assertEqual(filters['timeTo'], '2026.04.28 12:00:00')

    def test_time_range_non_overlapping_ranges(self):
        presets = {
            'early': {
                'id': 'early',
                'filters': {
                    'timeFrom': '2026.04.28 06:00:00',
                    'timeTo':   '2026.04.28 10:00:00'
                }
            }
        }
        filters = {
            'preset': 'early',
            'timeFrom': '2026.04.28 15:00:00',
            'timeTo':   '2026.04.28 20:00:00'
        }
        PresetService.apply_preset(filters, presets)
        # Intersection of (6:00-10:00) and (15:00-20:00) is (15:00-10:00)
        self.assertEqual(filters['timeFrom'], '2026.04.28 15:00:00')
        self.assertEqual(filters['timeTo'], '2026.04.28 10:00:00')


# ============================================================================
# PresetService.load_user_presets
# ============================================================================
class TestLoadUserPresets(unittest.TestCase):
    def test_returns_empty_dict_when_file_does_not_exist(self):
        result = PresetService.load_user_presets('/tmp/nonexistent-preset-xyz.json')
        self.assertEqual(len(result), 0)

    def test_loads_and_parses_a_valid_preset_json_file(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({
                'test_preset': {
                    'id': 'test_preset',
                    'label': 'Test preset',
                    'description': 'A test preset',
                    'filters': {'componentExclude': ['%Test%']}
                }
            }, f)
            tmp_path = f.name
        try:
            result = PresetService.load_user_presets(tmp_path)
            self.assertEqual(result.get('test_preset', {}).get('id'), 'test_preset')
        finally:
            os.unlink(tmp_path)

    def test_returns_empty_dict_for_malformed_json_file(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write('not valid json {{{')
            tmp_path = f.name
        try:
            warnings = []
            result = PresetService.load_user_presets(tmp_path, lambda msg: warnings.append(msg))
            self.assertEqual(len(result), 0)
            self.assertEqual(len(warnings), 1)
        finally:
            os.unlink(tmp_path)

    def test_skips_and_warns_for_entries_missing_filters_property(self):
        data = {
            'good_preset':        {'id': 'good_preset',        'label': 'Good',   'description': 'ok',     'filters': {'logLevelInclude': ['ERROR']}},
            'bad_no_filters':     {'id': 'bad_no_filters',      'label': 'No flt', 'description': 'missing'},
            'bad_null_filters':   {'id': 'bad_null_filters',    'label': 'Null',   'description': 'null',   'filters': None},
            'bad_string_filters': {'id': 'bad_string_filters',  'label': 'Str',    'description': 'str',    'filters': 'ERROR'},
        }
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(data, f)
            tmp_path = f.name
        try:
            warnings = []
            result = PresetService.load_user_presets(tmp_path, lambda msg: warnings.append(msg))
            self.assertIn('good_preset', result)
            self.assertNotIn('bad_no_filters', result)
            self.assertNotIn('bad_null_filters', result)
            self.assertNotIn('bad_string_filters', result)
            self.assertEqual(len(warnings), 3)
        finally:
            os.unlink(tmp_path)

    def test_user_presets_from_project_root_are_loadable(self):
        presets = PresetService.load_user_presets()
        valid = all(
            isinstance(p.get('id'), str) and
            isinstance(p.get('label'), str) and
            isinstance(p.get('description'), str) and
            isinstance(p.get('filters'), dict)
            for p in presets.values()
        )
        self.assertTrue(valid)

    def test_static_presets_from_preset_json_can_be_applied(self):
        user_presets = PresetService.load_user_presets()
        filters = {'preset': 'exclude_endpoint_tester'}
        PresetService.apply_preset(filters, user_presets)
        self.assertIsInstance(filters.get('componentExclude'), list)
        self.assertIn('%Endpoint%', filters['componentExclude'])


# ============================================================================
# PresetService.load_preset — merged from preset.json + snapshot
# ============================================================================
class TestLoadPreset(unittest.TestCase):
    def test_returns_user_presets_when_no_snapshot_file_exists(self):
        result = PresetService.load_preset('/tmp/nonexistent-db-dir-xyz')
        self.assertIsNotNone(result)
        self.assertIsInstance(result, dict)
        self.assertIn('exclude_endpoint_tester', result)

    def test_merges_snapshot_presets_with_user_presets_snapshot_takes_precedence(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            snapshot_path = os.path.join(tmp_dir, 'neuf-presets.json')
            snapshot = {
                'custom_snap': {
                    'id': 'custom_snap',
                    'label': 'Snapshot preset',
                    'description': 'From snapshot',
                    'filters': {'logLevelInclude': ['ERROR']}
                },
                'exclude_endpoint_tester': {
                    'id': 'exclude_endpoint_tester',
                    'label': 'Overridden by snapshot',
                    'description': 'Snapshot version',
                    'filters': {'componentExclude': ['%SnapshotEndpoint%']}
                }
            }
            with open(snapshot_path, 'w') as f:
                json.dump(snapshot, f)
            result = PresetService.load_preset(tmp_dir)
            self.assertIn('exclude_historical_data', result)
            self.assertIn('custom_snap', result)
            self.assertEqual(result['exclude_endpoint_tester']['label'], 'Overridden by snapshot')

    def test_returns_user_presets_when_snapshot_file_is_malformed(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            snapshot_path = os.path.join(tmp_dir, 'neuf-presets.json')
            with open(snapshot_path, 'w') as f:
                f.write('not valid json')
            warnings = []
            result = PresetService.load_preset(tmp_dir, lambda msg: warnings.append(msg))
            self.assertIn('exclude_endpoint_tester', result)
            self.assertEqual(len(warnings), 1)

    def test_logs_warning_when_snapshot_shadows_user_preset(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            snapshot_path = os.path.join(tmp_dir, 'neuf-presets.json')
            snapshot = {
                'exclude_endpoint_tester': {
                    'id': 'exclude_endpoint_tester',
                    'label': 'Snapshot version',
                    'description': 'Shadowing user preset',
                    'filters': {'componentExclude': ['%Endpoint%']}
                }
            }
            with open(snapshot_path, 'w') as f:
                json.dump(snapshot, f)
            warnings = []
            PresetService.load_preset(tmp_dir, lambda msg: warnings.append(msg))
            has_warning = any(
                'exclude_endpoint_tester' in w and 'overridden' in w.lower()
                for w in warnings
            )
            self.assertTrue(has_warning)


if __name__ == '__main__':
    unittest.main()
