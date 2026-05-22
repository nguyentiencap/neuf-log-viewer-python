"""
Scenario:
  1000 unique (u0_xxxx)
  [A, B, C, D, E, F]
  1000 unique (u1_xxxx)  <- different from first batch
  [A, B, C, E, F]        <- missing D vs first block
  1000 unique (u2_xxxx)  <- different again

Measure V (unique emitted keys), max_entries, max/key, and all match events.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.lz77_grouping import _find_longest_match, group_similar_lines


# ---- instrumented engine ----

def instrumented(items, min_match=1):
    n              = len(items)
    keys           = items
    handled        = set()
    emitted_starts = {}
    result         = []
    running_total  = 0
    max_total      = 0
    max_list_len   = 0
    match_events   = []

    for i in range(n):
        if i in handled:
            continue
        match = _find_longest_match(keys, i, emitted_starts)
        if match is None or match[1] < min_match:
            result.append(keys[i])
            lst = emitted_starts.setdefault(keys[i], [])
            lst.append(i)
            running_total += 1
            if running_total > max_total:  max_total    = running_total
            if len(lst) > max_list_len:    max_list_len = len(lst)
        else:
            ms, ml = match
            match_events.append((i, keys[i], ms, ml))
            for off in range(ml):
                handled.add(i + off)

    return len(emitted_starts), max_total, max_list_len, len(result), match_events, emitted_starts


# ---- build scenario ----

data = (
    [f"u0_{i:04d}" for i in range(1000)] +   # positions 0..999
    ["A", "B", "C", "D", "E", "F"] +          # positions 1000..1005
    [f"u1_{i:04d}" for i in range(1000)] +    # positions 1006..2005
    ["A", "B", "C", "E", "F"] +               # positions 2006..2010  (no D!)
    [f"u2_{i:04d}" for i in range(1000)]       # positions 2011..3010
)

print(f"Total items : {len(data)}")
print(f"Layout      : 1000 unique | A B C D E F | 1000 unique | A B C E F | 1000 unique")
print()

V, max_total, max_ml, kept, events, emitted = instrumented(data, min_match=1)

print(f"V  (emitted_starts keys) = {V:,}")
print(f"max_entries total        = {max_total:,}")
print(f"max list len per key     = {max_ml}")
print(f"kept in result           = {kept:,}")
print()

# show list lengths for A-F in emitted_starts
print("emitted_starts list lengths for block keys:")
for k in ["A", "B", "C", "D", "E", "F"]:
    lst = emitted.get(k, [])
    print(f"  '{k}' -> positions {lst}")
print()

print(f"Match events ({len(events)} total):")
for pos, key, ms, ml in events:
    print(f"  pos={pos:5d}  key={key!r:12}  match_start={ms:5d}  match_len={ml}")

print()
print("---- Breakdown ----")
print("  1000 unique u0: all emitted     -> +1000 keys")
print("  ABCDEF block 1: all emitted     -> +6 keys   (first occurrence)")
print("  1000 unique u1: all emitted     -> +1000 keys")
print("  ABCEF block 2 : match vs block1?  (see match events above)")
print("  1000 unique u2: all emitted     -> +1000 keys")
print("  Expected V = 1000+6+1000+?+1000 = 3006 or 3007 depending on D")
