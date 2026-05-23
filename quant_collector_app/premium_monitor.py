from __future__ import annotations

from datetime import datetime

import requests
from PySide6 import QtCore

from app_config import BJT


P2P_HEADERS = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}


def get_binance_p2p_price(trade_type: str):
    url = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
    data = {
        "asset": "USDT",
        "fiat": "CNY",
        "merchantCheck": False,
        "page": 1,
        "payTypes": [],
        "publisherType": None,
        "rows": 5,
        "tradeType": trade_type,
    }
    resp = requests.post(url, json=data, headers=P2P_HEADERS, timeout=10)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != "000000":
        raise RuntimeError(f"P2P接口返回异常: {payload}")
    prices = [float(ad["adv"]["price"]) for ad in payload.get("data", [])]
    if len(prices) >= 3:
        prices.remove(max(prices))
        prices.remove(min(prices))
    if not prices:
        raise RuntimeError("P2P报价为空")
    return sum(prices) / len(prices)


def get_usd_cny_primary():
    url = "https://api.frankfurter.dev/v1/latest?base=USD&symbols=CNY"
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    payload = resp.json()
    rate = payload.get("rates", {}).get("CNY")
    if rate is None:
        raise RuntimeError(f"frankfurter返回异常: {payload}")
    return float(rate), "frankfurter"


def get_usd_cny_backup():
    url = "https://open.er-api.com/v6/latest/USD"
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("result") != "success":
        raise RuntimeError(f"open.er-api返回异常: {payload}")
    rate = payload.get("rates", {}).get("CNY")
    if rate is None:
        raise RuntimeError(f"open.er-api缺少CNY: {payload}")
    return float(rate), "open.er-api"


def get_real_usd_cny():
    errors = []
    for fn in (get_usd_cny_primary, get_usd_cny_backup):
        try:
            return fn()
        except Exception as e:
            errors.append(f"{fn.__name__}: {type(e).__name__}: {e}")
    raise RuntimeError(" | ".join(errors))


class PremiumWorker(QtCore.QObject):
    finished = QtCore.Signal(dict)

    @QtCore.Slot()
    def fetch_once(self):
        sample_time = datetime.now(BJT).isoformat(timespec="seconds")
        try:
            buy = get_binance_p2p_price("BUY")
            sell = get_binance_p2p_price("SELL")
            usd_cny, fx_source = get_real_usd_cny()
            avg = (buy + sell) / 2.0
            buy_premium_pct = ((buy - usd_cny) / usd_cny) * 100.0
            sell_premium_pct = ((sell - usd_cny) / usd_cny) * 100.0
            avg_premium_pct = ((avg - usd_cny) / usd_cny) * 100.0
            self.finished.emit(
                {
                    "sample_time_bjt": sample_time,
                    "p2p_buy_price_cny": buy,
                    "p2p_sell_price_cny": sell,
                    "p2p_avg_price_cny": avg,
                    "usd_cny_rate": usd_cny,
                    "buy_premium_pct": buy_premium_pct,
                    "sell_premium_pct": sell_premium_pct,
                    "avg_premium_pct": avg_premium_pct,
                    "premium_pct": avg_premium_pct,
                    "fx_source": fx_source,
                    "sample_status": "OK",
                    "error_message": None,
                }
            )
        except Exception as e:
            self.finished.emit(
                {
                    "sample_time_bjt": sample_time,
                    "p2p_buy_price_cny": None,
                    "p2p_sell_price_cny": None,
                    "p2p_avg_price_cny": None,
                    "usd_cny_rate": None,
                    "buy_premium_pct": None,
                    "sell_premium_pct": None,
                    "avg_premium_pct": None,
                    "premium_pct": None,
                    "fx_source": None,
                    "sample_status": "ERROR",
                    "error_message": f"{type(e).__name__}: {e}",
                }
            )
