import pandas as pd
from datetime import datetime, timedelta

from nifty500 import NIFTY500
from indicators import (
    calculate_rsi,
    calculate_ema,
    calculate_vwap,
    calculate_supertrend,
    calculate_volume_signal
)
from smart_score import calculate_smart_score, get_signal

def detect_pattern(df):
    last = df.iloc[-1]
    prev = df.iloc[-2]

    open_p = last["open"]
    close_p = last["close"]
    high_p = last["high"]
    low_p = last["low"]

    body = abs(close_p - open_p)
    candle_range = high_p - low_p

    if candle_range == 0:
        return "NA"

    upper_shadow = high_p - max(open_p, close_p)
    lower_shadow = min(open_p, close_p) - low_p

    if body <= candle_range * 0.10:
        return "Doji"

    if lower_shadow >= body * 2 and upper_shadow <= body:
        return "Hammer"

    if upper_shadow >= body * 2 and lower_shadow <= body:
        return "Shooting Star"

    if (
        prev["close"] < prev["open"]
        and close_p > open_p
        and close_p > prev["open"]
        and open_p < prev["close"]
    ):
        return "Bullish Engulfing"

    if (
        prev["close"] > prev["open"]
        and close_p < open_p
        and open_p > prev["close"]
        and close_p < prev["open"]
    ):
        return "Bearish Engulfing"

        return "NA"

def get_historical_df(fyers, symbol):
    to_date = datetime.now().strftime("%Y-%m-%d")
    from_date = (datetime.now() - timedelta(days=120)).strftime("%Y-%m-%d")

    data = {
        "symbol": symbol,
        "resolution": "D",
        "date_format": "1",
        "range_from": from_date,
        "range_to": to_date,
        "cont_flag": "1"
    }

    response = fyers.history(data)

    if response.get("s") != "ok":
        return None

    candles = response.get("candles", [])

    if not candles:
        return None

    df = pd.DataFrame(
        candles,
        columns=["timestamp", "open", "high", "low", "close", "volume"]
    )

    return df


def scan_nifty500(fyers, start=0, limit=50):
    results = []

    for symbol in NIFTY500[start:start+limit]:
        try:
            df = get_historical_df(fyers, symbol)

            print("Scanning:", symbol)
            
            if df is None:
                print("No data:", symbol)
            else:
                print("Rows:", symbol, len(df))

            if df is None or len(df) < 60:
                continue

            price = round(df["close"].iloc[-1], 2)
            rsi = calculate_rsi(df)
            ema20 = calculate_ema(df, 20)
            ema50 = calculate_ema(df, 50)
            ema200 = calculate_ema(df, 200)
            vwap = calculate_vwap(df)
            supertrend = calculate_supertrend(df)
            volume_signal = calculate_volume_signal(df)
            
            pattern = detect_pattern(df)
            if not pattern:
                pattern = "NA"
            support = round(df["low"].tail(20).min(), 2)
            resistance = round(df["high"].tail(20).max(), 2)
            prev_resistance = round(df["high"].iloc[-21:-1].max(), 2)
            entry = resistance

            stoploss = support

            risk = entry - stoploss

            target1 = round(entry + risk, 2)

            target2 = round(entry + (risk * 2), 2)
            avg_volume = df["volume"].tail(20).mean()
            today_volume = df["volume"].iloc[-1]

            if price > prev_resistance:
                if today_volume >= avg_volume * 1.5:
                    breakout = "STRONG"
                else:
                    breakout = "WEAK"
            else:
                breakout = "NO"
            data = {
                "symbol": symbol.replace("NSE:", "").replace("-EQ", ""),
                "price": price,
                "rsi": rsi,
                "ema20": ema20,
                "ema50": ema50,
                "ema200": ema200,
                "vwap": vwap,
                "supertrend": supertrend,
                "volume_signal": volume_signal,
                "pattern": pattern,
                "support": support,
                "resistance": resistance,
                "entry": entry,
                "stoploss": stoploss,
                "target1": target1,
                "target2": target2,
                "breakout": breakout 
            }

            score = calculate_smart_score(data)
            signal = get_signal(score)

            # Strong Breakout Confirmation

            if breakout == "STRONG":
                score += 10

                if signal in ["BUY", "STRONG BUY"]:
                    signal = "STRONG BUY"

            data["score"] = score
            data["signal"] = signal

            institutional_breakout = "NO"

            if (
                price > ema20
                and price > ema50
                and price > ema200
                and rsi >= 55
                and volume_signal in ["HIGH", "NORMAL"]
                and score >= 70
            ):
                institutional_breakout = "YES"

            data["institutional_breakout"] = institutional_breakout
            if (
                 score >= 70
                 and breakout == "STRONG"
                 and institutional_breakout == "YES"
                 and signal in ["BUY", "STRONG BUY"]
             ):

                 results.append(data)

        except Exception:
            continue

    results = sorted(results, key=lambda x: x["score"], reverse=True)
    
    print("TOTAL SCANNER RESULTS:", len(results))
    return results
