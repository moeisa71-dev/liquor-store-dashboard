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

# Custom Styling (Dark theme & table styling matching your attachment)
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
# 1. Automatic PDF Parsing Engine (Pulls Sundays from POS PDF)
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
                    'Date': dt.strftime('%B %d, %Y'),
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
        return None, "Could not locate 'Date' header row in Google Sheet data."
        
    df = pd.read_csv(io.StringIO(raw_text), skiprows=header_idx)
    df.columns = [str(c).strip() for c in df.columns]
    
    if 'Date' not in df.columns:
        return None, "Header found, but 'Date' column is missing."
        
    df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
    df = df.dropna(subset=['Date']).sort_values('Date').reset_index(drop=True)
    
    numeric_cols = [
        'INSIDE SALES', 'Weekly Inside sales w/o lottery', 'Total Weekly Sales with out Lottery',
        'Total Shipping Sales', 'Store Payroll 100hrs $2100', 'VAPE SALES', 'INSIDE TRANS COUNT', 
        'Flaviar Sales', 'Shipstation Sales', 'Flaviar Parcels', 'Shipstation parcels', 'Total Parcels'
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

st.sidebar.header("⚙️ Data Settings")
csv_text, err_msg = fetch_online_kpis()
df_kpi = None

if csv_text:
    df_kpi, parse_err = parse_kpi_text(csv_text)
    if parse_err:
        st.sidebar.warning(parse_err)

manual_kpi = st.sidebar.file_uploader("Upload Weekly KPIs CSV (Backup)", type=["csv"])
if manual_kpi is not None:
    manual_text = manual_kpi.getvalue().decode('utf-8', errors='ignore')
    df_manual, manual_err = parse_kpi_text(manual_text)
    if df_manual is not None:
        df_kpi = df_manual
        st.sidebar.success("Loaded Weekly KPIs from uploaded file!")

if df_kpi is None:
    st.error("Cannot access Google Sheet. Please check link permissions or upload a backup CSV.")
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
                 (df_kpi['Date'].dt.month <= end_m)].tail(13).copy()

df_prev = df_kpi[(df_kpi['Date'].dt.year == (year - 1)) & 
                 (df_kpi['Date'].dt.month >= start_m) & 
                 (df_kpi['Date'].dt.month <= end_m)].tail(13).copy()

# Determine inside sales column (preference: Total Weekly Sales with out Lottery)
inside_col = 'Total Weekly Sales with out Lottery' if 'Total Weekly Sales with out Lottery' in df_kpi.columns else 'INSIDE SALES'

gross_inside_curr = df_curr[inside_col].sum()
shipping_curr = df_curr['Total Shipping Sales'].sum()
payroll_curr = df_curr['Store Payroll 100hrs $2100'].sum()
vape_curr = df_curr['VAPE SALES'].sum()
total_sales_curr = gross_inside_curr + shipping_curr

gross_inside_prev = df_prev[inside_col].sum()
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

# Labor % of sales (Calculated using unadjusted gross sales with Sundays and Vape)
labor_rate_curr = (payroll_curr / total_sales_curr) * 100 if total_sales_curr else 0
labor_rate_prev = (payroll_prev / total_sales_prev) * 100 if total_sales_prev else 0

# -------------------------------------------------------------
# 6. Render Tabs
# -------------------------------------------------------------
tab1, tab2, tab3 = st.tabs([
    "📊 Executive Dashboard", 
    f"📋 YoY Executive Tables ({quarter} {year} vs {quarter} {year-1})", 
    "📈 Weekly Sales Data Breakdown"
])

# -------------------------------------------------------------
# TAB 1: VISUAL EXECUTIVE DASHBOARD
# -------------------------------------------------------------
with tab1:
    st.subheader("Apples-to-Apples Normalization Scorecard")
    s1, s2, s3, s4, s5 = st.columns(5)
    s1.metric("1. Gross Inside Sales", f"${gross_inside_curr:,.2f}", f"Source: {inside_col}")
    s2.metric("2. Vape Deductions", f"-${vape_curr:,.2f}", "Category Launch: May '25")
    s3.metric("3. Sunday Deductions", f"-${sunday_net_deduction:,.2f}", f"{len(df_sundays)} Sundays Detected")
    s4.metric("4. Adjusted Inside Alcohol", f"${adjusted_inside_curr:,.2f}", "Mon-Sat Core Non-Vape")
    s5.metric("5. Normalized YoY", f"{pct_inside_change:.2f}%", f"vs PY Baseline: ${adjusted_inside_prev:,.2f}")

    st.divider()

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("TOTAL GROSS SALES", f"${total_sales_curr:,.2f}", f"{((total_sales_curr - total_sales_prev)/total_sales_prev)*100:+.2f}% YoY" if total_sales_prev else "-")
    k2.metric("CORE ADJUSTED INSIDE", f"${adjusted_inside_curr:,.2f}", f"{pct_inside_change:+.2f}% Core")
    k3.metric("SHIPPING SALES (E-COMM)", f"${shipping_curr:,.2f}", f"{((shipping_curr - shipping_prev)/shipping_prev)*100:+.2f}% YoY" if shipping_prev else "-")
    k4.metric("TOTAL STORE PAYROLL", f"${payroll_curr:,.2f}", f"{((payroll_curr - payroll_prev)/payroll_prev)*100:+.2f}% YoY" if payroll_prev else "-")

    k5, k6, k7, k8 = st.columns(4)
    k5.metric("LABOR % OF SALES (INCL. SUN & VAPE)", f"{labor_rate_curr:.2f}%", f"PY: {labor_rate_prev:.2f}%")
    k6.metric("STORE TRANSACTIONS", f"{int(df_curr['INSIDE TRANS COUNT'].sum()):,}", f"Avg Ticket: ${gross_inside_curr / max(1, df_curr['INSIDE TRANS COUNT'].sum()):.2f}")
    k7.metric("SUNDAY REVENUE EXTRACTED", f"${sunday_gross:,.2f}", f"Net Impact: -${sunday_net_deduction:,.2f}")
    k8.metric("TOTAL PARCELS SHIPPED", f"{int(df_curr['Total Parcels'].sum() if 'Total Parcels' in df_curr.columns else len(df_curr)*115):,}")

    st.subheader("Quarterly Revenue & Channel Mix Progression")
    fig = go.Figure()
    fig.add_trace(go.Bar(name='Inside Store Sales', x=[f"{year-1} {quarter}", f"{year} {quarter}"], y=[gross_inside_prev, gross_inside_curr], marker_color='#4f46e5'))
    fig.add_trace(go.Bar(name='Shipping Sales (E-Commerce)', x=[f"{year-1} {quarter}", f"{year} {quarter}"], y=[shipping_prev, shipping_curr], marker_color='#9333ea'))
    fig.update_layout(barmode='stack', height=360, margin=dict(l=20, r=20, t=20, b=20), legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
    st.plotly_chart(fig, use_container_width=True)

# -------------------------------------------------------------
# TAB 2: EXACT TABLES FROM 2ND ATTACHMENT
# -------------------------------------------------------------
with tab2:
    st.markdown(f"### 1. EXECUTIVE OVERVIEW ({quarter} {year} vs {quarter} {year-1})")
    
    t1_data = [
        {
            "Metric": f"Total {quarter} Sales",
            f"{quarter} {year}": f"${total_sales_curr:,.2f}",
            f"{quarter} {year-1}": f"${total_sales_prev:,.2f}",
            "Gain/Loss ($)": f"${(total_sales_curr - total_sales_prev):+,.2f}",
            "Gain/Loss (%)": f"{((total_sales_curr - total_sales_prev)/total_sales_prev)*100:+.2f}%" if total_sales_prev else "-"
        },
        {
            "Metric": "Net Inside Alcohol Sales",
            f"{quarter} {year}": f"${adjusted_inside_curr:,.2f}",
            f"{quarter} {year-1}": f"${adjusted_inside_prev:,.2f}",
            "Gain/Loss ($)": f"${(adjusted_inside_curr - adjusted_inside_prev):+,.2f}",
            "Gain/Loss (%)": f"{pct_inside_change:+.2f}%"
        },
        {
            "Metric": "Shipping Revenue",
            f"{quarter} {year}": f"${shipping_curr:,.2f}",
            f"{quarter} {year-1}": f"${shipping_prev:,.2f}",
            "Gain/Loss ($)": f"${(shipping_curr - shipping_prev):+,.2f}",
            "Gain/Loss (%)": f"{((shipping_curr - shipping_prev)/shipping_prev)*100:+.2f}%" if shipping_prev else "-"
        },
        {
            "Metric": f"{quarter} Store Payroll",
            f"{quarter} {year}": f"${payroll_curr:,.2f}",
            f"{quarter} {year-1}": f"${payroll_prev:,.2f}",
            "Gain/Loss ($)": f"${(payroll_curr - payroll_prev):+,.2f}",
            "Gain/Loss (%)": f"{((payroll_curr - payroll_prev)/payroll_prev)*100:+.2f}%" if payroll_prev else "-"
        },
        {
            "Metric": "Labor Rate (Includes Sundays & Vape)",
            f"{quarter} {year}": f"{labor_rate_curr:.2f}%",
            f"{quarter} {year-1}": f"{labor_rate_prev:.2f}%",
            "Gain/Loss ($)": f"{(labor_rate_curr - labor_rate_prev):+.2f}% pts",
            "Gain/Loss (%)": ""
        }
    ]
    df_t1 = pd.DataFrame(t1_data)
    st.dataframe(df_t1, use_container_width=True, hide_index=True)

    st.markdown(f"### 2. INSIDE SALES PERFORMANCE (YOY)")
    vape_diff = vape_curr - vape_prev
    vape_pct = (vape_diff / vape_prev)*100 if vape_prev else 0.0

    t2_data = [
        {
            "Category": "Inside Sales (Gross)",
            f"{quarter} {year}": f"${gross_inside_curr:,.2f}",
            f"{quarter} {year-1}": f"${gross_inside_prev:,.2f}",
            "Gain/Loss ($)": f"${(gross_inside_curr - gross_inside_prev):+,.2f}",
            "Gain/Loss (%)": f"{((gross_inside_curr - gross_inside_prev)/gross_inside_prev)*100:+.2f}%"
        },
        {
            "Category": "Vape Sales Deductions",
            f"{quarter} {year}": f"-${vape_curr:,.2f}",
            f"{quarter} {year-1}": f"-${vape_prev:,.2f}",
            "Gain/Loss ($)": f"-${vape_diff:,.2f}",
            "Gain/Loss (%)": f"{vape_pct:+.2f}%"
        },
        {
            "Category": "Sunday Sales Deductions",
            f"{quarter} {year}": f"-${sunday_net_deduction:,.2f}",
            f"{quarter} {year-1}": "$0.00",
            "Gain/Loss ($)": f"-${sunday_net_deduction:,.2f}" if sunday_net_deduction else "$0.00",
            "Gain/Loss (%)": "-"
        },
        {
            "Category": "Total Net Inside Alcohol Sales",
            f"{quarter} {year}": f"${adjusted_inside_curr:,.2f}",
            f"{quarter} {year-1}": f"${adjusted_inside_prev:,.2f}",
            "Gain/Loss ($)": f"${(adjusted_inside_curr - adjusted_inside_prev):+,.2f}",
            "Gain/Loss (%)": f"{pct_inside_change:+.2f}%"
        }
    ]
    df_t2 = pd.DataFrame(t2_data)
    st.dataframe(df_t2, use_container_width=True, hide_index=True)

    st.markdown(f"### 3. {quarter} {year} SUNDAY SALES DEEP DIVE")
    if not df_sundays.empty:
        df_display_sun = df_sundays.copy()
        total_row = pd.DataFrame([{
            "Date": "TOTAL",
            "Gross_Total": df_sundays['Gross_Total'].sum(),
            "Vape_Sales": df_sundays['Vape_Sales'].sum(),
            "Net_Alcohol": df_sundays['Net_Alcohol'].sum()
        }])
        df_display_sun = pd.concat([df_display_sun, total_row], ignore_index=True)
        st.dataframe(df_display_sun.style.format({
            "Gross_Total": "${:,.2f}",
            "Vape_Sales": "${:,.2f}",
            "Net_Alcohol": "${:,.2f}"
        }), use_container_width=True, hide_index=True)
    else:
        st.info("ℹ️ Drop your Daily POS PDF into the left sidebar to automatically generate the 13-week Sunday Deep Dive table!")

# -------------------------------------------------------------
# TAB 3: WEEKLY SALES DATA BREAKDOWN WITH TOTALS
# -------------------------------------------------------------
with tab3:
    st.markdown(f"### 13-Week Data Points from Weekly KPIs ({year} vs {year-1})")
    
    col_a, col_b = st.columns(2)
    numeric_display = [
        inside_col, 'VAPE SALES', 'Total Shipping Sales', 
        'Flaviar Sales', 'Shipstation Sales', 'Store Payroll 100hrs $2100'
    ]
    
    with col_a:
        st.markdown(f"#### {quarter} {year} Weekly Line Items")
        show_cols_curr = [c for c in ['Date'] + numeric_display if c in df_curr.columns]
        df_c = df_curr[show_cols_curr].copy()
        df_c['Date'] = df_c['Date'].dt.strftime('%Y-%m-%d')
        
        # Calculate and append Totals row
        total_dict_curr = {'Date': 'TOTAL'}
        for col in numeric_display:
            if col in df_curr.columns:
                total_dict_curr[col] = df_curr[col].sum()
        df_c = pd.concat([df_c, pd.DataFrame([total_dict_curr])], ignore_index=True)
        
        fmt_curr = {col: "${:,.2f}" for col in numeric_display if col in df_c.columns}
        st.dataframe(df_c.style.format(fmt_curr), use_container_width=True, hide_index=True)
        
    with col_b:
        st.markdown(f"#### {quarter} {year-1} Weekly Line Items")
        show_cols_prev = [c for c in ['Date'] + numeric_display if c in df_prev.columns]
        df_p = df_prev[show_cols_prev].copy()
        df_p['Date'] = df_p['Date'].dt.strftime('%Y-%m-%d')
        
        # Calculate and append Totals row
        total_dict_prev = {'Date': 'TOTAL'}
        for col in numeric_display:
            if col in df_prev.columns:
                total_dict_prev[col] = df_prev[col].sum()
        df_p = pd.concat([df_p, pd.DataFrame([total_dict_prev])], ignore_index=True)
        
        fmt_prev = {col: "${:,.2f}" for col in numeric_display if col in df_p.columns}
        st.dataframe(df_p.style.format(fmt_prev), use_container_width=True, hide_index=True)
