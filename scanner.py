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
from fundamental import calculate_fundamental_score
from risk_reward import calculate_trade_levels

def calculate_technical_score_70(
    price,
    rsi,
    ema20,
    ema50,
    ema200,
    vwap,
    supertrend,
    volume_signal,
    breakout,
    pattern
):
    score = 0

    # 1. Price EMA20 के ऊपर — 7 marks
    if price > ema20:
        score += 7

    # 2. Price EMA50 के ऊपर — 7 marks
    if price > ema50:
        score += 7

    # 3. Price EMA200 के ऊपर — 7 marks
    if price > ema200:
        score += 7

    # 4. Strong EMA alignment — 7 marks
    if ema20 > ema50 > ema200:
        score += 7

    # 5. RSI Momentum — Maximum 8 marks
    if 55 <= rsi <= 70:
        score += 8
    elif 50 <= rsi < 55:
        score += 4
    elif 70 < rsi <= 75:
        score += 4

    # 6. Price VWAP के ऊपर — 6 marks
    if price > vwap:
        score += 6

    # 7. Supertrend bullish — 8 marks
    supertrend_text = str(supertrend).upper()

    if supertrend_text in ["BUY", "BULLISH", "UP", "GREEN"]:
        score += 8

    # 8. Volume strength — Maximum 7 marks
    volume_text = str(volume_signal).upper()

    if volume_text == "HIGH":
        score += 7
    elif volume_text == "NORMAL":
        score += 3

    # 9. Breakout confirmation — Maximum 7 marks
    if breakout == "STRONG":
        score += 7
    elif breakout == "WEAK":
        score += 3

    # 10. Bullish candlestick pattern — 6 marks
    bullish_patterns = [
        "HAMMER",
        "BULLISH ENGULFING",
        "MORNING STAR",
        "PIERCING PATTERN",
        "BULLISH HARAMI",
        "MARUBOZU"
    ]

    if str(pattern).upper() in bullish_patterns:
        score += 6

    return min(score, 70)

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


def scan_nifty500(fyers, start=0, limit=50, symbols=None):
    results = []

    if symbols:
        selected_symbols = symbols
    else:
        selected_symbols = NIFTY500[start:start+limit]

    for symbol in selected_symbols:
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
            trade = calculate_trade_levels(price)
            fundamental_data = {
                "roe": 18,
                "roce": 20,
                "debt_equity": 0.30,
                "promoter_holding": 55,
                "sales_growth": 15,
                "profit_growth": 18,
                "eps_growth": 14,
                "cash_flow_positive": True,
                "fii_dii_positive": True
            }

            fundamental_score = calculate_fundamental_score(fundamental_data)

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
            final_target = round(entry + (risk * 3), 2)

            data["final_target"] = final_target

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
                "vwap": vwap,
                "supertrend": supertrend,
                "volume_signal": volume_signal,
                "pattern": pattern,
                "stoploss": stoploss,
                "breakout": breakout,
                "fundamental_score": fundamental_score,
                "entry": trade["entry"],
                "sl": trade["sl"],
                "risk_reward": trade["risk_reward"],
                "hold": trade["hold"],
                "expected_move": trade["expected_move"],
            }

            technical_score = calculate_technical_score_70(
                price=price,
                rsi=rsi,
                ema20=ema20,
                ema50=ema50,
                ema200=ema200,
                vwap=vwap,
                supertrend=supertrend,
                volume_signal=volume_signal,
                breakout=breakout,
                pattern=pattern
            )

            data["technical_score"] = technical_score
            # Final Score = Technical (70) + Fundamental (30)
            final_score = technical_score + (fundamental_score * 0.30)

            data["final_score"] = round(final_score)

            score = technical_score
        
            if technical_score >= 60:
                signal = "STRONG BUY"
            elif technical_score >= 52:
                signal = "BUY"
            else:
                signal = "NO BUY"

            data["score"] = technical_score
            data["technical_score"] = technical_score
            data["signal"] = signal

            missing_conditions = []

            if price <= ema20:
                missing_conditions.append("Price below EMA20")

            if price <= ema50:
                missing_conditions.append("Price below EMA50")

            if rsi < 55:
                missing_conditions.append("RSI < 55")

            if volume_signal not in ["HIGH", "NORMAL"]:
                missing_conditions.append("Volume Low")

            if technical_score < 52:
                missing_conditions.append("Technical Score < 52/70")
    
            if fundamental_score < 70:
                missing_conditions.append("Fund Score < 70")


            if trade["hold"] == "Avoid":
                missing_conditions.append("R:R Weak")

            if signal not in ["BUY", "STRONG BUY"]:
                missing_conditions.append("Signal Not BUY")

            if signal in ["BUY", "STRONG BUY"]:
                results.append(data)
                
        except Exception:
            continue

    results = sorted(results, key=lambda x: x["score"], reverse=True)
    
    print("TOTAL SCANNER RESULTS:", len(results))
    return results
