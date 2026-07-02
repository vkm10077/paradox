from fyers_apiv3 import fyersModel


def get_fyers(client_id, access_token):
    return fyersModel.FyersModel(
        client_id=client_id,
        token=access_token,
        is_async=False
    )
