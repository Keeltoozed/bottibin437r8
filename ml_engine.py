import os
import time
import math
import numpy as np
import pandas as pd
import joblib
from typing import Dict, Any, Tuple, Optional
import config
from quant_features import (
    FEATURE_COLS_LONG, FEATURE_COLS_SHORT,
    extract_features_from_candles, extract_features_from_dict_fallback
)

class QuantMLEngine:
    """
    Институциональный двусторонний инференс-движок квантовой модели (Dual XGBoost Alpha Engine).
    Имеет две специализированные модели:
      1. model_long: выявляет импульсные взлеты (+1.5% до стопа -0.75%).
      2. model_short: выявляет каскадные сливы (-1.5% до стопа +0.75%).
    Оценивает 30 институциональных факторов без Train-Serve Skew на базе реальных свечей.
    """

    def __init__(self, model_path: Optional[str] = None):
        if not model_path:
            model_path = os.path.join(os.path.dirname(__file__), "models", "crypto_alpha_model.joblib")
        self.model_path = model_path
        self.model = None
        self.model_long = None
        self.model_short = None
        self.feature_cols_long = FEATURE_COLS_LONG
        self.feature_cols_short = FEATURE_COLS_SHORT
        self.feature_cols = FEATURE_COLS_LONG
        cfg_thresh = float(getattr(config, "ML_CONFIDENCE_THRESHOLD", 0.60))
        self.threshold = cfg_thresh
        self.threshold_long = cfg_thresh
        self.threshold_short = cfg_thresh
        self.winrate = 0.0
        self.winrate_long = 0.0
        self.winrate_short = 0.0
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
                self.model_long = payload.get("model_long", payload.get("model"))
                self.model_short = payload.get("model_short")
                self.model = self.model_long
                self.feature_cols_long = payload.get("feature_cols_long", FEATURE_COLS_LONG)
                self.feature_cols_short = payload.get("feature_cols_short", FEATURE_COLS_SHORT)
                self.feature_cols = self.feature_cols_long

                cfg_thresh = float(getattr(config, "ML_CONFIDENCE_THRESHOLD", 0.60))
                self.threshold_long = cfg_thresh
                self.threshold_short = cfg_thresh
                self.threshold = cfg_thresh

                self.winrate_long = payload.get("winrate_long", payload.get("winrate", 70.0))
                self.winrate_short = payload.get("winrate_short", 70.0)
                self.winrate = self.winrate_long
                self.profit_factor = payload.get("profit_factor", 3.0)

                short_status = f"OK (WR {self.winrate_short:.1f}%)" if self.model_short is not None else "Не загружена"
                print(f"✅ [ML Engine] Двусторонняя квантовая модель готова! LONG WR: {self.winrate_long:.1f}%, SHORT: {short_status}, PF: {self.profit_factor:.2f}", flush=True)
                return
            except Exception as e:
                print(f"⚠️ [ML Engine] Ошибка загрузки модели: {e}", flush=True)
                self.model = None
                self.model_long = None
                self.model_short = None

        # 3. Резервное обучение
        print("⚡ [ML Engine] Запуск резервного обучения через Binance Vision...", flush=True)
        try:
            import train_quant_model
            train_quant_model.train_and_validate()
            if os.path.exists(self.model_path):
                payload = joblib.load(self.model_path)
                self.model_long = payload.get("model_long", payload.get("model"))
                self.model_short = payload.get("model_short")
                self.model = self.model_long
                self.feature_cols_long = payload.get("feature_cols_long", FEATURE_COLS_LONG)
                self.feature_cols_short = payload.get("feature_cols_short", FEATURE_COLS_SHORT)
                self.feature_cols = self.feature_cols_long
                cfg_thresh = float(getattr(config, "ML_CONFIDENCE_THRESHOLD", 0.60))
                self.threshold_long = cfg_thresh
                self.threshold_short = cfg_thresh
                self.threshold = cfg_thresh
                self.winrate_long = payload.get("winrate_long", 70.0)
                self.winrate_short = payload.get("winrate_short", 70.0)
                self.winrate = self.winrate_long
                self.profit_factor = payload.get("profit_factor", 3.0)
                print(f"✅ [ML Engine] Авто-обучение завершено! LONG WR: {self.winrate_long:.1f}%, SHORT WR: {self.winrate_short:.1f}%", flush=True)
        except Exception as e:
            print(f"⚠️ [ML Engine] Ошибка авто-обучения: {e}", flush=True)
            self.model = None

    def evaluate_candidate(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Принимает контекст сканера и возвращает математический скоринг специализированной
        модели для соответствующего направления (LONG или SHORT).
        Использует реальный свечной расчет признаков через quant_features.
        """
        cand_side = context.get("candidate_side", "LONG").upper()
        target_model = self.model_short if (cand_side == "SHORT" and self.model_short is not None) else (self.model_long or self.model)
        target_features = self.feature_cols_short if (cand_side == "SHORT" and self.model_short is not None) else (self.feature_cols_long or self.feature_cols)
        target_threshold = self.threshold_short if (cand_side == "SHORT" and self.model_short is not None) else self.threshold_long

        if target_model is None or not target_features:
            return {
                "ml_active": False,
                "candidate_side": cand_side,
                "ml_probability": 0.50,
                "ml_approved": True,
                "reason": "ML модель ожидает обучения"
            }

        try:
            # 1. Точный расчет институциональных признаков
            candles = context.get("candles")
            feat_df = None
            if candles and isinstance(candles, list) and len(candles) >= 15:
                feat_df = extract_features_from_candles(candles, side=cand_side)

            if feat_df is None or feat_df.empty:
                feat_df = extract_features_from_dict_fallback(context, side=cand_side)

            # Формируем матрицу входов
            X = feat_df[target_features].values

            # Инференс модели
            probs = target_model.predict_proba(X)[0]
            raw_prob_win = float(probs[1]) if len(probs) > 1 else float(probs[0])
            prob_win = raw_prob_win

            # 2. Институциональные фильтры качества
            penalties = []
            vol_surge = float(context.get("volume_surge_ratio", 1.5))
            p5m = float(context.get("pct_5m", 0.0)) / 100.0

            # Защита от мертвого объема (Dead Volume Penalty)
            if vol_surge < 1.10 and abs(p5m) < 0.0015:
                prob_win = min(prob_win, 0.52)
                penalties.append("мертвый объем < 1.10x")

            # Проверка соответствия допустимого стоп-лосса плечу
            sl_dist = context.get("sl_pct_distance", 0.0) if cand_side == "LONG" else context.get("short_sl_dist", 0.0)
            max_sl_cap = getattr(config, "MAX_ALLOWED_SL_PCT", 0.0125)
            if sl_dist > max_sl_cap:
                prob_win = min(prob_win, 0.49)
                penalties.append(f"опасный стоп ({sl_dist*100:.2f}% > {max_sl_cap*100:.2f}%)")

            # Защита от покупки на излете экстремального импульса
            rsi_val = float(context.get("rsi", 50.0))
            if cand_side == "LONG" and rsi_val > 88.0:
                prob_win *= 0.90
                penalties.append(f"RSI перегрет ({rsi_val:.0f} > 88)")
            elif cand_side == "SHORT" and rsi_val < 15.0:
                prob_win *= 0.90
                penalties.append(f"RSI перепродан ({rsi_val:.0f} < 15)")

            is_approved = (prob_win >= target_threshold)
            status_text = "ОДОБРЕНО" if is_approved else "ОТКЛОНЕНО"
            reason = f"ML {cand_side}: {int(prob_win*100)}% (порог {int(target_threshold*100)}%) — {status_text}"
            if penalties:
                reason += f" | Штрафы: {', '.join(penalties)}"

            return {
                "ml_active": True,
                "candidate_side": cand_side,
                "ml_probability": round(prob_win, 3),
                "raw_probability": round(raw_prob_win, 3),
                "ml_approved": is_approved,
                "threshold": target_threshold,
                "model_type": "Dual-XGBoost-Titan",
                "penalties": penalties,
                "reason": reason
            }

        except Exception as e:
            print(f"⚠️ [ML Engine] Ошибка инференса для {context.get('symbol', 'UNKNOWN')}: {e}", flush=True)
            return {
                "ml_active": True,
                "candidate_side": cand_side,
                "ml_probability": 0.50,
                "ml_approved": False,
                "reason": f"Ошибка инференса: {e}"
            }

ml_engine = QuantMLEngine()
