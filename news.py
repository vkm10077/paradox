import time

news_cache = {
    "last_update": 0,
    "data": {}
}

NEWS_UPDATE_SECONDS = 30 * 60   # 30 minutes


def get_news_impact(symbol, sector=""):
    current_time = time.time()

    if current_time - news_cache["last_update"] < NEWS_UPDATE_SECONDS:
        return news_cache["data"].get(symbol, "Neutral")

    # अभी free version के लिए dummy safe logic
    # बाद में CNBC / NSE / BSE / News API से connect करेंगे

    impact = "Neutral"

    news_cache["data"][symbol] = impact
    news_cache["last_update"] = current_time

    return impact
