from fyers_apiv3 import fyersModel


def get_dashboard_data(client_id, access_token):

   fyers = fyersModel.FyersModel(
    client_id=str(client_id),
    token=f"{client_id}:{access_token}",
    is_async=False
) 
    market_symbols = [
        "NSE:SBIN-EQ"
        
    ]

    print("CLIENT_ID:", client_id)
    print("ACCESS_TOKEN START:", access_token[:20])

    quotes = fyers.quotes({
        "symbols": ",".join(market_symbols)
    })

    return quotes
