import pandas as pd
import numpy as np
from datetime import datetime


# =========================================================
# LOAD & STANDARDIZE DATA
# =========================================================

def load_data(path: str) -> pd.DataFrame:

    if path.endswith(".csv"):
        df = pd.read_csv(path)
    else:
        df = pd.read_excel(path)

    # ---- Normalize column names ----
    df.columns = (
        df.columns
        .str.strip()
        .str.lower()
        .str.replace("%", "", regex=False)
        .str.replace("(cr)", "", regex=False)
        .str.replace(" ", "_", regex=False)
    )

    df = df.rename(columns={
        "symbol": "symbol",
        "adr": "adr",
        "liquidity_rush": "liquidity",
        "price": "price",
        "daily_change": "pct_chg",
        "sector": "sector"
    })

    df = df.loc[:, ~df.columns.duplicated()]

    required = ["symbol", "adr", "liquidity", "price", "pct_chg", "sector"]
    for col in required:
        if col not in df.columns:
            df[col] = 0

    df = compute_macd_status(df)

    return df


# =========================================================
# VOLUME SERIES HELPER (30 Days)
# =========================================================

def get_close_series(row):

    vol_cols = [c for c in row.index if c.startswith("volume")]

    def extract_number(col):
        if col == "volume":
            return 0
        digits = ''.join(filter(str.isdigit, col))
        return int(digits) if digits else 0

    vol_cols_sorted = sorted(vol_cols, key=extract_number, reverse=True)
    volumes = row[vol_cols_sorted].astype(float).values

    return pd.Series(volumes)


# =========================================================
# ENTRY + SIGNAL (SL + Volume + 52W)
# =========================================================


def compute_entry_signal(row):

    close_series = get_close_series(row)
    vol_series = get_volume_series(row)

    if len(close_series) < 30:
        return "", "", ""

    pivot_close = close_series.iloc[-30:].max()
    current_close = close_series.iloc[-1]

    # ----- Structure-Based SL (10-day low) -----
    recent_low = close_series.iloc[-10:].min()
    sl_price = round(recent_low * 0.995, 2)

    entry_price = round(pivot_close * 1.002, 2)
    distance_pct = (pivot_close - current_close) / pivot_close * 100

    icon = ""
    signal = ""

    # ----- Volume Baseline -----
    if len(vol_series) >= 30:
        current_vol = vol_series.iloc[-1]
        avg_vol_30 = vol_series.iloc[-30:].mean()
    else:
        current_vol = 0
        avg_vol_30 = 0

    # ----- Breakout Logic -----
    if current_close >= pivot_close:
        icon = " 🔥"

        if avg_vol_30 > 0 and current_vol > 1.3 * avg_vol_30:
            signal = "Breakout – Strong Vol"
        else:
            signal = "Breakout"

    elif distance_pct <= 2:
        icon = " ⚡"
        signal = f"Near Pivot ({round(distance_pct,2)}%)"

    else:
        signal = f"Watching – {round(distance_pct,2)}% below"

    # ----- 52 Week High Context -----
    if "52week_high" in row and row["52week_high"] > 0:
        high_52 = float(row["52week_high"])
        dist_52 = (high_52 - current_close) / high_52 * 100
        if dist_52 <= 3:
            signal += " | Near 52W High"

    return f"{entry_price}{icon}", sl_price, signal   


# =========================================================
# MACD ENGINE
# =========================================================

def compute_macd_status(df: pd.DataFrame) -> pd.DataFrame:

    close_cols = [c for c in df.columns if c.startswith("close")]

    if len(close_cols) < 26:
        df["macd_status"] = "Negative"
        return df

    def extract_number(col):
        if col == "close":
            return 0
        digits = ''.join(filter(str.isdigit, col))
        return int(digits) if digits else 0

    close_cols_sorted = sorted(close_cols, key=extract_number, reverse=True)

    macd_results = []

    for _, row in df.iterrows():

        closes = row[close_cols_sorted].astype(float).values
        series = pd.Series(closes)

        ema12 = series.ewm(span=12, adjust=False).mean()
        ema26 = series.ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9, adjust=False).mean()
        hist = macd - signal

        last_hist = hist.iloc[-1]
        prev_hist = hist.iloc[-2]

        if last_hist > 0 and prev_hist <= 0:
            macd_results.append("Early Expansion")
        elif last_hist > prev_hist > 0:
            macd_results.append("Expansion")
        elif last_hist > 0:
            macd_results.append("Positive")
        else:
            macd_results.append("Negative")

    df["macd_status"] = macd_results
    return df


# =========================================================
# SWING FILTER
# =========================================================

def swing_filter(df: pd.DataFrame) -> pd.DataFrame:

    return df[
        (df["liquidity"] >= 100) &
        (df["adr"] >= 2.5) &
        (df["macd_status"].isin(["Early Expansion", "Expansion", "Positive"]))
    ].copy()


# =========================================================
# SCORING ENGINES (UNCHANGED)
# =========================================================

def compute_swing_score(row):

    liquidity_score = min(row["liquidity"] / 1000, 1) * 30
    adr_score = min(row["adr"] / 5, 1) * 25

    macd_map = {
        "Expansion": 30,
        "Positive": 25,
        "Early Expansion": 20
    }

    macd_score = macd_map.get(row["macd_status"], 0)

    return round(liquidity_score + adr_score + macd_score + 15, 2)


def compute_positional_score(row):

    liquidity_score = min(row["liquidity"] / 2000, 1) * 30
    adr_score = min(row["adr"] / 5, 1) * 15

    macd_map = {
        "Expansion": 25,
        "Early Expansion": 22,
        "Positive": 18,
        "Negative": 5
    }

    macd_score = macd_map.get(row["macd_status"], 5)

    suitability_score = 10 if row["macd_status"] == "Negative" else 30

    total_score = liquidity_score + adr_score + macd_score + suitability_score

    if row["macd_status"] == "Negative":
        total_score = min(total_score, 60)

    return round(total_score, 2)


# =========================================================
# SWING TABLE
# =========================================================

def build_swing_table(df: pd.DataFrame) -> pd.DataFrame:

    df = swing_filter(df)

    df["score"] = df.apply(compute_swing_score, axis=1)
    df["trade_bias"] = "Bullish"
    df["trade_style"] = "Momentum"

    entries = df.apply(compute_entry_signal, axis=1)

    df["Entry (₹)"] = [e[0] for e in entries]
    df["SL (₹)"] = [e[1] for e in entries]
    df["Signal"] = [e[2] for e in entries]

    df = df.sort_values("score", ascending=False).reset_index(drop=True)
    df["rank"] = df.index + 1

    return df.rename(columns={
    "symbol": "Symbol",
    "macd_status": "MACD Status",
    "score": "Score",
    "price": "Price",
    "pct_chg": "% Chg",
    "adr": "ADR %",
    "liquidity": "Liquidity",
    "sector": "Sector",
    "trade_bias": "Trade Bias",
    "trade_style": "Trade Style",
    "rank": "Rank"
})[[
    "Rank","Symbol","Trade Bias","Trade Style","MACD Status",
    "Score","Entry (₹)","SL (₹)","Signal",
    "Price","% Chg","ADR %","Liquidity","Sector"
]]


# =========================================================
# VCP (Close-Based Fast Cycle)
# =========================================================

def compute_vcp_status(row):

    series = get_close_series(row).tail(50)

    if len(series) < 40:
        return ""

    seg_A = series.iloc[0:15].std()
    seg_B = series.iloc[15:30].std()
    seg_C = series.iloc[30:].std()

    contraction = (seg_B < seg_A) and (seg_C < seg_B)

    pivot_close = series.iloc[-30:].max()
    current_close = series.iloc[-1]
    distance_pct = (pivot_close - current_close) / pivot_close * 100

    if contraction and distance_pct <= 2:
        return "Confirmed VCP"
    elif contraction and distance_pct <= 4:
        return "Valid VCP"
    elif seg_C < seg_B:
        return "Developing VCP"
    else:
        return ""


# =========================================================
# POSITIONAL TABLE
# =========================================================

def build_positional_table(df: pd.DataFrame) -> pd.DataFrame:

    df["score"] = df.apply(compute_positional_score, axis=1)

    df = df[
        (df["macd_status"].isin(["Expansion", "Early Expansion", "Positive"])) &
        (df["score"] >= 70)
    ].copy()

    df["trade_bias"] = "Bullish"
    df["trade_style"] = "Positional"
    df["trend_strength"] = np.where(df["score"] >= 85, "Strong", "Moderate")
    df["portfolio_action"] = np.where(df["score"] >= 80, "Accumulate", "Hold")

    df["VCP Status"] = df.apply(compute_vcp_status, axis=1)

    df = df.sort_values("score", ascending=False).reset_index(drop=True)
    df["rank"] = df.index + 1

    return df.rename(columns={
        "symbol": "Symbol",
        "macd_status": "MACD Status",
        "score": "Score",
        "price": "Price",
        "pct_chg": "% Chg",
        "adr": "ADR %",
        "liquidity": "Liquidity",
        "sector": "Sector",
        "trade_bias": "Trade Bias",
        "trade_style": "Trade Style",
        "trend_strength": "Trend Strength",
        "portfolio_action": "Portfolio Action",
        "rank": "Rank"
    })[[
        "Rank","Symbol","Trade Bias","Trade Style","MACD Status",
        "VCP Status",
        "Score","Price","% Chg","ADR %","Liquidity",
        "Trend Strength","Portfolio Action","Sector"
    ]]

# =========================================================
# NEAR MISS FILTER (LOCKED)
# =========================================================

def near_miss_filter(df: pd.DataFrame) -> pd.DataFrame:

    adr_near = df[
        (df["liquidity"] >= 100) &
        (df["adr"].between(2.0, 2.49)) &
        (df["macd_status"].isin(["Early Expansion", "Expansion", "Positive"]))
    ]

    macd_near = df[
        (df["liquidity"] >= 100) &
        (df["adr"] >= 2.5) &
        (~df["macd_status"].isin(["Early Expansion", "Expansion", "Positive"]))
    ]

    return pd.concat([adr_near, macd_near]).copy()
    
    


# =========================================================
# METADATA
# =========================================================

def metadata_footer(source_file, version="Legacy v1.3.0"):

    now = datetime.now()
    session = "LIVE" if 9 <= now.hour < 15 else "POST"

    return {
        "Source_File": source_file,
        "Run_Timestamp": now.strftime("%d-%b-%Y %H:%M"),
        "Run_ID": f"LEG-{now.strftime('%d%m%y-%H%M')}",
        "Version_Tag": version,
        "Market Session": session
    }
    
    
# =========================================================
# STYLING HELPERS
# =========================================================

def color_macd(val):

    if val == "Expansion":
        return "background-color: #c6e6c3"

    if val == "Early Expansion":
        return "background-color: #d4f4dd"

    if val == "Positive":
        return "background-color: #fff3cd"

    if val == "Negative":
        return "background-color: #f8d7da"

    return ""


def color_trend(val):

    if val == "Strong":
        return "background-color: #c6e6c3"

    if val == "Moderate":
        return "background-color: #fff3cd"

    if val == "Weak":
        return "background-color: #f8d7da"

    return ""