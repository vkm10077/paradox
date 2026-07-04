from fyers_apiv3 import fyersModel

def get_dashboard_data(client_id, access_token):

    return {
        "s": "ok",
        "d": [
            {
                "s": "ok",
                "n": "NSE:SBIN-EQ",
                "v": {
                    "short_name": "SBIN",
                    "lp": 800,
                    "ch": 5,
                    "chp": 0.65,
                    "high_price": 805,
                    "low_price": 795,
                    "open_price": 798,
                    "prev_close_price": 795
                }
            }
        ]
    }
