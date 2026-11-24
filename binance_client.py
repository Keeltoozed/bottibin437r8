import aiohttp
import asyncio
import time
from typing import List, Dict, Any, Optional, Tuple, Set
import config

class BinanceClient:
    """
    Асинхронный отказоустойчивый клиент для Binance Futures API.
    Поддерживает:
      - Прямое подключение к Binance Perpetual Futures (fapi.binance.com, нативно в регионе Frankfurt EU)
        с автоматическим резервированием на Binance Vision при гео-блокировке.
      - Умный радар пробоев (24h High/Low Proximity + Институциональный объем).
      - Структурный расчет пробоев Дончиана (20 баров), силы закрытия свечи (CLV), RVOL и честных стопов по ATR/фитилям.
    """
    def __init__(self):
        self.mirrors = [
            {"name": "fapi", "base": "https://fapi.binance.com", "ticker24": "/fapi/v1/ticker/24hr", "klines": "/fapi/v1/klines", "book": "/fapi/v1/ticker/bookTicker", "price": "/fapi/v1/ticker/price", "info": "/fapi/v1/exchangeInfo"},
            {"name": "vision", "base": "https://data-api.binance.vision", "ticker24": "/api/v3/ticker/24hr", "klines": "/api/v3/klines", "book": "/api/v3/ticker/bookTicker", "price": "/api/v3/ticker/price", "info": "/api/v3/exchangeInfo"},
            {"name": "spot", "base": "https://api.binance.com", "ticker24": "/api/v3/ticker/24hr", "klines": "/api/v3/klines", "book": "/api/v3/ticker/bookTicker", "price": "/api/v3/ticker/price", "info": "/api/v3/exchangeInfo"}
        ]
        self.active_mirror_idx = 0
        self._session: Optional[aiohttp.ClientSession] = None
        self._book_tickers_cache: Dict[str, Tuple[float, float]] = {}
        self._book_tickers_cache_time: float = 0.0
        self._valid_crypto_perps: Set[str] = set()
        self._valid_crypto_perps_time: float = 0.0

    @property
    def active_mirror_name(self) -> str:
        if 0 <= self.active_mirror_idx < len(self.mirrors):
            return self.mirrors[self.active_mirror_idx]["name"]
        return "unknown"

    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=10)
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
            self._session = aiohttp.ClientSession(timeout=timeout, headers=headers)
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def _request_with_fallback(self, route_key: str, params: Optional[Dict[str, Any]] = None) -> Optional[Any]:
        session = await self.get_session()

        indices = list(range(len(self.mirrors)))
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
                    elif resp.status == 400:
                        # HTTP 400 означает, что конкретный тикер отсутствует на данном зеркале (например PEPEUSDT vs 1000PEPEUSDT).
                        # НЕ переключаем глобальное зеркало, чтобы не сбивать работу с fapi на vision!
                        return None
                    elif resp.status in [451, 403]:
                        if self.active_mirror_idx == idx:
                            print(f"⚠️ [Binance API] {mirror['name']} вернул HTTP {resp.status} (гео-ограничение сервера). Пробуем резервное зеркало...", flush=True)
                    elif resp.status == 429:
                        await asyncio.sleep(1.0)
            except Exception:
                pass
        return None

    async def fetch_valid_crypto_perps(self) -> Set[str]:
        """Возвращает официальный список чистых крипто-фьючерсов (PERPETUAL + COIN), исключая все 255 TradFi акций/сырья."""
        now = time.time()
        if self._valid_crypto_perps and (now - self._valid_crypto_perps_time) < 3600.0:
            return self._valid_crypto_perps
        if self.active_mirror_name != "fapi":
            return set()
        try:
            session = await self.get_session()
            url = f"{self.mirrors[0]['base']}/fapi/v1/exchangeInfo"
            async with session.get(url) as resp:
                if resp.status == 200:
                    info = await resp.json()
                    perps = {
                        s["symbol"] for s in info.get("symbols", [])
                        if s.get("status") == "TRADING"
                        and s.get("contractType") == "PERPETUAL"
                        and s.get("underlyingType") == "COIN"
                        and s.get("quoteAsset") == "USDT"
                    }
                    if len(perps) >= 100:
                        self._valid_crypto_perps = perps
                        self._valid_crypto_perps_time = now
                        return perps
        except Exception:
            pass
        return self._valid_crypto_perps

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
        Формирует профессиональный радар Охотника за Ракетами (Structural Rocket Radar):
        1. Автоматически адаптирует порог объема при работе через Spot-зеркало (data-api.binance.vision на US сервере Render),
           так как спотовый оборот USDT в 8-10 раз ниже фьючерсного (fapi), сохраняя полный охват 110-120 живых крипто-пар!
        2. Отсекает делистнутые/замороженные пары (closeTime > 5 мин), стейблкоины ($0.97..$1.03 с узким диапазоном) и токенизированные акции (*BUSDT).
        3. Приоритезирует монеты у суточных экстремумов (24h High/Low Proximity) и лидеров ликвидности.
        """
        data = await self._request_with_fallback("ticker24")
        if not data or not isinstance(data, list):
            return []

        # Адаптация порога ликвидности под активное зеркало:
        # На fapi (Perpetual Futures) $5M отбирает 200+ пар; на vision/spot $350K Spot USDT эквивалентны ~$5M Futures!
        is_spot_mirror = (self.active_mirror_name != "fapi")
        if is_spot_mirror and min_vol_usdt >= 1_500_000.0:
            spot_floor = float(getattr(config, "SPOT_MIRROR_MIN_VOL_USDT", 350_000.0))
            effective_min_vol = max(spot_floor, min_vol_usdt * 0.07)
        else:
            effective_min_vol = min_vol_usdt

        valid_crypto_perps = await self.fetch_valid_crypto_perps() if not is_spot_mirror else set()
        excluded = getattr(config, "EXCLUDED_TICKERS", set())
        stock_roots = getattr(config, "STOCK_TICKER_ROOTS", set())
        strict = getattr(config, "STRICT_WHITELIST_ONLY", False)
        whitelist = set(getattr(config, "TOP_CRYPTO_UNIVERSE", []))
        max_24h_cap = float(getattr(config, "MAX_24H_CHANGE_CAP", 100.0))
        min_trades = int(getattr(config, "MIN_24H_TRADES_COUNT", 2500))
        lev_tokens = ("UPUSDT", "DOWNUSDT", "BEARUSDT", "BULLUSDT")
        fiat_commodities = {"XAU", "XAUT", "PAXG", "XAG", "XPT", "XPD", "CL", "BZ", "COPPER", "NATGAS", "EUR", "EURI", "AEUR", "GBP", "AUD", "BRL", "TRY", "JPY"}
        real_crypto_b = {"BNB", "ARB", "SHIB", "1000SHIB", "TRB", "BB", "CKB", "YB", "PHB", "AMB", "BLUR", "BOME", "BONK", "1000BONK"}
        now_ms = int(time.time() * 1000)

        fresh_books: Dict[str, Tuple[float, float]] = {}
        valid_tickers = []
        for item in data:
            if not isinstance(item, dict):
                continue
            sym = item.get("symbol", "")
            if not sym.endswith("USDT") or sym in excluded:
                continue
            if valid_crypto_perps and sym not in valid_crypto_perps:
                continue
            if any(sym.endswith(lt) for lt in lev_tokens):
                continue
            if not all(ord(c) < 128 and (c.isalnum() or c == '_') for c in sym):
                continue

            base = sym[:-4]
            if base in fiat_commodities:
                continue
            # Все токенизированные акции и TradFi отсекаются как по exchangeInfo, так и по корням:
            if base in stock_roots or (is_spot_mirror and base.endswith("B") and base not in real_crypto_b and base[:-1] in stock_roots):
                continue
            if strict and sym not in whitelist:
                continue

            try:
                # Защита от делистнутых/архивных пар на data-api.binance.vision (closeTime старше 5 минут)
                close_time_ms = int(item.get("closeTime", 0) or 0)
                if close_time_ms > 0 and (now_ms - close_time_ms) > 300_000:
                    continue

                # Фильтр минимального количества сделок за 24ч (отсев монет-зомби с искусственным объемом)
                cnt = int(item.get("count", 0) or 0)
                if cnt > 0 and cnt < min_trades:
                    continue

                vol = float(item.get("quoteVolume", 0) or 0)
                if vol < effective_min_vol:
                    continue
                last_p = float(item.get("lastPrice", 0) or 0)
                if last_p <= 0:
                    continue
                pct = float(item.get("priceChangePercent", 0) or 0)
                high_p = max(float(item.get("highPrice", 0) or 0), last_p)
                low_p = min(float(item.get("lowPrice", 0) or last_p), last_p)

                # Автоматический детектор привязанных к $1.00 стейблкоинов (USD1, RLUSD, RWUSD, USDE, U и др.)
                if 0.97 <= last_p <= 1.03 and low_p > 0 and ((high_p - low_p) / low_p) < 0.012:
                    continue

                # Попутно кешируем свежие bid/ask из ticker24 (экономит 100+ запросов к стакану!)
                bid_p = float(item.get("bidPrice", 0) or 0)
                ask_p = float(item.get("askPrice", 0) or 0)
                if bid_p > 0 and ask_p >= bid_p:
                    fresh_books[sym] = (bid_p, ask_p)

                dist_to_high = (high_p - last_p) / max(high_p, 1e-9)
                dist_to_low = (last_p - low_p) / max(last_p, 1e-9)
                # Индекс ракетной активности: сочетает силу суточного тренда и близость к пробою экстремума
                rocket_heat = abs(pct) / max(min(dist_to_high, dist_to_low) * 100.0 + 0.5, 0.5)

                valid_tickers.append({
                    "symbol": sym,
                    "price": last_p,
                    "volume_24h": vol,
                    "price_change_24h_pct": pct,
                    "high_24h": high_p,
                    "low_24h": low_p,
                    "dist_to_high_24h": round(dist_to_high, 4),
                    "dist_to_low_24h": round(dist_to_low, 4),
                    "rocket_heat": round(rocket_heat, 3)
                })
            except (ValueError, TypeError):
                continue

        if fresh_books:
            self._book_tickers_cache.update(fresh_books)
            self._book_tickers_cache_time = time.time()

        if not valid_tickers:
            return []

        # 1. Горячие LONG ракеты (активный рост + поджатие к хаям)
        breakout_long_pool = [
            x for x in valid_tickers
            if 0.8 <= x["price_change_24h_pct"] <= max_24h_cap and x["dist_to_high_24h"] <= 0.065
        ]
        breakout_long_pool.sort(key=lambda x: (-x["rocket_heat"], x["dist_to_high_24h"], -x["volume_24h"]))

        # 2. Горячие SHORT пробои (активный слив + поджатие к лоям)
        breakdown_short_pool = [
            x for x in valid_tickers
            if -max_24h_cap <= x["price_change_24h_pct"] <= -0.8 and x["dist_to_low_24h"] <= 0.065
        ]
        breakdown_short_pool.sort(key=lambda x: (-x["rocket_heat"], x["dist_to_low_24h"], -x["volume_24h"]))

        # 3. Топ волатильных лидеров дня (все монеты с сильным движением за 24ч независимо от локального отката)
        top_movers = sorted(valid_tickers, key=lambda x: abs(x["price_change_24h_pct"]), reverse=True)

        # 4. Топ ликвидности и элитный юниверс
        by_volume = sorted(valid_tickers, key=lambda x: (1 if x["symbol"] in whitelist else 0, x["volume_24h"]), reverse=True)

        combined_dict: Dict[str, Dict[str, Any]] = {}

        # 30% квоты: горячие LONG ракеты у хаев
        q_long = max(25, int(limit * 0.30))
        for item in breakout_long_pool[:q_long]:
            combined_dict[item["symbol"]] = item

        # 25% квоты: горячие SHORT пробои у лоев
        q_short = max(20, int(limit * 0.25))
        for item in breakdown_short_pool[:q_short]:
            combined_dict[item["symbol"]] = item

        # 20% квоты: главные ракеты дня (включая фазы булл-флага / отката к EMA9 перед второй волной)
        q_movers = max(20, int(limit * 0.20))
        for item in top_movers[:q_movers]:
            if abs(item["price_change_24h_pct"]) <= max_24h_cap:
                combined_dict[item["symbol"]] = item

        # 25% квоты + добор: лидеры ликвидности и элитный юниверс
        for item in by_volume:
            if len(combined_dict) >= limit:
                break
            if item["symbol"] not in combined_dict and abs(item["price_change_24h_pct"]) <= max_24h_cap * 1.15:
                combined_dict[item["symbol"]] = item

        return list(combined_dict.values())[:limit]

    async def fetch_candles_analysis(self, symbol: str, interval: str = "5m", limit: int = 200) -> Optional[Dict[str, Any]]:
        """
        Запрашивает 5m свечи (200 баров = 16.6ч для прогрева EMA150 / 15m EMA50) и выполняет структурный анализ:
        - 6H Structural Breakout (72 бара) + 3H Tight Squeeze Ignition (36 баров при сжатии <= 6.5%).
        - Rug-Hunter Breakdown (перехват слива после пампа >= +16% при пробое 16-барной полки и EMA50).
        - Строгий 15m MTF фильтр (EMA27 > EMA63 > EMA150 на 5m — без допуска пилы CHOP!).
        - Anti-Rug Top Guard: блокирует покупку параболического хая, если монета уже была растянута 15 мин назад.
        """
        raw_candles = await self._request_with_fallback("klines", params={"symbol": symbol, "interval": interval, "limit": limit})
        if not raw_candles or len(raw_candles) < 30:
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

        if len(candles) < 30:
            return None

        # Защита от приостановленных/замороженных торгов (свеча старше 10 минут)
        if (int(time.time() * 1000) - candles[-1]["time"]) > 600_000:
            return None

        # СТРОГАЯ СВЕЧНАЯ ДИСЦИПЛИНА:
        # Все индикаторы и условия сигнала считаются строго по ЗАКРЫТЫМ свечам (closed_candles),
        # а формирующаяся свеча (candles[-1]) дает актуальную рыночную цену входа и контроль погони!
        closed_candles = candles[:-1]
        current_live_c = candles[-1]
        closed_signal_c = closed_candles[-1]   # candles[-2] — закрытый сигнальный бар
        prev_closed_c = closed_candles[-2]     # candles[-3] — предыдущий закрытый бар
        current_price = current_live_c["close"]

        # Относительный всплеск объема RVOL по закрытой сигнальной свече к 20 предыдущим закрытым барам
        prior_20_vols = [c["quote_vol"] for c in closed_candles[-21:-1]]
        avg_vol = (sum(prior_20_vols) / len(prior_20_vols)) if prior_20_vols else 1.0
        surge_ratio = round(closed_signal_c["quote_vol"] / avg_vol, 2) if avg_vol > 0 else 1.0

        # Анатомия сигнальной свечи и сила закрытия (Close Location Value — CLV)
        candle_range = max(closed_signal_c["high"] - closed_signal_c["low"], 1e-9)
        body_top = max(closed_signal_c["open"], closed_signal_c["close"])
        body_bottom = min(closed_signal_c["open"], closed_signal_c["close"])

        upper_wick_pct = round((closed_signal_c["high"] - body_top) / candle_range, 3)
        lower_wick_pct = round((body_bottom - closed_signal_c["low"]) / candle_range, 3)
        close_strength_long = round((closed_signal_c["close"] - closed_signal_c["low"]) / candle_range, 3)
        close_strength_short = round((closed_signal_c["high"] - closed_signal_c["close"]) / candle_range, 3)

        # Отклонение живой цены относительно сигнального закрытия
        pullback_from_high_pct = round((current_price - closed_signal_c["high"]) / max(closed_signal_c["high"], 1e-9), 4)
        bounce_from_low_pct = round((current_price - closed_signal_c["low"]) / max(closed_signal_c["low"], 1e-9), 4)
        live_drift_long_pct = round((current_price - closed_signal_c["close"]) / max(closed_signal_c["close"], 1e-9), 4)
        live_drift_short_pct = round((closed_signal_c["close"] - current_price) / max(closed_signal_c["close"], 1e-9), 4)

        pct_5m = round((closed_signal_c["close"] - prev_closed_c["close"]) / max(prev_closed_c["close"], 1e-9) * 100, 2)
        pct_15m = round((closed_signal_c["close"] - closed_candles[-4]["close"]) / max(closed_candles[-4]["close"], 1e-9) * 100, 2) if len(closed_candles) >= 5 else pct_5m

        # ATR-14 строго по закрытым свечам
        true_ranges = []
        for i in range(1, len(closed_candles)):
            c_curr = closed_candles[i]
            c_prev = closed_candles[i - 1]
            tr = max(
                c_curr["high"] - c_curr["low"],
                abs(c_curr["high"] - c_prev["close"]),
                abs(c_curr["low"] - c_prev["close"])
            )
            true_ranges.append(tr)

        atr14 = (sum(true_ranges[-14:]) / min(len(true_ranges), 14)) if true_ranges else candle_range
        atr14_pct = round(atr14 / max(closed_signal_c["close"], 1e-9), 4)

        # EMA-9, EMA-21 и RSI-14 строго по закрытым свечам (без дрожания незакрытого тика)
        closed_closes = [c["close"] for c in closed_candles]

        def calc_ema(values: List[float], period: int) -> float:
            k = 2.0 / (period + 1.0)
            ema_val = values[0]
            for v in values[1:]:
                ema_val = v * k + ema_val * (1.0 - k)
            return ema_val

        ema9 = config.round_price(calc_ema(closed_closes, 9))
        ema21 = config.round_price(calc_ema(closed_closes, 21) if len(closed_closes) >= 21 else calc_ema(closed_closes, len(closed_closes)))
        ema50 = config.round_price(calc_ema(closed_closes, 50) if len(closed_closes) >= 50 else calc_ema(closed_closes, len(closed_closes)))
        ema21_ext_pct = round(abs(closed_signal_c["close"] - ema21) / max(ema21, 1e-9), 4)

        # Макро-фильтр старшей скользящей (EMA-50 на 5m = тренд 4+ часов):
        is_macro_trend_long = (closed_signal_c["close"] >= ema50 * 0.996)
        is_macro_trend_short = (closed_signal_c["close"] <= ema50 * 1.004)

        gains, losses = [], []
        for i in range(1, len(closed_closes)):
            delta = closed_closes[i] - closed_closes[i - 1]
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

        # 15m Multi-Timeframe (MTF) Trend Analysis: EMA27 (=15m EMA9), EMA63 (=15m EMA21), EMA150 (=15m EMA50)
        def calc_ema_series(values: List[float], period: int) -> List[float]:
            k = 2.0 / (period + 1.0)
            res = [values[0]]
            for v in values[1:]:
                res.append(v * k + res[-1] * (1.0 - k))
            return res

        ema21_series = calc_ema_series(closed_closes, min(21, len(closed_closes)))
        ema27 = config.round_price(calc_ema(closed_closes, min(27, len(closed_closes))))
        ema63 = config.round_price(calc_ema(closed_closes, min(63, len(closed_closes))))
        ema150 = config.round_price(calc_ema(closed_closes, min(150, len(closed_closes))))

        sig_cl = closed_signal_c["close"]
        if sig_cl >= ema63 * 0.998 and ema27 >= ema63 * 0.998 and ema63 >= ema150 * 0.996:
            trend_15m = "BULL"
        elif sig_cl <= ema63 * 1.002 and ema27 <= ema63 * 1.002 and ema63 <= ema150 * 1.004:
            trend_15m = "BEAR"
        else:
            trend_15m = "CHOP"

        # СТРОГИЙ MTF ФИЛЬТР (ИСПРАВЛЕН БАГ ДОПУСКА CHOP!): в лонг только в BULL, в шорт только в BEAR (или при RUG_HUNTER_SHORT)
        is_mtf_long_ok = (trend_15m == "BULL")
        is_mtf_short_ok = (trend_15m == "BEAR")

        # ANTI-RUG TOP GUARD (защита от покупки параболического хая перед сливом):
        # 1) За 3 свечи (15 мин) до пробоя цена должна находиться в базе рядом с EMA21 (<= 2.6%), а не лететь в 4-й свече пампа!
        # 2) Не входить, если монета уже сделала вертикальный климакс > +18% за последние 3 часа (36 баров).
        if len(closed_closes) >= 5:
            ext_prev3_pct = round(abs(closed_closes[-4] - ema21_series[-4]) / max(ema21_series[-4], 1e-9), 4)
        else:
            ext_prev3_pct = 0.0
        if len(closed_closes) >= 38:
            ret_3h_pct = round((sig_cl - closed_closes[-37]) / max(closed_closes[-37], 1e-9), 4)
        else:
            ret_3h_pct = round((sig_cl - closed_closes[0]) / max(closed_closes[0], 1e-9), 4)

        max_pre_ext = float(getattr(config, "MAX_PRE_BREAKOUT_EXT_PCT", 0.026))
        max_climax_3h = float(getattr(config, "MAX_3H_CLIMAX_RETURN_PCT", 0.18))
        anti_rug_long_ok = (ext_prev3_pct <= max_pre_ext) and (ret_3h_pct <= max_climax_3h)
        anti_rug_short_ok = (ext_prev3_pct <= max_pre_ext) and (ret_3h_pct >= -max_climax_3h)

        # 3-свечной кумулятивный приток объема (Volume Persistence за последние 15 минут)
        prior_3_vols = [c["quote_vol"] for c in closed_candles[-3:]]
        v3_surge = round((sum(prior_3_vols) / 3.0) / max(avg_vol, 1.0), 2)

        # ======================================================================
        # 3-РЕЖИМНЫЙ ПЕРЕХВАТ РАКЕТ И СЛИВОВ (ROCKET & RUG HUNTER ENGINE):
        # 1) STRUCT_6H: Пробой 72-барного канала Дончиана (6 часов) на RVOL >= 2.0x
        # 2) SQUEEZE_3H: Ранний старт ракеты из узкого 3ч сжатия (36 баров <= 6.5%) на RVOL >= 2.2x
        # 3) RUG_SHORT: Слив памповой монеты (после роста >= +16% за 6ч пробой 16-барного лоя и EMA50 на RVOL >= 2.1x)
        # ======================================================================
        lookback = int(getattr(config, "BREAKOUT_LOOKBACK_BARS", 72))
        sq_lb = int(getattr(config, "SQUEEZE_LOOKBACK_BARS", 36))
        sq_max_rng = float(getattr(config, "SQUEEZE_MAX_RANGE_PCT", 0.065))
        sq_min_rvol = float(getattr(config, "SQUEEZE_MIN_RVOL", 2.20))
        min_rvol = float(getattr(config, "MIN_5M_VOLUME_SURGE_RATIO", 2.00))

        struct_slice = closed_candles[-(lookback + 1):-1] if len(closed_candles) > lookback else closed_candles[:-1]
        sq_slice = closed_candles[-(sq_lb + 1):-1] if len(closed_candles) > sq_lb else closed_candles[:-1]

        donchian_high = max(c["high"] for c in struct_slice)
        donchian_low = min(c["low"] for c in struct_slice)
        sq_high = max(c["high"] for c in sq_slice)
        sq_low = min(c["low"] for c in sq_slice)
        sq_range_pct = (sq_high - sq_low) / max(sq_low, 1e-9)

        is_struct_long = (sig_cl > donchian_high) and (surge_ratio >= min_rvol)
        is_struct_short = (sig_cl < donchian_low) and (surge_ratio >= min_rvol)

        is_squeeze_long = (not is_struct_long) and (sq_range_pct <= sq_max_rng) and (sig_cl > sq_high) and (surge_ratio >= max(min_rvol, sq_min_rvol))
        is_squeeze_short = (not is_struct_short) and (sq_range_pct <= sq_max_rng) and (sig_cl < sq_low) and (surge_ratio >= max(min_rvol, sq_min_rvol))

        # Детектор слива после пампа (Rug-Hunter Short)
        is_rug_short = False
        if getattr(config, "ENABLE_RUG_HUNTER_SHORT", True) and not is_struct_short and not is_squeeze_short and len(closed_candles) >= 20:
            rug_lb = int(getattr(config, "RUG_SUPPORT_BARS", 16))
            rug_slice = closed_candles[-(rug_lb + 1):-1] if len(closed_candles) > rug_lb else closed_candles[:-1]
            rug_low_16 = min(c["low"] for c in rug_slice)
            pump_6h = (donchian_high - donchian_low) / max(donchian_low, 1e-9)
            off_high_6h = (donchian_high - sig_cl) / max(donchian_high, 1e-9)
            if (
                pump_6h >= float(getattr(config, "RUG_PUMP_MIN_PCT", 0.16))
                and 0.03 <= off_high_6h <= 0.22
                and sig_cl < rug_low_16
                and sig_cl < ema50
                and surge_ratio >= 2.10
            ):
                is_rug_short = True
                is_mtf_short_ok = True  # Слом после пампа идет раньше разворота медленной 12-часовой EMA150!

        is_breakout_long = is_struct_long or is_squeeze_long
        is_breakout_short = is_struct_short or is_squeeze_short or is_rug_short

        if is_rug_short:
            breakout_type = "RUG_SHORT"
        elif is_squeeze_long or is_squeeze_short:
            breakout_type = "SQUEEZE_3H"
        elif is_struct_long or is_struct_short:
            breakout_type = "STRUCT_6H"
        else:
            breakout_type = "WATCH"

        target_high_ref = sq_high if sq_range_pct <= sq_max_rng else donchian_high
        target_low_ref = sq_low if sq_range_pct <= sq_max_rng else donchian_low
        ref_price_for_dist = sig_cl
        dist_to_breakout_long_pct = round(max(0.0, (target_high_ref - ref_price_for_dist) / max(ref_price_for_dist, 1e-9) * 100.0), 2)
        dist_to_breakout_short_pct = round(max(0.0, (ref_price_for_dist - target_low_ref) / max(ref_price_for_dist, 1e-9) * 100.0), 2)

        # УМНЫЙ СТРУКТУРНЫЙ СТОП-ЛОСС (1.60 * ATR14 БУФЕР ЗА ФИТИЛЬ СВЕЧИ):
        active_sig_c = closed_signal_c
        recent_wick_low = min(prev_closed_c["low"], active_sig_c["low"])
        raw_wick_sl = config.round_price(recent_wick_low * (1.0 - config.WICK_BUFFER_PCT))
        raw_sl_pct = (current_price - raw_wick_sl) / max(current_price, 1e-9)
        max_allowed_sl = float(getattr(config, "STOP_LOSS_MAX_PCT", 0.0350))
        min_allowed_sl = float(getattr(config, "STOP_LOSS_MIN_PCT", 0.0080))
        sl_atr_mult = float(getattr(config, "SL_ATR_MULT", 1.60))

        true_long_sl_pct = round(min(max(raw_sl_pct, sl_atr_mult * atr14_pct, min_allowed_sl), max_allowed_sl), 4)
        wick_stop_loss = config.round_price(current_price * (1.0 - true_long_sl_pct))

        recent_wick_high = max(prev_closed_c["high"], active_sig_c["high"])
        raw_short_sl = config.round_price(recent_wick_high * (1.0 + config.WICK_BUFFER_PCT))
        raw_short_sl_pct = (raw_short_sl - current_price) / max(current_price, 1e-9)

        true_short_sl_pct = round(min(max(raw_short_sl_pct, sl_atr_mult * atr14_pct, min_allowed_sl), max_allowed_sl), 4)
        short_wick_stop_loss = config.round_price(current_price * (1.0 + true_short_sl_pct))

        ref_close_trend = closed_signal_c["close"]
        if ref_close_trend >= ema9 >= ema21:
            trend = "BULLISH"
        elif ref_close_trend <= ema9 <= ema21:
            trend = "BEARISH"
        else:
            trend = "CHOP"

        return {
            "symbol": symbol,
            "current_price": current_price,
            "signal_close": active_sig_c["close"],
            "signal_open": active_sig_c["open"],
            "recent_high": donchian_high,
            "recent_low": donchian_low,
            "dist_to_breakout_long_pct": dist_to_breakout_long_pct,
            "dist_to_breakout_short_pct": dist_to_breakout_short_pct,
            "is_breakout_long": is_breakout_long,
            "is_breakout_short": is_breakout_short,
            "breakout_type": breakout_type,
            "is_live_ignition": False,
            "close_strength_long": close_strength_long,
            "close_strength_short": close_strength_short,
            "ema21_ext_pct": ema21_ext_pct,
            "live_drift_long_pct": live_drift_long_pct,
            "live_drift_short_pct": live_drift_short_pct,
            "breakout_failed_long": current_price < min(closed_signal_c["close"] * 0.991, ema9 * 0.999),
            "breakout_failed_short": current_price > max(closed_signal_c["close"] * 1.009, ema9 * 1.001),
            "pullback_from_high_pct": pullback_from_high_pct,
            "bounce_from_low_pct": bounce_from_low_pct,
            "volume_surge_ratio": surge_ratio,
            "rvol": surge_ratio,
            "upper_wick_pct": upper_wick_pct,
            "lower_wick_pct": lower_wick_pct,
            "wick_stop_loss": wick_stop_loss,
            "sl_pct_distance": true_long_sl_pct,
            "short_wick_sl": short_wick_stop_loss,
            "short_wick_stop_loss": short_wick_stop_loss,
            "short_sl_dist": true_short_sl_pct,
            "short_sl_pct_distance": true_short_sl_pct,
            "pct_5m": pct_5m,
            "pct_15m": pct_15m,
            "trend_15m": trend_15m,
            "is_mtf_long_ok": is_mtf_long_ok,
            "is_mtf_short_ok": is_mtf_short_ok,
            "anti_rug_long_ok": anti_rug_long_ok,
            "anti_rug_short_ok": anti_rug_short_ok,
            "ext_prev3_pct": ext_prev3_pct,
            "ret_3h_pct": ret_3h_pct,
            "ema50": ema50,
            "is_macro_trend_long": is_macro_trend_long,
            "is_macro_trend_short": is_macro_trend_short,
            "v3_surge": v3_surge,
            "avg_5m_quote_vol": round(avg_vol, 1),
            "last_quote_volume": active_sig_c["quote_vol"],
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
        Блокирует входы против резких импульсных проливов/выносов BTC.
        """
        analysis = await self.fetch_candles_analysis("BTCUSDT", interval="5m", limit=35)
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

        is_dumping = (p15 <= -0.45) or (p5 <= -0.35 and p15 <= -0.10)
        is_pumping = (p15 >= +0.45) or (p5 >= +0.35 and p15 >= +0.10)

        if is_dumping:
            status_str = f"🔴 Медвежий импульс BTC ({p15:+.2f}%, {trend}) — ЛОНГИ ЗАБЛОКИРОВАНЫ | Приоритет: SHORT"
        elif is_pumping:
            status_str = f"🟢 Бычий импульс BTC ({p15:+.2f}%, {trend}) — ШОРТЫ ЗАБЛОКИРОВАНЫ | Приоритет: LONG"
        else:
            status_str = f"🟡 Спокойный BTC ({p15:+.2f}%, {trend}) — Разрешены LONG и SHORT ракеты"

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
