import numpy as np
import pandas as pd
from datetime import datetime



# ---------- Load & Clean Data ----------
def load_data(path: str) -> pd.DataFrame:
    df = pd.read_excel(path)

    df.columns = (
        df.columns
        .str.strip()
        .str.lower()
        .str.replace("%", "", regex=False)
        .str.replace("(cr)", "", regex=False)
    )

    return df


# ---------- Helpers ----------
def ensure_column(df, col, default=0):
    if col not in df.columns:
        df[col] = default
    return df


# ---------- Swing Eligibility ----------
def swing_filter(df: pd.DataFrame) -> pd.DataFrame:
    df = ensure_column(df, "macd status", "Unknown")

    swing = df[
        (df["liquidity"] >= 100)
        & (df["adr"] >= 2.5)
        & (df["macd status"].isin(["Early Expansion", "Expansion", "Positive", "Unknown"]))
    ].copy()

    swing["trade style"] = "Swing"
    swing["trade bias"] = "Bullish"

    return swing.sort_values("adr", ascending=False)


# ---------- Near-Miss Detection ----------
def near_miss_filter(df: pd.DataFrame) -> pd.DataFrame:
    df = ensure_column(df, "macd status", "Unknown")

    near = df[
        (df["liquidity"] >= 100)
        & (df["adr"] >= 2.0)
        & (df["adr"] < 2.5)
    ].copy()

    near["reason"] = "ADR slightly below Swing threshold"

    return near.sort_values("adr", ascending=False)


# ---------- Positional Weighted Scoring ----------
def positional_filter(df: pd.DataFrame) -> pd.DataFrame:
    df = ensure_column(df, "macd status", "Unknown")

    pos = df.copy()

    liq_score = (pos["liquidity"] / pos["liquidity"].max()) * 30
    adr_score = (pos["adr"] / pos["adr"].max()) * 15

    momentum_score = pos["macd status"].map(
        {"Early Expansion": 25, "Expansion": 22, "Positive": 18}
    ).fillna(10)

    suitability_score = 30

    pos["score"] = (liq_score + adr_score + momentum_score + suitability_score).round(2)

    pos = pos.sort_values("score", ascending=False)

    pos["trade style"] = "Positional"
    pos["trade bias"] = "Bullish"

    return pos.head(20)

# ---------- Market Mood ----------
def market_mood(df: pd.DataFrame) -> str:
    if df["adr"].mean() >= 3:
        return "Trending"
    if df["adr"].mean() >= 2:
        return "Range"
    return "Volatile"

# ---------- MACD ----------

def compute_macd_status(df: pd.DataFrame) -> pd.DataFrame:

    # ---- detect close columns ----
    close_cols = [c for c in df.columns if c.startswith("close")]

    if len(close_cols) < 26:
        df["macd status"] = "Unknown"
        return df

    # ---- correct chronological order: Close-40 ... Close ----
    def close_order(col):
        if col == "close":
            return 999  # latest
        try:
            return int(col.split("-")[1])
        except:
            return 0

    close_cols = sorted(close_cols, key=close_order, reverse=True)

    macd_results = []

    # ---- compute MACD row-wise ----
    for _, row in df.iterrows():

        prices = pd.to_numeric(row[close_cols], errors="coerce").dropna()

        if len(prices) < 26:
            macd_results.append("Unknown")
            continue

        ema12 = prices.ewm(span=12, adjust=False).mean()
        ema26 = prices.ewm(span=26, adjust=False).mean()

        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        hist = macd_line - signal_line

        last_hist = hist.iloc[-1]
        prev_hist = hist.iloc[-2] if len(hist) > 1 else 0

        # ---- Legacy classification ----
        if last_hist > 0 and prev_hist <= 0:
            macd_results.append("Early Expansion")
        elif last_hist > prev_hist > 0:
            macd_results.append("Expansion")
        elif last_hist > 0:
            macd_results.append("Positive")
        else:
            macd_results.append("Negative")

    df["macd status"] = macd_results

    return df









# ---------- Metadata ----------
def metadata_footer(source_file: str, df: pd.DataFrame) -> dict:
    now = datetime.now()

    session = "LIVE" if 9 <= now.hour < 15 else "PRE" if now.hour < 9 else "POST"

    return {
        "Source_File": source_file,
        "Run_Timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
        "Version_Tag": "Legacy v1.2.6 — Phase-2",
        "Market_Session": session,
        "Market_Mood": market_mood(df),
    }
    
    
# ---------- Locked Swing Table ----------
def build_swing_table(df: pd.DataFrame) -> pd.DataFrame:

    swing = df.copy().reset_index(drop=True)

    swing["Rank"] = swing.index + 1
    swing["Trade Bias"] = "Bullish"
    swing["Trade Style"] = "Swing"
    swing["Score"] = (swing["adr"] * 10).round(1)

    swing["Flags"] = swing["macd status"].apply(
        lambda x: "Early" if x == "Early Expansion" else ""
    )

    swing_table = swing[
        [
            "Rank",
            "symbol",
            "Trade Bias",
            "Trade Style",
            "macd status",
            "Score",
            "price",
            "daily change",
            "adr",
            "liquidity",
            "sector",
            "Flags",
        ]
    ].copy()

    swing_table.columns = [
        "Rank",
        "Symbol",
        "Trade Bias",
        "Trade Style",
        "MACD Status",
        "Score",
        "Price (₹)",
        "% Chg",
        "ADR %",
        "Liquidity (₹ Cr)",
        "Sector",
        "Flags",
    ]

    return swing_table

# ---------- Locked Positional Table ----------
def build_positional_table(df: pd.DataFrame) -> pd.DataFrame:

    pos = df.copy().reset_index(drop=True)

    pos["Rank"] = pos.index + 1
    pos["Trade Bias"] = "Bullish"
    pos["Trade Style"] = "Positional"

    pos["Trend Strength"] = pos["macd status"].map(
        {
            "Early Expansion": "Strong",
            "Expansion": "Strong",
            "Positive": "Moderate",
            "Negative": "Weak",
        }
    )

    pos["Portfolio Action"] = pos["Trend Strength"].map(
        {
            "Strong": "Add",
            "Moderate": "Hold",
            "Weak": "Avoid",
        }
    )

    pos["Flags"] = ""

    pos_table = pos[
        [
            "Rank",
            "symbol",
            "Trade Bias",
            "Trade Style",
            "macd status",
            "score",
            "price",
            "daily change",
            "adr",
            "liquidity",
            "Trend Strength",
            "Portfolio Action",
            "sector",
            "Flags",
        ]
    ].copy()

    pos_table.columns = [
        "Rank",
        "Symbol",
        "Trade Bias",
        "Trade Style",
        "MACD Status",
        "Score",
        "Price (₹)",
        "% Chg",
        "ADR %",
        "Liquidity (₹ Cr)",
        "Trend Strength",
        "Portfolio Action",
        "Sector",
        "Flags",
    ]

    return pos_table

# ---------- Locked Near-Miss Swing Table ----------
def build_near_miss_table(df: pd.DataFrame) -> pd.DataFrame:


        near = df.copy().reset_index(drop=True)


        near["Rank"] = near.index + 1
        near["Trade Bias"] = "Bullish"
        near["Trade Style"] = "Near-Miss"
        near["Score"] = (near["adr"] * 10).round(1)


        near["Flags"] = "ADR < 2.5%"

        near_table = near[
            [       
                "Rank",
                "symbol",
                "Trade Bias",
                "Trade Style",
                "macd status",
                "Score",
                "price",
                "daily change",
                "adr",
                "liquidity",
                "sector",
                "Flags",
            ]
        ].copy()
        
        near_table.columns = [
                "Rank",
                "Symbol",
                "Trade Bias",
                "Trade Style",
                "MACD Status",
                "Score",
                "Price (₹)",
                "% Chg",
                "ADR %",
                "Liquidity (₹ Cr)",
                "Sector",
                "Flags",
        ]


        return near_table
        


# ---------- Styling Helpers ----------
def color_macd(val: str):
    if val in ["Early Expansion", "Expansion"]:
        return "background-color: #d4f4dd"  # soft green
    if val == "Positive":
        return "background-color: #fff3cd"  # soft yellow
    if val == "Negative":
        return "background-color: #f8d7da"  # soft red
    return ""

def color_trend(val: str):
    if val == "Strong":
        return "background-color: #d4f4dd"
    if val == "Moderate":
        return "background-color: #fff3cd"
    if val == "Weak":
        return "background-color: #f8d7da"
    return ""