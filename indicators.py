import pandas as pd
import numpy as np


def calculate_rsi(df, period=14):
    delta = df["close"].diff()

    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)

    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    return round(rsi.iloc[-1], 2)


def calculate_ema(df, period):
    ema = df["close"].ewm(span=period, adjust=False).mean()
    return round(ema.iloc[-1], 2)


def calculate_vwap(df):
    vwap = (df["close"] * df["volume"]).cumsum() / df["volume"].cumsum()
    return round(vwap.iloc[-1], 2)


def calculate_supertrend(df, period=10, multiplier=3):
    hl2 = (df["high"] + df["low"]) / 2

    high_low = df["high"] - df["low"]
    high_close = abs(df["high"] - df["close"].shift())
    low_close = abs(df["low"] - df["close"].shift())

    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()

    upper_band = hl2 + (multiplier * atr)
    lower_band = hl2 - (multiplier * atr)

    if df["close"].iloc[-1] > upper_band.iloc[-1]:
        return "BUY"
    elif df["close"].iloc[-1] < lower_band.iloc[-1]:
        return "SELL"
    else:
        return "NEUTRAL"


def calculate_volume_signal(df):
    avg_volume = df["volume"].rolling(20).mean().iloc[-1]
    current_volume = df["volume"].iloc[-1]

    if current_volume > avg_volume * 1.5:
        return "HIGH"
    elif current_volume < avg_volume * 0.7:
        return "LOW"
    else:
        return "NORMAL"
