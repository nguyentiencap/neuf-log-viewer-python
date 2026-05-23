import sys
import os

from src.repair_grouping import RePairGroupingAlgorithm

class ModifiedRePair(RePairGroupingAlgorithm):
    def group(self, items, key_fn=None, **kwargs):
        # We need to override group just to inject the action-merge logic,
        # but to test it, let's just patch the method directly.
        pass

def patch_repair():
    original_run_repair = RePairGroupingAlgorithm.group
    
    def group(self, items, key_fn=None, **kwargs):
        if key_fn is None:
            key_fn = lambda x: x
        
        # We need the full implementation of group to inject the merge logic
        from src.grouping_interface import GroupingResult
        from src.repair_grouping import _run_repair
        
        keys = [key_fn(item) for item in items]
        rules, _final, rule_first_pos, drop_ranges, rule_all_starts = _run_repair(keys)
        
        on_duplicate = kwargs.get('on_duplicate')
        
        if not drop_ranges:
            deduplicated = list(items)
        else:
            action = [None] * len(keys)
            for (start, end, first_orig) in drop_ranges:
                action[start] = (end, first_orig)
                for k in range(start + 1, end + 1):
                    action[k] = -1
                    
            # --- MERGE LOGIC ---
            idx = 0
            while idx < len(items):
                act = action[idx]
                if act is None or act == -1:
                    idx += 1
                    continue
                
                end, first_orig = act
                next_idx = end + 1
                while next_idx < len(items):
                    next_act = action[next_idx]
                    if next_act is None or next_act == -1:
                        break
                    
                    next_end, next_first_orig = next_act
                    if next_first_orig == first_orig + (end - idx + 1):
                        end = next_end
                        action[idx] = (end, first_orig)
                        action[next_idx] = -1
                        next_idx = end + 1
                    else:
                        break
                idx = end + 1
            # -------------------
            
            deduplicated = []
            idx = 0
            while idx < len(items):
                act = action[idx]
                if act is None:
                    deduplicated.append(items[idx])
                    idx += 1
                elif act == -1:
                    idx += 1
                else:
                    end, first_orig = act
                    if on_duplicate:
                        annotated = on_duplicate(items, idx, first_orig, end - idx + 1)
                        if annotated is not None:
                            deduplicated.append(annotated)
                    idx = end + 1
                    
        return GroupingResult(deduplicated=deduplicated, dictionary=[])
        
    RePairGroupingAlgorithm.group = group

def main():
    patch_repair()
    
    # 9-12: A,B,C,D
    # 50-51: A,B
    # 60-61: C,D
    # 100-103: A,B,C,D
    items = []
    for i in range(8): items.append({'timestamp': str(i)})
    items.extend([{'timestamp': 'A'}, {'timestamp': 'B'}, {'timestamp': 'C'}, {'timestamp': 'D'}]) # 8-11
    for i in range(38): items.append({'timestamp': str(i+20)})
    items.extend([{'timestamp': 'A'}, {'timestamp': 'B'}]) # 50-51
    for i in range(8): items.append({'timestamp': str(i+60)})
    items.extend([{'timestamp': 'C'}, {'timestamp': 'D'}]) # 60-61
    for i in range(38): items.append({'timestamp': str(i+80)})
    items.extend([{'timestamp': 'A'}, {'timestamp': 'B'}, {'timestamp': 'C'}, {'timestamp': 'D'}]) # 100-103
    
    def on_duplicate(items, dup_pos, match_start, match_len):
        start_ts = items[match_start].get('timestamp', '')
        if match_len == 1:
            return f"Index {dup_pos}: Same as {start_ts}"
        else:
            end_ts = items[match_start + match_len - 1].get('timestamp', '')
            return f"Index {dup_pos}: Same as {start_ts} -> {end_ts}"

    alg = RePairGroupingAlgorithm()
    res = alg.group(items, lambda x: x['timestamp'], on_duplicate=on_duplicate)
    
    print("=== DEDUPLICATED ===")
    for i, it in enumerate(res.deduplicated):
        if isinstance(it, str) and it.startswith("Index"):
            print(it)

if __name__ == '__main__':
    main()
