from datetime import datetime

daily_trade_count = {
    "NIFTY": 0,
    "BANKNIFTY": 0,
    "SENSEX": 0
}

MAX_TRADES_PER_DAY = 3


def scalping_score(data):
    score = 0

    if data["price"] > data["vwap"]:
        score += 10

    if data["price"] > data["ema20"]:
        score += 10

    if data["ema20"] > data["ema50"]:
        score += 10

    if data["supertrend"] == "BUY":
        score += 10

    if 60 <= data["rsi"] <= 75:
        score += 10

    if data["macd"] == "BULLISH":
        score += 10

    if data["volume_spike"] == True:
        score += 10

    if data["oi_signal"] == "BULLISH":
        score += 10

    if data["candle_pattern"] in ["Bullish Engulfing", "Hammer", "Morning Star", "Bullish Marubozu"]:
        score += 10

    if data["breakout"] == True:
        score += 10

    return score


def generate_scalping_signal(index_name, data):
    buy_conditions = {
        "Price > VWAP": data["price"] > data["vwap"],
        "EMA20 > EMA50": data["ema20"] > data["ema50"],
        "Supertrend BUY": data["supertrend"] == "BUY",
        "RSI 55-70": 55 <= data["rsi"] <= 70,
        "MACD Bullish": data["macd"] == "BULLISH",
        "Volume Spike": data["volume_spike"] == True,
        "OI Bullish": data["oi_signal"] == "BULLISH",
        "Breakout": data["breakout"] == True
    }

    passed = sum(buy_conditions.values())
    missing = [k for k, v in buy_conditions.items() if not v]

    if passed >= 6:
        entry = data["price"]
        sl = data["swing_low"]

        risk = entry - sl
        if risk <= 0:
            return None

        return {
            "index": index_name,
            "signal": "BUY",
            "entry": round(entry, 2),
            "sl": round(sl, 2),
            "target1": round(entry + risk, 2),
            "target2": round(entry + risk * 2, 2),
            "target3": round(entry + risk * 3, 2),
            "score": passed * 12.5,
            "missing": ", ".join(missing[:2])
        }

    return {
        "index": index_name,
        "signal": "WAIT",
        "entry": data["price"],
        "sl": "-",
        "target1": "-",
        "target2": "-",
        "target3": "-",
        "score": passed * 12.5,
        "missing": ", ".join(missing[:2])
    }
