from flask import Flask
import pandas as pd

from modules.scanner import scan_stock

app = Flask(__name__)


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
