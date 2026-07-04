from fyers_apiv3 import fyersModel

def get_dashboard_data(client_id, access_token):

    return {
        "s": "ok",
        "d": [
            {
                "s": "ok",
                "n": "NSE:NIFTY50-INDEX",
                "v": {
                    "short_name": "NIFTY 50",
                    "lp": 25000,
                    "ch": 120,
                    "chp": 0.48,
                    "high_price": 25100,
                    "low_price": 24880,
                    "open_price": 24920,
                    "prev_close_price": 24880
                }
            },
            {
                "s": "ok",
                "n": "NSE:NIFTYBANK-INDEX",
                "v": {
                    "short_name": "BANK NIFTY",
                    "lp": 57500,
                    "ch": 180,
                    "chp": 0.31,
                    "high_price": 57620,
                    "low_price": 57250,
                    "open_price": 57310,
                    "prev_close_price": 57320
                }
            },
            {
                "s": "ok",
                "n": "BSE:SENSEX-INDEX",
                "v": {
                    "short_name": "SENSEX",
                    "lp": 83000,
                    "ch": 250,
                    "chp": 0.30,
                    "high_price": 83200,
                    "low_price": 82850,
                    "open_price": 82920,
                    "prev_close_price": 82750
                }
            }
        ]
    }
