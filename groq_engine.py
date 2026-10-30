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
        self.models = [config.GROQ_PRIMARY_MODEL, config.GROQ_FALLBACK_MODEL, "qwen/qwen3.8-27b"]
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
            if now - ts < 300:
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

        if cand_side == "LONG":
            prompt = f"""You are the Lead Risk & Execution Officer at an elite quantitative crypto prop desk.
Analyze this high-momentum breakout candidate for a LONG position on Binance Futures.

RULES OF ENGAGEMENT (OPTIMIZED FOR {lev}x LEVERAGE & EXPLOSIVE ALTS):
1. 'We bid the flush, not the candle': NEVER buy the very top of a candle. An entry on a local pullback (-0.2% to -1.5% from high) is required for a clean risk-managed entry.
2. 'The stop lives under the wick': The stop-loss must be placed right below the lower wick of recent candles ({context.get('wick_stop_loss')}). Because we are running {lev}x leverage, the stop distance MUST be strictly tight (<= {max_sl:.1f}%). If the stop distance is > {max_sl:.1f}%, REJECT it (liquidation prevention).
3. 'Momentum already spent': If price pumped > 15% in 15m with a massive upper wick (> 45%), reject (exhaustion wick/dump risk).
4. Minimum Risk-to-Reward ratio must be at least 1.8 to 1.

CANDIDATE CONTEXT:
- Symbol: {symbol}
- Direction: LONG
- Current Price: ${context.get('current_price')}
- 24h Volume: ${context.get('volume_24h', 0):,.0f}
- 5m Volume Surge vs Avg: {context.get('volume_surge_ratio')}x
- 5m Price Change: {context.get('pct_5m'):+.2f}%
- 15m Price Change: {context.get('pct_15m'):+.2f}%
- Pullback from Recent High: {context.get('pullback_from_high_pct', 0) * 100:+.2f}%
- Upper Wick Ratio: {context.get('upper_wick_pct', 0) * 100:.1f}% (selling pressure at top)
- Lower Wick Ratio: {context.get('lower_wick_pct', 0) * 100:.1f}% (buyers defending dip)
- Suggested Wick SL: ${context.get('wick_stop_loss')} ({context.get('sl_pct_distance', 0) * 100:.2f}% distance)

Respond STRICTLY with a valid JSON object matching this schema, with no preamble or markdown:
{{
  "decision": "BUY" or "SKIP",
  "confidence": float between 0.0 and 1.0,
  "entry_price": float (price to buy, near current or slightly below),
  "stop_loss": float (tight under-wick stop loss, <= {max_sl:.1f}% distance),
  "tp1": float (take profit target 1, approx +1.5% to +2.0%, yielding +{tp1_min_roi}% to +{tp1_max_roi}% ROI on {lev}x),
  "tp2": float (take profit target 2, approx +3.0% to +4.5%, yielding +{tp2_min_roi}% to +{tp2_max_roi}% ROI on {lev}x),
  "reason": "1-2 concise sentences explaining why this passed or was rejected based on wicks and flush"
}}
"""
        else:  # SHORT
            prompt = f"""You are the Lead Risk & Execution Officer at an elite quantitative crypto prop desk.
Analyze this high-momentum breakdown candidate for a SHORT position on Binance Futures.

RULES OF ENGAGEMENT (OPTIMIZED FOR {lev}x LEVERAGE & BREAKDOWNS):
1. 'We sell the bounce, not the bottom': NEVER short the very low of a dump candle. An entry on a local micro-bounce into resistance (+0.2% to +1.5% from low) is required for a clean entry.
2. 'The stop lives above the wick': The stop-loss must be placed right above the upper wick of recent candles ({context.get('short_wick_sl')}). With {lev}x leverage, the stop distance MUST be strictly tight (<= {max_sl:.1f}%). If the stop distance is > {max_sl:.1f}%, REJECT it (liquidation prevention).
3. 'Dump exhaustion': If price already dumped > 15% in 15m with a massive lower wick (> 45%), reject (buyer absorption / bounce risk).
4. Minimum Risk-to-Reward ratio must be at least 1.8 to 1.

CANDIDATE CONTEXT:
- Symbol: {symbol}
- Direction: SHORT
- Current Price: ${context.get('current_price')}
- 24h Volume: ${context.get('volume_24h', 0):,.0f}
- 5m Volume Surge vs Avg: {context.get('volume_surge_ratio')}x
- 5m Price Change: {context.get('pct_5m'):+.2f}%
- 15m Price Change: {context.get('pct_15m'):+.2f}%
- Bounce from Recent Low: {context.get('bounce_from_low_pct', 0) * 100:+.2f}%
- Upper Wick Ratio: {context.get('upper_wick_pct', 0) * 100:.1f}% (sellers dominating top)
- Lower Wick Ratio: {context.get('lower_wick_pct', 0) * 100:.1f}% (buying support at low)
- Suggested Wick SL: ${context.get('short_wick_sl')} ({context.get('short_sl_dist', 0) * 100:.2f}% distance above price)

Respond STRICTLY with a valid JSON object matching this schema, with no preamble or markdown:
{{
  "decision": "SHORT" or "SKIP",
  "confidence": float between 0.0 and 1.0,
  "entry_price": float (price to short, near current or slightly above),
  "stop_loss": float (tight above-wick stop loss, <= {max_sl:.1f}% distance),
  "tp1": float (take profit target 1, approx -1.5% to -2.0% below entry, yielding +{tp1_min_roi}% to +{tp1_max_roi}% ROI on {lev}x),
  "tp2": float (take profit target 2, approx -3.0% to -4.5% below entry, yielding +{tp2_min_roi}% to +{tp2_max_roi}% ROI on {lev}x),
  "reason": "1-2 concise sentences explaining why this passed or was rejected based on wicks and resistance"
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
                "temperature": 0.2,
                "max_tokens": 300
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
        """Резервный алгоритмический скоринг по правилам Grok/JEV (LONG и SHORT)."""
        cand_side = context.get("candidate_side", "LONG")
        price = context.get("current_price", 1.0)
        surge = context.get("volume_surge_ratio", 1.0)
        upper_wick = context.get("upper_wick_pct", 0.0)
        lower_wick = context.get("lower_wick_pct", 0.0)

        score = 0.5
        reasons = []

        if cand_side == "LONG":
            pullback = context.get("pullback_from_high_pct", 0.0)
            sl_pct = context.get("sl_pct_distance", 0.02)
            wick_sl = context.get("wick_stop_loss", price * 0.98)

            if surge >= 2.0:
                score += 0.2
                reasons.append(f"Объемный всплеск {surge}x")
            elif surge >= 1.5:
                score += 0.1

            if upper_wick < 0.35:
                score += 0.1
                reasons.append("Нет сильного давления продавцов на верхушке")
            else:
                score -= 0.25
                reasons.append("Большой верхний фитиль (риск разворота)")

            if -0.025 <= pullback <= -0.002:
                score += 0.15
                reasons.append(f"Здоровый откат ({pullback*100:+.1f}%)")
            elif pullback > -0.001:
                score -= 0.1
                reasons.append("Вход на самом пике без отката")

            if sl_pct <= config.MAX_ALLOWED_SL_PCT:
                score += 0.1
                reasons.append(f"Плотный стоп под фитиль ({sl_pct*100:.1f}%)")
            else:
                score -= 0.2
                reasons.append(f"Стоп слишком широкий ({sl_pct*100:.1f}%)")

            score = min(max(round(score, 2), 0.0), 1.0)
            decision = "BUY" if score >= config.GROQ_MIN_CONFIDENCE else "SKIP"

            return {
                "decision": decision,
                "confidence": score,
                "entry_price": price,
                "stop_loss": wick_sl,
                "tp1": round(price * (1.0 + config.TP1_PCT), 6),
                "tp2": round(price * (1.0 + config.TP2_PCT), 6),
                "reason": "; ".join(reasons)
            }
        else:  # SHORT
            bounce = context.get("bounce_from_low_pct", 0.0)
            short_sl_pct = context.get("short_sl_dist", 0.02)
            short_sl = context.get("short_wick_sl", price * 1.02)

            if surge >= 2.0:
                score += 0.2
                reasons.append(f"Дамп на объеме {surge}x")
            elif surge >= 1.5:
                score += 0.1

            if lower_wick < 0.35:
                score += 0.1
                reasons.append("Покупатели не защищают дно свечи")
            else:
                score -= 0.25
                reasons.append("Большой нижний фитиль (риск отскока)")

            if 0.002 <= bounce <= 0.025:
                score += 0.15
                reasons.append(f"Вход на микро-отскоке в сопротивление (+{bounce*100:.1f}%)")
            elif bounce < 0.001:
                score -= 0.1
                reasons.append("Шорт на самом дне пролива")

            if short_sl_pct <= config.MAX_ALLOWED_SL_PCT:
                score += 0.1
                reasons.append(f"Плотный стоп над фитилем ({short_sl_pct*100:.1f}%)")
            else:
                score -= 0.2
                reasons.append(f"Стоп слишком широкий ({short_sl_pct*100:.1f}%)")

            score = min(max(round(score, 2), 0.0), 1.0)
            decision = "SHORT" if score >= config.GROQ_MIN_CONFIDENCE else "SKIP"

            return {
                "decision": decision,
                "confidence": score,
                "entry_price": price,
                "stop_loss": short_sl,
                "tp1": round(price * (1.0 - config.TP1_PCT), 6),
                "tp2": round(price * (1.0 - config.TP2_PCT), 6),
                "reason": "; ".join(reasons)
            }

# Глобальный инстанс
groq_engine = GroqEngine()
