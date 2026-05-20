"""
Log Parser Module (Python port of src/log-parser.js)
Handles parsing of individual NEUF log entries.
Responsibility: Parse log line format and extract structured data.
Uses service object pattern to encapsulate parsing operations.
"""

import re
import calendar


class LogParserService:
    """
    Log Parser Service.
    Encapsulates all log parsing operations.
    Port of JavaScript LogParserService in src/log-parser.js.
    """

    # Pre-compiled regex patterns
    _TIMESTAMP_RE = re.compile(r'^(\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}:\d{2}\.\d{3})')
    _LEVEL_RE = re.compile(r'^\[(\w+)\]')
    _CLASS_RE = re.compile(r'^(?:class\s+[\w.]+):\s+')
    _THREAD_RE = re.compile(r'^([^:]+):')
    _DEVICE_RE = re.compile(r'^<([^>]+)>\s+')
    _COMPONENT_RE = re.compile(r'^\(([^)]+)\)')
    _TS_PARTS_RE = re.compile(
        r'^(\d{4})\.(\d{2})\.(\d{2}) (\d{2}):(\d{2})(?::(\d{2}))?'
    )

    def parse_line(self, line, filename):
        """
        Parse a log line to extract all structured log fields.

        @param line: Raw log line string
        @param filename: Source filename string
        @returns: Dict or None
        """
        if not line:
            return None

        # Step 1: Extract timestamp
        m = self._TIMESTAMP_RE.match(line)
        if not m:
            return None

        timestamp = m.group(1)
        time_bucket = self.get_time_bucket(timestamp)
        remaining = line[len(m.group(0)):].strip()

        # Step 2: Extract log level
        lm = self._LEVEL_RE.match(remaining)
        if not lm:
            return None

        log_level = lm.group(1)
        remaining = remaining[len(lm.group(0)):].strip()

        # Step 3: Skip optional class prefix
        cm = self._CLASS_RE.match(remaining)
        if cm:
            remaining = remaining[len(cm.group(0)):]

        # Step 4: Extract thread name
        tm = self._THREAD_RE.match(remaining)
        if not tm:
            return None

        thread_name = tm.group(1).strip()
        remaining = remaining[len(tm.group(0)):].strip()

        # Step 5: Extract optional device ID
        device_id = None
        dm = self._DEVICE_RE.match(remaining)
        if dm:
            device_id = dm.group(1)
            remaining = remaining[len(dm.group(0)):]

        # Step 6: Extract optional component name
        component_name = None
        comp_m = self._COMPONENT_RE.match(remaining)
        if comp_m:
            component_name = self.normalize_component_name(comp_m.group(1))
            remaining = remaining[len(comp_m.group(0)):].strip()

        # Step 7: Remaining content is message
        message = remaining

        return {
            'filename': filename,
            'timestamp': timestamp,
            'timeBucket': time_bucket,
            'logLevel': log_level,
            'threadName': self.normalize_thread_name(thread_name),
            'deviceId': device_id,
            'componentName': component_name,
            'message': message,
        }

    def detect_log_line_start(self, line):
        """
        Detect if a line starts a new log entry.

        @param line: Raw log line string
        @returns: Dict with key (timestamp) or None
        """
        if not line:
            return None

        m = self._TIMESTAMP_RE.match(line)
        if not m:
            return None

        return {'timestamp': m.group(1)}

    def normalize_component_name(self, component_name):
        """
        Normalize component name by extracting everything before the last dot.

        @param component_name: Raw component name string or None
        @returns: Normalized string or None
        """
        if not component_name:
            return None

        last_dot = component_name.rfind('.')
        if last_dot <= 0:
            return component_name
        return component_name[:last_dot]

    def normalize_thread_name(self, thread_name):
        """
        Normalize thread name by removing trailing numeric suffix after dash.

        @param thread_name: Raw thread name or None
        @returns: Normalized string
        """
        if not thread_name:
            return 'unknown'
        return re.sub(r'-\d+$', '', thread_name)

    def get_time_bucket(self, value):
        """
        Convert a timestamp to Unix seconds (UTC).

        @param value: str, int, float or None
        @returns: int (Unix seconds) or None
        """
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return value
        try:
            m = self._TS_PARTS_RE.match(str(value))
            if not m:
                return None
            year   = int(m.group(1))
            month  = int(m.group(2))
            day    = int(m.group(3))
            hour   = int(m.group(4))
            minute = int(m.group(5))
            second = int(m.group(6)) if m.group(6) else 0
            return int(calendar.timegm((year, month, day, hour, minute, second, 0, 0, 0)))
        except Exception:
            return None

    def format_log_entry(self, log, format_type='full'):
        """
        Format log entry for display/export.

        @param log: Log entry dict
        @param format_type: 'full' | 'compact' | 'json'
        @returns: Dict with original log fields plus 'formattedLog' key
        """
        timestamp = log.get('timestamp', '')
        formatted_log = ''

        if format_type == 'compact':
            formatted_log = f"({log.get('filename')}) {timestamp} [{log.get('log_level')}]"
            if log.get('component_name'):
                formatted_log += f" ({log.get('component_name')})"

            is_error = (log.get('log_level') or '').upper() == 'ERROR'
            message = log.get('message', '')
            if not is_error and message and len(message) > 750:
                message = message[:750] + '...'
            formatted_log = (formatted_log + ' ' + message).strip()
        else:
            # Full format (default)
            formatted_log = (
                f"({log.get('filename')}) {timestamp} [{log.get('log_level')}]"
                f" {log.get('thread_name')}:"
            )
            if log.get('device_id'):
                formatted_log += f" <{log.get('device_id')}>"
            if log.get('component_name'):
                formatted_log += f" ({log.get('component_name')})"
            formatted_log = (formatted_log + ' ' + log.get('message', '')).strip()

        return {
            'id': log.get('id'),
            'filename': log.get('filename'),
            'timestamp': log.get('timestamp'),
            'thread_name': log.get('thread_name'),
            'device_id': log.get('device_id'),
            'component_name': log.get('component_name'),
            'log_level': log.get('log_level'),
            'time_bucket': log.get('time_bucket'),
            'message': log.get('message'),
            'formattedLog': formatted_log,
        }


# Singleton instance for stateless service (mirrors JS export pattern)
log_parser_service = LogParserService()
default_log_parser_service = log_parser_service
