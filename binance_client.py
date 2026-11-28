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
        # 6-уровневый отказоустойчивый пул крипто-фьючерсов (защита от shared-IP банов Render HTTP 418/403/429):
        # fapi (Binance 500 перпов) -> bybit (430+ перпов) -> bitget (550+ перпов isRwa=NO)
        # -> okx (289 топ-ликвидных SWAP instCategory=1) -> gate (400+ перпов, 900 req/s) -> vision (Spot резерв)
        self.mirrors = [
            {"name": "fapi", "base": "https://fapi.binance.com", "ticker24": "/fapi/v1/ticker/24hr", "klines": "/fapi/v1/klines", "book": "/fapi/v1/ticker/bookTicker", "price": "/fapi/v1/ticker/price", "info": "/fapi/v1/exchangeInfo"},
            {"name": "bybit", "base": "https://api.bybit.com", "ticker24": "/v5/market/tickers", "klines": "/v5/market/kline", "book": "/v5/market/tickers", "price": "/v5/market/tickers", "info": "/v5/market/instruments-info"},
            {"name": "bitget", "base": "https://api.bitget.com", "ticker24": "/api/v2/mix/market/tickers", "klines": "/api/v2/mix/market/candles", "book": "/api/v2/mix/market/tickers", "price": "/api/v2/mix/market/ticker", "info": "/api/v2/mix/market/contracts"},
            {"name": "okx", "base": "https://www.okx.com", "ticker24": "/api/v5/market/tickers", "klines": "/api/v5/market/candles", "book": "/api/v5/market/tickers", "price": "/api/v5/market/ticker", "info": "/api/v5/public/instruments"},
            {"name": "gate", "base": "https://api.gateio.ws", "ticker24": "/api/v4/futures/usdt/tickers", "klines": "/api/v4/futures/usdt/candlesticks", "book": "/api/v4/futures/usdt/tickers", "price": "/api/v4/futures/usdt/tickers", "info": "/api/v4/futures/usdt/contracts"},
            {"name": "vision", "base": "https://data-api.binance.vision", "ticker24": "/api/v3/ticker/24hr", "klines": "/api/v3/klines", "book": "/api/v3/ticker/bookTicker", "price": "/api/v3/ticker/price", "info": "/api/v3/exchangeInfo"}
        ]
        self.active_mirror_idx = 0
        self._mirror_cooldowns: Dict[int, float] = {}
        self._mirror_ban_type: Dict[int, str] = {}   # "hard" (418/451/403) vs "soft" (429)
        self._last_err_log: Dict[str, float] = {}
        # Персональный rate-pacer для каждого зеркала (полностью исключает всплески HTTP 429 на shared IP Render!)
        self._mirror_min_interval: Dict[str, float] = {
            "fapi": 0.14,    # ~7 req/s
            "bybit": 0.14,   # ~7 req/s
            "bitget": 0.11,  # ~9 req/s (лимит Bitget 20 req/s)
            "okx": 0.11,     # ~9 req/s (лимит OKX 20 req/2s)
            "gate": 0.08,    # ~12 req/s (лимит Gate 900 req/s)
            "vision": 0.18,  # ~5.5 req/s
        }
        self._mirror_next_allowed: Dict[str, float] = {}
        self._rate_locks: Dict[str, asyncio.Lock] = {}
        self._session: Optional[aiohttp.ClientSession] = None
        self._book_tickers_cache: Dict[str, Tuple[float, float]] = {}
        self._book_tickers_cache_time: float = 0.0
        self._ticker24_cache: Tuple[str, float, List[Dict[str, Any]]] = ("", 0.0, [])
        self._candles_cache: Dict[Tuple[str, str, int, int], Dict[str, Any]] = {}
        self._valid_crypto_perps: Dict[str, Tuple[float, Set[str]]] = {}
        self._new_crypto_perps: Dict[str, Set[str]] = {}
        self._prev_scan_prices: Dict[str, float] = {}
        self.last_full_market_count: int = 0

    @property
    def active_mirror_name(self) -> str:
        if 0 <= self.active_mirror_idx < len(self.mirrors):
            return self.mirrors[self.active_mirror_idx]["name"]
        return "unknown"

    @property
    def is_spot_mirror(self) -> bool:
        return self.active_mirror_name in ("vision", "spot")

    async def _acquire_rate_slot(self, m_name: str):
        """Плавный rate-limiter по каждому зеркалу — исключает burst-волны HTTP 429."""
        lock = self._rate_locks.get(m_name)
        if lock is None:
            lock = asyncio.Lock()
            self._rate_locks[m_name] = lock
        async with lock:
            gap = self._mirror_min_interval.get(m_name, 0.12)
            now_m = time.monotonic()
            wait_s = self._mirror_next_allowed.get(m_name, 0.0) - now_m
            if wait_s > 0:
                await asyncio.sleep(wait_s)
            self._mirror_next_allowed[m_name] = time.monotonic() + gap

    def _log_once(self, key: str, msg: str, ttl: float = 30.0):
        now = time.time()
        if (now - self._last_err_log.get(key, 0.0)) >= ttl:
            self._last_err_log[key] = now
            print(msg, flush=True)

    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=12)
            headers = {"Accept": "application/json"}
            self._session = aiohttp.ClientSession(timeout=timeout, headers=headers)
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    def _normalize_bybit_response(self, route_key: str, raw: Any) -> Optional[Any]:
        """Нормализует ответы Bybit v5 Linear Perpetual в единый формат Binance."""
        if not isinstance(raw, dict) or raw.get("retCode") != 0:
            return None
        items = raw.get("result", {}).get("list")
        if items is None:
            return None
        now_ms = int(raw.get("time") or time.time() * 1000)

        if route_key == "ticker24":
            out = []
            for x in items:
                try:
                    sym = x.get("symbol", "")
                    if not sym.endswith("USDT"):
                        continue
                    lp = float(x.get("lastPrice", 0) or 0)
                    if lp <= 0:
                        continue
                    prev1h = float(x.get("prevPrice1h", 0) or 0)
                    pct_1h = round((lp - prev1h) / prev1h * 100.0, 2) if prev1h > 0 else 0.0
                    out.append({
                        "symbol": sym,
                        "lastPrice": str(lp),
                        "quoteVolume": str(x.get("turnover24h") or 0),
                        "priceChangePercent": str(round(float(x.get("price24hPcnt", 0) or 0) * 100.0, 4)),
                        "pct_1h_hint": pct_1h,
                        "highPrice": str(x.get("highPrice24h") or lp),
                        "lowPrice": str(x.get("lowPrice24h") or lp),
                        "bidPrice": str(x.get("bid1Price") or lp),
                        "askPrice": str(x.get("ask1Price") or lp),
                        "closeTime": now_ms,
                        "count": 10000
                    })
                except (ValueError, TypeError):
                    continue
            return out

        if route_key == "klines":
            # Bybit: [startTime, open, high, low, close, volume, turnover] (newest first)
            out = []
            for c in items:
                if isinstance(c, list) and len(c) >= 7:
                    out.append([int(c[0]), c[1], c[2], c[3], c[4], c[5], int(c[0]), c[6]])
            out.sort(key=lambda r: r[0])
            return out

        if route_key == "book":
            out = []
            for x in items:
                sym = x.get("symbol", "")
                if sym.endswith("USDT") and x.get("bid1Price") and x.get("ask1Price"):
                    out.append({"symbol": sym, "bidPrice": x["bid1Price"], "askPrice": x["ask1Price"]})
            return out

        if route_key == "price":
            if isinstance(items, list) and items:
                x0 = items[0]
                return {"price": str(self._pick_live_price(x0.get("lastPrice"), x0.get("bid1Price"), x0.get("ask1Price"), x0.get("markPrice")))}
            return None

        return items

    @staticmethod
    def _pick_live_price(last_raw: Any, bid_raw: Any = None, ask_raw: Any = None, mark_raw: Any = None) -> float:
        """Возвращает живую цену (mid стакана при узком спреде или mark_price), исключая замирание старого last!"""
        def _f(v: Any) -> float:
            try:
                return float(v or 0)
            except (ValueError, TypeError):
                return 0.0
        lp, bp, ap, mp = _f(last_raw), _f(bid_raw), _f(ask_raw), _f(mark_raw)
        if bp > 0 and ap >= bp and ((ap - bp) / bp) <= 0.012:
            return round((bp + ap) * 0.5, 10)
        if mp > 0:
            return mp
        return lp

    def _normalize_okx_response(self, route_key: str, raw: Any) -> Optional[Any]:
        """Нормализует ответы OKX v5 USDT-SWAP в единый формат Binance."""
        if not isinstance(raw, dict) or str(raw.get("code", "")) != "0":
            return None
        items = raw.get("data")
        if not isinstance(items, list):
            return None
        now_ms = int(time.time() * 1000)

        if route_key == "ticker24":
            out = []
            for x in items:
                try:
                    inst_id = x.get("instId", "")
                    if not inst_id.endswith("-USDT-SWAP"):
                        continue
                    sym = inst_id[:-10] + "USDT"
                    lp = float(x.get("last", 0) or 0)
                    if lp <= 0:
                        continue
                    o24 = float(x.get("open24h", 0) or lp)
                    pct = round((lp - o24) / o24 * 100.0, 4) if o24 > 0 else 0.0
                    qvol = float(x.get("volCcy24h", 0) or 0) * lp
                    out.append({
                        "symbol": sym,
                        "lastPrice": str(lp),
                        "quoteVolume": str(qvol),
                        "priceChangePercent": str(pct),
                        "highPrice": str(x.get("high24h") or lp),
                        "lowPrice": str(x.get("low24h") or lp),
                        "bidPrice": str(x.get("bidPx") or lp),
                        "askPrice": str(x.get("askPx") or lp),
                        "closeTime": int(x.get("ts") or now_ms),
                        "count": 10000
                    })
                except (ValueError, TypeError):
                    continue
            return out

        if route_key == "klines":
            out = []
            for c in items:
                if isinstance(c, list) and len(c) >= 8:
                    out.append([int(c[0]), c[1], c[2], c[3], c[4], c[5], int(c[0]), c[7]])
            out.sort(key=lambda r: r[0])
            return out

        if route_key == "book":
            out = []
            for x in items:
                inst_id = x.get("instId", "")
                if inst_id.endswith("-USDT-SWAP") and x.get("bidPx") and x.get("askPx"):
                    out.append({"symbol": inst_id[:-10] + "USDT", "bidPrice": x["bidPx"], "askPrice": x["askPx"]})
            return out

        if route_key == "price":
            if items and isinstance(items[0], dict):
                x0 = items[0]
                return {"price": str(self._pick_live_price(x0.get("last"), x0.get("bidPx"), x0.get("askPx"), None))}
            return None

        return items

    def _normalize_gate_response(self, route_key: str, raw: Any) -> Optional[Any]:
        """Нормализует ответы Gate.io v4 USDT Perpetual в единый формат Binance."""
        if not isinstance(raw, list):
            return None
        now_ms = int(time.time() * 1000)

        if route_key == "ticker24":
            out = []
            for x in raw:
                try:
                    contract = x.get("contract", "")
                    if not contract.endswith("_USDT"):
                        continue
                    sym = contract[:-5] + "USDT"
                    lp = float(x.get("last", 0) or 0)
                    if lp <= 0:
                        continue
                    out.append({
                        "symbol": sym,
                        "lastPrice": str(lp),
                        "quoteVolume": str(x.get("volume_24h_settle") or x.get("volume_24h_quote") or 0),
                        "priceChangePercent": str(x.get("change_percentage") or 0),
                        "highPrice": str(x.get("high_24h") or lp),
                        "lowPrice": str(x.get("low_24h") or lp),
                        "bidPrice": str(x.get("highest_bid") or lp),
                        "askPrice": str(x.get("lowest_ask") or lp),
                        "closeTime": now_ms,
                        "count": 10000
                    })
                except (ValueError, TypeError):
                    continue
            return out

        if route_key == "klines":
            # Gate: {'t': sec, 'o', 'h', 'l', 'c', 'v', 'sum': quoteVol}
            out = []
            for c in raw:
                if isinstance(c, dict) and "t" in c and "c" in c:
                    ts_ms = int(c["t"]) * 1000
                    qvol = c.get("sum") if c.get("sum") is not None else c.get("v", 0)
                    out.append([ts_ms, c.get("o", 0), c.get("h", 0), c.get("l", 0), c.get("c", 0), c.get("v", 0), ts_ms, qvol])
            out.sort(key=lambda r: r[0])
            return out

        if route_key == "book":
            out = []
            for x in raw:
                contract = x.get("contract", "")
                if contract.endswith("_USDT") and x.get("highest_bid") and x.get("lowest_ask"):
                    out.append({"symbol": contract[:-5] + "USDT", "bidPrice": x["highest_bid"], "askPrice": x["lowest_ask"]})
            return out

        if route_key == "price":
            if raw and isinstance(raw[0], dict):
                x0 = raw[0]
                return {"price": str(self._pick_live_price(x0.get("last"), x0.get("highest_bid"), x0.get("lowest_ask"), x0.get("mark_price")))}
            return None

        return raw

    def _normalize_bitget_response(self, route_key: str, raw: Any) -> Optional[Any]:
        """Нормализует ответы Bitget USDT-FUTURES v2 в единый формат Binance (100% совместимость со всем кодом)."""
        if not isinstance(raw, dict) or raw.get("code") != "00000":
            return None
        items = raw.get("data")
        if items is None:
            return None
        now_ms = int(time.time() * 1000)

        if route_key == "ticker24":
            out = []
            for x in items:
                try:
                    sym = x.get("symbol", "")
                    if not sym.endswith("USDT"):
                        continue
                    lp = float(x.get("lastPr", 0) or 0)
                    if lp <= 0:
                        continue
                    out.append({
                        "symbol": sym,
                        "lastPrice": str(lp),
                        "quoteVolume": str(x.get("usdtVolume") or x.get("quoteVolume") or 0),
                        "priceChangePercent": str(round(float(x.get("change24h", 0) or 0) * 100.0, 4)),
                        "highPrice": str(x.get("high24h") or lp),
                        "lowPrice": str(x.get("low24h") or lp),
                        "bidPrice": str(x.get("bidPr") or lp),
                        "askPrice": str(x.get("askPr") or lp),
                        "closeTime": int(x.get("ts") or now_ms),
                        "count": 10000
                    })
                except (ValueError, TypeError):
                    continue
            return out

        if route_key == "klines":
            # Bitget: [ts, open, high, low, close, baseVol, quoteVol] -> Binance: [ts, o, h, l, c, bv, ts, qv]
            out = []
            for c in items:
                if isinstance(c, list) and len(c) >= 7:
                    out.append([int(c[0]), c[1], c[2], c[3], c[4], c[5], int(c[0]), c[6]])
            out.sort(key=lambda r: r[0])
            return out

        if route_key == "book":
            out = []
            for x in items:
                sym = x.get("symbol", "")
                if sym.endswith("USDT") and x.get("bidPr") and x.get("askPr"):
                    out.append({"symbol": sym, "bidPrice": x["bidPr"], "askPrice": x["askPr"]})
            return out

        if route_key == "price":
            if isinstance(items, list) and items:
                x0 = items[0]
                return {"price": str(self._pick_live_price(x0.get("lastPr"), x0.get("bidPr"), x0.get("askPr"), x0.get("markPrice")))}
            if isinstance(items, dict):
                return {"price": str(self._pick_live_price(items.get("lastPr"), items.get("bidPr"), items.get("askPr"), items.get("markPrice")))}
            return None

        return items

    async def _request_with_fallback(self, route_key: str, params: Optional[Dict[str, Any]] = None) -> Optional[Any]:
        session = await self.get_session()
        now = time.time()

        # Формируем порядок зеркал: активное первым, далее остальные ЗДОРОВЫЕ зеркала.
        # НИКОГДА не лезем в зеркала с активным жестким баном HTTP 418/451!
        all_indices = list(range(len(self.mirrors)))
        if self.active_mirror_idx in all_indices:
            all_indices.remove(self.active_mirror_idx)
            all_indices.insert(0, self.active_mirror_idx)

        indices = [i for i in all_indices if now >= self._mirror_cooldowns.get(i, 0.0)]
        if not indices:
            # Пробуем ТОЛЬКО мягкие 429-зеркала (не 418/451!)
            soft_candidates = [i for i in all_indices if self._mirror_ban_type.get(i) != "hard"]
            if soft_candidates:
                indices = sorted(soft_candidates, key=lambda i: self._mirror_cooldowns.get(i, 0.0))[:1]
            else:
                return None

        for idx in indices:
            # Перепроверяем кулдаун прямо перед запросом (защита от 6 параллельных задач при одновременном 418/429)
            if time.time() < self._mirror_cooldowns.get(idx, 0.0):
                continue

            mirror = self.mirrors[idx]
            m_name = mirror["name"]
            url = f"{mirror['base']}{mirror[route_key]}"
            req_params: Dict[str, Any] = dict(params) if params else {}

            if m_name == "bybit":
                req_params["category"] = "linear"
                if route_key == "klines":
                    iv = str(req_params.pop("interval", "5m"))
                    req_params["interval"] = iv[:-1] if iv.endswith("m") else iv
                    if "limit" in req_params:
                        req_params["limit"] = str(min(int(req_params["limit"]), 200))
            elif m_name == "gate":
                if "symbol" in req_params:
                    s_val = str(req_params.pop("symbol"))
                    req_params["contract"] = (s_val[:-4] + "_USDT") if (s_val.endswith("USDT") and "_" not in s_val) else s_val
                if route_key == "klines":
                    if "limit" in req_params:
                        req_params["limit"] = str(min(int(req_params["limit"]), 200))
            elif m_name == "bitget":
                req_params["productType"] = "USDT-FUTURES"
                if route_key == "klines":
                    req_params["granularity"] = req_params.pop("interval", "5m")
                    if "limit" in req_params:
                        req_params["limit"] = str(min(int(req_params["limit"]), 200))
            elif m_name == "okx":
                if route_key in ("ticker24", "book", "info"):
                    req_params["instType"] = "SWAP"
                if "symbol" in req_params:
                    s_val = str(req_params.pop("symbol"))
                    req_params["instId"] = (s_val[:-4] + "-USDT-SWAP") if (s_val.endswith("USDT") and "-" not in s_val) else s_val
                if route_key == "klines":
                    req_params["bar"] = req_params.pop("interval", "5m")
                    if "limit" in req_params:
                        req_params["limit"] = str(min(int(req_params["limit"]), 300))

            # Плавное ограничение частоты запросов для данного зеркала
            await self._acquire_rate_slot(m_name)
            if time.time() < self._mirror_cooldowns.get(idx, 0.0):
                continue

            try:
                async with session.get(url, params=req_params) as resp:
                    if resp.status == 200:
                        raw = await resp.json()
                        if m_name == "bybit":
                            rc = raw.get("retCode", -1) if isinstance(raw, dict) else -1
                            if rc == 10001:  # Тикер не найден на Bybit
                                return None
                            if rc == 10006:  # Bybit rate limit
                                self._mirror_min_interval[m_name] = min(0.50, self._mirror_min_interval.get(m_name, 0.08) * 1.5)
                                self._mirror_cooldowns[idx] = time.time() + 15.0
                                self._mirror_ban_type[idx] = "soft"
                                self._log_once(f"429_{m_name}", f"🚫 [Market API] {m_name} rate-limit (retCode 10006, пауза 15с) → переход на резерв!", ttl=25.0)
                                continue
                            raw = self._normalize_bybit_response(route_key, raw)
                            if raw is None:
                                continue
                        elif m_name == "gate":
                            raw = self._normalize_gate_response(route_key, raw)
                            if raw is None:
                                continue
                        elif m_name == "bitget":
                            if isinstance(raw, dict) and str(raw.get("code", "")) in ("40034", "400172", "40007"):
                                return None
                            raw = self._normalize_bitget_response(route_key, raw)
                            if raw is None:
                                continue
                        elif m_name == "okx":
                            if isinstance(raw, dict) and str(raw.get("code", "")) in ("51001", "51000"):
                                return None
                            raw = self._normalize_okx_response(route_key, raw)
                            if raw is None:
                                continue

                        if self.active_mirror_idx != idx:
                            print(f"🌐 [Market API] Успешное подключение через зеркало {m_name} ({mirror['base']})", flush=True)
                            self.active_mirror_idx = idx
                        return raw
                    elif resp.status == 400:
                        return None
                    elif resp.status == 418:
                        retry_after = 0.0
                        try:
                            retry_after = float(resp.headers.get("Retry-After", 0) or 0)
                        except ValueError:
                            retry_after = 0.0
                        cd = max(retry_after, 600.0)
                        self._mirror_cooldowns[idx] = time.time() + cd
                        self._mirror_ban_type[idx] = "hard"
                        self._log_once(f"418_{m_name}", f"🚫 [Market API] {m_name} вернул HTTP 418 (shared-IP бан {int(cd)}с) → мгновенный переход на резерв!", ttl=60.0)
                        continue
                    elif resp.status == 429:
                        retry_after = 0.0
                        try:
                            retry_after = float(resp.headers.get("Retry-After", 0) or 0)
                        except ValueError:
                            retry_after = 0.0
                        # Самоадаптация скорости: при 429 замедляем pacer и даем короткую паузу (20с), не 120с
                        self._mirror_min_interval[m_name] = min(0.65, self._mirror_min_interval.get(m_name, 0.15) * 1.45)
                        cd = max(retry_after, 20.0)
                        self._mirror_cooldowns[idx] = time.time() + cd
                        self._mirror_ban_type[idx] = "soft"
                        self._log_once(f"429_{m_name}", f"⚠️ [Market API] {m_name} вернул HTTP 429 (пауза {int(cd)}с, темп снижен до {1.0/self._mirror_min_interval[m_name]:.1f} req/s) → резерв!", ttl=25.0)
                        continue
                    elif resp.status in (451, 403):
                        self._mirror_cooldowns[idx] = time.time() + 1800.0
                        self._mirror_ban_type[idx] = "hard"
                        self._log_once(f"451_{m_name}", f"⚠️ [Market API] {m_name} вернул HTTP {resp.status} (гео-ограничение, пауза 30м) → переход на резерв!", ttl=60.0)
                        continue
                    else:
                        if self.active_mirror_idx == idx:
                            self._log_once(f"http_{m_name}_{resp.status}", f"⚠️ [Market API] {m_name} вернул HTTP {resp.status} на {route_key}, пробуем резерв...", ttl=30.0)
            except Exception as e:
                if self.active_mirror_idx == idx:
                    self._log_once(f"exc_{m_name}", f"⚠️ [Market API] Ошибка сети на {m_name} ({type(e).__name__}), пробуем резерв...", ttl=30.0)
        return None

    async def fetch_valid_crypto_perps(self) -> Set[str]:
        """
        Возвращает официальный список чистых крипто-фьючерсов для активного зеркала
        (fapi: underlyingType=COIN; bybit: symbolType in ('','innovation') & marketRegion=='';
         bitget: isRwa=NO; gate: active USDT contracts), а также отмечает НОВЫЕ ЛИСТИНГИ (<= 45 дней)!
        """
        now = time.time()
        now_ms = int(now * 1000)
        new_cutoff_ms = now_ms - 45 * 86400 * 1000
        new_cutoff_sec = int(now) - 45 * 86400
        m_name = self.active_mirror_name
        if m_name not in ("fapi", "bybit", "bitget", "okx", "gate"):
            return set()
        cached_ts, cached_set = self._valid_crypto_perps.get(m_name, (0.0, set()))
        if cached_set and (now - cached_ts) < 3600.0:
            return cached_set
        if now < self._mirror_cooldowns.get(self.active_mirror_idx, 0.0):
            return cached_set
        try:
            session = await self.get_session()
            base_url = self.mirrors[self.active_mirror_idx]["base"]
            if m_name == "fapi":
                async with session.get(f"{base_url}/fapi/v1/exchangeInfo") as resp:
                    if resp.status == 200:
                        info = await resp.json()
                        perps, new_set = set(), set()
                        for s in info.get("symbols", []):
                            if (
                                s.get("status") == "TRADING"
                                and s.get("contractType") == "PERPETUAL"
                                and s.get("underlyingType") == "COIN"
                                and s.get("quoteAsset") == "USDT"
                            ):
                                sym = s["symbol"]
                                perps.add(sym)
                                if int(s.get("onboardDate", 0) or 0) >= new_cutoff_ms:
                                    new_set.add(sym)
                        if len(perps) >= 100:
                            self._valid_crypto_perps[m_name] = (now, perps)
                            self._new_crypto_perps[m_name] = new_set
                            return perps
                    elif resp.status in (418, 429):
                        cd = 600.0 if resp.status == 418 else 30.0
                        self._mirror_cooldowns[self.active_mirror_idx] = now + cd
                        self._mirror_ban_type[self.active_mirror_idx] = "hard" if resp.status == 418 else "soft"
                    elif resp.status in (451, 403):
                        self._mirror_cooldowns[self.active_mirror_idx] = now + 1800.0
                        self._mirror_ban_type[self.active_mirror_idx] = "hard"
            elif m_name == "bybit":
                async with session.get(f"{base_url}/v5/market/instruments-info", params={"category": "linear", "limit": "1000"}) as resp:
                    if resp.status == 200:
                        info = await resp.json()
                        if isinstance(info, dict) and info.get("retCode") == 0:
                            perps, new_set = set(), set()
                            for s in info.get("result", {}).get("list", []):
                                if (
                                    s.get("contractType") == "LinearPerpetual"
                                    and s.get("status") == "Trading"
                                    and s.get("quoteCoin") == "USDT"
                                    and s.get("symbolType", "") in ("", "innovation")
                                    and not s.get("marketRegion")
                                    and not s.get("underlyingTicker")
                                    and not s.get("isPreListing")
                                ):
                                    sym = s["symbol"]
                                    perps.add(sym)
                                    if s.get("symbolType") == "innovation" or int(s.get("launchTime", 0) or 0) >= new_cutoff_ms:
                                        new_set.add(sym)
                            if len(perps) >= 100:
                                self._valid_crypto_perps[m_name] = (now, perps)
                                self._new_crypto_perps[m_name] = new_set
                                return perps
                    elif resp.status in (451, 403):
                        self._mirror_cooldowns[self.active_mirror_idx] = now + 1800.0
                        self._mirror_ban_type[self.active_mirror_idx] = "hard"
            elif m_name == "bitget":
                async with session.get(f"{base_url}/api/v2/mix/market/contracts", params={"productType": "USDT-FUTURES"}) as resp:
                    if resp.status == 200:
                        info = await resp.json()
                        if isinstance(info, dict) and info.get("code") == "00000":
                            perps, new_set = set(), set()
                            for s in info.get("data", []):
                                if (
                                    s.get("symbolStatus") == "normal"
                                    and s.get("symbolType") == "perpetual"
                                    and str(s.get("isRwa", "NO")).upper() == "NO"
                                    and s.get("quoteCoin") == "USDT"
                                ):
                                    sym = s["symbol"]
                                    perps.add(sym)
                                    ot = int(s.get("openTime") or s.get("launchTime") or 0)
                                    if ot >= new_cutoff_ms:
                                        new_set.add(sym)
                            if len(perps) >= 100:
                                self._valid_crypto_perps[m_name] = (now, perps)
                                self._new_crypto_perps[m_name] = new_set
                                return perps
                    elif resp.status in (418, 429):
                        self._mirror_cooldowns[self.active_mirror_idx] = now + 20.0
                        self._mirror_ban_type[self.active_mirror_idx] = "soft"
            elif m_name == "okx":
                async with session.get(f"{base_url}/api/v5/public/instruments", params={"instType": "SWAP"}) as resp:
                    if resp.status == 200:
                        info = await resp.json()
                        if isinstance(info, dict) and str(info.get("code", "")) == "0":
                            perps, new_set = set(), set()
                            for s in info.get("data", []):
                                inst_id = s.get("instId", "")
                                if (
                                    inst_id.endswith("-USDT-SWAP")
                                    and s.get("state") == "live"
                                    and str(s.get("instCategory", "1")) == "1"
                                ):
                                    sym = inst_id[:-10] + "USDT"
                                    perps.add(sym)
                                    if int(s.get("listTime") or 0) >= new_cutoff_ms:
                                        new_set.add(sym)
                            if len(perps) >= 100:
                                self._valid_crypto_perps[m_name] = (now, perps)
                                self._new_crypto_perps[m_name] = new_set
                                return perps
            elif m_name == "gate":
                async with session.get(f"{base_url}/api/v4/futures/usdt/contracts", timeout=aiohttp.ClientTimeout(total=6)) as resp:
                    if resp.status == 200:
                        info = await resp.json()
                        if isinstance(info, list):
                            perps, new_set = set(), set()
                            for s in info:
                                name = s.get("name", "")
                                if (
                                    name.endswith("_USDT")
                                    and s.get("status") == "trading"
                                    and not s.get("in_delisting")
                                    and not s.get("is_pre_market")
                                ):
                                    sym = name[:-5] + "USDT"
                                    perps.add(sym)
                                    if int(s.get("create_time", 0) or 0) >= new_cutoff_sec:
                                        new_set.add(sym)
                            if len(perps) >= 100:
                                self._valid_crypto_perps[m_name] = (now, perps)
                                self._new_crypto_perps[m_name] = new_set
                                return perps
        except Exception:
            pass
        return cached_set

    async def fetch_price(self, symbol: str) -> Optional[float]:
        """Быстрое получение живой рыночной цены (mid стакана / mark) с кросс-зеркальной подстраховкой."""
        data = await self._request_with_fallback("price", params={"symbol": symbol})
        if data and isinstance(data, dict):
            try:
                p = float(data.get("price", 0) or 0)
                if p > 0:
                    return p
            except (ValueError, TypeError):
                pass
        saved_idx = self.active_mirror_idx
        now = time.time()
        for alt_idx in range(len(self.mirrors)):
            if alt_idx == saved_idx or now < self._mirror_cooldowns.get(alt_idx, 0.0):
                continue
            try:
                self.active_mirror_idx = alt_idx
                alt_data = await self._request_with_fallback("price", params={"symbol": symbol})
                if alt_data and isinstance(alt_data, dict):
                    p = float(alt_data.get("price", 0) or 0)
                    if p > 0:
                        return p
            except Exception:
                pass
            finally:
                self.active_mirror_idx = saved_idx
        return None

    async def fetch_top_tickers(self, min_vol_usdt: float = config.MIN_24H_VOLUME_USDT, limit: int = config.SCAN_TICKERS_LIMIT) -> List[Dict[str, Any]]:
        """
        Формирует профессиональный радар Охотника за Ракетами (Structural Rocket Radar):
        1. Автоматически адаптирует порог объема при работе через Spot-зеркало (data-api.binance.vision на US сервере Render),
           так как спотовый оборот USDT в 8-10 раз ниже фьючерсного (fapi), сохраняя полный охват 110-120 живых крипто-пар!
        2. Отсекает делистнутые/замороженные пары (closeTime > 5 мин), стейблкоины ($0.97..$1.03 с узким диапазоном) и токенизированные акции (*BUSDT).
        3. Приоритезирует монеты у суточных экстремумов (24h High/Low Proximity) и лидеров ликвидности.
        """
        # Кэш ticker24 на 45 секунд (снижает вес запросов на 80-90%, защищая от HTTP 418/429 на shared IP!)
        now_t = time.time()
        c_mirror, c_ts, c_data = self._ticker24_cache
        if c_data and c_mirror == self.active_mirror_name and (now_t - c_ts) < 45.0:
            data = c_data
        else:
            data = await self._request_with_fallback("ticker24")
            if data and isinstance(data, list):
                self._ticker24_cache = (self.active_mirror_name, now_t, data)
        if not data or not isinstance(data, list):
            return []

        # Адаптация порога ликвидности под активное зеркало + предфильтр ВСЕГО рынка (400-500+ крипто-перпов) за 1 запрос:
        is_spot_mirror = self.is_spot_mirror
        m_name = self.active_mirror_name
        if m_name == "fapi":
            base_min_vol = min(min_vol_usdt, 1_500_000.0)
            hard_floor_vol = 400_000.0
            new_listing_floor = 120_000.0
        elif m_name in ("bybit", "bitget", "okx", "gate"):
            base_min_vol = float(getattr(config, "ALT_FUTURES_MIN_VOL_USDT", 350_000.0))
            hard_floor_vol = 45_000.0
            new_listing_floor = 20_000.0
        else:
            base_min_vol = float(getattr(config, "SPOT_MIRROR_MIN_VOL_USDT", 350_000.0))
            hard_floor_vol = 150_000.0
            new_listing_floor = 80_000.0

        valid_crypto_perps = await self.fetch_valid_crypto_perps() if m_name in ("fapi", "bybit", "bitget", "okx", "gate") else set()
        new_crypto_perps = self._new_crypto_perps.get(m_name, set())
        excluded = getattr(config, "EXCLUDED_TICKERS", set())
        stock_roots = getattr(config, "STOCK_TICKER_ROOTS", set())
        strict = getattr(config, "STRICT_WHITELIST_ONLY", False)
        whitelist = set(getattr(config, "TOP_CRYPTO_UNIVERSE", []))
        max_24h_cap = float(getattr(config, "MAX_24H_CHANGE_CAP", 120.0))
        min_trades = int(getattr(config, "SPOT_MIRROR_MIN_TRADES", 800)) if is_spot_mirror else int(getattr(config, "MIN_24H_TRADES_COUNT", 1500))
        lev_tokens = ("UPUSDT", "DOWNUSDT", "BEARUSDT", "BULLUSDT")
        fiat_commodities = {"XAU", "XAUT", "PAXG", "XAG", "XPT", "XPD", "CL", "BZ", "COPPER", "NATGAS", "EUR", "EURI", "AEUR", "GBP", "AUD", "BRL", "TRY", "JPY"}
        real_crypto_b = {"BNB", "ARB", "SHIB", "1000SHIB", "TRB", "BB", "CKB", "YB", "PHB", "AMB", "BLUR", "BOME", "BONK", "1000BONK"}
        now_ms = int(time.time() * 1000)

        fresh_books: Dict[str, Tuple[float, float]] = {}
        all_clean_tickers = []
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
            if base in stock_roots or base.endswith("STOCK") or (is_spot_mirror and base.endswith("B") and base not in real_crypto_b and base[:-1] in stock_roots):
                continue
            if strict and sym not in whitelist:
                continue

            try:
                close_time_ms = int(item.get("closeTime", 0) or 0)
                if close_time_ms > 0 and (now_ms - close_time_ms) > 300_000:
                    continue

                is_new_pair = sym in new_crypto_perps
                cnt = int(item.get("count", 0) or 0)
                if (not is_new_pair) and cnt > 0 and cnt < min_trades:
                    continue

                vol = float(item.get("quoteVolume", 0) or 0)
                min_needed_vol = new_listing_floor if is_new_pair else hard_floor_vol
                if vol < min_needed_vol:
                    continue
                last_p = float(item.get("lastPrice", 0) or 0)
                if last_p <= 0:
                    continue
                pct = float(item.get("priceChangePercent", 0) or 0)
                high_p = max(float(item.get("highPrice", 0) or 0), last_p)
                low_p = min(float(item.get("lowPrice", 0) or last_p), last_p)

                # Автоматический детектор стейблкоинов ($0.97..$1.03 с узким диапазоном)
                if 0.97 <= last_p <= 1.03 and low_p > 0 and ((high_p - low_p) / low_p) < 0.012:
                    continue

                bid_p = float(item.get("bidPrice", 0) or 0)
                ask_p = float(item.get("askPrice", 0) or 0)
                if bid_p > 0 and ask_p >= bid_p:
                    fresh_books[sym] = (bid_p, ask_p)

                dist_to_high = (high_p - last_p) / max(high_p, 1e-9)
                dist_to_low = (last_p - low_p) / max(last_p, 1e-9)
                prev_p = self._prev_scan_prices.get(sym)
                delta_5m_abs = abs(last_p - prev_p) / max(prev_p, 1e-9) * 100.0 if (prev_p and prev_p > 0) else 0.0
                pct_1h_h = abs(float(item.get("pct_1h_hint", 0) or 0))
                rocket_heat = (abs(pct) + delta_5m_abs * 4.0 + pct_1h_h * 2.0) / max(min(dist_to_high, dist_to_low) * 100.0 + 0.5, 0.5)
                if is_new_pair:
                    rocket_heat *= 1.35  # Приоритет свежим листингам и новым ракетам

                all_clean_tickers.append({
                    "symbol": sym,
                    "price": last_p,
                    "volume_24h": vol,
                    "price_change_24h_pct": pct,
                    "delta_5m_abs": round(delta_5m_abs, 2),
                    "high_24h": high_p,
                    "low_24h": low_p,
                    "dist_to_high_24h": round(dist_to_high, 4),
                    "dist_to_low_24h": round(dist_to_low, 4),
                    "rocket_heat": round(rocket_heat, 3),
                    "is_new_listing": is_new_pair
                })
            except (ValueError, TypeError):
                continue

        if fresh_books:
            self._book_tickers_cache.update(fresh_books)
            self._book_tickers_cache_time = time.time()

        self.last_full_market_count = len(all_clean_tickers)
        for item_p in all_clean_tickers:
            self._prev_scan_prices[item_p["symbol"]] = item_p["price"]

        if not all_clean_tickers:
            return []

        # Приоритетно берем ВСЕ пары из 400-500+ пула с движением (|5m_delta| >= 0.40%, у 24h хай/лоу, новые листинги)
        # и мягко добираем до полного лимита (240+ самых перспективных пар для глубокого 200-свечного разбора!)
        valid_tickers = list(all_clean_tickers)

        # 0. Мгновенные 5m импульсы по ВСЕМ 400-500+ монетам рынка (ловит стартующие ракеты даже с $250K-$1M объема!)
        instant_movers = sorted(
            [x for x in valid_tickers if x.get("delta_5m_abs", 0.0) >= 0.40 or abs(x["price_change_24h_pct"]) >= 4.0],
            key=lambda x: (-x.get("delta_5m_abs", 0.0), -x["rocket_heat"])
        )

        # 1. Горячие LONG ракеты (активный рост + поджатие к хаям)
        breakout_long_pool = [
            x for x in valid_tickers
            if 0.6 <= x["price_change_24h_pct"] <= max_24h_cap and x["dist_to_high_24h"] <= 0.08
        ]
        breakout_long_pool.sort(key=lambda x: (-x["rocket_heat"], x["dist_to_high_24h"], -x["volume_24h"]))

        # 2. Горячие SHORT пробои (активный слив + поджатие к лоям)
        breakdown_short_pool = [
            x for x in valid_tickers
            if -max_24h_cap <= x["price_change_24h_pct"] <= -0.6 and x["dist_to_low_24h"] <= 0.08
        ]
        breakdown_short_pool.sort(key=lambda x: (-x["rocket_heat"], x["dist_to_low_24h"], -x["volume_24h"]))

        # 3. Новые крипто-листинги и взрывные монеты дня (ловит свежие ракеты до раздутия 24ч объема!)
        new_listing_pool = [x for x in valid_tickers if x["is_new_listing"] and abs(x["price_change_24h_pct"]) <= max_24h_cap]
        new_listing_pool.sort(key=lambda x: (-x["rocket_heat"], -x["volume_24h"]))

        # 4. Топ волатильных лидеров дня
        top_movers = sorted(valid_tickers, key=lambda x: abs(x["price_change_24h_pct"]), reverse=True)

        # 5. Топ ликвидности и элитный юниверс
        by_volume = sorted(valid_tickers, key=lambda x: (1 if x["symbol"] in whitelist else 0, x["volume_24h"]), reverse=True)

        combined_dict: Dict[str, Dict[str, Any]] = {}

        # Мгновенные 5m-движения со всего 500-парного рынка
        for item in instant_movers[:max(45, int(limit * 0.22))]:
            combined_dict[item["symbol"]] = item

        # Горячие LONG ракеты у хаев
        for item in breakout_long_pool[:max(45, int(limit * 0.22))]:
            combined_dict[item["symbol"]] = item

        # Горячие SHORT пробои у лоев
        for item in breakdown_short_pool[:max(40, int(limit * 0.18))]:
            combined_dict[item["symbol"]] = item

        # НОВЫЕ ЛИСТИНГИ / innovation-монеты
        for item in new_listing_pool[:max(35, int(limit * 0.15))]:
            combined_dict[item["symbol"]] = item

        # Главные волатильные лидеры дня
        for item in top_movers[:max(40, int(limit * 0.18))]:
            if len(combined_dict) >= limit:
                break
            if abs(item["price_change_24h_pct"]) <= max_24h_cap:
                combined_dict[item["symbol"]] = item

        # Добор до полного limit (240+ самых живых пар): лидеры ликвидности и элита
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

        # Защита от приостановленных/замороженных торгов (2 бара: 30 мин для 15m, 10 мин для 5m)
        stale_ms = 1_800_000 if interval == "15m" else 600_000
        if (int(time.time() * 1000) - candles[-1]["time"]) > stale_ms:
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
        recent_10_vols = [c["quote_vol"] for c in closed_candles[-11:-1]]
        min_recent_5m_qvol = round(min(recent_10_vols), 1) if recent_10_vols else round(avg_vol, 1)

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
        ema12_series = calc_ema_series(closed_closes, min(12, len(closed_closes)))
        ema26_series = calc_ema_series(closed_closes, min(26, len(closed_closes)))
        macd_line_s = [a - b for a, b in zip(ema12_series, ema26_series)]
        macd_sig_s = calc_ema_series(macd_line_s, min(9, len(macd_line_s)))
        macd_hist_s = [m - s for m, s in zip(macd_line_s, macd_sig_s)]
        macd_bull = (macd_line_s[-1] > macd_sig_s[-1]) and (len(macd_hist_s) < 2 or macd_hist_s[-1] > macd_hist_s[-2])
        macd_bear = (macd_line_s[-1] < macd_sig_s[-1]) and (len(macd_hist_s) < 2 or macd_hist_s[-1] < macd_hist_s[-2])

        ema27 = config.round_price(calc_ema(closed_closes, min(27, len(closed_closes))))
        ema63 = config.round_price(calc_ema(closed_closes, min(63, len(closed_closes))))
        ema150 = config.round_price(calc_ema(closed_closes, min(150, len(closed_closes))))
        ema200 = config.round_price(calc_ema(closed_closes, min(200, len(closed_closes))))

        sig_cl = closed_signal_c["close"]
        if sig_cl >= ema63 * 0.998 and ema27 >= ema63 * 0.998 and ema63 >= ema150 * 0.996:
            trend_15m = "BULL"
        elif sig_cl <= ema63 * 1.002 and ema27 <= ema63 * 1.002 and ema63 <= ema150 * 1.004:
            trend_15m = "BEAR"
        else:
            trend_15m = "CHOP"

        # Smart Money Confluence: ADX-14 (сила тренда) + недавний 3-свечной FVG (имбаланс за последние 6 баров) + HTF EMA200
        adx14 = 20.0
        if len(closed_candles) >= 20:
            tr_w, pdm_w, ndm_w = [], [], []
            for j in range(1, len(closed_candles)):
                c_j, c_p = closed_candles[j], closed_candles[j - 1]
                up_m = c_j["high"] - c_p["high"]
                dn_m = c_p["low"] - c_j["low"]
                pdm_w.append(up_m if (up_m > dn_m and up_m > 0) else 0.0)
                ndm_w.append(dn_m if (dn_m > up_m and dn_m > 0) else 0.0)
                tr_w.append(max(c_j["high"] - c_j["low"], abs(c_j["high"] - c_p["close"]), abs(c_j["low"] - c_p["close"])))
            alpha_w = 1.0 / 14.0
            atr_w = tr_w[0]
            p_w = pdm_w[0]
            n_w = ndm_w[0]
            adx_val = 20.0
            for j in range(1, len(tr_w)):
                atr_w = alpha_w * tr_w[j] + (1.0 - alpha_w) * atr_w
                p_w = alpha_w * pdm_w[j] + (1.0 - alpha_w) * p_w
                n_w = alpha_w * ndm_w[j] + (1.0 - alpha_w) * n_w
                if atr_w > 1e-12:
                    pdi = 100.0 * p_w / atr_w
                    ndi = 100.0 * n_w / atr_w
                    dx = 100.0 * abs(pdi - ndi) / max(pdi + ndi, 1e-12)
                    adx_val = alpha_w * dx + (1.0 - alpha_w) * adx_val
            adx14 = round(adx_val, 1)

        has_fvg_bull = any(
            closed_candles[j]["low"] > closed_candles[j - 2]["high"]
            for j in range(max(2, len(closed_candles) - 6), len(closed_candles))
        )
        has_fvg_bear = any(
            closed_candles[j]["high"] < closed_candles[j - 2]["low"]
            for j in range(max(2, len(closed_candles) - 6), len(closed_candles))
        )
        above_ema200 = (sig_cl >= ema200)

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
        # 3-РЕЖИМНЫЙ ALPHA ROCKET & RUG HUNTER ENGINE (7/7 SPLITS VALIDATED):
        # 1) STRUCT_3H: Пробой 36-барного канала Дончиана (3 часа) на RVOL >= 1.8x
        # 2) SQUEEZE_80M: Ранний старт ракеты из узкого сжатия (16 баров <= 6.5%) на RVOL >= 2.0x
        # 3) RUG_SHORT: Слив памповой монеты (после роста >= +15% за 6ч пробой 16-барного лоя и EMA50 на RVOL >= 2.0x)
        # ======================================================================
        lookback = int(getattr(config, "BREAKOUT_LOOKBACK_BARS", 36))
        sq_lb = int(getattr(config, "SQUEEZE_LOOKBACK_BARS", 16))
        sq_max_rng = float(getattr(config, "SQUEEZE_MAX_RANGE_PCT", 0.065))
        sq_min_rvol = float(getattr(config, "SQUEEZE_MIN_RVOL", 2.00))
        min_rvol = float(getattr(config, "MIN_5M_VOLUME_SURGE_RATIO", 1.80))

        struct_slice = closed_candles[-(lookback + 1):-1] if len(closed_candles) > lookback else closed_candles[:-1]
        sq_slice = closed_candles[-(sq_lb + 1):-1] if len(closed_candles) > sq_lb else closed_candles[:-1]
        h6_slice = closed_candles[-73:-1] if len(closed_candles) > 72 else closed_candles[:-1]
        h12_slice = closed_candles[-145:-1] if len(closed_candles) > 144 else closed_candles[:-1]

        donchian_high = max(c["high"] for c in struct_slice)
        donchian_low = min(c["low"] for c in struct_slice)
        sq_high = max(c["high"] for c in sq_slice)
        sq_low = min(c["low"] for c in sq_slice)
        sq_range_pct = (sq_high - sq_low) / max(sq_low, 1e-9)
        high_6h = max(c["high"] for c in h6_slice)
        low_6h = min(c["low"] for c in h6_slice)
        high_12h = max(c["high"] for c in h12_slice)
        low_12h = min(c["low"] for c in h12_slice)
        range_12h_pct = round((high_12h - low_12h) / max(low_12h, 1e-9), 4)
        pos_12h = round((sig_cl - low_12h) / max(high_12h - low_12h, 1e-9), 4)

        is_struct_long = (sig_cl > donchian_high) and (surge_ratio >= min_rvol)
        is_struct_short = (sig_cl < donchian_low) and (surge_ratio >= min_rvol)

        is_squeeze_long = (not is_struct_long) and (sq_range_pct <= sq_max_rng) and (sig_cl > sq_high) and (surge_ratio >= max(min_rvol, sq_min_rvol))
        is_squeeze_short = (not is_struct_short) and (sq_range_pct <= sq_max_rng) and (sig_cl < sq_low) and (surge_ratio >= max(min_rvol, sq_min_rvol))

        # Детектор слива после пампа (Rug-Hunter Short — опирается строго на 6-часовой памп >= +15%)
        is_rug_short = False
        if getattr(config, "ENABLE_RUG_HUNTER_SHORT", True) and not is_struct_short and not is_squeeze_short and len(closed_candles) >= 20:
            rug_lb = int(getattr(config, "RUG_SUPPORT_BARS", 16))
            rug_slice = closed_candles[-(rug_lb + 1):-1] if len(closed_candles) > rug_lb else closed_candles[:-1]
            rug_low_16 = min(c["low"] for c in rug_slice)
            pump_6h = (high_6h - low_6h) / max(low_6h, 1e-9)
            off_high_6h = (high_6h - sig_cl) / max(high_6h, 1e-9)
            if (
                pump_6h >= float(getattr(config, "RUG_PUMP_MIN_PCT", 0.15))
                and 0.03 <= off_high_6h <= 0.22
                and sig_cl < rug_low_16
                and sig_cl < ema50
                and surge_ratio >= 2.00
            ):
                is_rug_short = True
                is_mtf_short_ok = True  # Слом после пампа идет раньше разворота медленной 12-часовой EMA150!

        is_breakout_long = is_struct_long or is_squeeze_long
        is_breakout_short = is_struct_short or is_squeeze_short or is_rug_short

        # ANTI-DOUBLE-TOP / 12H EXHAUSTION WALL GUARD (PF 1.62 -> 1.87, MaxDD 43.7% -> 34.0%):
        # Блокирует повторный заход "на втором круге" прямо под непробитый 12-часовой потолок пампа (Double Top, как IDOL)
        # или шорт отскока прямо над непробитым 12-часовым дном после обвала (Higher Low squeeze, как MMT),
        # но свободно пропускает истинный пробой 12ч хая/лоя И свежие развороты со дна (pos_12h < 0.52) / RUG_SHORT!
        wall_min_rng = float(getattr(config, "WALL_GUARD_MIN_12H_RANGE_PCT", 0.14))
        anti_wall_long_ok = True
        anti_wall_short_ok = True
        if getattr(config, "ENABLE_12H_WALL_GUARD", True) and range_12h_pct >= wall_min_rng:
            dist_to_h12 = (high_12h - sig_cl) / max(sig_cl, 1e-9)
            dist_to_l12 = (sig_cl - low_12h) / max(sig_cl, 1e-9)
            max_wall_l = 0.090 if range_12h_pct >= 0.24 else max(0.035, 1.70 * atr14_pct * 1.75)
            max_wall_s = 0.095 if range_12h_pct >= 0.24 else max(0.035, 1.70 * atr14_pct * 1.75)
            if pos_12h >= 0.55 and 0.0 < dist_to_h12 <= max_wall_l:
                anti_wall_long_ok = False
            if pos_12h <= 0.45 and 0.0 < dist_to_l12 <= max_wall_s and not is_rug_short:
                anti_wall_short_ok = False

        if is_rug_short:
            breakout_type = "RUG_SHORT"
        elif is_squeeze_long or is_squeeze_short:
            breakout_type = "SQUEEZE_80M"
        elif is_struct_long or is_struct_short:
            breakout_type = "STRUCT_3H"
        else:
            breakout_type = "WATCH"

        # Детектор Smart Money + ранних разворотов со дна ("3/7 как #MON": 16b BOS + FVG + MACD + ADX>=20 выше EMA63 даже ДО переворота медленных EMA150/EMA200!)
        swing_12_slice = closed_candles[-13:-1] if len(closed_candles) > 12 else closed_candles[:-1]
        swing_12_low = min(c["low"] for c in swing_12_slice)
        swing_12_high = max(c["high"] for c in swing_12_slice)

        # Детектор снайперского трендового отката к EMA21 после импульса (70%+ WR Pullback Resumption):
        prior_20_qvols = [c["quote_vol"] for c in closed_candles[-21:-1]]
        max_prior_rvol_20 = round(max(prior_20_qvols) / avg_vol, 2) if (prior_20_qvols and avg_vol > 0) else surge_ratio
        pb_slice_4 = closed_candles[-4:] if len(closed_candles) >= 4 else closed_candles
        pb_low_4 = min(c["low"] for c in pb_slice_4)
        pb_high_4 = max(c["high"] for c in pb_slice_4)
        is_pullback_long = (
            len(closed_candles) >= 30
            and max_prior_rvol_20 >= 2.25
            and ema21 > ema63 > ema150
            and sig_cl > ema200
            and pb_low_4 <= ema21 * 1.004
            and pb_low_4 >= ema63 * 0.996
            and sig_cl > closed_signal_c["open"]
            and sig_cl > ema9
            and sig_cl > prev_closed_c["high"]
            and close_strength_long >= 0.72
            and upper_wick_pct <= 0.22
            and 1.15 <= surge_ratio <= 3.50
            and 45.0 <= rsi <= 68.0
            and adx14 >= 22.0
        )
        is_pullback_short = (
            len(closed_candles) >= 30
            and max_prior_rvol_20 >= 2.25
            and ema21 < ema63 < ema150
            and sig_cl < ema200
            and pb_high_4 >= ema21 * 0.996
            and pb_high_4 <= ema63 * 1.004
            and sig_cl < closed_signal_c["open"]
            and sig_cl < ema9
            and sig_cl < prev_closed_c["low"]
            and close_strength_short >= 0.72
            and lower_wick_pct <= 0.22
            and 1.15 <= surge_ratio <= 3.50
            and 32.0 <= rsi <= 55.0
            and adx14 >= 22.0
        )
        if sig_cl >= ema63 * 0.998 and ema27 >= ema63 * 0.998 and has_fvg_bull and macd_bull and adx14 >= 20.0:
            is_mtf_long_ok = True
        if sig_cl <= ema63 * 1.002 and ema27 <= ema63 * 1.002 and has_fvg_bear and macd_bear and adx14 >= 20.0:
            is_mtf_short_ok = True
        sm_bos_long = (sig_cl > sq_high) and has_fvg_bull and (above_ema200 or (sig_cl >= ema63 * 0.998 and macd_bull)) and (adx14 >= 20.0) and (surge_ratio >= 1.50)
        sm_bos_short = (sig_cl < sq_low) and has_fvg_bear and ((not above_ema200) or (sig_cl <= ema63 * 1.002 and macd_bear)) and (adx14 >= 20.0) and (surge_ratio >= 1.50)

        # 15m SMART MONEY 5/7 CONFLUENCE ENGINE (WR 70%, PF 2.02 на Bybit 7D и 8/8 исторических сплитов!):
        # 1. BOS 16 баров (4ч на 15m), 2. HTF EMA200, 3. EMA9 >= EMA21, 4. MACD импульс, 5. ADX>=20 + RSI, + бонусы FVG/ADX24/RVOL2.0 (>= 5/7)
        h48_slice = closed_candles[-49:-1] if len(closed_candles) > 48 else closed_candles[:-1]
        h48_high = max(c["high"] for c in h48_slice)
        h48_low = min(c["low"] for c in h48_slice)
        r48_pct = (h48_high - h48_low) / max(h48_low, 1e-9)
        pos48 = (sig_cl - h48_low) / max(h48_high - h48_low, 1e-9)
        sm15_wall_l = not (r48_pct >= 0.14 and pos48 >= 0.55 and 0.0 < (h48_high - sig_cl) / max(sig_cl, 1e-9) <= 0.045)
        sm15_wall_s = not (r48_pct >= 0.14 and pos48 <= 0.45 and 0.0 < (sig_cl - h48_low) / max(sig_cl, 1e-9) <= 0.045)
        sm15_conf_l = 4 + (1 if has_fvg_bull else 0) + (1 if adx14 >= 24.0 else 0) + (1 if surge_ratio >= 2.0 else 0)
        sm15_conf_s = 4 + (1 if has_fvg_bear else 0) + (1 if adx14 >= 24.0 else 0) + (1 if surge_ratio >= 2.0 else 0)
        sm15_long = (
            sm15_wall_l and (sig_cl > sq_high) and above_ema200
            and (sig_cl > ema9 >= ema21 * 0.998) and macd_bull
            and (adx14 >= 20.0) and (surge_ratio >= 1.50) and (atr14_pct >= 0.0035)
            and (ema21_ext_pct <= 0.055) and (50.0 <= rsi <= 80.0)
            and (close_strength_long >= 0.66) and (upper_wick_pct <= 0.28)
            and (sm15_conf_l >= 5)
        )
        sm15_short = (
            sm15_wall_s and (sig_cl < sq_low) and (not above_ema200)
            and (sig_cl < ema9 <= ema21 * 1.002) and macd_bear
            and (adx14 >= 20.0) and (surge_ratio >= 1.50) and (atr14_pct >= 0.0035)
            and (ema21_ext_pct <= 0.055) and (20.0 <= rsi <= 50.0)
            and (close_strength_short >= 0.66) and (lower_wick_pct <= 0.28)
            and (sm15_conf_s >= 5)
        )
        if interval == "15m":
            is_breakout_long = sm15_long
            is_breakout_short = sm15_short
            breakout_type = "SM_15M" if (sm15_long or sm15_short) else "WATCH"

        target_high_ref = sq_high if sq_range_pct <= sq_max_rng else donchian_high
        target_low_ref = sq_low if sq_range_pct <= sq_max_rng else donchian_low
        ref_price_for_dist = sig_cl
        dist_to_breakout_long_pct = round(max(0.0, (target_high_ref - ref_price_for_dist) / max(ref_price_for_dist, 1e-9) * 100.0), 2)
        dist_to_breakout_short_pct = round(max(0.0, (ref_price_for_dist - target_low_ref) / max(ref_price_for_dist, 1e-9) * 100.0), 2)

        # УМНЫЙ СТРУКТУРНЫЙ СТОП-ЛОСС (1.55 * ATR14 БУФЕР ЗА ФИТИЛЬ/СВИНГ):
        active_sig_c = closed_signal_c
        recent_wick_low = min(prev_closed_c["low"], active_sig_c["low"])
        raw_wick_sl = config.round_price(recent_wick_low * (1.0 - config.WICK_BUFFER_PCT))
        raw_sl_pct = (current_price - raw_wick_sl) / max(current_price, 1e-9)
        max_allowed_sl = float(getattr(config, "STOP_LOSS_MAX_PCT", 0.0450))
        min_allowed_sl = float(getattr(config, "STOP_LOSS_MIN_PCT", 0.0080))
        sl_atr_mult = float(getattr(config, "SL_ATR_MULT", 1.55))

        # ВАЖНО: НЕ зажимаем (не режем min(..., max_allowed_sl)) широкий стоп в воздухе внутри свечи!
        # Возвращаем честную структурную дистанцию до фитиля/свинга, чтобы scanner.py отсекал раздутые свечи > STOP_LOSS_MAX_PCT (3.65%)!
        true_long_sl_pct = round(max(raw_sl_pct, sl_atr_mult * atr14_pct, min_allowed_sl), 4)
        wick_stop_loss = config.round_price(current_price * (1.0 - true_long_sl_pct))
        sm_raw_sl_l = (current_price - swing_12_low * (1.0 - config.WICK_BUFFER_PCT)) / max(current_price, 1e-9)
        sm_long_sl_pct = round(max(sm_raw_sl_l, sl_atr_mult * atr14_pct, min_allowed_sl), 4)
        sm_long_wick_sl = config.round_price(current_price * (1.0 - sm_long_sl_pct))
        pb_raw_sl_l = (current_price - pb_low_4 * (1.0 - config.WICK_BUFFER_PCT)) / max(current_price, 1e-9)
        pb_long_sl_pct = round(max(pb_raw_sl_l, 1.55 * atr14_pct, min_allowed_sl), 4)
        pb_long_wick_sl = config.round_price(current_price * (1.0 - pb_long_sl_pct))

        recent_wick_high = max(prev_closed_c["high"], active_sig_c["high"])
        raw_short_sl = config.round_price(recent_wick_high * (1.0 + config.WICK_BUFFER_PCT))
        raw_short_sl_pct = (raw_short_sl - current_price) / max(current_price, 1e-9)

        true_short_sl_pct = round(max(raw_short_sl_pct, sl_atr_mult * atr14_pct, min_allowed_sl), 4)
        short_wick_stop_loss = config.round_price(current_price * (1.0 + true_short_sl_pct))
        sm_raw_sl_s = (swing_12_high * (1.0 + config.WICK_BUFFER_PCT) - current_price) / max(current_price, 1e-9)
        sm_short_sl_pct = round(max(sm_raw_sl_s, sl_atr_mult * atr14_pct, min_allowed_sl), 4)
        sm_short_wick_sl = config.round_price(current_price * (1.0 + sm_short_sl_pct))
        pb_raw_sl_s = (pb_high_4 * (1.0 + config.WICK_BUFFER_PCT) - current_price) / max(current_price, 1e-9)
        pb_short_sl_pct = round(max(pb_raw_sl_s, 1.55 * atr14_pct, min_allowed_sl), 4)
        pb_short_wick_sl = config.round_price(current_price * (1.0 + pb_short_sl_pct))

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
            "anti_wall_long_ok": anti_wall_long_ok,
            "anti_wall_short_ok": anti_wall_short_ok,
            "high_12h": high_12h,
            "low_12h": low_12h,
            "range_12h_pct": range_12h_pct,
            "pos_12h": pos_12h,
            "ext_prev3_pct": ext_prev3_pct,
            "ret_3h_pct": ret_3h_pct,
            "ema50": ema50,
            "is_macro_trend_long": is_macro_trend_long,
            "is_macro_trend_short": is_macro_trend_short,
            "v3_surge": v3_surge,
            "avg_5m_quote_vol": round(avg_vol, 1),
            "min_recent_5m_qvol": min_recent_5m_qvol,
            "prev_quote_volume": prev_closed_c["quote_vol"],
            "last_quote_volume": active_sig_c["quote_vol"],
            "rsi": rsi,
            "ema9": ema9,
            "ema21": ema21,
            "ema63": ema63,
            "ema150": ema150,
            "ema200": ema200,
            "above_ema200": above_ema200,
            "adx14": adx14,
            "has_fvg_bull": has_fvg_bull,
            "has_fvg_bear": has_fvg_bear,
            "sm_bos_long": sm_bos_long,
            "sm_bos_short": sm_bos_short,
            "sm15_long": sm15_long,
            "sm15_short": sm15_short,
            "sm15_conf_l": sm15_conf_l,
            "sm15_conf_s": sm15_conf_s,
            "macd_bull": macd_bull,
            "macd_bear": macd_bear,
            "sm_long_sl_pct": sm_long_sl_pct,
            "sm_long_wick_sl": sm_long_wick_sl,
            "sm_short_sl_pct": sm_short_sl_pct,
            "sm_short_wick_sl": sm_short_wick_sl,
            "is_pullback_long": is_pullback_long,
            "is_pullback_short": is_pullback_short,
            "pb_long_sl_pct": pb_long_sl_pct,
            "pb_long_wick_sl": pb_long_wick_sl,
            "pb_short_sl_pct": pb_short_sl_pct,
            "pb_short_wick_sl": pb_short_wick_sl,
            "max_prior_rvol_20": max_prior_rvol_20,
            "trend": trend,
            "atr14_pct": atr14_pct,
            "candles": candles
        }

    async def fetch_btc_regime(self) -> Dict[str, Any]:
        """
        Институциональный макро-фильтр рынка по Bitcoin (EMA63 на 5m = 15m EMA21 + импульс).
        Блокирует покупку альтов при падающем BTC (как в 14:30 UTC) и шорты против растущего BTC!
        """
        tf = str(getattr(config, "SCAN_TIMEFRAME", "5m")).strip() or "5m"
        analysis = await self.fetch_candles_analysis("BTCUSDT", interval=tf, limit=100)
        if not analysis:
            return {
                "trend": "CHOP",
                "pct_5m": 0.0,
                "pct_15m": 0.0,
                "rsi": 50.0,
                "is_dumping": False,
                "is_pumping": False,
                "btc_macro_bull": True,
                "btc_macro_bear": True,
                "status_str": "🟡 Нейтральный (BTC спокоен)"
            }

        p5 = analysis.get("pct_5m", 0.0)
        p15 = analysis.get("pct_15m", 0.0)
        sig_cl = float(analysis.get("signal_close", analysis.get("current_price", 0.0)) or 0.0)
        ema_ref = float(analysis.get("ema63" if tf == "5m" else "ema50", sig_cl) or sig_cl)
        trend = analysis.get("trend", "CHOP")
        rsi = analysis.get("rsi", 50.0)

        btc_macro_bull = (sig_cl >= ema_ref * 0.999)
        btc_macro_bear = (sig_cl <= ema_ref * 1.001)

        is_dumping = (p15 <= -0.55) or (p5 <= -0.40)
        is_pumping = (p15 >= +0.55) or (p5 >= +0.40)
        is_flush_down = (p5 <= -0.38) or (p15 <= -0.75)
        is_spike_up = (p5 >= +0.38) or (p15 >= +0.75)

        if is_flush_down:
            status_str = f"🔴 Панический слив BTC ({p5:+.2f}% / 15m {p15:+.2f}%) — Щит от ложных выносов активен!"
        elif is_spike_up:
            status_str = f"🟢 Резкий сквиз BTC ({p5:+.2f}% / 15m {p15:+.2f}%) — Щит от покупки хая активен!"
        elif btc_macro_bull and not btc_macro_bear:
            status_str = f"🟢 Бычий режим BTC (выше 15m EMA21, {p15:+.2f}%) — Активен охотник LONG + RUG_SHORT"
        elif btc_macro_bear and not btc_macro_bull:
            status_str = f"🔴 Медвежий режим BTC (ниже 15m EMA21, {p15:+.2f}%) — Активен охотник SHORT"
        else:
            status_str = f"🟡 Спокойный BTC ({p15:+.2f}%, у 15m EMA21) — Alpha Rocket активен (15 слотов)"

        return {
            "trend": trend,
            "pct_5m": p5,
            "pct_15m": p15,
            "rsi": rsi,
            "ema_ref": ema_ref,
            "btc_macro_bull": btc_macro_bull,
            "btc_macro_bear": btc_macro_bear,
            "is_dumping": is_dumping,
            "is_pumping": is_pumping,
            "is_flush_down": is_flush_down,
            "is_spike_up": is_spike_up,
            "status_str": status_str
        }

    async def fetch_all_book_tickers(self) -> Dict[str, Tuple[float, float]]:
        now = time.time()
        if self._book_tickers_cache and (now - self._book_tickers_cache_time) < 30.0:
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

        item = None
        if isinstance(data, dict):
            item = data
        elif isinstance(data, list):
            item = next((x for x in data if isinstance(x, dict) and x.get("symbol") == symbol), None)
        if not item:
            return 0.0, 0.0, 1.0

        try:
            bid = float(item.get("bidPrice", 0) or 0)
            ask = float(item.get("askPrice", 0) or 0)
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
