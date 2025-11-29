import streamlit as st
import pandas as pd
import re
import plotly.express as px
import io

# --- CONFIGURATION ---
st.set_page_config(page_title="Anik Stores Inventory", layout="wide")

# --- PARSING ENGINE (FOOL-PROOF VERSION) ---
def parse_chat_log(content):
    data = []
    
    # State variables
    current_date = None
    current_time = None
    current_source = "Unknown"
    current_dest = "Unknown"
    is_valid_transaction = False
    
    # 1. Timestamp Pattern
    # Matches: [1/27/25, 8:07:58 AM]
    timestamp_pattern = r'^\[(\d{1,2}/\d{1,2}/\d{2,4}),\s?(\d{1,2}:\d{2}:\d{2}\s?[AP]M)\]'
    
    lines = content.split('\n')
    
    for line in lines:
        line = line.strip()
        
        # --- A. Check for Timestamp & Header ---
        ts_match = re.match(timestamp_pattern, line)
        if ts_match:
            current_date = ts_match.group(1)
            current_time = ts_match.group(2)
            
            # Extract the message content after the timestamp
            # format: [Date, Time] Sender: Message
            parts = line.split(':', 2) # Split into max 3 parts
            if len(parts) > 2:
                message_content = parts[2].strip()
            else:
                continue # Skip malformed lines

            # --- HEADER DETECTION LOGIC ---
            # We look for "Goods" to start a transaction block
            if "Goods" in message_content and "Needed" not in message_content:
                # Reset defaults
                current_source = "Unknown"
                current_dest = "Unknown"
                
                # normalize text for searching
                text_lower = message_content.lower()
                
                # 1. Extract SOURCE (From X)
                if "from " in text_lower:
                    # Find text between "from" and "to" (if to exists)
                    start_idx = text_lower.find("from ") + 5
                    end_idx = text_lower.find(" to ")
                    
                    if end_idx != -1 and end_idx > start_idx:
                        # "From X To Y" format
                        current_source = message_content[start_idx:end_idx].strip()
                    else:
                        # "From X ..." (end of string or followed by date)
                        # Remove trailing "on [Date]" if present
                        raw_source = message_content[start_idx:].strip()
                        current_source = re.split(r' on \d', raw_source, flags=re.IGNORECASE)[0].strip()

                # 2. Extract DESTINATION (To Y)
                if " to " in text_lower:
                    start_idx = text_lower.find(" to ") + 4
                    # Check if "from" comes AFTER "to" (e.g. "Goods to Shop 1 from Store 4")
                    end_idx = text_lower.find(" from ")
                    
                    if end_idx != -1 and end_idx > start_idx:
                        current_dest = message_content[start_idx:end_idx].strip()
                    else:
                        # "To Y ..."
                        raw_dest = message_content[start_idx:].strip()
                        current_dest = re.split(r' on \d', raw_dest, flags=re.IGNORECASE)[0].strip()
                
                # 3. Handle "Offloaded" or "Received" as generic sources if From is missing
                if current_source == "Unknown" and "offloaded" in text_lower:
                    current_source = "Container/External"
                
                is_valid_transaction = True
                continue # Header processed, move to next line

            # If it's a new message but NOT a header, disable transaction 
            # (unless it's a continuation of a list, which usually doesn't have a new timestamp)
            # However, sometimes people send:
            # [Time] Header
            # [Time] Item 1
            # So we only disable if it looks like a conversation, not a list item.
            # We'll use a heuristic: If it has numbers and units, keep transaction open.
            if is_valid_transaction:
                if not re.search(r'\d', message_content):
                    is_valid_transaction = False

        # --- B. Process Items ---
        if is_valid_transaction:
            # Ignore the header line itself if we just processed it
            if "Goods" in line and "Needed" not in line:
                continue
                
            # Ignore timestamps lines (we already processed them above, this catches the item text part)
            # But wait, if the item is ON the same line as the timestamp, we need to extract it.
            # We already extracted message_content above. 
            
            # Let's clean the line for Item Processing
            # If line starts with [, it's a new message. We use the 'message_content' we extracted.
            # If line doesn't start with [, it's a continuation line.
            
            target_text = line
            if line.startswith("["):
                parts = line.split(':', 2)
                if len(parts) > 2:
                    target_text = parts[2].strip()
                else:
                    continue
            
            # Skip noise
            if "Goods" in target_text or "message was deleted" in target_text:
                continue

            # Clean numbering (1. Item, 2) Item)
            clean_text = re.sub(r'^\d+[\).]\s?', '', target_text)
            
            # FOOL-PROOF ITEM REGEX
            # Looks for: (Item Name) (Separator OR Space) (Quantity) (Unit)
            # This handles: "Item: 9pcs", "Item - 9pcs", "Item 9pcs"
            # It grabs the LAST number in the string to be safe.
            item_match = re.search(r'(.+?)[:\-\s]+(\d+)\s*(pcs|ctns|sets|dozens|packs|pc|ctn|set|dozen|pack|kg|g|L)?\s*$', clean_text, re.IGNORECASE)
            
            if item_match:
                item_name = item_match.group(1).strip()
                qty = item_match.group(2)
                unit = item_match.group(3) if item_match.group(3) else "pcs"
                
                # Final cleanup of item name (remove trailing separators)
                item_name = item_name.rstrip(":- ")

                if len(item_name) > 1:
                    data.append({
                        "Date": current_date,
                        "Time": current_time,
                        "Source": current_source,
                        "Destination": current_dest,
                        "Item": item_name,
                        "Quantity": int(qty),
                        "Unit": unit.lower()
                    })

    df = pd.DataFrame(data)
    
    # Drop exact duplicates (Same time, same item)
    if not df.empty:
        df = df.drop_duplicates()

    return df

# --- USER INTERFACE ---
st.title("📦 Anik Stores - Warehouse Platform")
st.markdown("""
**System Status: FOOL-PROOF MODE**
* Captures incomplete headers (e.g. "Goods from Warehouse" -> Destination: Unknown)
* Captures items with missing colons (e.g. "Item 50pcs")
* Removes duplicates automatically.
""")

uploaded_file = st.file_uploader("Upload WhatsApp Chat (.txt)", type="txt")

if uploaded_file:
    text_content = uploaded_file.read().decode("utf-8")
    df = parse_chat_log(text_content)
    
    if not df.empty:
        df["Date"] = pd.to_datetime(df["Date"], errors='coerce')
        
        # --- METRICS ---
        st.divider()
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Items", f"{df['Quantity'].sum():,}")
        c2.metric("Transactions", len(df))
        c3.metric("Unique Items", df['Item'].nunique())
        # Safe mode for Busiest Day
        busiest_day = df['Date'].dt.date.mode()[0] if not df['Date'].isnull().all() else "N/A"
        c4.metric("Busiest Day", str(busiest_day))
        
        st.divider()
        
        # --- TABS ---
        tab1, tab2 = st.tabs(["📊 Analytics", "📄 Full Data"])
        
        with tab1:
            col1, col2 = st.columns(2)
            with col1:
                st.subheader("Top Destinations")
                # Clean up "Unknown" for better charting
                chart_df = df[df['Destination'] != "Unknown"]
                if not chart_df.empty:
                    dest_group = chart_df.groupby("Destination")["Quantity"].sum().reset_index().sort_values("Quantity", ascending=False)
                    fig_dest = px.bar(dest_group, x="Quantity", y="Destination", orientation='h')
                    st.plotly_chart(fig_dest, use_container_width=True)
                else:
                    st.info("Most transactions have 'Unknown' destination. Please check chat format.")

            with col2:
                st.subheader("Daily Activity")
                daily_group = df.groupby("Date")["Quantity"].sum().reset_index()
                fig_date = px.line(daily_group, x="Date", y="Quantity", markers=True)
                st.plotly_chart(fig_date, use_container_width=True)

        with tab2:
            st.subheader("Transaction Log")
            st.markdown("This table allows you to filter by specific items or dates.")
            
            # Dynamic Filters
            col_a, col_b = st.columns(2)
            with col_a:
                filter_item = st.text_input("Search Item Name")
            with col_b:
                filter_source = st.multiselect("Filter by Source", options=df['Source'].unique())
            
            # Apply Filters
            view_df = df.copy()
            if filter_item:
                view_df = view_df[view_df['Item'].str.contains(filter_item, case=False)]
            if filter_source:
                view_df = view_df[view_df['Source'].isin(filter_source)]
            
            st.dataframe(view_df, use_container_width=True)
            
            # Download
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                view_df.to_excel(writer, index=False)
                
            st.download_button(
                label="📥 Download Report",
                data=buffer.getvalue(),
                file_name="anik_inventory_report.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

    else:
        st.warning("No data found. The chat file might be empty or the format is completely different.")
