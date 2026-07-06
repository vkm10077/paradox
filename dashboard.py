from market import get_fyers

def get_dashboard_data(client_id, access_token):
    fyers = get_fyers(client_id, access_token)

    return fyers.quotes({
        "symbols": "NSE:NIFTY50-INDEX,NSE:NIFTYBANK-INDEX,BSE:SENSEX-INDEX"
    })
