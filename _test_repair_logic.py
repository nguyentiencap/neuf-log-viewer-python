import json

# Dummy data
items = list("abcdabcdabce")
# A B C D -> A B C D -> A B C E
# R0 = a b
# R1 = c d
# R2 = R0 R1
# R3 = R0 c

def simulate_repair():
    keys = items
    # For a b c d a b c d a b c e
    
    # R0 -> a b (freq 3: 0, 4, 8)
    # R1 -> c d (freq 2: 2, 6)
    # R2 -> R0 R1 (freq 2: 0, 4)
    # R3 -> R0 c (freq 1, wait freq >=2 required) -> a b c e is R0 c e
    
    rules = [
        ('a', 'b', 3), # Rule 0
        ('c', 'd', 2), # Rule 1
        (0, 1, 2)      # Rule 2
    ]
    rule_first_pos = [0, 2, 0]
    drop_ranges = [
        (4, 5, 0, 0),
        (8, 9, 0, 0),
        (6, 7, 1, 2),
        (4, 7, 2, 0)
    ]
    
    action = [None] * len(keys)
    for (start, end, sym_id, first_orig) in drop_ranges:
        action[start] = (end, [(sym_id, first_orig, end - start + 1)])
        for k in range(start + 1, end + 1):
            action[k] = -1

    true_rule_duplicates = {}
    for idx in range(len(keys)):
        act = action[idx]
        if act is not None and act != -1:
            end, chunks = act
            sym_id = chunks[0][0]
            if sym_id not in true_rule_duplicates:
                true_rule_duplicates[sym_id] = []
            true_rule_duplicates[sym_id].append(idx)
            
    print("Action array:")
    for i, act in enumerate(action):
        print(f"{i}: {act}")
        
    print("\nTrue duplicates:")
    print(true_rule_duplicates)
    
simulate_repair()
