import aiohttp
import asyncio
import time
from typing import List, Dict, Any, Optional, Tuple
import config

class BinanceClient:
    """
    Асинхронный отказоустойчивый клиент для Binance API.
    Поддерживает:
      - Автоматическое переключение на глобальные зеркала (Binance Vision) при блокировке IP в США (Render).
      - Запрос цен, стакана, свечей и расчет фитилей (wicks).
      - Параллельный мониторинг цен открытых позиций.
    """
    def __init__(self):
        # Список доступных эндпоинтов (с авто-переключением при 451 / гео-блоке)
        self.mirrors = [
            {"name": "fapi", "base": "https://fapi.binance.com", "ticker24": "/fapi/v1/ticker/24hr", "klines": "/fapi/v1/klines", "book": "/fapi/v1/ticker/bookTicker", "price": "/fapi/v1/ticker/price"},
            {"name": "vision", "base": "https://data-api.binance.vision", "ticker24": "/api/v3/ticker/24hr", "klines": "/api/v3/klines", "book": "/api/v3/ticker/bookTicker", "price": "/api/v3/ticker/price"},
            {"name": "spot", "base": "https://api.binance.com", "ticker24": "/api/v3/ticker/24hr", "klines": "/api/v3/klines", "book": "/api/v3/ticker/bookTicker", "price": "/api/v3/ticker/price"}
        ]
        self.active_mirror_idx = 0
        self._session: Optional[aiohttp.ClientSession] = None

    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=6)
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
            self._session = aiohttp.ClientSession(timeout=timeout, headers=headers)
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def _request_with_fallback(self, route_key: str, params: Optional[Dict[str, Any]] = None) -> Optional[Any]:
        session = await self.get_session()
        
        # Сначала пробуем текущее активное зеркало
        indices = list(range(len(self.mirrors)))
        # Переставляем активное зеркало на первое место
        if self.active_mirror_idx in indices:
            indices.remove(self.active_mirror_idx)
            indices.insert(0, self.active_mirror_idx)

        for idx in indices:
            mirror = self.mirrors[idx]
            url = f"{mirror['base']}{mirror[route_key]}"
            try:
                async with session.get(url, params=params) as resp:
                    if resp.status == 200:
                        if self.active_mirror_idx != idx:
                            print(f"🌐 [Binance API] Успешное подключение через зеркало {mirror['name']} ({mirror['base']})", flush=True)
                            self.active_mirror_idx = idx
                        return await resp.json()
                    elif resp.status in [451, 403]:
                        # Гео-блокировка (часто на серверах Render в США)
                        if self.active_mirror_idx == idx:
                            print(f"⚠️ [Binance API] {mirror['name']} вернул HTTP {resp.status} (гео-ограничение сервера). Пробуем зеркало Binance Vision...", flush=True)
                    elif resp.status == 429:
                        await asyncio.sleep(1.0)
            except Exception as e:
                pass
        return None

    async def fetch_price(self, symbol: str) -> Optional[float]:
        """Быстрое получение текущей рыночной цены монеты."""
        data = await self._request_with_fallback("price", params={"symbol": symbol})
        if data and isinstance(data, dict):
            try:
                return float(data.get("price", 0) or 0)
            except (ValueError, TypeError):
                pass
        return None

    async def fetch_top_tickers(self, min_vol_usdt: float = 8000000, limit: int = 80) -> List[Dict[str, Any]]:
        """
        Получает 24ч статистику по всем парам USDT на Binance.
        Автоматически использует глобальное зеркало, если основной сервер блокирует регион.
        """
        data = await self._request_with_fallback("ticker24")
        if not data or not isinstance(data, list):
            return []

        candidates = []
        for item in data:
            sym = item.get("symbol", "")
            if not sym.endswith("USDT"):
                continue
            if any(sym.startswith(skip) for skip in ["USDC", "FDUSD", "TUSD", "BUSD", "EUR"]):
                continue

            try:
                quote_vol = float(item.get("quoteVolume", 0) or 0)
                price_pct = float(item.get("priceChangePercent", 0) or 0)
                last_price = float(item.get("lastPrice", 0) or 0)
                high_price = float(item.get("highPrice", 0) or 0)
                low_price = float(item.get("lowPrice", 0) or 0)

                if quote_vol >= min_vol_usdt and last_price > 0:
                    candidates.append({
                        "symbol": sym,
                        "price": last_price,
                        "volume_24h": quote_vol,
                        "price_change_24h_pct": price_pct,
                        "high_24h": high_price,
                        "low_24h": low_price
                    })
            except (ValueError, TypeError):
                continue

        candidates.sort(key=lambda x: (abs(x["price_change_24h_pct"]) > 1.2, x["volume_24h"]), reverse=True)
        return candidates[:limit]

    async def fetch_candles_analysis(self, symbol: str, interval: str = "5m", limit: int = 20) -> Optional[Dict[str, Any]]:
        """
        Запрашивает свечи и производит расчет:
        - Всплеск объема (Volume Surge)
        - Фитили последней свечи (Wick analysis)
        - Доля отката (Pullback)
        - Локальный минимум под фитилем (Wick Stop Loss)
        """
        raw_candles = await self._request_with_fallback("klines", params={"symbol": symbol, "interval": interval, "limit": limit})
        if not raw_candles or len(raw_candles) < 8:
            return None

        candles = []
        for c in raw_candles:
            try:
                candles.append({
                    "open": float(c[1]),
                    "high": float(c[2]),
                    "low": float(c[3]),
                    "close": float(c[4]),
                    "volume": float(c[5]),
                    "quote_vol": float(c[7])
                })
            except (ValueError, IndexError):
                continue

        if len(candles) < 5:
            return None

        last_c = candles[-1]
        prior_vols = [c["quote_vol"] for c in candles[-10:-1]]
        avg_vol = (sum(prior_vols) / len(prior_vols)) if prior_vols else 1.0
        surge_ratio = round(last_c["quote_vol"] / avg_vol, 2) if avg_vol > 0 else 1.0

        candle_range = max(last_c["high"] - last_c["low"], 1e-9)
        body_top = max(last_c["open"], last_c["close"])
        body_bottom = min(last_c["open"], last_c["close"])

        upper_wick_pct = round((last_c["high"] - body_top) / candle_range, 3)
        lower_wick_pct = round((body_bottom - last_c["low"]) / candle_range, 3)

        recent_high = max(c["high"] for c in candles[-5:])
        pullback_from_high_pct = round((last_c["close"] - recent_high) / recent_high, 4)

        recent_wick_low = min(c["low"] for c in candles[-3:])
        wick_stop_loss = round(recent_wick_low * (1.0 - config.WICK_BUFFER_PCT), 6)
        sl_pct_distance = round((last_c["close"] - wick_stop_loss) / last_c["close"], 4)

        pct_5m = round((candles[-1]["close"] - candles[-2]["close"]) / candles[-2]["close"] * 100, 2)
        pct_15m = round((candles[-1]["close"] - candles[-4]["close"]) / candles[-4]["close"] * 100, 2) if len(candles) >= 4 else pct_5m

        return {
            "symbol": symbol,
            "current_price": last_c["close"],
            "recent_high": recent_high,
            "pullback_from_high_pct": pullback_from_high_pct,
            "volume_surge_ratio": surge_ratio,
            "upper_wick_pct": upper_wick_pct,
            "lower_wick_pct": lower_wick_pct,
            "wick_stop_loss": wick_stop_loss,
            "sl_pct_distance": sl_pct_distance,
            "pct_5m": pct_5m,
            "pct_15m": pct_15m,
            "last_quote_volume": last_c["quote_vol"]
        }

    async def fetch_orderbook_spread(self, symbol: str) -> Tuple[float, float, float]:
        data = await self._request_with_fallback("book", params={"symbol": symbol})
        if not data:
            return 0.0, 0.0, 1.0

        try:
            bid = float(data.get("bidPrice", 0) or 0)
            ask = float(data.get("askPrice", 0) or 0)
            if bid > 0 and ask >= bid:
                spread = (ask - bid) / bid
                return bid, ask, spread
        except (ValueError, TypeError):
            pass
        return 0.0, 0.0, 1.0

# Глобальный экземпляр клиента
binance_client = BinanceClient()
