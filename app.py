import streamlit as st
import pandas as pd
from fuzzywuzzy import process
import io

# ==========================================
# 1. DESIGN OCH LAYOUT
# ==========================================
st.set_page_config(page_title="Campaign Matcher", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #f8f9fa; font-family: 'Inter', sans-serif; }
    .css-1r6slb0, .css-1y4p8pa { background-color: #ffffff; border-radius: 12px; padding: 24px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); }
    .stButton>button { background: linear-gradient(90deg, #6C63FF 0%, #3F3D56 100%); color: white; border-radius: 8px; border: none; padding: 10px 24px; font-weight: 600; transition: all 0.3s ease; }
    .stButton>button:hover { transform: translateY(-2px); box-shadow: 0 6px 12px rgba(108, 99, 255, 0.3); }
    </style>
""", unsafe_allow_html=True)

# testing pr

# ==========================================
# 2. HJÄLPFUNKTIONER (DATA-TVÄTT)
# ==========================================
def load_salesforce_excel(uploaded_file):
    # Letar upp rubrikraden dynamiskt (hanterar Salesforces skräp-rader)
    df = pd.read_excel(uploaded_file, header=None)
    header_idx = df[df.apply(lambda x: x.astype(str).str.contains('Opportunity Name', case=False, na=False).any(), axis=1)].index
    
    if len(header_idx) > 0:
        df = pd.read_excel(uploaded_file, header=header_idx[0])
    else:
        st.error("Kunde inte hitta kolumnen 'Opportunity Name' i Salesforce-filen.")
        return pd.DataFrame()
    
    df = df.dropna(subset=['Opportunity Name'])
    
    if 'Schedule Amount' in df.columns:
        df['Schedule Amount'] = df['Schedule Amount'].astype(str).str.replace(r'[^\d.]', '', regex=True)
        df['Schedule Amount'] = pd.to_numeric(df['Schedule Amount'], errors='coerce').fillna(0)
        
    return df

def load_campaign_excel(uploaded_file):
    # Enkel inläsning av kampanjdatan (tidigare Google Sheet)
    df = pd.read_excel(uploaded_file)
    if 'campaign_name' not in df.columns:
        st.error("Kunde inte hitta kolumnen 'campaign_name' i kampanj-filen.")
        return pd.DataFrame()
    return df

# ==========================================
# 3. HUVUDAPPLIKATION
# ==========================================
st.title("⚡ Campaign Matcher (Excel-version)")
st.write("Ladda upp Salesforce-export och Kampanj-rapport för att jämföra data.")

tab1, tab2, tab3 = st.tabs(["📁 1. Data & Kör", "🔍 2. Granska matchningar", "📊 3. Slutrapport"])

# Spara variabler i minnet
if 'sf_data' not in st.session_state:
    st.session_state['sf_data'] = None
    st.session_state['camp_data'] = None
    st.session_state['mappings'] = {}  # Sparar manuella val tillfälligt
    st.session_state['final_results'] = []
    st.session_state['unsure_matches'] = []

# --- FLIK 1: LADDA UPP & KÖR ---
with tab1:
    col1, col2 = st.columns(2)
    with col1:
        sf_file = st.file_uploader("1. Ladda upp Salesforce-export", type=['xlsx', 'csv'])
    with col2:
        camp_file = st.file_uploader("2. Ladda upp Kampanj-rapport (Faktisk spend)", type=['xlsx', 'csv'])

    if sf_file and camp_file:
        if st.button("Läs in filer"):
            with st.spinner("Tvättar data..."):
                try:
                    st.session_state['sf_data'] = load_salesforce_excel(sf_file)
                    st.session_state['camp_data'] = load_campaign_excel(camp_file)
                    st.success("Båda filerna är inlästa!")
                    
                    # Förhandsgranskning
                    st.write("**Salesforce Data (Förhandsgranskning):**", st.session_state['sf_data'].head(2))
                    st.write("**Kampanj Data (Förhandsgranskning):**", st.session_state['camp_data'].head(2))
                except Exception as e:
                    st.error(f"Ett fel uppstod vid inläsning: {e}")

        # STARTA MATCHNING
        if st.session_state['sf_data'] is not None and st.session_state['camp_data'] is not None:
            if st.button("Starta Jämförelse"):
                with st.spinner("Matchar kampanjer..."):
                    sf_df = st.session_state['sf_data']
                    camp_df = st.session_state['camp_data']
                    
                    camp_names = camp_df['campaign_name'].dropna().unique().tolist()
                    
                    results = []
                    unsure = []
                    
                    for index, row in sf_df.iterrows():
                        sf_name = str(row['Opportunity Name'])
                        sf_amount = row.get('Schedule Amount', 0)
                        
                        # Kolla om vi redan godkänt denna i denna session
                        best_match = st.session_state['mappings'].get(sf_name)
                        score = 100 if best_match else 0
                        
                        if not best_match and camp_names:
                            best_match, score = process.extractOne(sf_name, camp_names)
                        
                        # Räkna ut faktiskt spenderat belopp
                        actual_spend = 0
                        if best_match:
                            # Om det är en kolumn som heter Spent_client_currency
                            spend_col = 'Spent_client_currency' if 'Spent_client_currency' in camp_df.columns else camp_df.columns[-1]
                            actual_spend = camp_df[camp_df['campaign_name'] == best_match][spend_col].astype(float).sum()
                        
                        diff = sf_amount - actual_spend
                        status = "Godkänd" if abs(diff) < 10 else "Kräver korrigering"
                        
                        result_row = {
                            "Opportunity Name": sf_name,
                            "Line Item Code": row.get('Line Item Code', ''),
                            "Schedule Amount": sf_amount,
                            "Matchad Campaign Name": best_match,
                            "Faktisk Spend": actual_spend,
                            "Diff": diff,
                            "Status": status
                        }
                        
                        if score >= 90:
                            results.append(result_row)
                        else:
                            unsure.append(result_row)
                            
                    st.session_state['final_results'] = results
                    st.session_state['unsure_matches'] = unsure
                    st.success(f"Klar! {len(results)} rader matchades. Gå till flik 2 för att granska {len(unsure)} osäkra.")

# --- FLIK 2: GRANSKA OSÄKRA MATCHNINGAR ---
with tab2:
    if st.session_state.get('unsure_matches'):
        st.write("### Osäkra matchningar")
        camp_names = ["-- Välj rätt kampanj --"] + st.session_state['camp_data']['campaign_name'].dropna().unique().tolist()
        
        for i, row in enumerate(list(st.session_state['unsure_matches'])):
            with st.container():
                cols = st.columns([3, 3, 2])
                with cols[0]:
                    st.write("**Salesforce:**")
                    st.info(row['Opportunity Name'])
                with cols[1]:
                    st.write("**Välj från Kampanj-fil:**")
                    selected = st.selectbox("Välj kampanj", options=camp_names, index=0, key=f"sel_{i}")
                with cols[2]:
                    st.write("")
                    if st.button("Godkänn match", key=f"btn_{i}"):
                        if selected != "-- Välj rätt kampanj --":
                            # Spara i tillfälligt minne
                            st.session_state['mappings'][row['Opportunity Name']] = selected
                            
                            row['Matchad Campaign Name'] = selected
                            row['Status'] = "Manuellt Godkänd"
                            st.session_state['final_results'].append(row)
                            
                            st.success("Godkänd! (Klicka 'Starta Jämförelse' igen när du är klar med alla, eller gå till Flik 3)")
    else:
        st.info("Inga rader att granska just nu.")

# --- FLIK 3: SLUTRAPPORT ---
with tab3:
    if st.session_state.get('final_results'):
        final_df = pd.DataFrame(st.session_state['final_results'])
        st.metric("Totalt antal processade rader", len(final_df))
        st.dataframe(final_df, use_container_width=True)
        
        # Excel-nedladdning
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            final_df.to_excel(writer, index=False)
        
        st.download_button(
            label="📥 Ladda ner färdig Excel-rapport",
            data=buffer.getvalue(),
            file_name="kampanj_jamforelse.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    else:
        st.info("Ladda upp filer och kör jämförelsen i Flik 1 för att se resultatet.")
