"""
Manual test runner for group_neuf_logs (NEUF log wrapper over LZ77 engine).
Run: python _test_run.py
"""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, '.')
from src.log_grouping import group_neuf_logs, group_similar_lines

# ─────────────────────────────────────────────────────────────────────────────
# Helper: build a minimal NEUF log line
# ─────────────────────────────────────────────────────────────────────────────

def line(msg, device="D1", component="C1", ts=None):
    return {
        "device_id":      device,
        "component_name": component,
        "message":        msg,
        "filename":       "NEUF-test.log",
        "timestamp":      ts or "2026.05.11 10:00:00.000",
        "log_level":      "DEBUG",
        "thread_name":    "Thread",
    }

def show(title, lines_input, filter_duplicate, **kwargs):
    flag_str = "filter=TRUE (remove)" if filter_duplicate else "filter=FALSE (annotate)"
    extra    = ", ".join(f"{k}={v}" for k, v in kwargs.items())
    label    = f"{flag_str}{', ' + extra if extra else ''}"
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"  [{label}]")
    print(f"{'='*60}")
    print("  INPUT :", [r["message"] for r in lines_input])
    result = group_neuf_logs(lines_input, filter_duplicate=filter_duplicate, **kwargs)
    print("  OUTPUT:", [r["message"] for r in result])
    return result

# ─────────────────────────────────────────────────────────────────────────────
# Scenario 1 — Single-line duplicates: [A, B, C, A, B]
# ─────────────────────────────────────────────────────────────────────────────
lines1 = [line(m) for m in ["A", "B", "C", "A", "B"]]
show("Scenario 1: [A,B,C,A,B]", lines1, filter_duplicate=True)
show("Scenario 1: [A,B,C,A,B]", lines1, filter_duplicate=False)

# ─────────────────────────────────────────────────────────────────────────────
# Scenario 2 — Two-line block: [A, B, C, A, B, D]
# ─────────────────────────────────────────────────────────────────────────────
lines2 = [line(m) for m in ["A", "B", "C", "A", "B", "D"]]
show("Scenario 2: [A,B,C,A,B,D]", lines2, filter_duplicate=True)
show("Scenario 2: [A,B,C,A,B,D]", lines2, filter_duplicate=False)

# ─────────────────────────────────────────────────────────────────────────────
# Scenario 3 — The big block-collapse case: [A,B,C,A,B,C,A,B]
# Expected filter=False: [A, B, C, "Giong dong 1-3", "Giong dong 1-2"]
# ─────────────────────────────────────────────────────────────────────────────
lines3 = [line(m) for m in ["A", "B", "C", "A", "B", "C", "A", "B"]]
show("Scenario 3: [A,B,C,A,B,C,A,B]", lines3, filter_duplicate=True)
show("Scenario 3: [A,B,C,A,B,C,A,B]", lines3, filter_duplicate=False)

# ─────────────────────────────────────────────────────────────────────────────
# Scenario 4 — All unique (no grouping)
# ─────────────────────────────────────────────────────────────────────────────
lines4 = [line(m) for m in ["X", "Y", "Z", "W"]]
show("Scenario 4: All unique", lines4, filter_duplicate=True)

# ─────────────────────────────────────────────────────────────────────────────
# Scenario 5 — Same message, different devices: should NOT be grouped
# ─────────────────────────────────────────────────────────────────────────────
lines5 = [line("Same msg", device="D1"), line("Same msg", device="D2")]
show("Scenario 5: Same msg, different device", lines5, filter_duplicate=True)

# ─────────────────────────────────────────────────────────────────────────────
# Scenario 6 — Three identical lines
# ─────────────────────────────────────────────────────────────────────────────
lines6 = [line("X") for _ in range(3)]
show("Scenario 6: Three identical lines", lines6, filter_duplicate=True)
show("Scenario 6: Three identical lines", lines6, filter_duplicate=False)

# ─────────────────────────────────────────────────────────────────────────────
# Scenario 7 — max_match_len=1 caps to single-line matches
# ─────────────────────────────────────────────────────────────────────────────
lines7 = [line(m) for m in ["A", "B", "C", "A", "B"]]
show("Scenario 7: max_match_len=1", lines7, filter_duplicate=True, max_match_len=1)

# ─────────────────────────────────────────────────────────────────────────────
# Scenario 8 — Custom key_fn via generic API (non-log items)
# ─────────────────────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print("  Scenario 8: Generic API with custom key_fn (strings)")
print(f"{'='*60}")
words = ["hello", "world", "hello", "world", "foo"]
print("  INPUT :", words)
result8 = group_similar_lines(
    items        = words,
    key_fn       = lambda w: w,
    on_duplicate = lambda item, ds, ms, ml: f"[dup of pos {ms+1}]",
)
print("  OUTPUT:", result8)

print("\nDone.")
