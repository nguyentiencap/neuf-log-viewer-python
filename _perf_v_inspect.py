"""
Inspect the actual V (number of unique keys in emitted_starts) and
max candidates per key at each scenario for 100,000 items.
"""
import sys
import random
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from src.lz77_grouping import _find_longest_match

# ---- patched engine ----

def instrumented(items, min_match=1):
    n    = len(items)
    keys = items  # already strings

    handled         = set()
    emitted_starts  = {}
    result          = []
    running_total   = 0   # sum of all list lengths — updated incrementally
    max_total       = 0
    # per-key list length tracked via len(emitted_starts[k]) directly
    max_list_len    = 0

    for i in range(n):
        if i in handled:
            continue
        match = _find_longest_match(keys, i, emitted_starts)
        if match is None or match[1] < min_match:
            result.append(keys[i])
            lst = emitted_starts.setdefault(keys[i], [])
            lst.append(i)
            running_total += 1                          # O(1)
            if running_total > max_total:
                max_total = running_total
            if len(lst) > max_list_len:
                max_list_len = len(lst)
        else:
            ms, ml = match
            for off in range(ml):
                handled.add(i + off)

    V = len(emitted_starts)
    return V, max_total, max_list_len, len(result)


# ---- build scenarios ----

rng_4  = random.Random(42)
rng_26 = random.Random(42)
rng_m  = random.Random(7)
vocab  = [f"msg_{i:04d}" for i in range(500)]

N = 100_000
scenarios = [
    ("all_unique   ",  [f"key_{i:07d}" for i in range(N)],                      1),
    ("high_rep a=4 ",  [rng_4.choice("ABCD") for _ in range(N)],                1),
    ("high_rep a=26",  [rng_26.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ") for _ in range(N)], 1),
    ("block_repeat ",  (sum([[f"L{b:03d}_{l:03d}" for l in range(50)]
                             for b in range(20)] * 100, []))[:N],                1),
    ("random_mixed ",  [rng_m.choice(vocab) for _ in range(N)],                 1),
    ("all_same     ",  ["A"] * N,                                                1),
    ("rand min_m=2 ",  [random.Random(7).choice(vocab) for _ in range(N)],      2),
    ("rand min_m=5 ",  [random.Random(7).choice(vocab) for _ in range(N)],      5),
]

header = f"  {'Scenario':<16}  {'min_m':>5}  {'V (keys)':>9}  {'max_entries':>11}  {'max/key':>7}  {'kept':>7}"
print("\n" + "=" * len(header))
print(header)
print("=" * len(header))

for name, data, mm in scenarios:
    V, max_total, max_ml, kept = instrumented(data, min_match=mm)
    print(f"  {name}  {mm:>5}  {V:>9,}  {max_total:>11,}  {max_ml:>7,}  {kept:>7,}")

print("=" * len(header))
print("""
Columns:
  V (keys)    = number of distinct keys ever emitted (size of emitted_starts dict)
  max_entries = peak total positions stored across ALL lists in emitted_starts
  max/key     = peak length of the longest single candidate list
  kept        = items surviving into result
""")
