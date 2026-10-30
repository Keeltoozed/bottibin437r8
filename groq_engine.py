import os
import json
import time
import asyncio
import re
import aiohttp
from typing import Dict, Any, Tuple, Optional
import config

class GroqEngine:
    """
    Интеллектуальный AI-шлюз Groq (JEV Engine).
    Анализирует контекст рынка, подтверждает сетапы (LONG и SHORT) и фильтрует сделки по правилам:
      1. 'We bid the flush, not the candle' (для LONG: вход на откате -0.2%..-1.5% от хая).
      2. 'We sell the bounce, not the drop' (для SHORT: вход на микро-отскоке +0.2%..+1.5% в сопротивление).
      3. 'The stop lives under/above the wick' (динамический стоп за фитиль, <= 1.2% на 60x).
      4. Оценка риска 'Momentum already spent' (проверка, не выдохся ли импульс / пролив).
    """
    def __init__(self):
        self.api_key = config.GROQ_API_KEY
        self.url = "https://api.groq.com/openai/v1/chat/completions"
        self.models = ["qwen/qwen3.8-27b", config.GROQ_PRIMARY_MODEL, config.GROQ_FALLBACK_MODEL, "openai/gpt-oss-120b"]
        self._last_call_ts = 0.0
        self._lock = asyncio.Lock()
        self._eval_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}  # {symbol_side: (ts, result)}
        self.calls_count = 0
        self.approved_count = 0
        self.rejected_count = 0

    def _clean_json_response(self, text: str) -> Optional[Dict[str, Any]]:
        """Очищает ответ модели от markdown-тегов и парсит JSON."""
        if not text:
            return None
        text = text.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
        text = re.sub(r"\s*```$", "", text, flags=re.MULTILINE)
        try:
            return json.loads(text)
        except Exception:
            m = re.search(r"\{.*\}", text, flags=re.DOTALL)
            if m:
                try:
                    return json.loads(m.group(0))
                except Exception:
                    pass
        return None

    async def evaluate_setup(self, context: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """
        Отправляет сетап на анализ в Groq (поддержка LONG и SHORT).
        Возвращает: (is_approved: bool, evaluation_dict: dict)
        """
        symbol = context.get("symbol", "UNKNOWN")
        cand_side = context.get("candidate_side", "LONG")
        now = time.time()

        cache_key = f"{symbol}_{cand_side}"
        if cache_key in self._eval_cache:
            ts, cached_res = self._eval_cache[cache_key]
            if now - ts < 600:  # 10 минут кеширования для экономии токенов и фокуса
                expected_dec = "BUY" if cand_side == "LONG" else "SHORT"
                is_app = cached_res.get("decision") == expected_dec and cached_res.get("confidence", 0) >= config.GROQ_MIN_CONFIDENCE
                return is_app, cached_res

        if not self.api_key:
            res = self._algorithmic_eval(context)
            self._eval_cache[cache_key] = (now, res)
            expected_dec = "BUY" if cand_side == "LONG" else "SHORT"
            is_app = res.get("decision") == expected_dec
            return is_app, res

        async with self._lock:
            elapsed = time.time() - self._last_call_ts
            min_interval = 60.0 / config.GROQ_RPM_LIMIT
            if elapsed < min_interval:
                await asyncio.sleep(min_interval - elapsed)
            self._last_call_ts = time.time()

        lev = int(getattr(config, "LEVERAGE", 60))
        max_sl = config.MAX_ALLOWED_SL_PCT * 100.0
        tp1_min_roi = int(1.5 * lev)
        tp1_max_roi = int(2.0 * lev)
        tp2_min_roi = int(3.0 * lev)
        tp2_max_roi = int(4.5 * lev)

        rsi_val = context.get('rsi', 50.0)
        trend_val = context.get('trend', 'CHOP')
        ema9_val = context.get('ema9', 0)
        ema21_val = context.get('ema21', 0)

        if cand_side == "LONG":
            prompt = f"""You are the Chief Investment Officer at an institutional crypto prop desk evaluating a 60x leverage LONG on Binance Futures.

RULES OF ENGAGEMENT ({lev}x LEVERAGE - STRICT INSTITUTIONAL DISCIPLINE):
1. NO FOMO: Entry MUST be on a pullback (-0.2% to -2.0% from high). NEVER buy candle high.
2. STOP DISTANCE: Stop-loss under wick ({context.get('wick_stop_loss')}) MUST be <= {max_sl:.1f}% (liquidation prevention).
3. RSI HEALTH: 40 <= RSI <= 70. Reject if RSI > 70 (exhaustion).
4. TREND: Trend must be Bullish or healthy consolidation. Reject Bearish downtrend.
5. Minimum Risk-to-Reward ratio must be at least 2.0 to 1.

CANDIDATE CONTEXT:
- Symbol: {symbol} | Direction: LONG | Price: ${context.get('current_price')}
- 5m Volume Surge: {context.get('volume_surge_ratio')}x | 5m Move: {context.get('pct_5m'):+.2f}% | 15m Move: {context.get('pct_15m'):+.2f}%
- Pullback from High: {context.get('pullback_from_high_pct', 0) * 100:+.2f}%
- RSI(14): {rsi_val} | Trend: {trend_val} (EMA9: {ema9_val}, EMA21: {ema21_val})
- Upper Wick: {context.get('upper_wick_pct', 0) * 100:.1f}% | Lower Wick: {context.get('lower_wick_pct', 0) * 100:.1f}% (buyer defense)
- Suggested Wick SL: ${context.get('wick_stop_loss')} ({context.get('sl_pct_distance', 0) * 100:.2f}% distance)

Respond STRICTLY with raw valid JSON:
{{
  "decision": "BUY" or "SKIP",
  "confidence": float (0.0 to 1.0, >= 0.75 for approval),
  "entry_price": float (price to buy),
  "stop_loss": float (tight under-wick stop loss, <= {max_sl:.1f}% distance),
  "tp1": float (approx +1.5% to +2.0%, yielding +{tp1_min_roi}% to +{tp1_max_roi}% ROI on {lev}x),
  "tp2": float (approx +3.0% to +4.5%, yielding +{tp2_min_roi}% to +{tp2_max_roi}% ROI on {lev}x),
  "reason": "1-2 sharp sentences of institutional trade thesis covering structure, RSI, and wick defense"
}}
"""
        else:  # SHORT
            prompt = f"""You are the Chief Investment Officer at an institutional crypto prop desk evaluating a 60x leverage SHORT on Binance Futures.

RULES OF ENGAGEMENT ({lev}x LEVERAGE - STRICT INSTITUTIONAL DISCIPLINE):
1. NO SELLING FLOORS: Entry MUST be on a micro-bounce into resistance (+0.2% to +2.0% from low). NEVER short the lowest tick.
2. STOP DISTANCE: Stop-loss above wick ({context.get('short_wick_sl')}) MUST be <= {max_sl:.1f}% (liquidation prevention).
3. RSI HEALTH: 30 <= RSI <= 60. Reject if RSI < 30 (extreme oversold flush / short squeeze risk).
4. TREND: Trend must be Bearish or breakdown. Reject Bullish uptrend.
5. Minimum Risk-to-Reward ratio must be at least 2.0 to 1.

CANDIDATE CONTEXT:
- Symbol: {symbol} | Direction: SHORT | Price: ${context.get('current_price')}
- 5m Volume Surge: {context.get('volume_surge_ratio')}x | 5m Move: {context.get('pct_5m'):+.2f}% | 15m Move: {context.get('pct_15m'):+.2f}%
- Bounce from Low: +{context.get('bounce_from_low_pct', 0) * 100:.2f}%
- RSI(14): {rsi_val} | Trend: {trend_val} (EMA9: {ema9_val}, EMA21: {ema21_val})
- Upper Wick: {context.get('upper_wick_pct', 0) * 100:.1f}% (sellers defending) | Lower Wick: {context.get('lower_wick_pct', 0) * 100:.1f}%
- Suggested Wick SL: ${context.get('short_wick_sl')} ({context.get('short_sl_dist', 0) * 100:.2f}% distance above price)

Respond STRICTLY with raw valid JSON:
{{
  "decision": "SHORT" or "SKIP",
  "confidence": float (0.0 to 1.0, >= 0.75 for approval),
  "entry_price": float (price to short),
  "stop_loss": float (tight above-wick stop loss, <= {max_sl:.1f}% distance),
  "tp1": float (approx -1.5% to -2.0%, yielding +{tp1_min_roi}% to +{tp1_max_roi}% ROI on {lev}x),
  "tp2": float (approx -3.0% to -4.5%, yielding +{tp2_min_roi}% to +{tp2_max_roi}% ROI on {lev}x),
  "reason": "1-2 sharp sentences of institutional trade thesis covering structure, RSI, and wick rejection"
}}
"""

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Groq JEV Engine)"
        }

        eval_result = None
        for model in self.models:
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": "You are a professional prop trading execution model. You output only raw valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.1,
                "max_tokens": 180
            }

            try:
                timeout = aiohttp.ClientTimeout(total=8)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(self.url, headers=headers, json=payload) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            content = data["choices"][0]["message"]["content"]
                            parsed = self._clean_json_response(content)
                            if parsed and "decision" in parsed:
                                eval_result = parsed
                                eval_result["model"] = model
                                break
                        elif resp.status == 429:
                            continue
            except Exception as e:
                continue

        if not eval_result:
            eval_result = self._algorithmic_eval(context)
            eval_result["model"] = "algorithmic_fallback"

        eval_result["timestamp"] = now
        eval_result["symbol"] = symbol
        eval_result["side"] = cand_side
        self._eval_cache[cache_key] = (now, eval_result)
        self.calls_count += 1

        expected_decision = "BUY" if cand_side == "LONG" else "SHORT"
        sl_key = "sl_pct_distance" if cand_side == "LONG" else "short_sl_dist"

        is_approved = (
            eval_result.get("decision") == expected_decision and
            float(eval_result.get("confidence", 0)) >= config.GROQ_MIN_CONFIDENCE and
            float(context.get(sl_key, 0)) <= config.MAX_ALLOWED_SL_PCT
        )

        if is_approved:
            self.approved_count += 1
        else:
            self.rejected_count += 1

        return is_approved, eval_result

    def _algorithmic_eval(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Институциональный алгоритмический скоринг по дисциплине Day-Trader (LONG и SHORT)."""
        cand_side = context.get("candidate_side", "LONG")
        price = context.get("current_price", 1.0)
        surge = context.get("volume_surge_ratio", 1.0)
        upper_wick = context.get("upper_wick_pct", 0.0)
        lower_wick = context.get("lower_wick_pct", 0.0)
        rsi = context.get("rsi", 50.0)
        trend = context.get("trend", "CHOP")

        if cand_side == "LONG":
            pullback = context.get("pullback_from_high_pct", 0.0)
            sl_pct = context.get("sl_pct_distance", 0.02)
            wick_sl = context.get("wick_stop_loss", price * 0.988)

            # 1. ЖЕСТКИЕ ПРАВИЛА ОТСЕВА МУСОРА (INSTANT REJECTION)
            if pullback > -config.MIN_PULLBACK_PCT:
                return {
                    "decision": "SKIP", "confidence": 0.20, "entry_price": price, "stop_loss": wick_sl,
                    "tp1": round(price * (1.0 + config.TP1_PCT), 6), "tp2": round(price * (1.0 + config.TP2_PCT), 6),
                    "reason": f"Отказ (FOMO): покупка на хае свечи (откат {pullback*100:+.2f}% < 0.2%). Нужна коррекция к поддержке."
                }
            if sl_pct > config.MAX_ALLOWED_SL_PCT:
                return {
                    "decision": "SKIP", "confidence": 0.20, "entry_price": price, "stop_loss": wick_sl,
                    "tp1": round(price * (1.0 + config.TP1_PCT), 6), "tp2": round(price * (1.0 + config.TP2_PCT), 6),
                    "reason": f"Отказ: стоп {sl_pct*100:.2f}% шире лимита {config.MAX_ALLOWED_SL_PCT*100:.1f}% для 60x (риск ликвидации)."
                }
            if rsi > config.MAX_RSI_LONG:
                return {
                    "decision": "SKIP", "confidence": 0.20, "entry_price": price, "stop_loss": wick_sl,
                    "tp1": round(price * (1.0 + config.TP1_PCT), 6), "tp2": round(price * (1.0 + config.TP2_PCT), 6),
                    "reason": f"Отказ: RSI {rsi:.1f} > {config.MAX_RSI_LONG} (экстремальная перекупленность, риск резкого дампа)."
                }
            if upper_wick >= 0.35:
                return {
                    "decision": "SKIP", "confidence": 0.20, "entry_price": price, "stop_loss": wick_sl,
                    "tp1": round(price * (1.0 + config.TP1_PCT), 6), "tp2": round(price * (1.0 + config.TP2_PCT), 6),
                    "reason": f"Отказ: массивный верхний фитиль {upper_wick*100:.0f}% (сильное давление продавцов на вершине)."
                }
            if trend == "BEARISH":
                return {
                    "decision": "SKIP", "confidence": 0.20, "entry_price": price, "stop_loss": wick_sl,
                    "tp1": round(price * (1.0 + config.TP1_PCT), 6), "tp2": round(price * (1.0 + config.TP2_PCT), 6),
                    "reason": "Отказ: попытка лонга против нисходящего тренда (Price < EMA9 < EMA21)."
                }

            # 2. ПОДТВЕРЖДЕНИЕ КАЧЕСТВЕННОГО А+ ВХОДА
            score = 0.70
            if surge >= 2.0:
                score += 0.12
            if lower_wick >= 0.25:
                score += 0.08
            if trend == "BULLISH":
                score += 0.08

            score = min(round(score, 2), 0.95)
            decision = "BUY" if score >= config.GROQ_MIN_CONFIDENCE else "SKIP"

            return {
                "decision": decision,
                "confidence": score,
                "entry_price": price,
                "stop_loss": wick_sl,
                "tp1": round(price * (1.0 + config.TP1_PCT), 6),
                "tp2": round(price * (1.0 + config.TP2_PCT), 6),
                "reason": f"Институциональный LONG (A+): откат {pullback*100:+.1f}% к поддержке | RSI {rsi:.1f} (здоровый запас хода) | Выкуп фитиля {lower_wick*100:.0f}% | Стоп {sl_pct*100:.2f}%"
            }

        else:  # SHORT
            bounce = context.get("bounce_from_low_pct", 0.0)
            short_sl_pct = context.get("short_sl_dist", 0.02)
            short_sl = context.get("short_wick_sl", price * 1.012)

            # 1. ЖЕСТКИЕ ПРАВИЛА ОТСЕВА МУСОРА (INSTANT REJECTION)
            if bounce < config.MIN_PULLBACK_PCT:
                return {
                    "decision": "SKIP", "confidence": 0.20, "entry_price": price, "stop_loss": short_sl,
                    "tp1": round(price * (1.0 - config.TP1_PCT), 6), "tp2": round(price * (1.0 - config.TP2_PCT), 6),
                    "reason": f"Отказ (Bottom Short): цена на самом дне дампа (отскок +{bounce*100:.2f}% < 0.2%). Нужен тест сопротивления."
                }
            if short_sl_pct > config.MAX_ALLOWED_SL_PCT:
                return {
                    "decision": "SKIP", "confidence": 0.20, "entry_price": price, "stop_loss": short_sl,
                    "tp1": round(price * (1.0 - config.TP1_PCT), 6), "tp2": round(price * (1.0 - config.TP2_PCT), 6),
                    "reason": f"Отказ: стоп {short_sl_pct*100:.2f}% шире лимита {config.MAX_ALLOWED_SL_PCT*100:.1f}% для 60x (риск ликвидации)."
                }
            if rsi < config.MIN_RSI_SHORT:
                return {
                    "decision": "SKIP", "confidence": 0.20, "entry_price": price, "stop_loss": short_sl,
                    "tp1": round(price * (1.0 - config.TP1_PCT), 6), "tp2": round(price * (1.0 - config.TP2_PCT), 6),
                    "reason": f"Отказ: RSI {rsi:.1f} < {config.MIN_RSI_SHORT} (экстремальная перепроданность, высокий риск резкого отскока)."
                }
            if lower_wick >= 0.35:
                return {
                    "decision": "SKIP", "confidence": 0.20, "entry_price": price, "stop_loss": short_sl,
                    "tp1": round(price * (1.0 - config.TP1_PCT), 6), "tp2": round(price * (1.0 - config.TP2_PCT), 6),
                    "reason": f"Отказ: массивный нижний фитиль {lower_wick*100:.0f}% (покупатели активно поглощают пролив на дне)."
                }
            if trend == "BULLISH":
                return {
                    "decision": "SKIP", "confidence": 0.20, "entry_price": price, "stop_loss": short_sl,
                    "tp1": round(price * (1.0 - config.TP1_PCT), 6), "tp2": round(price * (1.0 - config.TP2_PCT), 6),
                    "reason": "Отказ: попытка шортить восходящий тренд (Price > EMA9 > EMA21)."
                }

            # 2. ПОДТВЕРЖДЕНИЕ КАЧЕСТВЕННОГО А+ ВХОДА
            score = 0.70
            if surge >= 2.0:
                score += 0.12
            if upper_wick >= 0.25:
                score += 0.08
            if trend == "BEARISH":
                score += 0.08

            score = min(round(score, 2), 0.95)
            decision = "SHORT" if score >= config.GROQ_MIN_CONFIDENCE else "SKIP"

            return {
                "decision": decision,
                "confidence": score,
                "entry_price": price,
                "stop_loss": short_sl,
                "tp1": round(price * (1.0 - config.TP1_PCT), 6),
                "tp2": round(price * (1.0 - config.TP2_PCT), 6),
                "reason": f"Институциональный SHORT (A+): отскок +{bounce*100:.1f}% в сопротивление | RSI {rsi:.1f} (запас падения) | Продавцы защищают хай {upper_wick*100:.0f}% | Стоп {short_sl_pct*100:.2f}%"
            }

# Глобальный инстанс
groq_engine = GroqEngine()
