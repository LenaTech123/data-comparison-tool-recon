import streamlit as st
import pandas as pd
from thefuzz import fuzz
import numpy as np
from datetime import datetime
from io import BytesIO
import json

def fuzzy_match(text1, text2, threshold=70):
    """Oskarp textmatchning"""
    if pd.isna(text1) or pd.isna(text2):
        return 0
    return fuzz.ratio(str(text1).lower(), str(text2).lower())

def clean_salesforce_data(df):
    """Rensa Salesforce-data"""
    # Konvertera Schedule Amount till float
    if 'Schedule Amount' in df.columns:
        df['Schedule Amount'] = pd.to_numeric(df['Schedule Amount'], errors='coerce')
    
    # Extrahera månad/år från datum
    if 'Date' in df.columns:
        df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
        df['Month_Year'] = df['Date'].dt.to_period('M').astype(str)
    elif 'Month' in df.columns:
        df['Month_Year'] = df['Month'].astype(str)
    else:
        df['Month_Year'] = '2024-01'
    
    return df

def clean_campaign_data(df):
    """Rensa kampanjdata"""
    # Konvertera Spent_client_currency till float
    if 'Spent_client_currency' in df.columns:
        df['Spent_client_currency'] = pd.to_numeric(df['Spent_client_currency'], errors='coerce')
    elif 'Spend' in df.columns:
        df['Spend'] = pd.to_numeric(df['Spend'], errors='coerce')
        df['Spent_client_currency'] = df['Spend']
    
    # Extrahera månad/år
    if 'Date' in df.columns:
        df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
        df['Month_Year'] = df['Date'].dt.to_period('M').astype(str)
    elif 'Month' in df.columns:
        df['Month_Year'] = df['Month'].astype(str)
    else:
        df['Month_Year'] = '2024-01'
    
    return df

def aggregate_campaign_data(df):
    """Aggregera kampanjdata per kampanj och månad"""
    if df is None or df.empty:
        return df
        
    # Anpassningsbara kolumnnamn
    client_col = None
    advertiser_col = None
    campaign_col = None
    campaign_id_col = None
    
    # Hitta rätt kolumner (flexibel mappning)
    for col in df.columns:
        col_lower = col.lower()
        if 'client' in col_lower and client_col is None:
            client_col = col
        elif 'advertiser' in col_lower and advertiser_col is None:
            advertiser_col = col
        elif 'campaign' in col_lower and 'name' in col_lower and campaign_col is None:
            campaign_col = col
        elif 'campaign' in col_lower and 'id' in col_lower and campaign_id_col is None:
            campaign_id_col = col
    
    grouping_columns = ['Month_Year']
    if client_col: grouping_columns.append(client_col)
    if advertiser_col: grouping_columns.append(advertiser_col)
    if campaign_col: grouping_columns.append(campaign_col)
    if campaign_id_col: grouping_columns.append(campaign_id_col)
    
    if 'Spent_client_currency' in df.columns and len(grouping_columns) > 1:
        try:
            aggregated = df.groupby(grouping_columns).agg({
                'Spent_client_currency': 'sum'
            }).reset_index()
            return aggregated
        except Exception as e:
            st.warning(f"Kunde inte aggregera data: {e}")
            return df
    
    return df

def find_best_match(sf_row, campaign_df, mappings):
    """Hitta bästa matchning för Salesforce-rad"""
    if campaign_df.empty:
        return None, 0
    
    # Flexibel kolumnmappning för kampanjdata
    client_col = None
    advertiser_col = None
    campaign_col = None
    
    for col in campaign_df.columns:
        col_lower = col.lower()
        if 'client' in col_lower and client_col is None:
            client_col = col
        elif 'advertiser' in col_lower and advertiser_col is None:
            advertiser_col = col
        elif 'campaign' in col_lower and 'name' in col_lower and campaign_col is None:
            campaign_col = col
    
    # Hämta Salesforce-värden
    sf_agency = str(sf_row.get('Booking Agency Office', ''))
    sf_account = str(sf_row.get('Account Name', ''))
    sf_opportunity = str(sf_row.get('Opportunity Name', ''))
    
    # Använd mappningar
    mapped_agency = mappings.get(sf_agency, sf_agency)
    mapped_account = mappings.get(sf_account, sf_account) 
    mapped_opportunity = mappings.get(sf_opportunity, sf_opportunity)
    
    # Filtrera data
    filtered_df = campaign_df.copy()
    
    # Filtrera på klient/byrå
    if client_col:
        agency_matches = campaign_df[client_col].apply(lambda x: fuzzy_match(mapped_agency, x) > 60)
        if agency_matches.any():
            filtered_df = campaign_df[agency_matches]
    
    # Filtrera på annonsör
    if advertiser_col and not filtered_df.empty:
        advertiser_matches = filtered_df[advertiser_col].apply(lambda x: fuzzy_match(mapped_account, x) > 60)
        if advertiser_matches.any():
            filtered_df = filtered_df[advertiser_matches]
    
    # Hitta bästa kampanjmatchning
    if campaign_col and not filtered_df.empty:
        campaign_scores = filtered_df[campaign_col].apply(lambda x: fuzzy_match(mapped_opportunity, x))
        if len(campaign_scores) > 0 and campaign_scores.max() > 70:
            best_idx = campaign_scores.idxmax()
            best_score = campaign_scores.max()
            return filtered_df.loc[best_idx], best_score
    
    return None, 0

def process_comparison(sf_df, campaign_df, mappings, tolerance=0.1):
    """Huvudfunktion för datajämförelse"""
    results = []
    
    # Hitta rätt kolumner i kampanjdata
    campaign_col = None
    campaign_id_col = None
    
    for col in campaign_df.columns:
        col_lower = col.lower()
        if 'campaign' in col_lower and 'name' in col_lower and campaign_col is None:
            campaign_col = col
        elif 'campaign' in col_lower and 'id' in col_lower and campaign_id_col is None:
            campaign_id_col = col
    
    for idx, sf_row in sf_df.iterrows():
        month_year = sf_row.get('Month_Year', '')
        
        # Filtrera kampanjdata för samma månad
        campaign_month_data = campaign_df[campaign_df['Month_Year'] == month_year] if 'Month_Year' in campaign_df.columns else campaign_df
        
        match, score = find_best_match(sf_row, campaign_month_data, mappings)
        
        result = {
            'Opportunity Name': sf_row.get('Opportunity Name', ''),
            'Line Item Code': sf_row.get('Line Item Code', ''),
            'Month': month_year,
            'Schedule Amount': sf_row.get('Schedule Amount', 0),
            'Matchad Campaign Name': match.get(campaign_col, '') if match is not None and campaign_col else '',
            'Campaign ID': match.get(campaign_id_col, '') if match is not None and campaign_id_col else '',
            'Faktisk Spend': match.get('Spent_client_currency', 0) if match is not None else 0,
            'Match Score': score
        }
        
        # Beräkna skillnad
        schedule_amount = result['Schedule Amount'] if not pd.isna(result['Schedule Amount']) else 0
        actual_spend = result['Faktisk Spend'] if not pd.isna(result['Faktisk Spend']) else 0
        
        result['Diff'] = schedule_amount - actual_spend
        
        # Status baserat på tolerans
        if abs(result['Diff']) <= abs(schedule_amount) * tolerance:
            result['Status'] = 'Godkänd'
            result['Korrigeringsförslag'] = ''
        else:
            result['Status'] = 'Kräver korrigering'
            if result['Diff'] > 0:
                result['Korrigeringsförslag'] = f'Underutgift på {result["Diff"]:.2f}'
            else:
                result['Korrigeringsförslag'] = f'Överutgift på {abs(result["Diff"]):.2f}'
        
        results.append(result)
    
    return pd.DataFrame(results)

def create_excel_report(results_df):
    """Skapa Excel-rapport"""
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        results_df.to_excel(writer, sheet_name='Jämförelserapport', index=False)
        
        # Formatering
        workbook = writer.book
        worksheet = writer.sheets['Jämförelserapport']
        
        # Autofit kolumner
        for column in worksheet.columns:
            max_length = 0
            column_letter = column[0].column_letter
            for cell in column:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            adjusted_width = min(max_length + 2, 50)
            worksheet.column_dimensions[column_letter].width = adjusted_width
    
    output.seek(0)
    return output

# Streamlit App
st.set_page_config(page_title="Excel Data Jämförelse", layout="wide")
st.title("📊 Salesforce vs Kampanjdata Jämförelse")

# Sessionsstatus för mappningar
if 'mappings' not in st.session_state:
    st.session_state.mappings = {}

# Huvudflikar
tab1, tab2 = st.tabs(["🔍 Jämför Data", "⚙️ Hantera Namn-mappningar"])

with tab1:
    st.header("Jämför Excel-filer")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("📄 Salesforce-fil")
        sf_file = st.file_uploader("Ladda upp Salesforce Excel-fil", type=['xlsx', 'xls', 'csv'], key="sf_file")
        
        # Filstorlekskontroll
        if sf_file is not None and sf_file.size > 10*1024*1024:  # 10MB
            st.error("❌ Filen är för stor. Max 10MB.")
            sf_file = None
        
    with col2:
        st.subheader("📊 Kampanjdata-fil")
        campaign_file = st.file_uploader("Ladda upp Kampanjdata Excel-fil", type=['xlsx', 'xls', 'csv'], key="campaign_file")
        
        # Filstorlekskontroll
        if campaign_file is not None and campaign_file.size > 10*1024*1024:  # 10MB
            st.error("❌ Filen är för stor. Max 10MB.")
            campaign_file = None
    
    # Inställningar
    st.subheader("⚙️ Inställningar")
    tolerance = st.slider("Toleransnivå (%)", 0, 50, 10) / 100
    
    # Förhandsvisa filer
    if sf_file:
        st.subheader("👀 Förhandsvy Salesforce-data")
        try:
            if sf_file.name.endswith('.csv'):
                sf_preview = pd.read_csv(sf_file, nrows=5)
            else:
                sf_preview = pd.read_excel(sf_file, nrows=5)
            st.dataframe(sf_preview)
        except Exception as e:
            st.error(f"Kunde inte läsa Salesforce-fil: {e}")
    
    if campaign_file:
        st.subheader("👀 Förhandsvy Kampanjdata")
        try:
            if campaign_file.name.endswith('.csv'):
                campaign_preview = pd.read_csv(campaign_file, nrows=5)
            else:
                campaign_preview = pd.read_excel(campaign_file, nrows=5)
            st.dataframe(campaign_preview)
        except Exception as e:
            st.error(f"Kunde inte läsa kampanj-fil: {e}")
    
    # Kör jämförelse
    if st.button("🚀 Kör Jämförelse", type="primary"):
        if sf_file is None or campaign_file is None:
            st.error("❌ Ladda upp både Salesforce-fil och kampanjdata-fil")
        else:
            with st.spinner("🔄 Bearbetar data..."):
                # Ladda Salesforce-data
                try:
                    if sf_file.name.endswith('.csv'):
                        sf_df = pd.read_csv(sf_file)
                    else:
                        sf_df = pd.read_excel(sf_file)
                    
                    sf_df = clean_salesforce_data(sf_df)
                    st.success(f"✅ Salesforce-data laddad: {len(sf_df)} rader")
                except Exception as e:
                    st.error(f"❌ Fel vid laddning av Salesforce-data: {e}")
                    st.stop()
                
                # Ladda kampanjdata
                try:
                    if campaign_file.name.endswith('.csv'):
                        campaign_df = pd.read_csv(campaign_file)
                    else:
                        campaign_df = pd.read_excel(campaign_file)
                    
                    campaign_df = clean_campaign_data(campaign_df)
                    campaign_df = aggregate_campaign_data(campaign_df)
                    st.success(f"✅ Kampanjdata laddad: {len(campaign_df)} rader")
                except Exception as e:
                    st.error(f"❌ Fel vid laddning av kampanjdata: {e}")
                    st.stop()
                
                # Kör jämförelse
                results_df = process_comparison(sf_df, campaign_df, st.session_state.mappings, tolerance)
                
                # Visa sammanfattning
                st.subheader("📈 Resultat Sammanfattning")
                
                total_rows = len(results_df)
                matched_rows = len(results_df[results_df['Match Score'] > 70])
                approved_rows = len(results_df[results_df['Status'] == 'Godkänd'])
                needs_correction = len(results_df[results_df['Status'] == 'Kräver korrigering'])
                
                col5, col6, col7, col8 = st.columns(4)
                col5.metric("Totalt rader", total_rows)
                col6.metric("Matchade rader", matched_rows, f"{matched_rows/total_rows*100:.1f}%" if total_rows > 0 else "0%")
                col7.metric("Godkända", approved_rows, f"{approved_rows/total_rows*100:.1f}%" if total_rows > 0 else "0%")
                col8.metric("Behöver korrigering", needs_correction, f"{needs_correction/total_rows*100:.1f}%" if total_rows > 0 else "0%")
                
                # Visa förhandsgranskning
                st.subheader("👀 Förhandsgranskning")
                st.dataframe(results_df, use_container_width=True)
                
                # Nedladdningsknapp
                excel_file = create_excel_report(results_df)
                st.download_button(
                    label="📥 Ladda ner Excel-rapport",
                    data=excel_file,
                    file_name=f"jamforelse_rapport_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

with tab2:
    st.header("Hantera Namn-mappningar")
    st.write("Här kan du hantera kända avvikelser mellan Salesforce och kampanjdata namn.")
    
    # Visa nuvarande mappningar
    if st.session_state.mappings:
        st.subheader("📋 Nuvarande mappningar")
        
        mappings_df = pd.DataFrame([
            {"Salesforce Namn": k, "Kampanjdata Namn": v}
            for k, v in st.session_state.mappings.items()
        ])
        
        edited_df = st.data_editor(
            mappings_df,
            num_rows="dynamic",
            use_container_width=True,
            key="mappings_editor"
        )
        
        # Uppdatera mappningar från editor
        if not edited_df.empty:
            new_mappings = {}
            for _, row in edited_df.iterrows():
                if pd.notna(row['Salesforce Namn']) and pd.notna(row['Kampanjdata Namn']):
                    new_mappings[row['Salesforce Namn']] = row['Kampanjdata Namn']
            st.session_state.mappings = new_mappings
    
    # Lägg till ny mappning
    st.subheader("➕ Lägg till ny mappning")
    col9, col10 = st.columns(2)
    
    with col9:
        sf_name = st.text_input("Salesforce namn")
    
    with col10:
        campaign_name = st.text_input("Kampanjdata namn")
    
    if st.button("➕ Lägg till mappning"):
        if sf_name and campaign_name:
            st.session_state.mappings[sf_name] = campaign_name
            st.success(f"✅ Mappning tillagd: {sf_name} → {campaign_name}")
            st.experimental_rerun()
        else:
            st.error("❌ Fyll i både Salesforce och kampanjdata namn")
    
    # Export/Import mappningar
    col11, col12 = st.columns(2)
    
    with col11:
        if st.session_state.mappings:
            mappings_json = json.dumps(st.session_state.mappings, indent=2)
            st.download_button(
                label="📥 Exportera mappningar",
                data=mappings_json,
                file_name="mappings.json",
                mime="application/json"
            )
    
    with col12:
        uploaded_mappings = st.file_uploader("📤 Importera mappningar", type=['json'])
        if uploaded_mappings:
            try:
                imported_mappings = json.load(uploaded_mappings)
                st.session_state.mappings.update(imported_mappings)
                st.success(f"✅ {len(imported_mappings)} mappningar importerade")
                st.experimental_rerun()
            except Exception as e:
                st.error(f"❌ Kunde inte importera mappningar: {e}")
    
    # Rensa mappningar
    if st.button("🗑️ Rensa alla mappningar", type="secondary"):
        st.session_state.mappings = {}
        st.success("✅ Alla mappningar rensade")
        st.experimental_rerun()

# Sidebar med information
with st.sidebar:
    st.header("ℹ️ Information")
    st.write("""
    **Så fungerar verktyget:**
    
    1. Ladda upp Salesforce Excel-fil
    2. Ladda upp kampanjdata Excel-fil
    3. Konfigurera eventuella namn-mappningar
    4. Kör jämförelsen
    5. Ladda ner rapport
    
    **Matchningslogik:**
    - Booking Agency Office ↔ Client
    - Account Name ↔ Advertiser  
    - Opportunity Name ↔ Campaign Name
    - Månad/År matchning
    
    **Tips:**
    - Använd namn-mappningar för kända avvikelser
    - Justera toleransnivån efter behov
    - Verktyget använder oskarp textmatchning
    """)
    
    st.header("📋 Kolumnkrav")
    st.write("""
    **Salesforce-fil:**
    - Opportunity Name
    - Line Item Code  
    - Schedule Amount
    - Booking Agency Office
    - Account Name
    - Date eller Month
    
    **Kampanjdata-fil:**
    - Campaign Name (eller liknande)
    - Campaign ID (valfritt)
    - Client (eller liknande)
    - Advertiser (eller liknande)
    - Spent_client_currency eller Spend
    - Date eller Month
    """)