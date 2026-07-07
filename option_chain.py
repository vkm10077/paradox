def get_step(index_name):
    if index_name == "NIFTY":
        return 50
    elif index_name in ["BANKNIFTY", "SENSEX"]:
        return 100
    return 50


def get_index_symbol(index_name):
    if index_name == "NIFTY":
        return "NSE:NIFTY50-INDEX"
    elif index_name == "BANKNIFTY":
        return "NSE:NIFTYBANK-INDEX"
    elif index_name == "SENSEX":
        return "BSE:SENSEX-INDEX"
    return index_name


def get_atm_itm(index_name, spot_price, signal):
    step = get_step(index_name)
    atm = round(spot_price / step) * step

    if signal == "BUY":
        return atm - step, "CE"     # ITM CE
    elif signal == "SELL":
        return atm + step, "PE"     # ITM PE
    else:
        return atm, "CE"


def get_live_option_premium(fyers, index_name, spot_price, signal):
    strike, option_type = get_atm_itm(index_name, spot_price, signal)

    premium = round(spot_price * 0.0075, 2)

    if fyers is None:
        return {
            "strike": strike,
            "option_type": option_type,
            "premium": premium
        }

    try:
        data = {
            "symbol": get_index_symbol(index_name),
            "strikecount": 3,
            "timestamp": ""
        }

        response = fyers.optionchain(data=data)

        print("OPTION CHAIN RESPONSE:", response)

        chain = (
            response.get("data", {}).get("optionsChain")
            or response.get("data", {}).get("optionChain")
            or []
        )

        for item in chain:
            item_strike = int(float(item.get("strike_price", 0)))
            item_type = item.get("option_type", "")

            if item_strike == strike and item_type == option_type:
                premium = item.get("ltp", item.get("lp", premium))
                premium = round(float(premium), 2)
                break

    except Exception as e:
        print("OPTION CHAIN ERROR:", e)

    return {
        "strike": strike,
        "option_type": option_type,
        "premium": premium
    }
