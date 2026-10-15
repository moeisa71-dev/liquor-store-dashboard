import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import pypdf
import re
from datetime import datetime
import io
import csv
import requests

st.set_page_config(page_title="Liquors Ventures Analytics", layout="wide")

# Custom header styling
st.markdown("""
<style>
    .header-box {
        background: linear-gradient(135deg, #1e1b4b 0%, #312e81 100%);
        color: white;
        padding: 22px;
        border-radius: 14px;
        margin-bottom: 20px;
    }
</style>
""", unsafe_allow_html=True)

# -------------------------------------------------------------
# 1. Automatic PDF Parsing Engine (Pulls Sundays from raw POS PDF)
# -------------------------------------------------------------
def parse_sundays_from_pdf(pdf_file_or_path):
    reader = pypdf.PdfReader(pdf_file_or_path)
    records = []
    
    for page in reader.pages:
        text = page.extract_text()
        if not text:
            continue
            
        date_match = re.search(r'Date\s*[:\|]?\s*(\d{1,2}/\d{1,2}/\d{4})', text)
        if not date_match:
            date_match = re.search(r'(\d{2}/\d{2}/\d{4})', text)
            
        if date_match:
            date_str = date_match.group(1)
            try:
                dt = datetime.strptime(date_str, "%m/%d/%Y")
            except Exception:
                continue
            
            # Python weekday 6 = Sunday
            if dt.weekday() == 6:
                vape_val = 0.0
                vape_match = re.search(r'VAPE\s*[:\|]?\s*\$?\s*([0-9,]+\.\d{2})', text)
                if vape_match:
                    vape_val = float(vape_match.group(1).replace(',', ''))
                
                total_val = 0.0
                tender_split = text.split('Tender Collected')
                if len(tender_split) > 1:
                    above_tender = tender_split[0].strip()
                    lines = above_tender.split('\n')
                    last_line = lines[-1]
                    nums = re.findall(r'\$([0-9,]+\.\d{2})', last_line)
                    if nums:
                        total_val = float(nums[0].replace(',', ''))
                
                records.append({
                    'Date': dt.strftime('%m/%d/%Y'),
                    'Gross_Total': total_val,
                    'Vape_Sales': vape_val,
                    'Net_Alcohol': total_val - vape_val
                })
                
    df = pd.DataFrame(records).drop_duplicates(subset=['Date'])
    return df

# -------------------------------------------------------------
# 2. Resilient Google Sheet / CSV Loader (Using gid=0)
# -------------------------------------------------------------
SHEET_ID = "1NYSifzt4YDDZUkHviAD7bjBSFqbAJCR6vXBoXmHzIv0"
URL_CANDIDATES = [
    f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid=0",
    f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&gid=0",
    f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet=Weekly%20KPIs"
]

def parse_kpi_text(raw_text):
    if "<!DOCTYPE html>" in raw_text or "<html" in raw_text.lower():
        return None, "Google returned an HTML login page instead of spreadsheet data."
    
    lines = raw_text.strip().split('\n')
    header_idx = None
    for idx, line in enumerate(lines[:20]):
        row = list(csv.reader([line]))[0] if line else []
        clean_tokens = [c.strip() for c in row]
        if 'Date' in clean_tokens:
            header_idx = idx
            break
            
    if header_idx is None:
        return None, "Could not locate 'Date' header row in the Google Sheet data."
        
    df = pd.read_csv(io.StringIO(raw_text), skiprows=header_idx)
    df.columns = [str(c).strip() for c in df.columns]
    
    if 'Date' not in df.columns:
        return None, "Header found, but 'Date' column is missing."
        
    df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
    df = df.dropna(subset=['Date']).sort_values('Date').reset_index(drop=True)
    
    numeric_cols = [
        'INSIDE SALES', 'Total Shipping Sales', 'Store Payroll 100hrs $2100', 
        'VAPE SALES', 'INSIDE TRANS COUNT'
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = df[col].astype(str).str.replace('$', '').str.replace(',', '').str.strip()
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            
    return df, None

@st.cache_data(ttl=300)
def fetch_online_kpis():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    }
    for url in URL_CANDIDATES:
        try:
            resp = requests.get(url, headers=headers, timeout=12)
            if resp.status_code == 200 and "Date" in resp.text:
                return resp.text, None
        except Exception:
            continue
    return None, "Could not connect to Google Sheet via export endpoints."

# Sidebar data loading
st.sidebar.header("⚙️ Data Settings")
csv_text, err_msg = fetch_online_kpis()
df_kpi = None

if csv_text:
    df_kpi, parse_err = parse_kpi_text(csv_text)
    if parse_err:
        st.sidebar.warning(parse_err)

# Backup manual upload
manual_kpi = st.sidebar.file_uploader("Upload Weekly KPIs CSV (Backup)", type=["csv"])
if manual_kpi is not None:
    manual_text = manual_kpi.getvalue().decode('utf-8', errors='ignore')
    df_manual, manual_err = parse_kpi_text(manual_text)
    if df_manual is not None:
        df_kpi = df_manual
        st.sidebar.success("Loaded Weekly KPIs from uploaded file!")

if df_kpi is None:
    st.error("""
    ### ⚠️ Cannot Access Google Sheet Data
    Google's automated export was blocked or returned unexpected data.
    
    **Immediate Fix:**
    1. In your Google Sheet, click **File** > **Download** > **Comma Separated Values (.csv)**.
    2. Click **Upload** under **Upload Weekly KPIs CSV (Backup)** in the left sidebar.
    """)
    st.stop()

# -------------------------------------------------------------
# 3. Header Controls
# -------------------------------------------------------------
st.markdown("""
<div class='header-box'>
    <h2>LIQUORS VENTURES, LLC — Automated Executive Dashboard</h2>
    <p>Automated Quarterly Tracking & Apples-to-Apples Reconciliation from Weekly KPIs</p>
</div>
""", unsafe_allow_html=True)

c1, c2, c3 = st.columns([1, 2, 1])
with c1:
    year = st.selectbox("Year", [2026, 2025, 2024], index=0)
with c2:
    quarter = st.radio("Quarter", ["Q1", "Q2", "Q3", "Q4"], horizontal=True, index=2)
with c3:
    apples_to_apples = st.toggle("Apples-to-Apples ON", value=True)

# -------------------------------------------------------------
# 4. Sidebar: POS PDF Upload
# -------------------------------------------------------------
st.sidebar.header("📁 Quarterly POS PDF Upload")
uploaded_pdf = st.sidebar.file_uploader(
    f"Drop the full {year} {quarter} Daily POS PDF here", 
    type=["pdf"]
)

df_sundays = pd.DataFrame()

if uploaded_pdf is not None:
    with st.spinner("Scanning pages and pulling Sundays..."):
        df_sundays = parse_sundays_from_pdf(uploaded_pdf)
        st.sidebar.success(f"Extracted {len(df_sundays)} Sundays successfully!")

sunday_gross = df_sundays['Gross_Total'].sum() if not df_sundays.empty else 0.0
sunday_vape = df_sundays['Vape_Sales'].sum() if not df_sundays.empty else 0.0
sunday_net_deduction = df_sundays['Net_Alcohol'].sum() if not df_sundays.empty else 0.0

# -------------------------------------------------------------
# 5. Quarter Aggregation (13-Week Blocks)
# -------------------------------------------------------------
quarter_map = {"Q1": (1, 3), "Q2": (4, 6), "Q3": (7, 9), "Q4": (10, 12)}
start_m, end_m = quarter_map[quarter]

df_curr = df_kpi[(df_kpi['Date'].dt.year == year) & 
                 (df_kpi['Date'].dt.month >= start_m) & 
                 (df_kpi['Date'].dt.month <= end_m)].tail(13)

df_prev = df_kpi[(df_kpi['Date'].dt.year == (year - 1)) & 
                 (df_kpi['Date'].dt.month >= start_m) & 
                 (df_kpi['Date'].dt.month <= end_m)].tail(13)

gross_inside_curr = df_curr['INSIDE SALES'].sum()
shipping_curr = df_curr['Total Shipping Sales'].sum()
payroll_curr = df_curr['Store Payroll 100hrs $2100'].sum()
vape_curr = df_curr['VAPE SALES'].sum()
total_sales_curr = gross_inside_curr + shipping_curr

gross_inside_prev = df_prev['INSIDE SALES'].sum()
shipping_prev = df_prev['Total Shipping Sales'].sum()
payroll_prev = df_prev['Store Payroll 100hrs $2100'].sum()
vape_prev = df_prev['VAPE SALES'].sum()
total_sales_prev = gross_inside_prev + shipping_prev

if apples_to_apples and year == 2026:
    adjusted_inside_curr = gross_inside_curr - vape_curr - sunday_net_deduction
    adjusted_inside_prev = gross_inside_prev - vape_prev
else:
    adjusted_inside_curr = gross_inside_curr
    adjusted_inside_prev = gross_inside_prev

pct_inside_change = ((adjusted_inside_curr - adjusted_inside_prev) / adjusted_inside_prev) * 100 if adjusted_inside_prev else 0
labor_rate = (payroll_curr / total_sales_curr) * 100 if total_sales_curr else 0

# -------------------------------------------------------------
# 6. Render Scorecard
# -------------------------------------------------------------
st.subheader("Apples-to-Apples Normalization Scorecard")
s1, s2, s3, s4, s5 = st.columns(5)
s1.metric("1. Gross Inside Sales", f"${gross_inside_curr:,.2f}", "All Register Inside")
s2.metric("2. Vape Deductions", f"-${vape_curr:,.2f}", "Category Launch: May '25")
s3.metric("3. Sunday Deductions", f"-${sunday_net_deduction:,.2f}", f"{len(df_sundays)} Sundays Detected")
s4.metric("4. Adjusted Inside Alcohol", f"${adjusted_inside_curr:,.2f}", "Mon-Sat Core Non-Vape")
s5.metric("5. Normalized YoY", f"{pct_inside_change:.2f}%", f"vs PY Baseline: ${adjusted_inside_prev:,.2f}")

st.divider()

# -------------------------------------------------------------
# 7. Render 8 KPI Cards
# -------------------------------------------------------------
k1, k2, k3, k4 = st.columns(4)
k1.metric("TOTAL GROSS SALES", f"${total_sales_curr:,.2f}", f"{((total_sales_curr - total_sales_prev)/total_sales_prev)*100:+.2f}% YoY" if total_sales_prev else "-")
k2.metric("CORE ADJUSTED INSIDE", f"${adjusted_inside_curr:,.2f}", f"{pct_inside_change:+.2f}% Core")
k3.metric("SHIPPING SALES (E-COMM)", f"${shipping_curr:,.2f}", f"{((shipping_curr - shipping_prev)/shipping_prev)*100:+.2f}% YoY" if shipping_prev else "-")
k4.metric("TOTAL STORE PAYROLL", f"${payroll_curr:,.2f}", f"{((payroll_curr - payroll_prev)/payroll_prev)*100:+.2f}% YoY" if payroll_prev else "-")

k5, k6, k7, k8 = st.columns(4)
k5.metric("LABOR % OF SALES", f"{labor_rate:.2f}%", f"PY: {(payroll_prev/total_sales_prev)*100:.2f}%" if total_sales_prev else "-")
k6.metric("STORE TRANSACTIONS", f"{int(df_curr['INSIDE TRANS COUNT'].sum()):,}", f"Avg Ticket: ${gross_inside_curr / max(1, df_curr['INSIDE TRANS COUNT'].sum()):.2f}")
k7.metric("SUNDAY REVENUE EXTRACTED", f"${sunday_gross:,.2f}", f"Net Impact: -${sunday_net_deduction:,.2f}")
k8.metric("TOTAL PARCELS SHIPPED", f"{int(df_curr['Total Shipping Sales'].count() * 115):,}")

# -------------------------------------------------------------
# 8. Revenue & Channel Mix Progression Bar Chart
# -------------------------------------------------------------
st.subheader("Quarterly Revenue & Channel Mix Progression")
fig = go.Figure()
fig.add_trace(go.Bar(name='Inside Store Sales', x=[f"{year-1} {quarter}", f"{year} {quarter}"], y=[gross_inside_prev, gross_inside_curr], marker_color='#4f46e5'))
fig.add_trace(go.Bar(name='Shipping Sales (E-Commerce)', x=[f"{year-1} {quarter}", f"{year} {quarter}"], y=[shipping_prev, shipping_curr], marker_color='#9333ea'))
fig.update_layout(barmode='stack', height=360, margin=dict(l=20, r=20, t=20, b=20), legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
st.plotly_chart(fig, use_container_width=True)

# -------------------------------------------------------------
# 9. Audit Table for Sundays
# -------------------------------------------------------------
if not df_sundays.empty:
    with st.expander("🔍 View Extracted Sunday Audit Table"):
        st.dataframe(df_sundays.style.format({
            "Gross_Total": "${:,.2f}",
            "Vape_Sales": "${:,.2f}",
            "Net_Alcohol": "${:,.2f}"
        }), use_container_width=True)
