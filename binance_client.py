import aiohttp
import asyncio
import time
from typing import List, Dict, Any, Optional, Tuple
import config

class BinanceClient:
    """
    Асинхронный клиент для взаимодействия с Binance Futures API.
    Поддерживает:
      - Публичные запросы котировок, стакана, свечей без API-ключа (zero-ban risk).
      - Запрос Open Interest для подтверждения притока Smart Money.
      - Расчет свечных фитилей (wicks) для правила 'Stop lives under the wick'.
    """
    def __init__(self):
        self.base_url = config.BINANCE_FUTURES_PUBLIC_URL
        self._session: Optional[aiohttp.ClientSession] = None
        self._last_request_time = 0.0

    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=8)
            headers = {"User-Agent": "Mozilla/5.0 (Autonomous Groq Trader)"}
            self._session = aiohttp.ClientSession(timeout=timeout, headers=headers)
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def _get(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Optional[Any]:
        session = await self.get_session()
        url = f"{self.base_url}{endpoint}"
        for attempt in range(3):
            try:
                async with session.get(url, params=params) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    elif resp.status == 429:
                        print(f"⚠️ [Binance API] 429 Rate Limit. Ждем {2 ** attempt}с...")
                        await asyncio.sleep(2 ** attempt)
                    else:
                        return None
            except Exception as e:
                if attempt == 2:
                    return None
                await asyncio.sleep(0.5)
        return None

    async def fetch_top_tickers(self, min_vol_usdt: float = config.MIN_24H_VOLUME_USDT, limit: int = 80) -> List[Dict[str, Any]]:
        """
        Получает 24ч статистику по всем парам USDT на Binance Futures.
        Фильтрует по минимальному объёму и сортирует по волатильности / объёму.
        """
        data = await self._get("/fapi/v1/ticker/24hr")
        if not data or not isinstance(data, list):
            return []

        candidates = []
        for item in data:
            sym = item.get("symbol", "")
            if not sym.endswith("USDT"):
                continue
            # Исключаем стейблкоины и сомнительные тикеры
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

        # Сортируем: сначала самые горячие по объёму и абсолютному изменению цены
        candidates.sort(key=lambda x: (abs(x["price_change_24h_pct"]) > 1.5, x["volume_24h"]), reverse=True)
        return candidates[:limit]

    async def fetch_candles_analysis(self, symbol: str, interval: str = "5m", limit: int = 20) -> Optional[Dict[str, Any]]:
        """
        Запрашивает свечи и производит расчет:
        - Всплеск объема (Volume Surge) относительно скользящего среднего.
        - Фитиль последней свечи (Wick analysis: верхний и нижний фитиль).
        - Доля отката (Pullback) от недавнего локального максимума.
        - Локальный минимум под фитилем (Stop level).
        """
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        raw_candles = await self._get("/fapi/v1/klines", params=params)
        if not raw_candles or len(raw_candles) < 10:
            return None

        # Преобразуем свечи: [open_time, open, high, low, close, volume, ...]
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
        prev_c = candles[-2]

        # Средний объем предыдущих свечей
        prior_vols = [c["quote_vol"] for c in candles[-10:-1]]
        avg_vol = (sum(prior_vols) / len(prior_vols)) if prior_vols else 1.0
        surge_ratio = round(last_c["quote_vol"] / avg_vol, 2) if avg_vol > 0 else 1.0

        # Расчет фитилей последней завершающейся свечи
        candle_range = max(last_c["high"] - last_c["low"], 1e-9)
        body_top = max(last_c["open"], last_c["close"])
        body_bottom = min(last_c["open"], last_c["close"])

        upper_wick_pct = round((last_c["high"] - body_top) / candle_range, 3)
        lower_wick_pct = round((body_bottom - last_c["low"]) / candle_range, 3)

        # Локальный максимум последних 5 свечей и текущий откат
        recent_high = max(c["high"] for c in candles[-5:])
        pullback_from_high_pct = round((last_c["close"] - recent_high) / recent_high, 4)

        # Свечной Stop-Loss (под фитиль минимальной цены за последние 3 свечи с буфером)
        recent_wick_low = min(c["low"] for c in candles[-3:])
        wick_stop_loss = round(recent_wick_low * (1.0 - config.WICK_BUFFER_PCT), 6)
        sl_pct_distance = round((last_c["close"] - wick_stop_loss) / last_c["close"], 4)

        # Изменение за 5 минут и за 15 минут
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
        """
        Возвращает (best_bid, best_ask, spread_pct).
        Позволяет отсекать монеты с плохой ликвидностью и широким спредом.
        """
        data = await self._get("/fapi/v1/ticker/bookTicker", params={"symbol": symbol})
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

    async def fetch_open_interest_info(self, symbol: str) -> Optional[float]:
        """
        Получает открытый интерес (Open Interest) на Binance Futures.
        Резкий рост OI подтверждает интерес крупных игроков.
        """
        data = await self._get("/fapi/v1/openInterest", params={"symbol": symbol})
        if not data:
            return None
        try:
            return float(data.get("openInterest", 0) or 0)
        except (ValueError, TypeError):
            return None

# Глобальный экземпляр клиента
binance_client = BinanceClient()

