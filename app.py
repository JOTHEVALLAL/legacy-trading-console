import streamlit as st
from datetime import datetime

from legacy_logic import (
    load_data,
    build_swing_table,
    build_positional_table,
    near_miss_filter,
    metadata_footer,
)

# --------------------------------------------------
# PAGE CONFIG
# --------------------------------------------------

st.set_page_config(page_title="Legacy Trading Console", layout="wide")
st.title("📊 Legacy Template — Production Dashboard")

# --------------------------------------------------
# DATA SOURCE
# --------------------------------------------------

DATA_PATH = "https://docs.google.com/spreadsheets/d/1mKkUz7qQlZr8KqCtIOQuBw2mbUEGlgel/export?format=xlsx"

df = load_data(DATA_PATH)

# --------------------------------------------------
# BUILD TABLES (NO DOUBLE FILTERING)
# --------------------------------------------------

swing_table = build_swing_table(df)
pos_table = build_positional_table(df)

near_df = near_miss_filter(df)

# Build near-miss table inline (cleaned format)
near_df = near_df.copy().reset_index(drop=True)
near_df["Rank"] = near_df.index + 1

near_table = near_df.rename(columns={
    "symbol": "Symbol",
    "macd_status": "MACD Status",
    "price": "Price",
    "pct_chg": "% Chg",
    "adr": "ADR %",
    "liquidity": "Liquidity",
    "sector": "Sector",
    "Rank": "Rank"
})[[
    "Rank","Symbol","MACD Status","Price","% Chg","ADR %","Liquidity","Sector"
]]

# --------------------------------------------------
# DISPLAY
# --------------------------------------------------

st.subheader("🚀 Swing Candidates")
st.dataframe(swing_table, use_container_width=True)

st.subheader("📈 Top Positional Opportunities")
st.dataframe(pos_table, use_container_width=True)

st.subheader("⚠️ Near-Miss Swing")
st.dataframe(near_table, use_container_width=True)

# --------------------------------------------------
# METADATA
# --------------------------------------------------

meta = metadata_footer(DATA_PATH)

st.divider()
st.subheader("Run Metadata")

for k, v in meta.items():
    st.write(f"**{k}:** {v}")


try:
    df = load_data(DATA_PATH)
except Exception as e:
    st.error("Data loading failed.")
    st.stop()
