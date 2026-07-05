def calculate_fundamental_score(data):
    score = 0

    if data.get("roe", 0) >= 15:
        score += 15

    if data.get("roce", 0) >= 15:
        score += 15

    if data.get("debt_equity", 99) <= 0.5:
        score += 10

    if data.get("promoter_holding", 0) >= 50:
        score += 10

    if data.get("sales_growth", 0) >= 10:
        score += 10

    if data.get("profit_growth", 0) >= 10:
        score += 10

    if data.get("eps_growth", 0) >= 10:
        score += 10

    if data.get("cash_flow_positive", False):
        score += 10

    if data.get("fii_dii_positive", False):
        score += 10

    return min(score, 100)
