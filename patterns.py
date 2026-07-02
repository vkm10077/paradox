def detect_hammer(df):
    o = df["open"].iloc[-1]
    h = df["high"].iloc[-1]
    l = df["low"].iloc[-1]
    c = df["close"].iloc[-1]

    body = abs(c - o)
    lower_shadow = min(o, c) - l
    upper_shadow = h - max(o, c)

    return (
        lower_shadow > body * 2 and
        upper_shadow < body
    )


def detect_bullish_engulfing(df):
    if len(df) < 2:
        return False

    prev_o = df["open"].iloc[-2]
    prev_c = df["close"].iloc[-2]

    curr_o = df["open"].iloc[-1]
    curr_c = df["close"].iloc[-1]

    return (
        prev_c < prev_o and
        curr_c > curr_o and
        curr_o <= prev_c and
        curr_c >= prev_o
    )


def detect_bearish_engulfing(df):
    if len(df) < 2:
        return False

    prev_o = df["open"].iloc[-2]
    prev_c = df["close"].iloc[-2]

    curr_o = df["open"].iloc[-1]
    curr_c = df["close"].iloc[-1]

    return (
        prev_c > prev_o and
        curr_c < curr_o and
        curr_o >= prev_c and
        curr_c <= prev_o
    )


def detect_doji(df):
    o = df["open"].iloc[-1]
    c = df["close"].iloc[-1]
    h = df["high"].iloc[-1]
    l = df["low"].iloc[-1]

    return abs(c - o) <= (h - l) * 0.1


def get_pattern(df):

    if detect_bullish_engulfing(df):
        return "Bullish Engulfing"

    if detect_bearish_engulfing(df):
        return "Bearish Engulfing"

    if detect_hammer(df):
        return "Hammer"

    if detect_doji(df):
        return "Doji"

    return "-"
