from fyers_apiv3 import fyersModel


def get_dashboard_data(client_id, access_token):

    fyers = fyersModel.FyersModel(
        client_id=str(client_id),
        token=access_token,
        is_async=False
    )

    market_symbols = [
        "NSE:SBIN-EQ"
    ]

    quotes = fyers.quotes({
        "symbols": ",".join(market_symbols)
    })

    return quotes
