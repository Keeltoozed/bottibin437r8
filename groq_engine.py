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
        self.models = ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b"]
        self._last_call_ts = 0.0
        self._lock = asyncio.Lock()
        self._model_cooldowns: Dict[str, float] = {}  # {model_name: cooldown_until_ts}
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
            if now - ts < 60:  # 60 секунд кеширования (1 цикл сканирования, чтобы не пропускать свежие сетапы)
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

        cur_p = context.get('current_price', 0)
        vol_surge = context.get('volume_surge_ratio', 1.0)
        p5m = context.get('pct_5m', 0)
        p15m = context.get('pct_15m', 0)
        atr_pct = context.get('atr14_pct', 0.004) * 100.0
        btc_reg = context.get('btc_regime', 'Neutral')
        u_wick = context.get('upper_wick_pct', 0) * 100.0
        l_wick = context.get('lower_wick_pct', 0) * 100.0

        # Получаем память актива из Obsidian и скоринг Quant ML
        token_mem = obsidian_vault.get_token_memory(symbol, cand_side)
        ml_res = ml_engine.evaluate_candidate(context)
        ml_prob_str = f"ML Win Prob: {int(ml_res['ml_probability']*100)}%" if ml_res.get('ml_active') else "ML: Standby"

        if cand_side == "LONG":
            pullback_pct = context.get('pullback_from_high_pct', 0) * 100.0
            sl_price = context.get('wick_stop_loss', cur_p * 0.99)
            sl_dist = context.get('sl_pct_distance', 0.008) * 100.0
            prompt = f"""Evaluate LONG Breakout & Retest setup for {symbol} on Binance Futures ({lev}x leverage).
Metrics: Price ${cur_p}, 5m Vol: {vol_surge}x, 5m: {p5m:+.2f}%, 15m: {p15m:+.2f}%, Pullback: {pullback_pct:+.2f}%, RSI14: {rsi_val}, Trend: {trend_val}, Wick U/L: {u_wick:.1f}%/{l_wick:.1f}%, ATR: {atr_pct:.2f}%, BTC: {btc_reg}, SL: ${sl_price} ({sl_dist:.2f}% dist).
Quant & Memory: {ml_prob_str} | {token_mem}
Rules: Approve (BUY) if volume conviction is real (surge >= 1.25x), candle shows solid momentum without exhaustion (upper wick <= 38%), and not overbought (RSI <= 75). Reject (SKIP) only if massive exhaustion wick > 40% or obvious bear divergence.
Output JSON:
{{"trap_risk": bool, "decision": "BUY"|"SKIP", "confidence": float, "entry_price": float, "stop_loss": float, "tp1": float, "tp2": float, "reason": "1-2 sentences with trade thesis"}}"""
        else:
            bounce_pct = context.get('bounce_from_low_pct', 0) * 100.0
            sl_price = context.get('short_wick_stop_loss', cur_p * 1.01)
            sl_dist = context.get('short_sl_pct_distance', 0.008) * 100.0
            prompt = f"""Evaluate SHORT Breakdown setup for {symbol} on Binance Futures ({lev}x leverage).
Metrics: Price ${cur_p}, 5m Vol: {vol_surge}x, 5m: {p5m:+.2f}%, 15m: {p15m:+.2f}%, Bounce: +{bounce_pct:.2f}%, RSI14: {rsi_val}, Trend: {trend_val}, Wick U/L: {u_wick:.1f}%/{l_wick:.1f}%, ATR: {atr_pct:.2f}%, BTC: {btc_reg}, SL: ${sl_price} ({sl_dist:.2f}% dist).
Quant & Memory: {ml_prob_str} | {token_mem}
Rules: Approve (SHORT) if breakdown volume is real (surge >= 1.25x), candle shows breakdown conviction without buyers stepping in (lower wick <= 38%), and not oversold (RSI >= 25). Reject (SKIP) only if massive lower rejection wick > 40%.
Output JSON:
{{"trap_risk": bool, "decision": "SHORT"|"SKIP", "confidence": float, "entry_price": float, "stop_loss": float, "tp1": float, "tp2": float, "reason": "1-2 sentences with trade thesis"}}"""

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Groq JEV Engine)"
        }

        eval_result = None
        for model in self.models:
            # Пропускаем модель, если на ней активен временный кулдаун после 429
            if now < self._model_cooldowns.get(model, 0.0):
                continue

            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": "You are a professional prop trading execution model. You output ONLY raw valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.1,
                "max_tokens": 650
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
                                print(f"🧠 [Groq API 200] {model} успешно оценил {symbol}: {parsed.get('decision')} (уверенность: {parsed.get('confidence')})", flush=True)
                                break
                            else:
                                print(f"⚠️ [Groq API Warning] {model} вернул невалидный JSON (finish_reason={finish_reason}): {content[:100]}", flush=True)
                        elif resp.status == 429:
                            err_txt = await resp.text()
                            # Устанавливаем кулдаун 90 секунд для этой модели
                            self._model_cooldowns[model] = time.time() + 90.0
                            print(f"⚠️ [Groq API 429] Rate limit hit на {model} (кулдаун 90с): {err_txt[:100]}", flush=True)
                            continue
                        else:
                            err_txt = await resp.text()
                            print(f"⚠️ [Groq API Error {resp.status}] {model}: {err_txt[:120]}", flush=True)
                            continue
            except Exception as e:
                print(f"⚠️ [Groq Connection Error] {model}: {e}", flush=True)
                continue

        if not eval_result:
            print(f"⚠️ [Groq Fallback] Все модели недоступны для {symbol}, применен аварийный алгоритм fallback", flush=True)
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
            if sl_pct > config.MAX_ALLOWED_SL_PCT:
                return {
                    "decision": "SKIP", "confidence": 0.20, "entry_price": price, "stop_loss": wick_sl,
                    "tp1": round(price * (1.0 + config.TP1_PCT), 6), "tp2": round(price * (1.0 + config.TP2_PCT), 6),
                    "reason": f"Отказ: стоп {sl_pct*100:.2f}% шире лимита {config.MAX_ALLOWED_SL_PCT*100:.1f}% (слишком большой риск)."
                }
            if rsi > config.MAX_RSI_LONG:
                return {
                    "decision": "SKIP", "confidence": 0.20, "entry_price": price, "stop_loss": wick_sl,
                    "tp1": round(price * (1.0 + config.TP1_PCT), 6), "tp2": round(price * (1.0 + config.TP2_PCT), 6),
                    "reason": f"Отказ: RSI {rsi:.1f} > {config.MAX_RSI_LONG} (экстремальная перекупленность)."
                }
            if upper_wick >= config.WICK_EXHAUSTION_MAX:
                return {
                    "decision": "SKIP", "confidence": 0.20, "entry_price": price, "stop_loss": wick_sl,
                    "tp1": round(price * (1.0 + config.TP1_PCT), 6), "tp2": round(price * (1.0 + config.TP2_PCT), 6),
                    "reason": f"Отказ: верхний фитиль истощения {upper_wick*100:.0f}% > {config.WICK_EXHAUSTION_MAX*100:.0f}% (давление продавцов)."
                }
            if trend == "BEARISH" and rsi < 40.0:
                return {
                    "decision": "SKIP", "confidence": 0.20, "entry_price": price, "stop_loss": wick_sl,
                    "tp1": round(price * (1.0 + config.TP1_PCT), 6), "tp2": round(price * (1.0 + config.TP2_PCT), 6),
                    "reason": "Отказ: попытка лонга в сильном нисходящем тренде (Price < EMA9 < EMA21)."
                }

            # 2. ПОДТВЕРЖДЕНИЕ КАЧЕСТВЕННОГО А+ ВХОДА
            score = 0.72
            if surge >= 1.50:
                score += 0.10
            if lower_wick >= 0.15:
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
                "reason": f"Подтвержденный Breakout & Retest LONG (A+): объем {surge:.2f}x | RSI {rsi:.1f} | Стоп {sl_pct*100:.2f}%"
            }

        else:  # SHORT
            bounce = context.get("bounce_from_low_pct", 0.0)
            short_sl_pct = context.get("short_sl_dist", 0.02)
            short_sl = context.get("short_wick_sl", price * 1.012)

            # 1. ЖЕСТКИЕ ПРАВИЛА ОТСЕВА МУСОРА (INSTANT REJECTION)
            if short_sl_pct > config.MAX_ALLOWED_SL_PCT:
                return {
                    "decision": "SKIP", "confidence": 0.20, "entry_price": price, "stop_loss": short_sl,
                    "tp1": round(price * (1.0 - config.TP1_PCT), 6), "tp2": round(price * (1.0 - config.TP2_PCT), 6),
                    "reason": f"Отказ: стоп {short_sl_pct*100:.2f}% шире лимита {config.MAX_ALLOWED_SL_PCT*100:.1f}% (слишком большой риск)."
                }
            if rsi < config.MIN_RSI_SHORT:
                return {
                    "decision": "SKIP", "confidence": 0.20, "entry_price": price, "stop_loss": short_sl,
                    "tp1": round(price * (1.0 - config.TP1_PCT), 6), "tp2": round(price * (1.0 - config.TP2_PCT), 6),
                    "reason": f"Отказ: RSI {rsi:.1f} < {config.MIN_RSI_SHORT} (экстремальная перепроданность, высокий риск резкого отскока)."
                }
            if lower_wick >= config.WICK_EXHAUSTION_MAX:
                return {
                    "decision": "SKIP", "confidence": 0.20, "entry_price": price, "stop_loss": short_sl,
                    "tp1": round(price * (1.0 - config.TP1_PCT), 6), "tp2": round(price * (1.0 - config.TP2_PCT), 6),
                    "reason": f"Отказ: массивный нижний фитиль {lower_wick*100:.0f}% (покупатели активно поглощают пролив на дне)."
                }
            if trend == "BULLISH" and rsi > 60.0:
                return {
                    "decision": "SKIP", "confidence": 0.20, "entry_price": price, "stop_loss": short_sl,
                    "tp1": round(price * (1.0 - config.TP1_PCT), 6), "tp2": round(price * (1.0 - config.TP2_PCT), 6),
                    "reason": "Отказ: попытка шортить восходящий тренд (Price > EMA9 > EMA21)."
                }

            # 2. ПОДТВЕРЖДЕНИЕ КАЧЕСТВЕННОГО А+ ВХОДА
            score = 0.72
            if surge >= 1.50:
                score += 0.10
            if upper_wick >= 0.15:
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
                "reason": f"Подтвержденный Breakdown SHORT (A+): объем {surge:.2f}x | RSI {rsi:.1f} | Стоп {short_sl_pct*100:.2f}%"
            }

# Глобальный инстанс
groq_engine = GroqEngine()
