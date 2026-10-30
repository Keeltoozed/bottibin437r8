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

    async def fetch_top_tickers(self, min_vol_usdt: float = config.MIN_24H_VOLUME_USDT, limit: int = config.SCAN_TICKERS_LIMIT) -> List[Dict[str, Any]]:
        """
        Формирует институциональный торговый радар:
        Торгует ИСКЛЮЧИТЕЛЬНО утвержденный белый список топ-активов (BTC, ETH, SOL, SUI, DOGE, NEAR, RENDER...).
        Любые случайные монеты, хаки/эксплойты протоколов (как INIT) на 100% заблокированы.
        """
        data = await self._request_with_fallback("ticker24")
        if not data or not isinstance(data, list):
            return []

        item_map = {item.get("symbol", ""): item for item in data if isinstance(item, dict) and "symbol" in item}
        selected = []
        excluded = getattr(config, "EXCLUDED_TICKERS", set())

        # Сканируем ИСКЛЮЧИТЕЛЬНО утвержденный элитный белый список
        for sym in getattr(config, "TOP_CRYPTO_UNIVERSE", []):
            if sym in item_map and sym not in excluded:
                item = item_map[sym]
                try:
                    vol = float(item.get("quoteVolume", 0) or 0)
                    pct = float(item.get("priceChangePercent", 0) or 0)
                    last_p = float(item.get("lastPrice", 0) or 0)
                    high_p = float(item.get("highPrice", 0) or 0)
                    low_p = float(item.get("lowPrice", 0) or 0)
                    if last_p > 0:
                        selected.append({
                            "symbol": sym,
                            "price": last_p,
                            "volume_24h": vol,
                            "price_change_24h_pct": pct,
                            "high_24h": high_p,
                            "low_24h": low_p
                        })
                except (ValueError, TypeError):
                    continue

        return selected[:limit]

    async def fetch_candles_analysis(self, symbol: str, interval: str = "5m", limit: int = 30) -> Optional[Dict[str, Any]]:
        """
        Запрашивает свечи и производит институциональный технический расчет:
        - Всплеск объема (Volume Surge)
        - Фитили последней свечи (Wick analysis)
        - Доля отката (Pullback) / микро-отскока (Bounce)
        - Локальный минимум/максимум под фитилем (Wick Stop Loss)
        - Индекс относительной силы RSI-14
        - Экспоненциальные скользящие средние EMA-9 и EMA-21 (Trend Alignment)
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
        prev_c = candles[-2]
        prior_vols = [c["quote_vol"] for c in candles[-11:-2]]
        avg_vol = (sum(prior_vols) / len(prior_vols)) if prior_vols else 1.0

        # Учитываем всплеск объема как последней закрытой 5m свечи, так и текущей
        surge_closed = prev_c["quote_vol"] / avg_vol if avg_vol > 0 else 1.0
        surge_live = last_c["quote_vol"] / avg_vol if avg_vol > 0 else 1.0
        surge_ratio = round(max(surge_closed, surge_live), 2)

        candle_range = max(last_c["high"] - last_c["low"], 1e-9)
        body_top = max(last_c["open"], last_c["close"])
        body_bottom = min(last_c["open"], last_c["close"])

        upper_wick_pct = round((last_c["high"] - body_top) / candle_range, 3)
        lower_wick_pct = round((body_bottom - last_c["low"]) / candle_range, 3)

        recent_high = max(c["high"] for c in candles[-5:])
        pullback_from_high_pct = round((last_c["close"] - recent_high) / recent_high, 4)

        recent_low = min(c["low"] for c in candles[-5:])
        bounce_from_low_pct = round((last_c["close"] - recent_low) / max(recent_low, 1e-9), 4)

        # Скальп-стоп за фитилем: локальный экстремум последних 2 свечей (текущая + предыдущая)
        recent_wick_low = min(c["low"] for c in candles[-2:])
        wick_stop_loss = round(recent_wick_low * (1.0 - config.WICK_BUFFER_PCT), 6)
        sl_pct_distance = round((last_c["close"] - wick_stop_loss) / last_c["close"], 4)

        # Расчет параметров для SHORT (стоп над верхним фитилем)
        recent_wick_high = max(c["high"] for c in candles[-2:])
        short_wick_stop_loss = round(recent_wick_high * (1.0 + config.WICK_BUFFER_PCT), 6)
        short_sl_pct_distance = round((short_wick_stop_loss - last_c["close"]) / last_c["close"], 4)

        pct_5m = round((candles[-1]["close"] - candles[-2]["close"]) / candles[-2]["close"] * 100, 2)
        pct_15m = round((candles[-1]["close"] - candles[-4]["close"]) / candles[-4]["close"] * 100, 2) if len(candles) >= 4 else pct_5m

        # ======================================================================
        # ИНСТИТУЦИОНАЛЬНЫЕ ИНДИКАТОРЫ: RSI-14 & EMA 9/21 TREND ALIGNMENT
        # ======================================================================
        closes = [c["close"] for c in candles]

        # EMA-9 & EMA-21
        def calc_ema(values, period):
            k = 2.0 / (period + 1.0)
            ema = values[0]
            for v in values[1:]:
                ema = v * k + ema * (1.0 - k)
            return ema

        ema9 = round(calc_ema(closes, 9), 6)
        ema21 = round(calc_ema(closes, 21) if len(closes) >= 21 else calc_ema(closes, len(closes)), 6)

        # RSI-14
        gains, losses = [], []
        for i in range(1, len(closes)):
            delta = closes[i] - closes[i - 1]
            if delta >= 0:
                gains.append(delta)
                losses.append(0.0)
            else:
                gains.append(0.0)
                losses.append(abs(delta))

        avg_gain = sum(gains[-14:]) / 14.0 if len(gains) >= 14 else 0.0
        avg_loss = sum(losses[-14:]) / 14.0 if len(losses) >= 14 else 0.0
        if avg_loss == 0:
            rsi = 100.0 if avg_gain > 0 else 50.0
        else:
            rs = avg_gain / avg_loss
            rsi = round(100.0 - (100.0 / (1.0 + rs)), 1)

        # Структура тренда
        if last_c["close"] >= ema9 >= ema21:
            trend = "BULLISH"
        elif last_c["close"] <= ema9 <= ema21:
            trend = "BEARISH"
        else:
            trend = "CHOP"

        return {
            "symbol": symbol,
            "current_price": last_c["close"],
            "recent_high": recent_high,
            "recent_low": recent_low,
            "pullback_from_high_pct": pullback_from_high_pct,
            "bounce_from_low_pct": bounce_from_low_pct,
            "volume_surge_ratio": surge_ratio,
            "upper_wick_pct": upper_wick_pct,
            "lower_wick_pct": lower_wick_pct,
            "wick_stop_loss": wick_stop_loss,
            "sl_pct_distance": sl_pct_distance,
            "short_wick_sl": short_wick_stop_loss,
            "short_sl_dist": short_sl_pct_distance,
            "pct_5m": pct_5m,
            "pct_15m": pct_15m,
            "last_quote_volume": last_c["quote_vol"],
            "rsi": rsi,
            "ema9": ema9,
            "ema21": ema21,
            "trend": trend
        }

    async def fetch_btc_regime(self) -> Dict[str, Any]:
        """
        Институциональный макро-фильтр рынка по Bitcoin (Поводырь рынка).
        Защищает депозит от общерыночных сливов, негативных новостей и FUD.
        """
        analysis = await self.fetch_candles_analysis("BTCUSDT", interval="5m", limit=30)
        if not analysis:
            return {
                "trend": "CHOP",
                "pct_5m": 0.0,
                "pct_15m": 0.0,
                "rsi": 50.0,
                "is_dumping": False,
                "is_pumping": False,
                "status_str": "🟡 Нейтральный (BTC спокоен)"
            }

        p5 = analysis.get("pct_5m", 0.0)
        p15 = analysis.get("pct_15m", 0.0)
        trend = analysis.get("trend", "CHOP")
        rsi = analysis.get("rsi", 50.0)

        # BTC Дамп на плохих новостях: пролив 15m свечи <= -0.40% или сильный медвежий тренд
        is_dumping = p15 <= -0.40 or (trend == "BEARISH" and p5 < -0.15) or rsi < 35.0

        # BTC Памп на позитиве: взлет 15m свечи >= +0.40% или сильный бычий тренд
        is_pumping = p15 >= 0.40 or (trend == "BULLISH" and p5 > 0.15) or rsi > 65.0

        if is_dumping:
            status_str = f"🔴 Медвежий дамп BTC ({p15:+.2f}%) — Лонги по альтам ЗАБЛОКИРОВАНЫ"
        elif is_pumping:
            status_str = f"🟢 Бычий импульс BTC ({p15:+.2f}%) — Шорты по альтам ЗАБЛОКИРОВАНЫ"
        else:
            status_str = f"🟡 Нейтральный (BTC: {p15:+.2f}%, тренд: {trend})"

        return {
            "trend": trend,
            "pct_5m": p5,
            "pct_15m": p15,
            "rsi": rsi,
            "is_dumping": is_dumping,
            "is_pumping": is_pumping,
            "status_str": status_str
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
