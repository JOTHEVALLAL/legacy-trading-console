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

    # ---- normalize column names ----
    df.columns = (
        df.columns
        .str.strip()
        .str.lower()
        .str.replace("%", "", regex=False)
        .str.replace("(cr)", "", regex=False)
        .str.replace(" ", "_", regex=False)
    )

    # ---- flexible column mapping ----
    column_map = {
        "symbol": "symbol",
        "adr": "adr",
        "adr_": "adr",
        "liquidity": "liquidity",
        "liquidity_rush": "liquidity",
        "price": "price",
        "close": "price",
        "daily_change": "pct_chg",
        "change": "pct_chg",
        "sector": "sector"
    }

    df = df.rename(columns=column_map)

    # ---- ensure required fields ----
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

    # If no historical series → fallback simple status
    if len(close_cols) < 26:
        df["macd_status"] = "Mixed"
        return df

    # Sort closes oldest → newest
    close_cols = sorted(close_cols)

    macd_status_list = []

    for _, row in df.iterrows():

        closes = row[close_cols].values.astype(float)
        series = pd.Series(closes)

        ema12 = series.ewm(span=12, adjust=False).mean()
        ema26 = series.ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9, adjust=False).mean()
        hist = macd - signal

        if macd.iloc[-1] > signal.iloc[-1] and hist.iloc[-1] > 0:
            if hist.iloc[-1] > 0.25:
                macd_status_list.append("Expansion")
            else:
                macd_status_list.append("Positive")
        elif macd.iloc[-1] > signal.iloc[-1]:
            macd_status_list.append("Early Expansion")
        elif macd.iloc[-1] < signal.iloc[-1] and hist.iloc[-1] < 0:
            macd_status_list.append("Distribution")
        else:
            macd_status_list.append("Mixed")

    df["macd_status"] = macd_status_list
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

    liquidity_score = min(row["liquidity"] / 2000, 1) * 30
    adr_score = min(row["adr"] / 5, 1) * 15

    macd_map = {
        "Expansion": 25,
        "Positive": 22,
        "Early Expansion": 18,
        "Mixed": 10
    }

    macd_score = macd_map.get(row["macd_status"], 5)

    return round(liquidity_score + adr_score + macd_score + 30, 2)


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
# BUILD POSITIONAL TABLE (LOCKED FORMAT)
# =========================================================

def build_positional_table(df: pd.DataFrame) -> pd.DataFrame:

    df["score"] = df.apply(compute_positional_score, axis=1)
    df["trade_bias"] = "Bullish"
    df["trade_style"] = df.apply(classify_positional_trade_style, axis=1)

    df["trend_strength"] = np.where(df["score"] >= 85, "Strong", "Moderate")
    df["portfolio_action"] = np.where(df["score"] >= 80, "Accumulate", "Hold")

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
