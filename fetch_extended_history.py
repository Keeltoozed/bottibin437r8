#!/usr/bin/env python3
"""
Загрузчик расширенной истории (30-60 дней 5-минутных свечей) с Binance API.
Включает обязательный сбор данных по BTCUSDT для моделирования реального Market Regime фильтра.
"""
import os
import json
import time
import requests
from typing import Dict, List, Any

CACHE_FILE = "candles_cache_extended.json"

TARGET_SYMBOLS = [
    "BTCUSDT",  # Поводырь рынка (обязательно!)
    "ETHUSDT", "SOLUSDT", "SUIUSDT", "DOGEUSDT", "NEARUSDT", 
    "AVAXUSDT", "LINKUSDT", "APTUSDT", "RENDERUSDT", "TIAUSDT", 
    "SEIUSDT", "ENAUSDT", "PEPEUSDT", "WIFUSDT", "BCHUSDT"
]

def fetch_symbol_candles(symbol: str, days: int = 30) -> List[Dict[str, float]]:
    """Постранично выкачивает 5m свечи за указанное количество дней."""
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - (days * 24 * 60 * 60 * 1000)
    candles = []
    cur_start = start_ms

    headers = {"User-Agent": "Mozilla/5.0"}
    endpoints = [
        "https://data-api.binance.vision/api/v3/klines",
        "https://api.binance.com/api/v3/klines"
    ]

    while cur_start < now_ms:
        chunk = None
        for ep in endpoints:
            try:
                params = {"symbol": symbol, "interval": "5m", "startTime": cur_start, "limit": 1000}
                res = requests.get(ep, params=params, headers=headers, timeout=10)
                if res.status_code == 200:
                    data = res.json()
                    if isinstance(data, list) and len(data) > 0:
                        chunk = data
                        break
            except Exception:
                continue

        if not chunk:
            break

        for c in chunk:
            candles.append({
                "time": int(c[0]),
                "open": float(c[1]),
                "high": float(c[2]),
                "low": float(c[3]),
                "close": float(c[4]),
                "volume": float(c[5]),
                "quote_vol": float(c[7])
            })

        cur_start = chunk[-1][0] + (5 * 60 * 1000)
        time.sleep(0.08)  # бережный rate limit к API
        if len(chunk) < 1000:
            break

    return candles

def download_extended_history(days: int = 30) -> Dict[str, List[Dict[str, float]]]:
    print(f"📥 Начало загрузки расширенной истории за {days} дней ({len(TARGET_SYMBOLS)} пар, включая BTC)...")
    dataset = {}
    
    for idx, sym in enumerate(TARGET_SYMBOLS, 1):
        print(f"[{idx}/{len(TARGET_SYMBOLS)}] Загрузка {sym}...", end="", flush=True)
        cdls = fetch_symbol_candles(sym, days=days)
        if len(cdls) > 500:
            dataset[sym] = cdls
            print(f" ✅ {len(cdls)} свечей ({len(cdls)//288} дней)")
        else:
            print(f" ⚠️ Не удалось получить достаточно свечей ({len(cdls)})")

    with open(CACHE_FILE, "w") as f:
        json.dump(dataset, f)
    
    size_mb = os.path.getsize(CACHE_FILE) / (1024 * 1024)
    print(f"\n🎉 Все данные успешно сохранены в '{CACHE_FILE}' ({size_mb:.1f} MB)")
    return dataset

if __name__ == "__main__":
    download_extended_history(days=30)

