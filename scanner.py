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


def scan_nifty500(fyers):
    results = []

    for symbol in NIFTY500:
        try:
            df = get_historical_df(fyers, symbol)

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

            data = {
                "symbol": symbol.replace("NSE:", "").replace("-EQ", ""),
                "price": price,
                "rsi": rsi,
                "ema20": ema20,
                "ema50": ema50,
                "ema200": ema200,
                "vwap": vwap,
                "supertrend": supertrend,
                "volume_signal": volume_signal
            }

            score = calculate_smart_score(data)
            signal = get_signal(score)

            data["score"] = score
            data["signal"] = signal

            results.append(data)

        except Exception:
            continue

    results = sorted(results, key=lambda x: x["score"], reverse=True)
    results = [stock for stock in results if stock["score"] >= 70]

    return results
