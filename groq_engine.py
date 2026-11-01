import os
import json
import time
import asyncio
import re
import aiohttp
from typing import Dict, Any, Tuple, Optional
import config
from obsidian_vault import obsidian_vault
from ml_engine import ml_engine

class GroqEngine:
    """
    Интеллектуальный AI-шлюз Groq (Structural Rocket Hunter Engine).
    Согласован со сканером структурных пробоев:
      1. Подтверждает истинные пробои диапазона Дончиана (20 баров) на высоком RVOL (>= 1.8x) и сильном закрытии (CLV >= 68%).
      2. НЕ бракует свежие импульсные пробои из-за RSI 70-85 (на пробое сжатия высокий RSI = сила моментума!).
      3. Отсекает только реальные ловушки распределения (Bull/Bear Trap с длинным встречным фитилем > 28%) и экстремальную перерастяжку от EMA21 (> 3.5%).
    """
    def __init__(self):
        self.api_key = config.GROQ_API_KEY
        self.url = "https://api.groq.com/openai/v1/chat/completions"
        self.models = ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b"]
        self._last_call_ts = 0.0
        self._lock = asyncio.Lock()
        self._model_cooldowns: Dict[str, float] = {}
        self._eval_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
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
        Отправляет структурный пробой на верификацию в Groq (LONG и SHORT).
        Возвращает: (is_approved: bool, evaluation_dict: dict)
        """
        symbol = context.get("symbol", "UNKNOWN")
        cand_side = context.get("candidate_side", "LONG")
        now = time.time()

        cache_key = f"{symbol}_{cand_side}"
        if cache_key in self._eval_cache:
            ts, cached_res = self._eval_cache[cache_key]
            if now - ts < 60:
                expected_dec = "BUY" if cand_side == "LONG" else "SHORT"
                is_app = cached_res.get("decision") == expected_dec and cached_res.get("confidence", 0) >= config.GROQ_MIN_CONFIDENCE
                return is_app, cached_res

        if not self.api_key:
            res = self._algorithmic_eval(context)
            self._eval_cache[cache_key] = (now, res)
            expected_dec = "BUY" if cand_side == "LONG" else "SHORT"
            return res.get("decision") == expected_dec, res

        async with self._lock:
            elapsed = time.time() - self._last_call_ts
            min_interval = 60.0 / config.GROQ_RPM_LIMIT
            if elapsed < min_interval:
                await asyncio.sleep(min_interval - elapsed)
            self._last_call_ts = time.time()

        lev = int(getattr(config, "LEVERAGE", 12))
        rsi_val = context.get("rsi", 50.0)
        trend_val = context.get("trend", "BULLISH")
        cur_p = context.get("current_price", 0)
        vol_surge = context.get("volume_surge_ratio", 1.8)
        p5m = context.get("pct_5m", 0)
        p15m = context.get("pct_15m", 0)
        atr_pct = context.get("atr14_pct", 0.005) * 100.0
        ema21_ext = context.get("ema21_ext_pct", 0.01) * 100.0
        btc_reg = context.get("btc_regime", "Neutral")
        u_wick = context.get("upper_wick_pct", 0) * 100.0
        l_wick = context.get("lower_wick_pct", 0) * 100.0

        token_mem = obsidian_vault.get_token_memory(symbol, cand_side)
        ml_prob_val = context.get("ml_prob")
        if ml_prob_val is None:
            ml_res = ml_engine.evaluate_candidate(context)
            ml_prob_val = ml_res.get("ml_probability", 0.5)
        ml_prob_str = f"Quant ML Win Prob: {int(ml_prob_val * 100)}%"

        if cand_side == "LONG":
            clv_pct = context.get("close_strength_long", 0.75) * 100.0
            sl_price = context.get("wick_stop_loss", cur_p * 0.99)
            sl_dist = context.get("sl_pct_distance", 0.01) * 100.0
            prompt = f"""Evaluate Structural Momentum Breakout LONG for {symbol} on Binance Futures ({lev}x leverage, fixed 2.5% equity risk).
Metrics: Price ${cur_p}, Confirmed 20-bar Range Breakout: YES, 5m RVOL: {vol_surge}x, Close Strength (CLV): {clv_pct:.0f}%, 5m Impulse: {p5m:+.2f}%, 15m: {p15m:+.2f}%, EMA21 Extension: {ema21_ext:.2f}%, RSI14: {rsi_val}, Trend: {trend_val}, Upper/Lower Wick: {u_wick:.1f}%/{l_wick:.1f}%, ATR14: {atr_pct:.2f}%, Structural SL: ${sl_price} ({sl_dist:.2f}%), BTC: {btc_reg}.
Quant & Memory: {ml_prob_str} | {token_mem}
Prop-Desk Rules:
1. Fresh volume breakouts (RVOL >= 1.8x, CLV >= 68%) naturally print RSI 70-85 on ignition — DO NOT reject for RSI <= 86!
2. Approve ("BUY", confidence 0.70-0.92) when volume expansion is strong, upper wick <= 28%, and EMA21 extension <= 3.5%.
3. Reject ("SKIP") ONLY if obvious Bull Trap (upper wick > 28%), extreme late climax (RSI > 86 or EMA21 extension > 3.5%), or BTC is dumping.
Return ONLY valid JSON matching exact keys:
{{"trap_risk": false, "decision": "BUY", "confidence": 0.78, "reason": "Concise 1-sentence prop-trader thesis in Russian"}}"""
        else:
            clv_pct = context.get("close_strength_short", 0.75) * 100.0
            sl_price = context.get("short_wick_stop_loss", cur_p * 1.01)
            sl_dist = context.get("short_sl_pct_distance", 0.01) * 100.0
            prompt = f"""Evaluate Structural Momentum Breakdown SHORT for {symbol} on Binance Futures ({lev}x leverage, fixed 2.5% equity risk).
Metrics: Price ${cur_p}, Confirmed 20-bar Range Breakdown: YES, 5m RVOL: {vol_surge}x, Bear Close Strength: {clv_pct:.0f}%, 5m Impulse: {p5m:+.2f}%, 15m: {p15m:+.2f}%, EMA21 Extension: {ema21_ext:.2f}%, RSI14: {rsi_val}, Trend: {trend_val}, Upper/Lower Wick: {u_wick:.1f}%/{l_wick:.1f}%, ATR14: {atr_pct:.2f}%, Structural SL: ${sl_price} ({sl_dist:.2f}%), BTC: {btc_reg}.
Quant & Memory: {ml_prob_str} | {token_mem}
Prop-Desk Rules:
1. Fresh breakdowns (RVOL >= 1.8x, Bear Close Strength >= 68%) naturally print RSI 15-30 on ignition — DO NOT reject for RSI >= 14!
2. Approve ("SHORT", confidence 0.70-0.92) when breakdown volume is real, lower wick <= 28%, and EMA21 extension <= 3.5%.
3. Reject ("SKIP") ONLY if obvious Bear Trap absorption (lower wick > 28%), extreme late exhaustion (RSI < 14 or EMA21 extension > 3.5%), or BTC is pumping.
Return ONLY valid JSON matching exact keys:
{{"trap_risk": false, "decision": "SHORT", "confidence": 0.78, "reason": "Concise 1-sentence prop-trader thesis in Russian"}}"""

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Groq Rocket Hunter)"
        }

        eval_result = None
        for model in self.models:
            if now < self._model_cooldowns.get(model, 0.0):
                continue

            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": "You are a quantitative crypto momentum trader. Respond strictly with a single JSON object containing keys: trap_risk (boolean), decision (string: BUY, SHORT, or SKIP), confidence (number 0..1), reason (string in Russian)."},
                    {"role": "user", "content": prompt}
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.1,
                "max_tokens": 350
            }

            try:
                timeout = aiohttp.ClientTimeout(total=8)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(self.url, headers=headers, json=payload) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            choice = data.get("choices", [{}])[0]
                            content = choice.get("message", {}).get("content", "")
                            finish_reason = choice.get("finish_reason", "unknown")
                            parsed = self._clean_json_response(content)
                            if parsed and "decision" in parsed:
                                eval_result = parsed
                                eval_result["model"] = model
                                eval_result["finish_reason"] = finish_reason
                                print(f"🧠 [Groq API 200] {model} оценил {symbol}: {parsed.get('decision')} (conf: {parsed.get('confidence')})", flush=True)
                                break
                            else:
                                print(f"⚠️ [Groq API Warning] {model} вернул невалидный JSON: {content[:100]}", flush=True)
                        elif resp.status == 429:
                            err_txt = await resp.text()
                            self._model_cooldowns[model] = time.time() + 90.0
                            print(f"⚠️ [Groq API 429] Rate limit на {model} (кулдаун 90с): {err_txt[:80]}", flush=True)
                            continue
                        else:
                            err_txt = await resp.text()
                            print(f"⚠️ [Groq API Error {resp.status}] {model}: {err_txt[:100]}", flush=True)
                            continue
            except Exception as e:
                print(f"⚠️ [Groq Connection Error] {model}: {e}", flush=True)
                continue

        if not eval_result:
            print(f"⚠️ [Groq Fallback] Модели недоступны для {symbol}, применен институциональный алгоритм пробоя", flush=True)
            eval_result = self._algorithmic_eval(context)
            eval_result["model"] = "algorithmic_fallback"
            eval_result["finish_reason"] = "fallback"

        eval_result["timestamp"] = now
        eval_result["symbol"] = symbol
        eval_result["side"] = cand_side
        self._eval_cache[cache_key] = (now, eval_result)
        self.calls_count += 1

        expected_decision = "BUY" if cand_side == "LONG" else "SHORT"
        sl_key = "sl_pct_distance" if cand_side == "LONG" else "short_sl_dist"

        is_approved = (
            eval_result.get("decision") == expected_decision and
            not eval_result.get("trap_risk", False) and
            float(eval_result.get("confidence", 0)) >= config.GROQ_MIN_CONFIDENCE and
            float(context.get(sl_key, 0)) <= config.MAX_ALLOWED_SL_PCT
        )

        if is_approved:
            self.approved_count += 1
        else:
            self.rejected_count += 1

        return is_approved, eval_result

    def _algorithmic_eval(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Согласованный алгоритмический скоринг Structural Rocket Hunter (LONG и SHORT)."""
        cand_side = context.get("candidate_side", "LONG")
        price = context.get("current_price", 1.0)
        surge = context.get("volume_surge_ratio", 1.8)
        upper_wick = context.get("upper_wick_pct", 0.0)
        lower_wick = context.get("lower_wick_pct", 0.0)
        rsi = context.get("rsi", 55.0)
        ema21_ext = context.get("ema21_ext_pct", 0.01)

        if cand_side == "LONG":
            sl_pct = context.get("sl_pct_distance", 0.01)
            wick_sl = context.get("wick_stop_loss", price * 0.99)
            clv = context.get("close_strength_long", 0.70)

            if sl_pct > config.MAX_ALLOWED_SL_PCT:
                return {"trap_risk": True, "decision": "SKIP", "confidence": 0.20, "entry_price": price, "stop_loss": wick_sl,
                        "reason": f"Отказ: структурный стоп {sl_pct*100:.2f}% шире лимита {config.MAX_ALLOWED_SL_PCT*100:.1f}%."}
            if rsi > config.MAX_RSI_LONG or ema21_ext > config.MAX_EMA21_EXTENSION_PCT:
                return {"trap_risk": True, "decision": "SKIP", "confidence": 0.25, "entry_price": price, "stop_loss": wick_sl,
                        "reason": f"Отказ: актив перегрет от EMA21 ({ema21_ext*100:.2f}%) или RSI {rsi:.1f} > {config.MAX_RSI_LONG}."}
            if upper_wick > config.WICK_EXHAUSTION_MAX or clv < config.MIN_CLOSE_STRENGTH:
                return {"trap_risk": True, "decision": "SKIP", "confidence": 0.25, "entry_price": price, "stop_loss": wick_sl,
                        "reason": f"Отказ: слабая сила закрытия ({clv*100:.0f}%) или верхний фитиль продавцов {upper_wick*100:.0f}%."}

            score = 0.72
            if surge >= 2.20:
                score += 0.10
            if clv >= 0.80:
                score += 0.08
            if context.get("ml_prob", 0.5) >= 0.55:
                score += 0.05
            score = min(round(score, 2), 0.95)

            return {
                "trap_risk": False,
                "decision": "BUY" if score >= config.GROQ_MIN_CONFIDENCE else "SKIP",
                "confidence": score,
                "entry_price": price,
                "stop_loss": wick_sl,
                "reason": f"Структурный пробой 20-барного хая LONG: RVOL {surge:.2f}x, закрытие в топ-{100-int(clv*100)}% свечи, стоп {sl_pct*100:.2f}%."
            }

        else:
            short_sl_pct = context.get("short_sl_dist", 0.01)
            short_sl = context.get("short_wick_sl", price * 1.01)
            clv = context.get("close_strength_short", 0.70)

            if short_sl_pct > config.MAX_ALLOWED_SL_PCT:
                return {"trap_risk": True, "decision": "SKIP", "confidence": 0.20, "entry_price": price, "stop_loss": short_sl,
                        "reason": f"Отказ: структурный стоп {short_sl_pct*100:.2f}% шире лимита {config.MAX_ALLOWED_SL_PCT*100:.1f}%."}
            if rsi < config.MIN_RSI_SHORT or ema21_ext > config.MAX_EMA21_EXTENSION_PCT:
                return {"trap_risk": True, "decision": "SKIP", "confidence": 0.25, "entry_price": price, "stop_loss": short_sl,
                        "reason": f"Отказ: актив перерастянут вниз ({ema21_ext*100:.2f}% от EMA21) или RSI {rsi:.1f} < {config.MIN_RSI_SHORT}."}
            if lower_wick > config.WICK_EXHAUSTION_MAX or clv < config.MIN_CLOSE_STRENGTH:
                return {"trap_risk": True, "decision": "SKIP", "confidence": 0.25, "entry_price": price, "stop_loss": short_sl,
                        "reason": f"Отказ: откуп снизу (нижний фитиль {lower_wick*100:.0f}%, сила закрытия {clv*100:.0f}%)."}

            score = 0.72
            if surge >= 2.20:
                score += 0.10
            if clv >= 0.80:
                score += 0.08
            if context.get("ml_prob", 0.5) >= 0.55:
                score += 0.05
            score = min(round(score, 2), 0.95)

            return {
                "trap_risk": False,
                "decision": "SHORT" if score >= config.GROQ_MIN_CONFIDENCE else "SKIP",
                "confidence": score,
                "entry_price": price,
                "stop_loss": short_sl,
                "reason": f"Структурный пробой поддержки SHORT: RVOL {surge:.2f}x, закрытие у лоя ({int(clv*100)}%), стоп {short_sl_pct*100:.2f}%."
            }

groq_engine = GroqEngine()
