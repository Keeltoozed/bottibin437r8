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
        self._book_tickers_cache: Dict[str, Tuple[float, float]] = {}
        self._book_tickers_cache_time: float = 0.0

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
        Сканирует самые ликвидные активы и топовые ракеты рынка (Top Gainers + High Volume):
        1. Топ-Гейнеры (Ракеты!): монеты с максимальным суточным ростом % при наличии реального объема.
        2. Институциональный объем: тяжеловесы с глубочайшим стаканом.
        3. Топ-Лузеры: лучшие кандидаты для шорт-пробоев.
        Исключает стейблкоины, фиат, токенизированные акции и неликвидный спам.
        """
        data = await self._request_with_fallback("ticker24")
        if not data or not isinstance(data, list):
            return []

        excluded = getattr(config, "EXCLUDED_TICKERS", set())
        strict = getattr(config, "STRICT_WHITELIST_ONLY", False)
        whitelist = set(getattr(config, "TOP_CRYPTO_UNIVERSE", []))
        lev_tokens = ("UPUSDT", "DOWNUSDT", "BEARUSDT", "BULLUSDT")

        valid_tickers = []
        for item in data:
            if not isinstance(item, dict):
                continue
            sym = item.get("symbol", "")
            if not sym.endswith("USDT"):
                continue
            if sym in excluded:
                continue
            if any(sym.endswith(lt) for lt in lev_tokens):
                continue
            # Фильтр: только валидные латинские символы и цифры
            if not all(ord(c) < 128 and (c.isalnum() or c == '_') for c in sym):
                continue
            if strict and sym not in whitelist:
                continue

            try:
                vol = float(item.get("quoteVolume", 0) or 0)
                if vol < min_vol_usdt:
                    continue
                last_p = float(item.get("lastPrice", 0) or 0)
                if last_p <= 0:
                    continue
                pct = float(item.get("priceChangePercent", 0) or 0)
                high_p = float(item.get("highPrice", 0) or 0)
                low_p = float(item.get("lowPrice", 0) or 0)
                valid_tickers.append({
                    "symbol": sym,
                    "price": last_p,
                    "volume_24h": vol,
                    "price_change_24h_pct": pct,
                    "high_24h": high_p,
                    "low_24h": low_p
                })
            except (ValueError, TypeError):
                continue

        if not valid_tickers:
            return []

        # ДИНАМИЧЕСКИЙ РАДАР (Ракеты + Ликвидность + Шорт-радар):
        # 1. Топ-Гейнеры (Ракеты прямо сейчас! Самый мощный импульс дня)
        by_gainers = sorted(valid_tickers, key=lambda x: x["price_change_24h_pct"], reverse=True)
        # 2. Топ по суточному объёму (Институциональные мажоры и L1/L2 гиганты)
        by_volume = sorted(valid_tickers, key=lambda x: x["volume_24h"], reverse=True)
        # 3. Топ-Лузеры (для поиска чистых шорт-пробоев)
        by_losers = sorted(valid_tickers, key=lambda x: x["price_change_24h_pct"])

        # Комбинируем без дубликатов, гарантируя присутствие ракет и ликвидности
        combined_dict = {}
        # Сначала отдаем 35% квоты под ракеты дня (Top Gainers)
        g_quota = max(15, int(limit * 0.35))
        for item in by_gainers[:g_quota]:
            combined_dict[item["symbol"]] = item

        # 45% квоты под топ-ликвидность (Volume Leaders)
        v_quota = max(25, int(limit * 0.45))
        for item in by_volume[:v_quota]:
            combined_dict[item["symbol"]] = item

        # 20% квоты под шорт-радар (Top Losers)
        l_quota = max(10, int(limit * 0.20))
        for item in by_losers[:l_quota]:
            combined_dict[item["symbol"]] = item

        # Если остался лимит, добираем следующими по объему
        if len(combined_dict) < limit:
            for item in by_volume:
                if item["symbol"] not in combined_dict:
                    combined_dict[item["symbol"]] = item
                    if len(combined_dict) >= limit:
                        break

        selected = list(combined_dict.values())
        return selected[:limit]

    async def fetch_candles_analysis(self, symbol: str, interval: str = "5m", limit: int = 80) -> Optional[Dict[str, Any]]:
        """
        Запрашивает свечи и производит институциональный технический расчет:
        - Всплеск объема (Volume Surge)
        - Фитили последней свечи (Wick analysis)
        - Доля отката (Pullback) / микро-отскока (Bounce)
        - Локальный минимум/максимум под фитилем (Wick Stop Loss)
        - Индекс относительной силы RSI-14
        - Экспоненциальные скользящие средние EMA-9 и EMA-21 (Trend Alignment)
        - Передает список свечей для квантового инференса в QuantMLEngine
        """
        raw_candles = await self._request_with_fallback("klines", params={"symbol": symbol, "interval": interval, "limit": limit})
        if not raw_candles or len(raw_candles) < 8:
            return None

        candles = []
        for c in raw_candles:
            try:
                candles.append({
                    "time": int(c[0]),
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

        # ======================================================================
        # РАСЧЕТ ATR-14 (Average True Range) ДЛЯ ФИЛЬТРАЦИИ СЛУЧАЙНОГО ШУМА
        # ======================================================================
        true_ranges = []
        for i in range(1, len(candles)):
            c_curr = candles[i]
            c_prev = candles[i-1]
            tr = max(
                c_curr["high"] - c_curr["low"],
                abs(c_curr["high"] - c_prev["close"]),
                abs(c_curr["low"] - c_prev["close"])
            )
            true_ranges.append(tr)

        atr14 = (sum(true_ranges[-14:]) / min(len(true_ranges), 14)) if true_ranges else candle_range
        atr14_pct = round(atr14 / last_c["close"], 4)

        # Скальп-стоп за фитилем: локальный экстремум последних 2 свечей (текущая + предыдущая)
        recent_wick_low = min(c["low"] for c in candles[-2:])
        raw_wick_sl = round(recent_wick_low * (1.0 - config.WICK_BUFFER_PCT), 6)
        raw_sl_pct = (last_c["close"] - raw_wick_sl) / last_c["close"]

        # Расчет параметров для SHORT (стоп над верхним фитилем)
        recent_wick_high = max(c["high"] for c in candles[-2:])
        raw_short_sl = round(recent_wick_high * (1.0 + config.WICK_BUFFER_PCT), 6)
        raw_short_sl_pct = (raw_short_sl - last_c["close"]) / last_c["close"]

        # Институциональный стоп-лосс: max(за_фитиль, 1.0 * ATR14, 0.35%)
        # Отражает РЕАЛЬНУЮ дистанцию до фитиля. Если она шире MAX_ALLOWED_SL_PCT (0.75%), сканер отсеет сетап!
        safe_long_sl_pct = round(max(raw_sl_pct, atr14_pct, 0.0035), 4)
        wick_stop_loss = round(last_c["close"] * (1.0 - safe_long_sl_pct), 6)
        sl_pct_distance = safe_long_sl_pct

        safe_short_sl_pct = round(max(raw_short_sl_pct, atr14_pct, 0.0035), 4)
        short_wick_stop_loss = round(last_c["close"] * (1.0 + safe_short_sl_pct), 6)
        short_sl_pct_distance = safe_short_sl_pct

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
            "trend": trend,
            "atr14_pct": atr14_pct,
            "candles": candles
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

        # Институциональный фильтр режима Bitcoin (Directional Market Lock):
        # В крипте бета альткоинов к BTC составляет 1.5x - 3.0x.
        # Если BTC в нисходящем тренде (ниже EMA9/EMA21) или сливается — ЛОНГИ ПО АЛЬТАМ КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНЫ.
        is_dumping = (trend == "BEARISH" and p15 <= -0.05) or (p15 <= -0.25) or (p5 <= -0.20) or (rsi < 40.0 and p5 < -0.05)
        is_pumping = (trend == "BULLISH" and p15 >= +0.05) or (p15 >= +0.25) or (p5 >= +0.20) or (rsi > 60.0 and p5 > +0.05)

        if is_dumping:
            status_str = f"🔴 Медвежий BTC ({p15:+.2f}%, {trend}) — ЛОНГИ ЗАБЛОКИРОВАНЫ | Приоритет: SHORT"
        elif is_pumping:
            status_str = f"🟢 Бычий BTC ({p15:+.2f}%, {trend}) — ШОРТЫ ЗАБЛОКИРОВАНЫ | Приоритет: LONG"
        else:
            status_str = f"🟡 Боковик BTC ({p15:+.2f}%, тренд: {trend}) — Разрешены LONG и SHORT"

        return {
            "trend": trend,
            "pct_5m": p5,
            "pct_15m": p15,
            "rsi": rsi,
            "is_dumping": is_dumping,
            "is_pumping": is_pumping,
            "status_str": status_str
        }

    async def fetch_all_book_tickers(self) -> Dict[str, Tuple[float, float]]:
        """
        Пакетная загрузка стаканов (best bid/ask) всех пар рынка за 1 быстрый запрос.
        Кэшируется на 4 секунды, избавляя от сотен повторных HTTP вызовов.
        """
        now = time.time()
        if self._book_tickers_cache and (now - self._book_tickers_cache_time) < 4.0:
            return self._book_tickers_cache

        data = await self._request_with_fallback("book")
        if data and isinstance(data, list):
            res = {}
            for item in data:
                if isinstance(item, dict):
                    sym = item.get("symbol", "")
                    try:
                        b = float(item.get("bidPrice", 0) or 0)
                        a = float(item.get("askPrice", 0) or 0)
                        if b > 0 and a >= b:
                            res[sym] = (b, a)
                    except (ValueError, TypeError):
                        pass
            self._book_tickers_cache = res
            self._book_tickers_cache_time = now
            return res
        return self._book_tickers_cache

    async def fetch_orderbook_spread(self, symbol: str) -> Tuple[float, float, float]:
        # Быстрый путь: берем из пакетного кэша стаканов (O(1) память)
        cache = await self.fetch_all_book_tickers()
        if symbol in cache:
            bid, ask = cache[symbol]
            spread = (ask - bid) / bid if bid > 0 else 0.0
            return bid, ask, spread

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

    async def fetch_recent_high_low(self, symbol: str, limit: int = 12) -> Optional[Tuple[float, float, float]]:
        """
        Возвращает (current_price, max_high, min_low) за последние limit 5m свечей.
        Гарантирует, что даже кратковременный всплеск или пролив цены не будет упущен.
        """
        raw = await self._request_with_fallback("klines", params={"symbol": symbol, "interval": "5m", "limit": limit})
        if not raw or not isinstance(raw, list):
            return None
        try:
            highs = [float(c[2]) for c in raw if len(c) > 4]
            lows = [float(c[3]) for c in raw if len(c) > 4]
            cur = float(raw[-1][4])
            if highs and lows:
                return cur, max(highs), min(lows)
        except Exception:
            pass
        return None

# Глобальный экземпляр клиента
binance_client = BinanceClient()
