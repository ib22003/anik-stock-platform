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
    timestamp_pattern = r'^\[(\d{1,2}/\d{1,2}/\d{2,4}),\s?(\d{1,2}:\d{2}:\d{2}\s?[AP]M)\]'
    
    lines = content.split('\n')
    
    for line in lines:
        line = line.strip()
        
        # --- A. Check for Timestamp & Header ---
        ts_match = re.match(timestamp_pattern, line)
        if ts_match:
            current_date = ts_match.group(1)
            current_time = ts_match.group(2)
            
            # Extract message content
            parts = line.split(':', 2) 
            if len(parts) > 2:
                message_content = parts[2].strip()
            else:
                continue 

            # --- HEADER DETECTION ---
            if "Goods" in message_content and "Needed" not in message_content:
                # Reset defaults
                current_source = "Unknown"
                current_dest = "Unknown"
                
                text_lower = message_content.lower()
                
                # 1. Extract SOURCE (From X)
                if "from " in text_lower:
                    start_idx = text_lower.find("from ") + 5
                    end_idx = text_lower.find(" to ")
                    
                    if end_idx != -1 and end_idx > start_idx:
                        current_source = message_content[start_idx:end_idx].strip()
                    else:
                        raw_source = message_content[start_idx:].strip()
                        current_source = re.split(r' on \d', raw_source, flags=re.IGNORECASE)[0].strip()

                # 2. Extract DESTINATION (To Y)
                if " to " in text_lower:
                    start_idx = text_lower.find(" to ") + 4
                    end_idx = text_lower.find(" from ")
                    
                    if end_idx != -1 and end_idx > start_idx:
                        current_dest = message_content[start_idx:end_idx].strip()
                    else:
                        raw_dest = message_content[start_idx:].strip()
                        current_dest = re.split(r' on \d', raw_dest, flags=re.IGNORECASE)[0].strip()
                
                if current_source == "Unknown" and "offloaded" in text_lower:
                    current_source = "Container/External"
                
                is_valid_transaction = True
                continue 

            # Disable transaction if it's a conversation message (no numbers)
            if is_valid_transaction:
                if not re.search(r'\d', message_content):
                    is_valid_transaction = False

        # --- B. Process Items ---
        if is_valid_transaction:
            if "Goods" in line or "Needed" in line: continue
            
            # Handle item lines that might start with a timestamp (rare but happens)
            target_text = line
            if line.startswith("["):
                parts = line.split(':', 2)
                if len(parts) > 2:
                    target_text = parts[2].strip()
                else:
                    continue
            
            clean_text = re.sub(r'^\d+[\).]\s?', '', target_text)
            
            # FOOL-PROOF ITEM REGEX
            item_match = re.search(r'(.+?)[:\-\s]+(\d+)\s*(pcs|ctns|sets|dozens|packs|pc|ctn|set|dozen|pack|kg|g|L)?\s*$', clean_text, re.IGNORECASE)
            
            if item_match:
                item_name = item_match.group(1).strip()
                qty = item_match.group(2)
                unit = item_match.group(3) if item_match.group(3) else "pcs"
                
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
    if not df.empty:
        df = df.drop_duplicates()
        df["Date"] = pd.to_datetime(df["Date"], errors='coerce')

    return df

# --- USER INTERFACE ---
st.title("📦 Anik Stores - Warehouse Platform")
st.markdown("Upload your chat file to see Stock Levels, Movements, and Reports.")

uploaded_file = st.file_uploader("Upload WhatsApp Chat (.txt)", type="txt")

if uploaded_file:
    text_content = uploaded_file.read().decode("utf-8")
    df = parse_chat_log(text_content)
    
    if not df.empty:
        # --- METRICS ---
        st.divider()
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Items Moved", f"{df['Quantity'].sum():,}")
        c2.metric("Transactions", len(df))
        c3.metric("Unique Items", df['Item'].nunique())
        
        # Calculate Busiest Day safely
        if not df['Date'].isnull().all():
            busiest_day = df['Date'].dt.date.mode()[0]
            c4.metric("Busiest Day", str(busiest_day))
        else:
            c4.metric("Busiest Day", "N/A")
        
        st.divider()
        
        # --- TABS ---
        tab1, tab2, tab3 = st.tabs(["🏭 Store Inventory", "📊 Analytics", "📄 Full Data"])
        
        # --- TAB 1: INVENTORY (NEW) ---
        with tab1:
            st.subheader("Stock Levels by Location")
            st.info("💡 Calculation: (Total Received) - (Total Sent) = Current Balance")
            
            # 1. Get List of All Locations
            all_locations = sorted(list(set(df['Source'].unique()) | set(df['Destination'].unique())))
            
            # 2. Select Location
            selected_location = st.selectbox("Select a Store / Warehouse:", all_locations)
            
            if selected_location:
                # 3. Calculate Inflow (Received)
                inflow = df[df['Destination'] == selected_location].groupby('Item')['Quantity'].sum().reset_index()
                inflow.columns = ['Item', 'Received']
                
                # 4. Calculate Outflow (Sent)
                outflow = df[df['Source'] == selected_location].groupby('Item')['Quantity'].sum().reset_index()
                outflow.columns = ['Item', 'Sent']
                
                # 5. Merge Data
                inventory = pd.merge(inflow, outflow, on='Item', how='outer').fillna(0)
                inventory['Current Balance'] = inventory['Received'] - inventory['Sent']
                
                # Formatting
                inventory = inventory.sort_values(by='Current Balance', ascending=False)
                
                # Display
                st.dataframe(inventory, use_container_width=True)
                
                # Download Button for this specific store
                csv_store = inventory.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label=f"📥 Download {selected_location} Stock",
                    data=csv_store,
                    file_name=f"{selected_location}_stock.csv",
                    mime="text/csv"
                )

        # --- TAB 2: ANALYTICS ---
        with tab2:
            col1, col2 = st.columns(2)
            with col1:
                st.subheader("Top Destinations")
                chart_df = df[df['Destination'] != "Unknown"]
                if not chart_df.empty:
                    dest_group = chart_df.groupby("Destination")["Quantity"].sum().reset_index().sort_values("Quantity", ascending=False)
                    fig_dest = px.bar(dest_group, x="Quantity", y="Destination", orientation='h')
                    st.plotly_chart(fig_dest, use_container_width=True)

            with col2:
                st.subheader("Daily Activity")
                if not df['Date'].isnull().all():
                    daily_group = df.groupby("Date")["Quantity"].sum().reset_index()
                    fig_date = px.line(daily_group, x="Date", y="Quantity", markers=True)
                    st.plotly_chart(fig_date, use_container_width=True)

        # --- TAB 3: FULL DATA ---
        with tab3:
            st.subheader("Transaction Log")
            
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
            
            # Drop Time column for cleaner display
            display_cols = ['Date', 'Source', 'Destination', 'Item', 'Quantity', 'Unit']
            st.dataframe(view_df[display_cols], use_container_width=True)
            
            # Download Full Report
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                view_df.to_excel(writer, index=False)
                
            st.download_button(
                label="📥 Download Full Report",
                data=buffer.getvalue(),
                file_name="anik_inventory_report.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

    else:
        st.warning("No data found. The chat file might be empty or the format is completely different.")
