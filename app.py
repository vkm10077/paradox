from flask import Flask

app = Flask(__name__)

@app.route("/")
def home():
    return "Fyers Dashboard is Running Successfully!"
