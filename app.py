import streamlit as st
import pandas as pd
import pypdf
import re
from datetime import datetime
import io
import csv
import requests
import os

st.set_page_config(page_title="Liquors Ventures Analytics", layout="wide")

# Custom Styling (Dark theme & table styling)
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
# 1. Automatic PDF Parsing Engine (Cached for speed)
# -------------------------------------------------------------
@st.cache_data(show_spinner=False)
def parse_sundays_from_pdf_bytes(pdf_bytes):
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
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
        'Total Shipping Sales', 'Store Payroll 100hrs \$2100', 'Shipping Payroll', 'Total Labor Under',
        'VAPE SALES', 'INSIDE TRANS COUNT', 'Flaviar Sales', 'Shipstation Sales', 
        'Flaviar Parcels', 'Shipstation parcels', 'Total Parcels'
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = df[col].astype(str).str.replace('\$', '', regex=False).str.replace(',', '', regex=False).str.strip()
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
# 4. Permanent Archive Loader + Sidebar Fallback
# -------------------------------------------------------------
st.sidebar.header("📁 Quarterly POS PDF")
uploaded_pdf = st.sidebar.file_uploader(
    f"Upload custom {year} {quarter} Daily POS PDF", 
    type=["pdf"]
)

df_sundays = pd.DataFrame()

# Check local repository archive paths
possible_pdf_paths = [
    f"pdf_archive/{year}_{quarter}.pdf",
    f"sundays/{year}_{quarter}.pdf",
    f"{year}_{quarter}.pdf"
]

found_archived_file = None
for p in possible_pdf_paths:
    if os.path.exists(p):
        found_archived_file = p
        break

if uploaded_pdf is not None:
    with st.spinner(f"Parsing uploaded {quarter} PDF..."):
        df_sundays = parse_sundays_from_pdf_bytes(uploaded_pdf.getvalue())
        st.sidebar.success(f"Loaded from upload: {len(df_sundays)} Sundays found!")
elif found_archived_file is not None:
    with open(found_archived_file, "rb") as f:
        file_bytes = f.read()
    df_sundays = parse_sundays_from_pdf_bytes(file_bytes)
    st.sidebar.info(f"📂 Auto-loaded permanent archive: `{found_archived_file}` ({len(df_sundays)} Sundays)")
else:
    # Check if a pre-calculated CSV exists
    possible_csv_paths = [f"sundays/{year}_{quarter}.csv", f"{year}_{quarter}.csv"]
    for cp in possible_csv_paths:
        if os.path.exists(cp):
            df_sundays = pd.read_csv(cp)
            st.sidebar.info(f"Loaded cached Sundays from `{cp}`")
            break

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

# Inside sales column definition
inside_col = 'Weekly Inside sales w/o lottery' if 'Weekly Inside sales w/o lottery' in df_kpi.columns else 'INSIDE SALES'

# Current Quarter Figures
gross_inside_curr = df_curr[inside_col].sum()
shipping_curr = df_curr['Total Shipping Sales'].sum()
store_payroll_curr = df_curr['Store Payroll 100hrs \$2100'].sum()
shipping_payroll_curr = df_curr['Shipping Payroll'].sum() if 'Shipping Payroll' in df_curr.columns else 0.0
total_labor_curr = store_payroll_curr + shipping_payroll_curr

vape_curr = df_curr['VAPE SALES'].sum()
total_sales_curr = gross_inside_curr + shipping_curr

# Previous Year Figures
gross_inside_prev = df_prev[inside_col].sum()
shipping_prev = df_prev['Total Shipping Sales'].sum()
store_payroll_prev = df_prev['Store Payroll 100hrs \$2100'].sum()
shipping_payroll_prev = df_prev['Shipping Payroll'].sum() if 'Shipping Payroll' in df_prev.columns else 0.0
total_labor_prev = store_payroll_prev + shipping_payroll_prev

vape_prev = df_prev['VAPE SALES'].sum()
total_sales_prev = gross_inside_prev + shipping_prev

# Normalization
if apples_to_apples and year == 2026:
    adjusted_inside_curr = gross_inside_curr - vape_curr - sunday_net_deduction
    adjusted_inside_prev = gross_inside_prev - vape_prev
else:
    adjusted_inside_curr = gross_inside_curr
    adjusted_inside_prev = gross_inside_prev

pct_inside_change = ((adjusted_inside_curr - adjusted_inside_prev) / adjusted_inside_prev) * 100 if adjusted_inside_prev else 0

# Total Labor Rate (Total Labor / Total Sales including Sundays and Vape)
labor_rate_curr = (total_labor_curr / total_sales_curr) * 100 if total_sales_curr else 0
labor_rate_prev = (total_labor_prev / total_sales_prev) * 100 if total_sales_prev else 0

# -------------------------------------------------------------
# 6. Bonus Calculations Engine (Using Total Labor Rate)
# -------------------------------------------------------------
def get_sales_bonus(growth):
    if growth >= 25.0:
        return 2500
    elif growth >= 20.0:
        return 2000
    elif growth >= 15.0:
        return 1500
    elif growth >= 8.0:
        return 1000
    elif growth >= 6.0:
        return 750
    elif growth >= 4.0:
        return 500
    return 0

def get_labor_bonus(rate):
    if rate <= 8.00:
        return 1000
    elif rate <= 9.00:
        return 750
    elif rate <= 11.00:
        return 500
    return 0

sales_bonus = get_sales_bonus(pct_inside_change)
labor_bonus = get_labor_bonus(labor_rate_curr)
total_bonus = sales_bonus + labor_bonus

# -------------------------------------------------------------
# 7. Render Tabs
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
    s1.metric("1. Gross Inside Sales", f"\${gross_inside_curr:,.2f}", f"Source: {inside_col}")
    s2.metric("2. Vape Deductions", f"-\${vape_curr:,.2f}", "Category Launch: May '25")
    s3.metric("3. Sunday Deductions", f"-\${sunday_net_deduction:,.2f}", f"{len(df_sundays)} Sundays Detected")
    s4.metric("4. Adjusted Inside Alcohol", f"\${adjusted_inside_curr:,.2f}", "Mon-Sat Core Non-Vape")
    s5.metric("5. Normalized YoY", f"{pct_inside_change:.2f}%", f"vs PY Baseline: \${adjusted_inside_prev:,.2f}")

    st.divider()

    # 8 KPI Cards
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("TOTAL GROSS SALES", f"\${total_sales_curr:,.2f}", f"{((total_sales_curr - total_sales_prev)/total_sales_prev)*100:+.2f}% YoY" if total_sales_prev else "-")
    k2.metric("CORE ADJUSTED INSIDE", f"\${adjusted_inside_curr:,.2f}", f"{pct_inside_change:+.2f}% Core")
    k3.metric("SHIPPING SALES (E-COMM)", f"\${shipping_curr:,.2f}", f"{((shipping_curr - shipping_prev)/shipping_prev)*100:+.2f}% YoY" if shipping_prev else "-")
    k4.metric("TOTAL LABOR (STORE + SHIP)", f"\${total_labor_curr:,.2f}", f"{((total_labor_curr - total_labor_prev)/total_labor_prev)*100:+.2f}% YoY" if total_labor_prev else "-")

    k5, k6, k7, k8 = st.columns(4)
    k5.metric("TOTAL LABOR % OF SALES", f"{labor_rate_curr:.2f}%", f"PY: {labor_rate_prev:.2f}%")
    k6.metric("STORE TRANSACTIONS", f"{int(df_curr['INSIDE TRANS COUNT'].sum()):,}", f"Avg Ticket: \${gross_inside_curr / max(1, df_curr['INSIDE TRANS COUNT'].sum()):.2f}")
    k7.metric("SUNDAY REVENUE EXTRACTED", f"\${sunday_gross:,.2f}", f"Net Impact: -\${sunday_net_deduction:,.2f}")
    k8.metric("TOTAL PARCELS SHIPPED", f"{int(df_curr['Total Parcels'].sum() if 'Total Parcels' in df_curr.columns else len(df_curr)*115):,}")

    st.divider()

    # BONUS QUALIFICATION CARDS
    st.subheader("🎯 Quarterly Bonus Qualification")
    b1, b2, b3 = st.columns(3)
    b1.metric("Store Sales Bonus", f"\${sales_bonus:,.2f}", f"Core Growth: {pct_inside_change:+.2f}%")
    b2.metric("Labor Rate Bonus", f"\${labor_bonus:,.2f}", f"Total Labor Rate: {labor_rate_curr:.2f}%")
    b3.metric("Total Qualified Bonus", f"\${total_bonus:,.2f}", "Combined Payout")

# -------------------------------------------------------------
# TAB 2: EXACT TABLES FROM 2ND ATTACHMENT + BONUS SUMMARY
# -------------------------------------------------------------
with tab2:
    st.markdown(f"### 1. EXECUTIVE OVERVIEW ({quarter} {year} vs {quarter} {year-1})")
    
    labor_diff = total_labor_curr - total_labor_prev
    labor_pct = (labor_diff / total_labor_prev)*100 if total_labor_prev else 0.0

    t1_data = [
        {
            "Metric": f"Total {quarter} Sales",
            f"{quarter} {year}": f"\${total_sales_curr:,.2f}",
            f"{quarter} {year-1}": f"\${total_sales_prev:,.2f}",
            "Gain/Loss (\$)": f"\${(total_sales_curr - total_sales_prev):+,.2f}",
            "Gain/Loss (%)": f"{((total_sales_curr - total_sales_prev)/total_sales_prev)*100:+.2f}%" if total_sales_prev else "-"
        },
        {
            "Metric": "Net Inside Alcohol Sales",
            f"{quarter} {year}": f"\${adjusted_inside_curr:,.2f}",
            f"{quarter} {year-1}": f"\${adjusted_inside_prev:,.2f}",
            "Gain/Loss (\$)": f"\${(adjusted_inside_curr - adjusted_inside_prev):+,.2f}",
            "Gain/Loss (%)": f"{pct_inside_change:+.2f}%"
        },
        {
            "Metric": "Shipping Revenue",
            f"{quarter} {year}": f"\${shipping_curr:,.2f}",
            f"{quarter} {year-1}": f"\${shipping_prev:,.2f}",
            "Gain/Loss (\$)": f"\${(shipping_curr - shipping_prev):+,.2f}",
            "Gain/Loss (%)": f"{((shipping_curr - shipping_prev)/shipping_prev)*100:+.2f}%" if shipping_prev else "-"
        },
        {
            "Metric": f"{quarter} Total Labor (Store + Shipping Payroll)",
            f"{quarter} {year}": f"\${total_labor_curr:,.2f}",
            f"{quarter} {year-1}": f"\${total_labor_prev:,.2f}",
            "Gain/Loss (\$)": f"\${labor_diff:+,.2f}",
            "Gain/Loss (%)": f"{labor_pct:+.2f}%" if total_labor_prev else "-"
        },
        {
            "Metric": "Labor Rate (Total Labor / Total Sales)",
            f"{quarter} {year}": f"{labor_rate_curr:.2f}%",
            f"{quarter} {year-1}": f"{labor_rate_prev:.2f}%",
            "Gain/Loss (\$)": f"{(labor_rate_curr - labor_rate_prev):+.2f}% pts",
            "Gain/Loss (%)": ""
        },
        {
            "Metric": "🏆 Total Qualified Bonus",
            f"{quarter} {year}": f"\${total_bonus:,.2f}",
            f"{quarter} {year-1}": "-",
            "Gain/Loss (\$)": f"Sales: ${sales_bonus} \vert{} Labor:${labor_bonus}",
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
            f"{quarter} {year}": f"\${gross_inside_curr:,.2f}",
            f"{quarter} {year-1}": f"\${gross_inside_prev:,.2f}",
            "Gain/Loss (\$)": f"\${(gross_inside_curr - gross_inside_prev):+,.2f}",
            "Gain/Loss (%)": f"{((gross_inside_curr - gross_inside_prev)/gross_inside_prev)*100:+.2f}%"
        },
        {
            "Category": "Vape Sales Deductions",
            f"{quarter} {year}": f"-\${vape_curr:,.2f}",
            f"{quarter} {year-1}": f"-\${vape_prev:,.2f}",
            "Gain/Loss (\$)": f"-\${vape_diff:,.2f}",
            "Gain/Loss (%)": f"{vape_pct:+.2f}%"
        },
        {
            "Category": "Sunday Sales Deductions",
            f"{quarter} {year}": f"-\${sunday_net_deduction:,.2f}",
            f"{quarter} {year-1}": "\$0.00",
            "Gain/Loss (\$)": f"-\${sunday_net_deduction:,.2f}" if sunday_net_deduction else "\$0.00",
            "Gain/Loss (%)": "-"
        },
        {
            "Category": "Total Net Inside Alcohol Sales",
            f"{quarter} {year}": f"\${adjusted_inside_curr:,.2f}",
            f"{quarter} {year-1}": f"\${adjusted_inside_prev:,.2f}",
            "Gain/Loss (\$)": f"\${(adjusted_inside_curr - adjusted_inside_prev):+,.2f}",
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
            "Gross_Total": "\${:,.2f}",
            "Vape_Sales": "\${:,.2f}",
            "Net_Alcohol": "\${:,.2f}"
        }), use_container_width=True, hide_index=True)
    else:
        st.info(f"ℹ️ Drop `{year}_{quarter}.pdf` into your repository or the sidebar to populate the 13-week Sunday table!")

# -------------------------------------------------------------
# TAB 3: WEEKLY SALES DATA BREAKDOWN WITH TOTALS
# -------------------------------------------------------------
with tab3:
    st.markdown(f"### 13-Week Data Points from Weekly KPIs ({year} vs {year-1})")
    
    col_a, col_b = st.columns(2)
    numeric_display = [
        inside_col, 'Total Shipping Sales', 'Total Weekly Sales with out Lottery', 
        'VAPE SALES', 'Store Payroll 100hrs \$2100', 'Shipping Payroll', 'Total Labor Under'
    ]
    
    with col_a:
        st.markdown(f"#### {quarter} {year} Weekly Line Items")
        show_cols_curr = [c for c in ['Date'] + numeric_display if c in df_curr.columns]
        df_c = df_curr[show_cols_curr].copy()
        df_c['Date'] = df_c['Date'].dt.strftime('%Y-%m-%d')
        
        # Append Totals row
        total_dict_curr = {'Date': 'TOTAL'}
        for col in numeric_display:
            if col in df_curr.columns:
                total_dict_curr[col] = df_curr[col].sum()
        df_c = pd.concat([df_c, pd.DataFrame([total_dict_curr])], ignore_index=True)
        
        fmt_curr = {col: "\${:,.2f}" for col in numeric_display if col in df_c.columns}
        st.dataframe(df_c.style.format(fmt_curr), use_container_width=True, hide_index=True)
        
    with col_b:
        st.markdown(f"#### {quarter} {year-1} Weekly Line Items")
        show_cols_prev = [c for c in ['Date'] + numeric_display if c in df_prev.columns]
        df_p = df_prev[show_cols_prev].copy()
        df_p['Date'] = df_p['Date'].dt.strftime('%Y-%m-%d')
        
        # Append Totals row
        total_dict_prev = {'Date': 'TOTAL'}
        for col in numeric_display:
            if col in df_prev.columns:
                total_dict_prev[col] = df_prev[col].sum()
        df_p = pd.concat([df_p, pd.DataFrame([total_dict_prev])], ignore_index=True)
        
        fmt_prev = {col: "\${:,.2f}" for col in numeric_display if col in df_p.columns}
        st.dataframe(df_p.style.format(fmt_prev), use_container_width=True, hide_index=True)
