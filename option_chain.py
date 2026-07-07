def get_step(index_name):
    if index_name == "NIFTY":
        return 50
    elif index_name in ["BANKNIFTY", "SENSEX"]:
        return 100
    return 50


def get_symbol_prefix(index_name):
    if index_name == "NIFTY":
        return "NIFTY"
    elif index_name == "BANKNIFTY":
        return "BANKNIFTY"
    elif index_name == "SENSEX":
        return "SENSEX"
    return index_name


def get_atm_itm(index_name, spot_price, signal):
    step = get_step(index_name)
    atm = round(spot_price / step) * step

    if signal == "BUY":
        return atm - step, "CE"
    elif signal == "SELL":
        return atm + step, "PE"
    else:
        return atm, "CE"


def get_live_option_premium(fyers, index_name, spot_price, signal):
    strike, option_type = get_atm_itm(index_name, spot_price, signal)

    # अभी fallback premium रहेगा, ताकि dashboard crash न हो
    premium = round(spot_price * 0.0075, 2)

    return {
        "strike": strike,
        "option_type": option_type,
        "premium": premium
    }
