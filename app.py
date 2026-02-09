import streamlit as st
import time
from datetime import datetime

from legacy_logic import (
    load_data,
    swing_filter,
    positional_filter,
    near_miss_filter,
    metadata_footer,
    build_swing_table,
    build_positional_table,
    build_near_miss_table,
    compute_macd_status,
    color_macd,      # ✅ added
    color_trend,     # ✅ added
)

# ---------- NSE auto refresh ----------
now = datetime.now()
if 9 <= now.hour < 15:
    time.sleep(900)  # 15-minute refresh
    st.rerun()

# ---------- File path ----------
DATA_PATH = "https://docs.google.com/spreadsheets/d/1mKkUz7qQlZr8KqCtIOQuBw2mbUEGlgel/export?format=xlsx"


# ---------- Page setup ----------
st.set_page_config(page_title="Legacy Trading Console", layout="wide")
st.title("📊 Legacy Template — Production Dashboard")

# ---------- Load data ----------
df = load_data(DATA_PATH)

# 🔴 Ensure MACD computed
df = compute_macd_status(df)

swing_df = swing_filter(df)
pos_df = positional_filter(df)
near_df = near_miss_filter(df)
meta = metadata_footer(DATA_PATH, df)

# ---------- Build locked tables ----------
swing_table = build_swing_table(swing_df)
pos_table = build_positional_table(pos_df)
near_table = build_near_miss_table(near_df)

# ---------- Display tables with institutional styling + 2-decimal format ----------

num_format = {
    "Score": "{:.2f}",
    "Price (₹)": "{:.2f}",
    "% Chg": "{:.2f}",
    "ADR %": "{:.2f}",
    "Liquidity (₹ Cr)": "{:.2f}",
}


st.subheader("🚀 Swing Candidates")
st.dataframe(
    swing_table.style
        .applymap(color_macd, subset=["MACD Status"])
        .format(num_format),
    width="stretch",
)

st.subheader("📈 Top Positional Opportunities")
st.dataframe(
    pos_table.style
        .applymap(color_macd, subset=["MACD Status"])
        .applymap(color_trend, subset=["Trend Strength"])
        .format(num_format),
    width="stretch",
)

st.subheader("⚠️ Near-Miss Swing")
st.dataframe(
    near_table.style
        .applymap(color_macd, subset=["MACD Status"])
        .format(num_format),
    width="stretch",
)

from legacy_logic import send_telegram_alert

# ---------- Detect NEW Early Expansion ----------
early_expansion = swing_df[swing_df["macd status"] == "Early Expansion"]

if not early_expansion.empty:
    for _, row in early_expansion.iterrows():
        msg = (
            "📈 *NEW EARLY EXPANSION*\n\n"
            f"Stock: {row['symbol']}\n"
            f"ADR: {row['adr']:.2f}%\n"
            f"Liquidity: ₹{row['liquidity']:.2f} Cr"
        )
        send_telegram_alert(msg)


# ---------- Metadata ----------
st.divider()
st.subheader("Run Metadata")

for k, v in meta.items():
    st.write(f"**{k}:** {v}")
