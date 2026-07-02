import pandas as pd


def get_support(df, period=20):
    return round(df["low"].rolling(period).min().iloc[-1], 2)


def get_resistance(df, period=20):
    return round(df["high"].rolling(period).max().iloc[-1], 2)


def breakout_signal(df):
    resistance = get_resistance(df)
    support = get_support(df)

    close = df["close"].iloc[-1]

    if close > resistance:
        return "BREAKOUT"

    elif close < support:
        return "BREAKDOWN"

    else:
        return "RANGE"
