import pandas as pd

URL = "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"

try:
    df = pd.read_csv(URL)
    NIFTY500 = ["NSE:" + s + "-EQ" for s in df["Symbol"].dropna().tolist()]
except Exception:
    NIFTY500 = [
        "NSE:RELIANCE-EQ",
        "NSE:TCS-EQ",
        "NSE:HDFCBANK-EQ",
        "NSE:ICICIBANK-EQ",
        "NSE:INFY-EQ",
        "NSE:SBIN-EQ",
        "NSE:BHARTIARTL-EQ",
        "NSE:ITC-EQ",
        "NSE:LT-EQ",
        "NSE:AXISBANK-EQ",
    ]
