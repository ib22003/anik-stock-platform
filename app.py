import streamlit as st
import pandas as pd
import re
import plotly.express as px
import io

# --- CONFIGURATION ---
st.set_page_config(page_title="Anik Stores Inventory", layout="wide")

# --- PARSING ENGINE ---
def parse_chat_log(content):
    data = []
    
    # State variables
    current_date = None
    current_time = None
    current_source = None
    current_dest = None
    is_valid_transaction = False
    
    # 1. Regex to find Date AND Time (to track unique messages)
    # Matches: [1/27/25, 8:07:58 AM]
    timestamp_pattern = r'^\[(\d{1,2}/\d{1,2}/\d{2,4}),\s?(\d{1,2}:\d{2}:\d{2}\s?[AP]M)\]'
    
    # 2. Regex to find Movement Headers (Source -> Destination)
    # Handles: "Goods From Store 4 to Shop 1", "Goods Received From Warehouse to Store"
    movement_pattern = r'Goods (?:Received )?(?:From|Offloaded) (.+?) (?:to|To) (.+?)(?: on|$)'
    
    # 3. Regex for Items
    # Handles: "Item Name: 50pcs" or "Item Name - 1ctn"
    # The ^([^\[]+?) part ensures we DO NOT match lines starting with [ (timestamps)
    item_pattern = r'^([^\[]+?)(?::|-| -)\s?(\d+)\s?([a-zA-Z]+)?'

    lines = content.split('\n')
    
    for line in lines:
        line = line.strip()
        
        # --- A. Check for Timestamp ---
        ts_match = re.match(timestamp_pattern, line)
        if ts_match:
            current_date = ts_match.group(1)
            current_time = ts_match.group(2)
            
            # Reset transaction state
            # If a new message starts, we assume the previous transaction list ended
            # unless this message is a HEADER or a continuation.
            is_valid_transaction = False

            # EXCLUDE "Goods Needed" messages (Request vs Actual Movement)
            if "Needed" in line:
                continue

            # CHECK for valid movement header
            move_match = re.search(movement_pattern, line, re.IGNORECASE)
            if move_match:
                current_source = move_match.group(1).strip()
                # Clean up destination (remove trailing dates)
                raw_dest = move_match.group(2).strip()
                current_dest = raw_dest.split(' on ')[0].strip()
                is_valid_transaction = True
                continue 

        # --- B. Process Items (Inside valid transaction) ---
        if is_valid_transaction and current_source and current_dest:
            # SECURITY CHECK: Skip lines that look like timestamps to prevent errors
            if line.startswith("["):
                continue

            # Clean line (remove numbering like "1.", "1)")
            clean_line = re.sub(r'^\d+[\).]\s?', '', line)
            
            # Extract Item
            item_match = re.search(item_pattern, clean_line)
            if item_match:
                item_name = item_match.group(1).strip()
                qty = item_match.group(2)
                unit = item_match.group(3) if item_match.group(3) else "pcs"
                
                # Filter out short noise/dates
                if len(item_name) > 2 and " on " not in item_name:
                    data.append({
                        "Date": current_date,
                        "Time": current_time, # Used for de-duplication
                        "Source": current_source,
                        "Destination": current_dest,
                        "Item": item_name,
                        "Quantity": int(qty),
                        "Unit": unit.lower()
                    })

    df = pd.DataFrame(data)
    
    # --- C. DUPLICATE REMOVAL ---
    # If the exact same message appears twice (same time, same item, same qty), remove it.
    if not df.empty:
        df = df.drop_duplicates()

    return df

# --- USER INTERFACE ---
st.title("📦 Anik Stores - Warehouse Platform")
st.markdown("""
**How to use:**
1. Open your WhatsApp Group.
2. Tap Group Name -> **Export Chat** -> **Without Media**.
3. Upload the `_chat.txt` file below.
""")

uploaded_file = st.file_uploader("Upload WhatsApp Chat (.txt)", type="txt")

if uploaded_file:
    text_content = uploaded_file.read().decode("utf-8")
    df = parse_chat_log(text_content)
    
    if not df.empty:
        # Convert Date
        df["Date"] = pd.to_datetime(df["Date"], errors='coerce')
        
        # --- TOP METRICS ---
        st.divider()
        total_items = df['Quantity'].sum()
        top_dest = df['Destination'].mode()[0]
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Total Items Moved", f"{total_items:,}")
        c2.metric("Total Transactions", len(df))
        c3.metric("Top Receiver", top_dest)
        
        st.divider()
        
        # --- TABS ---
        tab1, tab2 = st.tabs(["📊 Dashboard", "📄 Stock Data"])
        
        with tab1:
            # 1. Movement by Shop
            st.subheader("Where is stock going?")
            dest_group = df.groupby("Destination")["Quantity"].sum().reset_index().sort_values("Quantity", ascending=False)
            fig_dest = px.bar(dest_group, x="Quantity", y="Destination", orientation='h', text="Quantity")
            st.plotly_chart(fig_dest, use_container_width=True)
            
            # 2. Source Analysis
            st.subheader("Where is stock coming from?")
            source_group = df.groupby("Source")["Quantity"].sum().reset_index()
            fig_src = px.pie(source_group, values="Quantity", names="Source", hole=0.4)
            st.plotly_chart(fig_src, use_container_width=True)

        with tab2:
            st.subheader("Search & Download")
            
            # Search Bar
            search = st.text_input("Search for an item (e.g. 'Korkmaz', 'Pizza Plate')")
            if search:
                display_df = df[df['Item'].str.contains(search, case=False, na=False)]
            else:
                display_df = df
            
            st.dataframe(display_df, use_container_width=True)
            
            # Excel Download
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                # Remove the 'Time' column from the export to keep it clean
                export_df = display_df.drop(columns=['Time'], errors='ignore')
                export_df.to_excel(writer, index=False, sheet_name='Stock Data')
                
            st.download_button(
                label="📥 Download as Excel",
                data=buffer.getvalue(),
                file_name="anik_stock_report.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

    else:
        st.warning("No stock movements found. Please upload a valid chat export.")
