from flask import Flask, redirect, request
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
    
@app.route("/callback")
def callback():

    auth_code = request.args.get("auth_code")

    if not auth_code:
        return "Authorization code not received."

    session.set_token(auth_code)

    response = session.generate_token()

    access_token = response["access_token"]

    fyers = fyersModel.FyersModel(
        client_id=CLIENT_ID,
        token=access_token,
        is_async=False
    )

    profile = fyers.get_profile()

    return f"""
    <h2>FYERS Login Successful</h2>
    <pre>{profile}</pre>
    """
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
<!DOCTYPE html>
<html>
<head>
<title>Professional Trading Dashboard</title>

<style>
body {{
    font-family: Arial;
    background:#f5f5f5;
    padding:30px;
}}

.card {{
    background:white;
    border-radius:10px;
    padding:20px;
    box-shadow:0 2px 10px rgba(0,0,0,.15);
}}

.btn {{
    background:#28a745;
    color:white;
    padding:12px 25px;
    text-decoration:none;
    border-radius:8px;
    font-size:18px;
}}

pre {{
    background:#eee;
    padding:15px;
    border-radius:8px;
}}
</style>

</head>

<body>

<div class="card">

<h1>Professional Trading Dashboard</h1>

<p>
<a class="btn" href="/login">
🔐 Login with FYERS
</a>
</p>

<h2>Scanner Result</h2>

<pre>{result}</pre>

</div>

</body>
</html>
"""
