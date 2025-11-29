def parse_chat_log(content):
    data = []
    
    # State variables
    current_date = None
    current_time = None  # NEW: Track time to prevent duplicates
    current_source = None
    current_dest = None
    is_valid_transaction = False
    
    # 1. Regex to find Date AND Time
    # Matches: [1/27/25, 8:07:58 AM]
    timestamp_pattern = r'^\[(\d{1,2}/\d{1,2}/\d{2,4}),\s?(\d{1,2}:\d{2}:\d{2}\s?[AP]M)\]'
    
    # 2. Movement Headers
    movement_pattern = r'Goods (?:Received )?(?:From|Offloaded) (.+?) (?:to|To) (.+?)(?: on|$)'
    
    # 3. Items (Ignore lines starting with [ to avoid timestamp errors)
    item_pattern = r'^([^\[]+?)(?::|-| -)\s?(\d+)\s?([a-zA-Z]+)?'

    lines = content.split('\n')
    
    for line in lines:
        line = line.strip()
        
        # --- A. Check for Timestamp ---
        ts_match = re.match(timestamp_pattern, line)
        if ts_match:
            current_date = ts_match.group(1)
            current_time = ts_match.group(2) # Capture time
            
            # Reset transaction state
            is_valid_transaction = False

            # EXCLUDE "Goods Needed"
            if "Needed" in line:
                continue

            # CHECK for valid movement header
            move_match = re.search(movement_pattern, line, re.IGNORECASE)
            if move_match:
                current_source = move_match.group(1).strip()
                raw_dest = move_match.group(2).strip()
                current_dest = raw_dest.split(' on ')[0].strip()
                is_valid_transaction = True
                continue 

        # --- B. Process Items ---
        if is_valid_transaction and current_source and current_dest:
            if line.startswith("["): continue

            clean_line = re.sub(r'^\d+[\).]\s?', '', line)
            
            item_match = re.search(item_pattern, clean_line)
            if item_match:
                item_name = item_match.group(1).strip()
                qty = item_match.group(2)
                unit = item_match.group(3) if item_match.group(3) else "pcs"
                
                if len(item_name) > 2:
                    data.append({
                        "Date": current_date,
                        "Time": current_time, # Store time for ID
                        "Source": current_source,
                        "Destination": current_dest,
                        "Item": item_name,
                        "Quantity": int(qty),
                        "Unit": unit.lower()
                    })

    df = pd.DataFrame(data)
    
    # --- C. THE DUPLICATE CHECKER ---
    # This removes rows where EVERYTHING (Date, Time, Item, Qty) is exactly the same.
    if not df.empty:
        df = df.drop_duplicates()
        
    return df
