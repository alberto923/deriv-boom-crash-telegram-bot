import os
import json
import time
import requests
import websocket
import threading
from datetime import datetime
from statistics import mean, stdev

# ====== CONFIGURACIÓN ======
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_TOKEN_DEMO = os.getenv("API_TOKEN_DEMO")
API_TOKEN_REAL = os.getenv("API_TOKEN_REAL")
MODE = os.getenv("MODE", "demo")  # 'demo' o 'real'
CHAT_ID = os.getenv("CHAT_ID", None)

SYMBOLS = ["boom_1000", "crash_1000"]
STAKE = float(os.getenv("STAKE", 0.35))
TP_USD = float(os.getenv("TP_USD", 0.50))
SL_USD = float(os.getenv("SL_USD", 1.00))

EMA_SHORT = int(os.getenv("EMA_SHORT", 8))
EMA_LONG = int(os.getenv("EMA_LONG", 34))
Z_THRESHOLD = float(os.getenv("Z_THRESHOLD", 3.0))

# ====== VARIABLES DE ESTADO ======
running = True
profit_today = 0.0

# ====== FUNCIONES AUXILIARES ======
def telegram_send(msg):
    if CHAT_ID:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = {"chat_id": CHAT_ID, "text": msg}
        try:
            requests.post(url, data=data)
        except:
            pass

def ema(values, period):
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    ema_val = values[0]
    for price in values[1:]:
        ema_val = price * k + ema_val * (1 - k)
    return ema_val

def z_score(values):
    if len(values) < 20:
        return 0
    m = mean(values)
    s = stdev(values)
    return (values[-1] - m) / s if s != 0 else 0

# ====== TRADING ======
def trade(symbol, direction):
    global profit_today
    api_token = API_TOKEN_DEMO if MODE == "demo" else API_TOKEN_REAL
    ws = websocket.create_connection("wss://ws.derivws.com/websockets/v3?app_id=1089")
    ws.send(json.dumps({"authorize": api_token}))
    time.sleep(1)
    contract = "CALL" if direction == "buy" else "PUT"
    proposal = {
        "buy": 1,
        "price": STAKE,
        "parameters": {
            "amount": STAKE,
            "basis": "stake",
            "contract_type": contract,
            "currency": "USD",
            "duration": 1,
            "duration_unit": "m",
            "symbol": symbol.upper()
        }
    }
    ws.send(json.dumps({"buy": proposal["buy"], "parameters": proposal["parameters"]}))
    telegram_send(f"🚀 Entrada: {symbol} | Dirección: {direction}")
    # Aquí deberías añadir seguimiento de TP/SL usando profit_today
    ws.close()

def strategy_loop(symbol):
    prices = []
    api_token = API_TOKEN_DEMO if MODE == "demo" else API_TOKEN_REAL
    ws = websocket.create_connection("wss://ws.derivws.com/websockets/v3?app_id=1089")
    ws.send(json.dumps({"authorize": api_token}))
    ws.send(json.dumps({"ticks_history": symbol, "count": 100, "end": "latest", "style": "ticks"}))
    while running:
        try:
            data = ws.recv()
            msg = json.loads(data)
            if "history" in msg:
                prices = [float(p) for p in msg["history"]["prices"]]
            elif "tick" in msg:
                prices.append(float(msg["tick"]["quote"]))
                if len(prices) > 100:
                    prices.pop(0)
                short_ema = ema(prices, EMA_SHORT)
                long_ema = ema(prices, EMA_LONG)
                z = z_score(prices)
                if short_ema and long_ema:
                    if short_ema > long_ema and z > Z_THRESHOLD:
                        trade(symbol, "buy")
                    elif short_ema < long_ema and z < -Z_THRESHOLD:
                        trade(symbol, "sell")
        except Exception as e:
            telegram_send(f"Error en {symbol}: {str(e)}")
            break
    ws.close()

# ====== TELEGRAM HANDLER ======
def telegram_handler():
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    offset = None
    global running
    while True:
        try:
            params = {"timeout": 100, "offset": offset}
            r = requests.get(url, params=params).json()
            for update in r.get("result", []):
                offset = update["update_id"] + 1
                message = update.get("message", {}).get("text", "")
                chat_id = update.get("message", {}).get("chat", {}).get("id", "")
                if CHAT_ID is None:
                    os.environ["CHAT_ID"] = str(chat_id)
                if message == "/start":
                    telegram_send("🤖 Bot iniciado")
                elif message == "/pause":
                    running = False
                    telegram_send("⏸ Bot en pausa")
                elif message == "/resume":
                    running = True
                    telegram_send("▶ Bot reanudado")
                elif message == "/status":
                    telegram_send(f"Modo: {MODE} | Profit hoy: {profit_today} USD")
        except:
            time.sleep(5)

# ====== MAIN ======
if __name__ == "__main__":
    telegram_thread = threading.Thread(target=telegram_handler)
    telegram_thread.daemon = True
    telegram_thread.start()
    for sym in SYMBOLS:
        t = threading.Thread(target=strategy_loop, args=(sym,))
        t.daemon = True
        t.start()
    while True:
        time.sleep(1)
