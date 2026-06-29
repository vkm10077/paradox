from modules.indicators import add_ema, ema_bullish


def scan_stock(df):
    """
    सभी Technical Conditions यहीं Check होंगी
    """

    df = add_ema(df)

    result = {
        "EMA Bullish": ema_bullish(df)
    }

    return result
