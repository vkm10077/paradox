import pandas as pd


def ema(df, period):
    return df["close"].ewm(span=period, adjust=False).mean()


def add_ema(df):
    df["EMA20"] = ema(df, 20)
    df["EMA50"] = ema(df, 50)
    df["EMA200"] = ema(df, 200)
    return df


def ema_bullish(df):
    last = df.iloc[-1]

    return (
        last["EMA20"] >
        last["EMA50"] >
        last["EMA200"] >
        last["close"]
    ) is False and (
        last["close"] >
        last["EMA20"] >
        last["EMA50"] >
        last["EMA200"]
    )
