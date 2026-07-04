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
    global daily_trade_count

    current_time = datetime.now().time()

    allowed_time = (
        current_time >= datetime.strptime("09:20", "%H:%M").time()
        and current_time <= datetime.strptime("15:10", "%H:%M").time()
    )

    if not allowed_time:
        return None

    if daily_trade_count[index_name] >= MAX_TRADES_PER_DAY:
        return None

    score = scalping_score(data)

    if score >= 85:
        daily_trade_count[index_name] += 1

        entry = data["price"]
        sl = data["swing_low"]
        risk = entry - sl

        return {
            "index": index_name,
            "signal": "BUY",
            "entry": round(entry, 2),
            "sl": round(sl, 2),
            "target1": round(entry + risk, 2),
            "target2": round(entry + risk * 2, 2),
            "target3": round(entry + risk * 3, 2),
            "score": score,
            "reason": "VWAP + EMA + RSI + Volume + OI + Breakout confirmed"
        }

    return None
