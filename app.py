from nifty500 import NIFTY500
import time
from market import get_fyers
from flask import Flask, render_template, redirect, request, session
import os
from fyers_apiv3 import fyersModel
import pandas as pd

from modules.scanner import scan_stock
from dashboard import get_dashboard_data
from scanner import scan_nifty500
from scalping import generate_scalping_signal
from fundamental import calculate_fundamental_score
from risk_reward import calculate_trade_levels

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY")
CLIENT_ID = os.environ.get("FYERS_CLIENT_ID")
SECRET_KEY = os.environ.get("FYERS_SECRET_KEY")

REDIRECT_URI = "https://rocky-jvah.onrender.com/callback"

fyers_session = fyersModel.SessionModel(
    client_id=CLIENT_ID,
    secret_key=SECRET_KEY,
    redirect_uri=REDIRECT_URI,
    response_type="code",
    grant_type="authorization_code"
)
@app.route("/login")
def login():
    return redirect(fyers_session.generate_authcode())
    
@app.route("/callback")
def callback():
    auth_code = request.args.get("auth_code")

    if not auth_code:
        return "Authorization code not received.", 400

    fyers_session.set_token(auth_code)
    response = fyers_session.generate_token()

    print("FYERS TOKEN STATUS:", response.get("s"))

    if response.get("s") != "ok":
        return f"""
        <h2>Token Error</h2>
        <pre>{response}</pre>
        <a href="/login">Login Again</a>
        """, 400

    access_token = response.get("access_token")

    if not access_token:
        return f"""
        <h2>Access Token Not Received</h2>
        <pre>{response}</pre>
        <a href="/login">Login Again</a>
        """, 400

    session["access_token"] = access_token
    return redirect("/dashboard")

@app.route("/")
def home():
    if "access_token" in session:
        return redirect("/dashboard")

    return redirect("/login")

def build_index_data(rows):
    index_data = {}

    for row in rows:
        symbol = row.get("symbol", "").upper()

        if "NIFTY" in symbol and "BANK" not in symbol:
            index_name = "NIFTY"
        elif "BANK" in symbol:
            index_name = "BANKNIFTY"
        elif "SENSEX" in symbol:
            index_name = "SENSEX"
        else:
            continue

        price = row.get("price", 0)
        open_price = row.get("open", 0)
        high = row.get("high", 0)
        low = row.get("low", 0)
        prev_close = row.get("prev_close", 0)

        bullish = price > open_price and price > prev_close
        bearish = price < open_price and price < prev_close

        index_data[index_name] = {
            "price": price,
            "vwap": open_price,
            "ema20": open_price,
            "ema50": prev_close,
            "supertrend": "BUY" if bullish else "SELL",
            "rsi": 65 if bullish else 35,
            "macd": "BULLISH" if bullish else "BEARISH",
            "volume_spike": True if abs(row.get("change_pct", 0)) > 0.25 else False,
            "oi_signal": "BULLISH" if bullish else "BEARISH",
            "candle_pattern": "Bullish Marubozu" if bullish else "Bearish Marubozu",
            "breakout": price >= high or price <= low,
            "swing_low": low,
            "swing_high": high
        }

    return index_data

def scan_single_stock_from_nifty500(fyers, search_stock):
    search_stock = search_stock.upper().strip()

    matched_symbol = None

    for symbol in NIFTY500:
        clean_symbol = symbol.replace("NSE:", "").replace("-EQ", "").upper()

        if search_stock == clean_symbol or search_stock in clean_symbol:
            matched_symbol = symbol
            break

    if not matched_symbol:
        return None

    result = scan_nifty500(
        fyers,
        symbols=[matched_symbol]
    )

    if result and len(result) > 0:
        return result[0]

    return None

@app.route("/dashboard")
def dashboard():
    if "access_token" not in session:
        return redirect("/login")

    fyers = None
    fyers_error = None
    quotes = {"s": "ok", "d": []}
    rows = []
    scanner_results = []
    scalping_trades = []

    try:
        fyers = get_fyers(
            CLIENT_ID,
            session["access_token"]
        )

        quotes = get_dashboard_data(
            CLIENT_ID,
            session["access_token"]
        )

        print(
            "QUOTES STATUS:",
            quotes.get("s")
            if isinstance(quotes, dict)
            else "invalid"
        )

        if not isinstance(quotes, dict):
            fyers_error = "Invalid quotes response"
            quotes = {"s": "ok", "d": []}

        elif quotes.get("s") != "ok":
            fyers_error = quotes
            quotes = {"s": "ok", "d": []}

    except Exception as e:
        print("FYERS DASHBOARD ERROR:", repr(e))
        fyers_error = str(e)

    # Dashboard quote rows
    for item in quotes.get("d", []):
        if item.get("s") != "ok":
            continue

        value = item.get("v", {})

        rows.append({
            "symbol": value.get(
                "short_name",
                item.get("n", "-")
            ),
            "price": value.get("lp", 0),
            "change": value.get("ch", 0),
            "change_pct": value.get("chp", 0),
            "high": value.get("high_price", 0),
            "low": value.get("low_price", 0),
            "open": value.get("open_price", 0),
            "prev_close": value.get("prev_close_price", 0),
        })

    # हर 30 सेकंड में NIFTY 500 का अगला batch
    batch = int(time.time() / 30) % 10
    start = batch * 50

    if fyers is not None:
        try:
            scanner_response = scan_nifty500(
                fyers,
                start=start,
                limit=50
            )

            if isinstance(scanner_response, list):
                scanner_results = scanner_response
            else:
                print(
                    "INVALID SCANNER RESPONSE:",
                    scanner_response
                )

        except Exception as e:
            print("SCANNER ERROR:", repr(e))
            fyers_error = fyers_error or str(e)

    print("Scanner Results:", scanner_results)
    print("Total Stocks:", len(scanner_results))

    
    search_stock = request.args.get(
        "stock",
        ""
    ).upper().strip()

    selected_signal = request.args.get(
        "signal",
        "ALL"
    ).upper().strip()

    if selected_signal != "ALL":
        scanner_results = [
            stock
            for stock in scanner_results
            if str(
                stock.get("signal", "")
            ).upper() == selected_signal
        ]

    searched_stock = None

    if search_stock:
        searched_stock = next(
            (
                stock
                for stock in scanner_results
                if search_stock in str(
                    stock.get("stock", "")
                ).upper()
            ),
            None
        )

    return render_template(
        "dashboard.html",
        rows=rows,
        scanner_results=scanner_results,
        selected_signal=selected_signal,
        search_stock=search_stock,
        searched_stock=searched_stock,
        fyers_error=fyers_error
    )
    
@app.route("/api/scalping")
def api_scalping():
    if "access_token" not in session:
        return {
            "error": "login required",
            "scalping_trades": []
        }, 401

    try:
        fyers = get_fyers(
            CLIENT_ID,
            session["access_token"]
        )

        quotes = get_dashboard_data(
            CLIENT_ID,
            session["access_token"]
        )

        if (
            not isinstance(quotes, dict)
            or quotes.get("s") != "ok"
        ):
            return {
                "error": "Unable to fetch quotes",
                "details": quotes,
                "scalping_trades": []
            }, 502

        rows = []

        for item in quotes.get("d", []):
            if item.get("s") != "ok":
                continue

            value = item.get("v", {})

            rows.append({
                "symbol": value.get(
                    "short_name",
                    item.get("n", "-")
                ),
                "price": value.get("lp", 0),
                "change": value.get("ch", 0),
                "change_pct": value.get("chp", 0),
                "high": value.get("high_price", 0),
                "low": value.get("low_price", 0),
                "open": value.get("open_price", 0),
                "prev_close": value.get(
                    "prev_close_price",
                    0
                ),
            })

        index_data = build_index_data(rows)
        scalping_trades = []

        for index_name, data in index_data.items():
            try:
                trade = generate_scalping_signal(
                    index_name,
                    data,
                    fyers
                )

                if trade:
                    scalping_trades.append(trade)

            except Exception as e:
                print(
                    f"API SCALPING ERROR {index_name}:",
                    repr(e)
                )

        return {
            "scalping_trades": scalping_trades[:3]
        }, 200

    except Exception as e:
        print("API SCALPING ERROR:", repr(e))

        return {
            "error": str(e),
            "scalping_trades": []
        }, 500
        
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )
