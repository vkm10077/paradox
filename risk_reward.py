def calculate_trade_levels(price, atr=0):
    if atr <= 0:
        atr = price * 0.025   # 2.5% default risk

    entry = round(price, 2)
    sl = round(price - atr, 2)

    expected_move_percent = 8
    expected_target = price * (1 + expected_move_percent / 100)

    risk = entry - sl
    reward = expected_target - entry

    rr = round(reward / risk, 2) if risk > 0 else 0

    if rr >= 3:
        hold = "15-25D"
    elif rr >= 2:
        hold = "8-15D"
    else:
        hold = "Avoid"

    return {
        "entry": entry,
        "sl": sl,
        "risk_reward": f"1:{rr}",
        "hold": hold,
        "expected_move": f"+{expected_move_percent}%"
    }
