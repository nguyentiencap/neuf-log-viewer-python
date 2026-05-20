"""
Preset Module (Python port of src/preset.js)
Provides dynamic filter suggestions for the preset feature.
Responsibility: Generate contextual filter suggestions based on data analytics.
"""

import json
import os
import re
import calendar


class PresetService:
    """
    Preset Service.
    Generates dynamic filter suggestions and manages preset persistence.
    All methods are static, mirroring the JavaScript PresetService.
    """

    @staticmethod
    def get_presets_path(filter_db_dir):
        """Return full path to the scan-time preset snapshot JSON file."""
        return os.path.join(filter_db_dir, 'neuf-presets.json')

    @staticmethod
    def get_user_presets_path():
        """Return full path to the user-defined preset.json at the project root."""
        # python-port/src/ → up two levels → project root
        return os.path.join(
            os.path.dirname(__file__), '..', '..', 'preset.json'
        )

    @staticmethod
    def load_preset_file(file_path, logger=print):
        """Load and parse a single preset JSON file from disk."""
        if not os.path.exists(file_path):
            return None
        try:
            with open(file_path, encoding='utf-8') as fh:
                return json.load(fh) or None
        except Exception as e:
            logger(f'⚠️  Failed to load preset file "{file_path}": {e}')
            return None

    @staticmethod
    def load_user_presets(json_path=None, logger=print):
        """
        Load user-defined presets from preset.json.
        Returns empty dict if absent or unparseable.
        Validates each entry has a 'filters' dict; warns and skips malformed entries.
        """
        file_path = json_path if json_path is not None \
                    else PresetService.get_user_presets_path()
        parsed = PresetService.load_preset_file(file_path, logger)
        if not parsed:
            return {}

        valid = {}
        for preset_id, entry in parsed.items():
            if (not entry or
                    not entry.get('filters') or
                    not isinstance(entry.get('filters'), dict)):
                logger(
                    f'⚠️  Skipping malformed preset "{preset_id}" in {file_path}: '
                    f'missing or invalid "filters" property'
                )
                continue
            valid[preset_id] = entry
        return valid

    @staticmethod
    def save_preset(presets_path, presets, logger=print):
        """Persist a presets dict to disk as JSON."""
        with open(presets_path, 'w', encoding='utf-8') as fh:
            json.dump(presets, fh, indent=2)
        logger(f'💾 Preset snapshot saved to {presets_path}')

    @staticmethod
    def load_preset(filter_db_dir, logger=print):
        """
        Load and merge user presets (preset.json) with scan-time snapshot presets.
        Snapshot presets take precedence on id collision.
        """
        user_presets = PresetService.load_user_presets(None, logger)

        presets_path = PresetService.get_presets_path(filter_db_dir)
        snapshot = PresetService.load_preset_file(presets_path, logger)
        if not snapshot:
            return user_presets

        # Warn when snapshot shadows user preset
        shadowed = [pid for pid in user_presets if pid in snapshot]
        for pid in shadowed:
            logger(f'⚠️  User preset "{pid}" is overridden by scan preset')

        return {**user_presets, **snapshot}

    # ------------------------------------------------------------------ #
    #  Time range helpers                                                   #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _merge_time_range(user_time, preset_time, range_type):
        """
        Intersect a single timeFrom or timeTo value from user + preset.
        """
        if not user_time and not preset_time:
            return None
        if not user_time:
            return preset_time
        if not preset_time:
            return user_time

        user_sec = (user_time if isinstance(user_time, (int, float))
                    else (PresetService._parse_timestamp_sec(user_time) or {}).get('floorSec'))
        preset_sec = (preset_time if isinstance(preset_time, (int, float))
                      else (PresetService._parse_timestamp_sec(preset_time) or {}).get('floorSec'))

        if user_sec is None or preset_sec is None:
            return user_time

        selected_sec = max(user_sec, preset_sec) if range_type == 'from' \
                       else min(user_sec, preset_sec)

        if isinstance(user_time, (int, float)):
            return selected_sec
        return PresetService._format_unix_sec(selected_sec)

    @staticmethod
    def apply_preset(filters, presets, logger=print):
        """
        Mutate filters dict by merging filters from one or more preset IDs.
        """
        if not filters or 'preset' not in filters:
            return

        raw = filters['preset']
        preset_ids = [p for p in (raw if isinstance(raw, list) else [raw]) if p]

        if not preset_ids:
            return

        for preset_id in preset_ids:
            suggestion = presets.get(preset_id)
            if not suggestion:
                logger(f'⚠️  Preset not found: "{preset_id}"')
                continue

            for key, value in suggestion['filters'].items():
                if key in ('timeFrom', 'timeTo'):
                    filters[key] = PresetService._merge_time_range(
                        filters.get(key), value,
                        'from' if key == 'timeFrom' else 'to'
                    )
                elif isinstance(value, list) and isinstance(filters.get(key), list):
                    # Merge without duplicates, preserving order
                    seen = []
                    for v in [*filters[key], *value]:
                        if v not in seen:
                            seen.append(v)
                    filters[key] = seen
                else:
                    if filters.get(key) is None or filters.get(key) == '' or key not in filters:
                        filters[key] = value

    # ------------------------------------------------------------------ #
    #  Timestamp helpers                                                    #
    # ------------------------------------------------------------------ #

    _TS_RE = re.compile(
        r'^(\d{4})\.(\d{2})\.(\d{2}) (\d{2}):(\d{2}):(\d{2})(?:\.(\d{3}))?'
    )

    @staticmethod
    def _parse_timestamp_sec(ts):
        """Parse NEUF timestamp string to floor/ceil Unix seconds."""
        m = PresetService._TS_RE.match(ts)
        if not m:
            return None
        ms = int(m.group(7)) if m.group(7) else 0
        unix_ms = int(calendar.timegm((
            int(m.group(1)), int(m.group(2)), int(m.group(3)),
            int(m.group(4)), int(m.group(5)), int(m.group(6)),
            0, 0, 0
        ))) * 1000 + ms
        return {
            'floorSec': unix_ms // 1000,
            'ceilSec':  (unix_ms + 999) // 1000,
        }

    @staticmethod
    def _format_unix_sec(unix_sec):
        """Format Unix seconds (UTC) to "YYYY.MM.DD HH:mm:ss" string."""
        import datetime
        d = datetime.datetime.utcfromtimestamp(unix_sec)
        return (f'{d.year:04d}.{d.month:02d}.{d.day:02d}'
                f' {d.hour:02d}:{d.minute:02d}:{d.second:02d}')

    @staticmethod
    def create_install_presets(install_logs):
        """
        Generate install-based presets from LifecycleProvider install log rows.
        """
        presets = {}

        # Group timestamps by device_id
        by_device = {}
        for log in install_logs:
            dev = log.get('device_id')
            if not dev:
                continue
            by_device.setdefault(dev, []).append(log['timestamp'])

        for device_id, timestamps in by_device.items():
            timestamps.sort()

            for i, ts in enumerate(timestamps):
                parsed_from = PresetService._parse_timestamp_sec(ts)
                if not parsed_from:
                    continue

                time_from_sec = parsed_from['floorSec']
                time_from_str = PresetService._format_unix_sec(time_from_sec)
                preset_id = f'fujifilm_{device_id}_install_{i + 1}'

                if i < len(timestamps) - 1:
                    parsed_to = PresetService._parse_timestamp_sec(timestamps[i + 1])
                    if not parsed_to:
                        continue
                    time_to_sec = parsed_to['ceilSec']
                    time_to_str = PresetService._format_unix_sec(time_to_sec)
                    label = (f'📦 Fujifilm-{device_id} install from '
                             f'{time_from_str} -> {time_to_str}')
                    filt = {
                        'timeFrom': time_from_sec,
                        'timeTo': time_to_sec,
                        'deviceInclude': [device_id, None],
                    }
                else:
                    label = f'📦 Fujifilm-{device_id} install from {time_from_str}'
                    filt = {'timeFrom': time_from_sec, 'deviceInclude': [device_id, None]}

                presets[preset_id] = {
                    'id': preset_id,
                    'label': label,
                    'description': label,
                    'filters': filt,
                }

        return presets
