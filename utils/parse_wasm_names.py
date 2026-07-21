import sys

def read_leb128(data, pos):
    result = 0
    shift = 0
    while True:
        b = data[pos]
        pos += 1
        result |= (b & 0x7f) << shift
        if not (b & 0x80):
            break
        shift += 7
    return result, pos

def parse_wasm_names(wasm_path, target_indices):
    print(f"Reading {wasm_path}...")
    with open(wasm_path, 'rb') as f:
        data = f.read()
    
    # Check magic
    if data[:4] != b'\x00asm':
        print("Not a valid WASM file")
        return
        
    pos = 8 # Skip magic and version
    data_len = len(data)
    
    names_map = {}
    
    while pos < data_len:
        sec_id = data[pos]
        pos += 1
        sec_len, pos = read_leb128(data, pos)
        next_sec_pos = pos + sec_len
        print(f"Section ID: {sec_id}, Length: {sec_len}")
        
        if sec_id == 0: # Custom section
            name_len, pos = read_leb128(data, pos)
            sec_name = data[pos:pos+name_len].decode('utf-8', errors='ignore')
            print(f"Found custom section: {sec_name}")
            pos += name_len
            
            if sec_name == "name":
                print("Found 'name' section!")
                # Parse name subsections
                while pos < next_sec_pos:
                    sub_id = data[pos]
                    pos += 1
                    sub_len, pos = read_leb128(data, pos)
                    next_sub_pos = pos + sub_len
                    
                    if sub_id == 1: # Function names
                        num_names, pos = read_leb128(data, pos)
                        print(f"Parsing {num_names} function names...")
                        for _ in range(num_names):
                            if pos >= next_sub_pos:
                                break
                            func_idx, pos = read_leb128(data, pos)
                            fn_name_len, pos = read_leb128(data, pos)
                            fn_name = data[pos:pos+fn_name_len].decode('utf-8', errors='ignore')
                            pos += fn_name_len
                            if func_idx in target_indices:
                                names_map[func_idx] = fn_name
                    else:
                        pos = next_sub_pos
                break
        
        pos = next_sec_pos

    print("\n--- Results ---")
    for idx in sorted(target_indices):
        name = names_map.get(idx, "UNKNOWN")
        print(f"WASM Function {idx}: {name}")

if __name__ == '__main__':
    wasm_file = "/Volumes/SSD/re3DOS/re3sky/game.wasm"
    targets = [2243, 3510, 3507, 2342, 2721]
    parse_wasm_names(wasm_file, targets)
