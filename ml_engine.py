import os
import time
import math
import numpy as np
import pandas as pd
import joblib
from typing import Dict, Any, Tuple, Optional

class QuantMLEngine:
    """
    Инференс-движок обученной квантовой модели (XGBoost / HistGradientBoosting).
    Рассчитывает 21 институциональный фактор и выдает математическую вероятность
    того, что ракета возьмет TP (+1.5%) до выбивания стопа (-0.7%).
    """

    def __init__(self, model_path: Optional[str] = None):
        if not model_path:
            model_path = os.path.join(os.path.dirname(__file__), "models", "crypto_alpha_model.joblib")
        self.model_path = model_path
        self.model = None
        self.feature_cols = []
        self.threshold = 0.60
        self.winrate = 0.0
        self.profit_factor = 0.0
        self.load_model()

    def load_model(self):
        """Загружает сохраненные веса модели или мгновенно распаковывает встроенную модель."""
        # 1. Если файл модели отсутствует на диске (например, чистый деплой на Render)
        if not os.path.exists(self.model_path):
            print("⚡ [ML Engine] Файл модели не найден на диске. Мгновенная распаковка встроенной квантовой модели...", flush=True)
            try:
                import prebuilt_model_data
                prebuilt_model_data.restore_prebuilt_model(self.model_path)
            except Exception as e:
                print(f"⚠️ [ML Engine] Ошибка распаковки встроенной модели: {e}", flush=True)

        # 2. Загружаем модель с диска
        if os.path.exists(self.model_path):
            try:
                payload = joblib.load(self.model_path)
                self.model = payload["model"]
                self.feature_cols = payload["feature_cols"]
                self.threshold = payload.get("threshold", 0.60)
                self.winrate = payload.get("winrate", 0.0)
                self.profit_factor = payload.get("profit_factor", 0.0)
                print(f"✅ [ML Engine] Обученная модель загружена: WR {self.winrate:.1f}%, PF {self.profit_factor:.2f}", flush=True)
                return
            except Exception as e:
                print(f"⚠️ [ML Engine] Ошибка загрузки модели: {e}", flush=True)
                self.model = None

        # 3. Резервное обучение через зеркало Binance Vision
        print("⚡ [ML Engine] Запуск резервного обучения через Binance Vision...", flush=True)
        try:
            import train_quant_model
            train_quant_model.train_and_validate()
            if os.path.exists(self.model_path):
                payload = joblib.load(self.model_path)
                self.model = payload["model"]
                self.feature_cols = payload["feature_cols"]
                self.threshold = payload.get("threshold", 0.60)
                self.winrate = payload.get("winrate", 0.0)
                self.profit_factor = payload.get("profit_factor", 0.0)
                print(f"✅ [ML Engine] Авто-обучение завершено! Модель готова: WR {self.winrate:.1f}%, PF {self.profit_factor:.2f}", flush=True)
        except Exception as e:
            print(f"⚠️ [ML Engine] Ошибка авто-обучения: {e}", flush=True)
            self.model = None

    def evaluate_candidate(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Принимает контекст сканера и возвращает математический скоринг модели.
        """
        if self.model is None:
            # Если модель еще не обучена, пропускаем оценку
            return {
                "ml_active": False,
                "ml_probability": 0.50,
                "ml_approved": True,
                "reason": "ML модель ожидает обучения"
            }

        try:
            # Извлекаем сырые показатели из контекста
            cur_p = context.get("current_price", 1.0)
            u_wick = context.get("upper_wick_pct", 0.0)
            l_wick = context.get("lower_wick_pct", 0.0)
            vol_surge = context.get("volume_surge_ratio", 1.0)
            rvol = context.get("rvol", vol_surge)
            ema9 = context.get("ema9", cur_p)
            ema21 = context.get("ema21", cur_p)
            rsi = context.get("rsi", 50.0)
            atr_pct = context.get("atr14_pct", 0.004)
            pullback = abs(context.get("pullback_from_high_pct", 0.0))
            bounce = abs(context.get("bounce_from_low_pct", 0.0))
            p5m = context.get("pct_5m", 0.0) / 100.0
            p15m = context.get("pct_15m", 0.0) / 100.0

            # Вычисляем признаки
            ema9_dist = (cur_p - ema9) / (ema9 + 1e-9)
            ema21_dist = (cur_p - ema21) / (ema21 + 1e-9)
            ema50_dist = ema21_dist * 1.5
            ema_spread = (ema9 - ema21) / (ema21 + 1e-9)
            ema_bull = 1 if (cur_p >= ema9 and ema9 >= ema21) else 0
            ema_slope_9 = p5m * 0.5

            # Временные циклы (текущий час UTC)
            utc_hour = (time.time() / 3600) % 24
            hour_sin = math.sin(2.0 * math.pi * utc_hour / 24.0)
            hour_cos = math.cos(2.0 * math.pi * utc_hour / 24.0)

            # Формируем полный вектор признаков строго в порядке feature_cols
            feat_map = {
                "upper_wick": u_wick,
                "lower_wick": l_wick,
                "body_ratio": max(0.0, 1.0 - u_wick - l_wick),
                "wick_trap_long": 1 if u_wick > 0.30 else 0,
                "wick_defense_long": 1 if l_wick > 0.35 else 0,
                "rvol": rvol,
                "vol_surge": vol_surge,
                "vol_zscore": (vol_surge - 1.0) / 0.5,
                "vol_trend": vol_surge,
                "ema9_dist": ema9_dist,
                "ema21_dist": ema21_dist,
                "ema50_dist": ema50_dist,
                "ema_spread": ema_spread,
                "ema_bullish": ema_bull,
                "ema_slope_9": ema_slope_9,
                "rsi14": rsi,
                "rsi_slope": p5m * 10.0,
                "rsi_exhausted": 1 if rsi > 70.0 else 0,
                "atr_pct": atr_pct,
                "atr_surge": max(0.5, atr_pct / 0.0035),
                "bb_width": atr_pct * 4.0,
                "bb_pct_b": max(0.0, min(1.0, 0.5 + (p5m / (atr_pct * 4.0 + 1e-9)))),
                "bb_squeeze": 1 if atr_pct < 0.003 else 0,
                "pullback_pct": pullback,
                "bounce_pct": bounce,
                "ret_5m": p5m,
                "ret_15m": p15m,
                "ret_1h": p15m * 2.0,
                "hour_sin": hour_sin,
                "hour_cos": hour_cos
            }

            row = [feat_map.get(col, 0.0) for col in self.feature_cols]
            X = np.array([row])

            probs = self.model.predict_proba(X)[0]
            prob_win = float(probs[1]) if len(probs) > 1 else float(probs[0])

            approved = prob_win >= self.threshold
            return {
                "ml_active": True,
                "ml_probability": round(prob_win, 3),
                "ml_approved": approved,
                "threshold": self.threshold,
                "winrate_backtest": self.winrate,
                "profit_factor": self.profit_factor,
                "reason": f"ML Вероятность: {int(prob_win*100)}% (порог {int(self.threshold*100)}%)"
            }
        except Exception as e:
            return {
                "ml_active": True,
                "ml_probability": 0.50,
                "ml_approved": True,
                "reason": f"Ошибка расчета ML: {e}"
            }

# Экземпляр
ml_engine = QuantMLEngine()
