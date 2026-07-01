from fyers_apiv3 import fyersModel

def get_dashboard_data(client_id, access_token):

    fyers = fyersModel.FyersModel(
        client_id=client_id,
        token=access_token,
        is_async=False
    )

    market_symbols = [
        # Indian Indices
        "NSE:NIFTY50-INDEX",
        "NSE:NIFTYBANK-INDEX",
        "BSE:SENSEX-INDEX",
        "NSE:FINNIFTY-INDEX",
        "NSE:MIDCPNIFTY-INDEX",
        "NSE:INDIAVIX-INDEX",

        # Global
        "NSE:GIFTNIFTY-INDEX",

        # US
        "DJI",
        "SPX",
        "IXIC",

        # UK
        "UKX",

        # Japan
        "N225",

        # China
        "SSE"
    ]

    quotes = fyers.quotes({
        "symbols": ",".join(market_symbols)
    })

    return quotes
