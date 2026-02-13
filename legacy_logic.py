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
    
    # ---- Rename only what is needed ----
    df = df.rename(columns={
        "symbol": "symbol",
        "adr": "adr",
        "liquidity_rush": "liquidity",
        "price": "price",
        "daily_change": "pct_chg",
        "sector": "sector"
    })

    # ---- DO NOT MAP close → price ----
    # Close columns must remain separate for MACD

    # ---- Remove duplicate columns safely ----
    df = df.loc[:, ~df.columns.duplicated()]

    # ---- Ensure required fields ----
    required = ["symbol", "adr", "liquidity", "price", "pct_chg", "sector"]
    for col in required:
        if col not in df.columns:
            df[col] = 0

    df = compute_macd_status(df)

    return df
    


# =========================================================
# MACD ENGINE (Row-wise historical close support)
# =========================================================

def compute_macd_status(df: pd.DataFrame) -> pd.DataFrame:

    close_cols = [c for c in df.columns if c.startswith("close")]

    if len(close_cols) < 26:
        df["macd_status"] = "Negative"
        return df

    # ---- Proper chronological sorting ----
    def extract_number(col):
        if col == "close":
            return 0
        return int(col.split("-")[1])

    # Oldest → Newest
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

        # ---- Legacy Classification ----
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
# SWING HARD GATE FILTER
# =========================================================

def swing_filter(df: pd.DataFrame) -> pd.DataFrame:

    return df[
        (df["liquidity"] >= 100) &
        (df["adr"] >= 2.5) &
        (df["macd_status"].isin(["Early Expansion", "Expansion", "Positive"]))
    ].copy()


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
# SCORING ENGINES
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

    # --- Base scaling ---
    liquidity_score = min(row["liquidity"] / 2000, 1) * 30
    adr_score = min(row["adr"] / 5, 1) * 15

    macd_map = {
        "Expansion": 25,
        "Early Expansion": 22,
        "Positive": 18,
        "Negative": 5
    }

    macd_score = macd_map.get(row["macd_status"], 5)

    # --- Suitability adjustment ---
    if row["macd_status"] == "Negative":
        suitability_score = 10   # reduced from 30
    else:
        suitability_score = 30

    total_score = liquidity_score + adr_score + macd_score + suitability_score

    # Optional: Cap negative momentum score
    if row["macd_status"] == "Negative":
        total_score = min(total_score, 60)

    return round(total_score, 2)



# =========================================================
# TRADE STYLE (STANDARDIZED)
# =========================================================

def classify_swing_trade_style(row):

    if row["macd_status"] in ["Expansion", "Positive"] and row["adr"] >= 5:
        return "Volatility Expansion"

    if row["macd_status"] in ["Expansion", "Early Expansion"] and row["pct_chg"] >= 2:
        return "Breakout Setup"

    if row["macd_status"] == "Early Expansion":
        return "Momentum Expansion"

    return "Trend Continuation"


def classify_positional_trade_style(row):


    if row["macd_status"] == "Negative":
        return "Weak Structure"

    if row["score"] >= 85 and row["macd_status"] in ["Expansion", "Positive"]:
        return "Structural Trend"

    if row["score"] >= 75:
        return "Positional Momentum"

    return "Accumulation Phase"

# =========================================================
# BUILD SWING TABLE (LOCKED FORMAT)
# =========================================================

def build_swing_table(df: pd.DataFrame) -> pd.DataFrame:

    df = swing_filter(df)
    df["score"] = df.apply(compute_swing_score, axis=1)
    df["trade_bias"] = "Bullish"
    df["trade_style"] = df.apply(classify_swing_trade_style, axis=1)

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
        "Score","Price","% Chg","ADR %","Liquidity","Sector"
    ]]


# =========================================================
# BUILD POSITIONAL TABLE (QUALITY FILTERED)
# =========================================================

def build_positional_table(df: pd.DataFrame) -> pd.DataFrame:

    # --- Compute score first ---
    df["score"] = df.apply(compute_positional_score, axis=1)

    # --- Quality Filter ---
    df = df[
        (df["macd_status"].isin(["Expansion", "Early Expansion", "Positive"])) &
        (df["score"] >= 70)
    ].copy()

    # --- Add Bias & Style ---
    df["trade_bias"] = "Bullish"
    df["trade_style"] = df.apply(classify_positional_trade_style, axis=1)

    # --- Strength & Action ---
    df["trend_strength"] = np.where(df["score"] >= 85, "Strong", "Moderate")
    df["portfolio_action"] = np.where(df["score"] >= 80, "Accumulate", "Hold")

    # --- Sort & Rank ---
    df = df.sort_values("score", ascending=False).reset_index(drop=True)
    df["rank"] = df.index + 1

    # --- Return Locked Structure ---
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
        "Score","Price","% Chg","ADR %","Liquidity",
        "Trend Strength","Portfolio Action","Sector"
    ]]


# =========================================================
# METADATA FOOTER
# =========================================================

def metadata_footer(source_file, version="Legacy v1.2.6"):

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
        return "background-color: #c6e6c3"   # soft green

    if val == "Early Expansion":
        return "background-color: #d4f4dd"   # lighter green

    if val == "Positive":
        return "background-color: #fff3cd"   # soft yellow

    if val == "Negative":
        return "background-color: #f8d7da"   # soft red

    return ""


def color_trend(val):

    if val == "Strong":
        return "background-color: #c6e6c3"   # green

    if val == "Moderate":
        return "background-color: #fff3cd"   # yellow

    if val == "Weak":
        return "background-color: #f8d7da"   # red

    return ""
