from flask import Flask, redirect
import os
from fyers_apiv3 import fyersModel
import pandas as pd

from modules.scanner import scan_stock

app = Flask(__name__)
CLIENT_ID = os.environ.get("FYERS_CLIENT_ID")
SECRET_KEY = os.environ.get("FYERS_SECRET_KEY")

REDIRECT_URI = "https://rocky-jvah.onrender.com/callback"

session = fyersModel.SessionModel(
    client_id=CLIENT_ID,
    secret_key=SECRET_KEY,
    redirect_uri=REDIRECT_URI,
    response_type="code",
    grant_type="authorization_code"
)
@app.route("/login")
def login():
    return redirect(session.generate_authcode())

@app.route("/")
def home():

    # Demo Data (अभी टेस्ट के लिए)
    data = {
        "close": [
            100,101,102,103,104,105,106,107,108,109,
            110,111,112,113,114,115,116,117,118,119,
            120,121,122,123,124,125,126,127,128,129,
            130,131,132,133,134,135,136,137,138,139,
            140,141,142,143,144,145,146,147,148,149,
            150
        ]
    }

    df = pd.DataFrame(data)

    result = scan_stock(df)

    return f"""
    <h1>Professional Trading Dashboard</h1>

    <h2>Scanner Result</h2>

    <pre>{result}</pre>
    """


if __name__ == "__main__":
    app.run(debug=True)
