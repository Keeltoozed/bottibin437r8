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
    Анализирует контекст рынка, подтверждает сетапы и фильтрует сделки по правилам:
      1. 'We bid the flush, not the candle' (вход на микро-откате, а не на хаях)
      2. 'The stop lives under the wick' (расчет динамического стоп-лосса под фитиль)
      3. Оценка риска 'Momentum already spent' (проверка, не выдохся ли импульс)
    """
    def __init__(self):
        self.api_key = config.GROQ_API_KEY
        self.url = "https://api.groq.com/openai/v1/chat/completions"
        self.models = [config.GROQ_PRIMARY_MODEL, config.GROQ_FALLBACK_MODEL, "qwen/qwen3.8-27b"]
        self._last_call_ts = 0.0
        self._lock = asyncio.Lock()
        self._eval_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}  # {symbol: (ts, result)}
        self.calls_count = 0
        self.approved_count = 0
        self.rejected_count = 0

    def _clean_json_response(self, text: str) -> Optional[Dict[str, Any]]:
        """Очищает ответ модели от markdown-тегов и парсит JSON."""
        if not text:
            return None
        text = text.strip()
        # Удаляем ```json и ```
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
        text = re.sub(r"\s*```$", "", text, flags=re.MULTILINE)
        try:
            return json.loads(text)
        except Exception:
            # Ищем первую скобку { и последнюю }
            m = re.search(r"\{.*\}", text, flags=re.DOTALL)
            if m:
                try:
                    return json.loads(m.group(0))
                except Exception:
                    pass
        return None

    async def evaluate_setup(self, context: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """
        Отправляет сетап на анализ в Groq.
        Возвращает: (is_approved: bool, evaluation_dict: dict)
        """
        symbol = context.get("symbol", "UNKNOWN")
        now = time.time()

        # Кэш на 5 минут: не переспрашиваем одну и ту же пару слишком часто
        if symbol in self._eval_cache:
            ts, cached_res = self._eval_cache[symbol]
            if now - ts < 300:
                is_app = cached_res.get("decision") == "BUY" and cached_res.get("confidence", 0) >= config.GROQ_MIN_CONFIDENCE
                return is_app, cached_res

        if not self.api_key:
            # Если ключ не задан, используем качественный алгоритмический скорер
            res = self._algorithmic_eval(context)
            self._eval_cache[symbol] = (now, res)
            is_app = res.get("decision") == "BUY"
            return is_app, res

        # Троттлинг запросов (соблюдение лимита Groq RPM)
        async with self._lock:
            elapsed = time.time() - self._last_call_ts
            min_interval = 60.0 / config.GROQ_RPM_LIMIT
            if elapsed < min_interval:
                await asyncio.sleep(min_interval - elapsed)
            self._last_call_ts = time.time()

        prompt = f"""You are the Lead Risk & Execution Officer at an elite quantitative crypto prop desk.
Analyze this high-momentum breakout candidate on Binance Futures.

RULES OF ENGAGEMENT:
1. 'We bid the flush, not the candle': NEVER buy the top of an overextended green candle without consolidation. A healthy pullback (-0.3% to -2.0% from recent high) is required for a clean entry.
2. 'The stop lives under the wick': The stop-loss must be placed right below the lower wick of recent candles ({context.get('wick_stop_loss')}). If the stop distance is > 3.5%, REJECT it (risk too high).
3. 'Momentum already spent': If price pumped > 12% in 15m with a massive upper wick (> 45%), reject (exhaustion wick/dump risk).
4. Minimum Risk-to-Reward ratio must be at least 1.8 to 1.

CANDIDATE CONTEXT:
- Symbol: {symbol}
- Current Price: ${context.get('current_price')}
- 24h Volume: ${context.get('volume_24h', 0):,.0f}
- 5m Volume Surge vs Avg: {context.get('volume_surge_ratio')}x
- 5m Price Change: {context.get('pct_5m'):+.2f}%
- 15m Price Change: {context.get('pct_15m'):+.2f}%
- Pullback from Recent High: {context.get('pullback_from_high_pct', 0) * 100:+.2f}%
- Upper Wick Ratio: {context.get('upper_wick_pct', 0) * 100:.1f}% (high means selling pressure at top)
- Lower Wick Ratio: {context.get('lower_wick_pct', 0) * 100:.1f}% (high means buyers defending the dip)
- Suggested Wick SL: ${context.get('wick_stop_loss')} ({context.get('sl_pct_distance', 0) * 100:.2f}% distance)

Respond STRICTLY with a valid JSON object matching this schema, with no preamble or markdown:
{{
  "decision": "BUY" or "SKIP",
  "confidence": float between 0.0 and 1.0,
  "entry_price": float (price to buy, near current or slightly below),
  "stop_loss": float (under wick stop loss),
  "tp1": float (take profit target 1, approx +2.0% to +3.0%),
  "tp2": float (take profit target 2, approx +4.0% to +6.0%),
  "reason": "1-2 concise sentences explaining why this passed or was rejected based on wicks and flush"
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
            # Если все модели Groq не ответили, переключаемся на алгоритмический скоринг
            eval_result = self._algorithmic_eval(context)
            eval_result["model"] = "algorithmic_fallback"

        eval_result["timestamp"] = now
        eval_result["symbol"] = symbol
        self._eval_cache[symbol] = (now, eval_result)
        self.calls_count += 1

        is_approved = (
            eval_result.get("decision") == "BUY" and
            float(eval_result.get("confidence", 0)) >= config.GROQ_MIN_CONFIDENCE and
            float(context.get("sl_pct_distance", 0)) <= config.MAX_ALLOWED_SL_PCT
        )

        if is_approved:
            self.approved_count += 1
        else:
            self.rejected_count += 1

        return is_approved, eval_result

    def _algorithmic_eval(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Резервный алгоритмический скоринг по правилам Grok/JEV."""
        price = context.get("current_price", 1.0)
        surge = context.get("volume_surge_ratio", 1.0)
        pullback = context.get("pullback_from_high_pct", 0.0)
        upper_wick = context.get("upper_wick_pct", 0.0)
        sl_pct = context.get("sl_pct_distance", 0.02)
        wick_sl = context.get("wick_stop_loss", price * 0.98)

        # Проверки:
        # 1. Всплеск объема >= 1.6x
        # 2. Не на пике свечи (верхний фитиль не слишком большой)
        # 3. Адекватный стоп под фитиль (до 3.2%)
        # 4. Есть откат
        score = 0.5
        reasons = []

        if surge >= 2.0:
            score += 0.2
            reasons.append(f"Объемный всплеск {surge}x")
        elif surge >= 1.5:
            score += 0.1

        if upper_wick < 0.35:
            score += 0.1
            reasons.append("Нет давления продавцов на верхушке свечи")
        else:
            score -= 0.25
            reasons.append("Большой верхний фитиль (риск разворота)")

        if -0.025 <= pullback <= -0.002:
            score += 0.15
            reasons.append(f"Здоровый откат ({pullback*100:+.1f}%)")
        elif pullback > -0.001:
            score -= 0.1
            reasons.append("Вход на самом пике без отката")

        if sl_pct <= 0.028:
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

# Глобальный инстанс
groq_engine = GroqEngine()

