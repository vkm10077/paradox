import os
from fyers_apiv3 import fyersModel


def get_fyers():
    client_id = os.environ.get("FYERS_CLIENT_ID")
    access_token = os.environ.get("FYERS_ACCESS_TOKEN")

    return fyersModel.FyersModel(
        client_id=client_id,
        token=access_token,
        is_async=False
    )
