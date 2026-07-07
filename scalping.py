def get_atm_itm_strike(index_name, spot_price, signal):
    if index_name == "NIFTY":
        step = 50
    elif index_name in ["BANKNIFTY", "SENSEX"]:
        step = 100
    else:
        step = 50

    atm = round(spot_price / step) * step

    if signal == "BUY":
        strike = atm - step      # ITM CE
        option_type = "CE"
    elif signal == "SELL":
        strike = atm + step      # ITM PE
        option_type = "PE"
    else:
        strike = atm
        option_type = "CE"

    return strike, option_type


def generate_scalping_signal(index_name, data):
    price = data.get("price", 0)
    vwap = data.get("vwap", 0)
    ema20 = data.get("ema20", 0)
    ema50 = data.get("ema50", 0)
    supertrend = data.get("supertrend", "")
    rsi = data.get("rsi", 50)
    macd = data.get("macd", "")
    volume_spike = data.get("volume_spike", False)
    breakout = data.get("breakout", False)

    score = 0
    missing = []

    if price > vwap:
        score += 15
    else:
        missing.append("VWAP")

    if ema20 >= ema50:
        score += 15
    else:
        missing.append("EMA")

    if supertrend == "BUY":
        score += 20
    else:
        missing.append("Supertrend")

    if rsi >= 55:
        score += 15
    else:
        missing.append("RSI")

    if macd == "BULLISH":
        score += 15
    else:
        missing.append("MACD")

    if volume_spike:
        score += 10
    else:
        missing.append("Volume")

    if breakout:
        score += 10
    else:
        missing.append("Breakout")

    if score >= 70:
        signal = "BUY"
    else:
        signal = "WATCHLIST"

    strike, option_type = get_atm_itm_strike(index_name, price, signal)

    premium = round(price * 0.0075, 2)  # temporary estimate

    return {
        "index": index_name,
        "strike": strike,
        "option_type": option_type,
        "premium": premium,
        "entry": premium,
        "sl": round(premium * 0.85, 2),
        "t1": round(premium * 1.15, 2),
        "t2": round(premium * 1.30, 2),
        "t3": round(premium * 1.45, 2),
        "confidence": score,
        "missing": ", ".join(missing) if missing else "All OK",
        "signal": signal
    }
