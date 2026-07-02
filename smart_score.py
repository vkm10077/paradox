def calculate_smart_score(data):
    score = 0

    if data["rsi"] >= 55 and data["rsi"] <= 70:
        score += 15

    if data["price"] > data["ema20"]:
        score += 15

    if data["price"] > data["ema50"]:
        score += 15

    if data["price"] > data["ema200"]:
        score += 15

    if data["price"] > data["vwap"]:
        score += 15

    if data["supertrend"] == "BUY":
        score += 15

    if data["volume_signal"] == "HIGH":
        score += 10

    return min(score, 100)


def get_signal(score):
    if score >= 80:
        return "STRONG BUY"
    elif score >= 65:
        return "BUY"
    elif score >= 45:
        return "NEUTRAL"
    elif score >= 30:
        return "SELL"
    else:
        return "STRONG SELL"
