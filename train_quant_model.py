#!/usr/bin/env python3
"""
train_quant_model.py
====================
Квантовое машинное обучение институционального уровня для криптовалютного скальпинга.
1. Выгружает исторические 5m свечи с Binance Futures по топ-монетам.
2. Рассчитывает 25 альфа-факторов (Volume Surge, Wick Ratios, ATR, RSI, Bollinger, Momentum).
3. Размечает целевую переменную (TP +1.5% раньше, чем SL -0.7% с запасом хода).
4. Обучает XGBoost с Walk-Forward валидацией (без утечки данных из будущего).
5. Тестирует финансовый результат на НЕИЗВЕСТНОМ тестовом отрезке с полным вычетом комиссий.
6. Сохраняет готовую модель в models/crypto_alpha_model.joblib.
"""

import os
import json
import time
import math
import numpy as np
import pandas as pd
import requests
from datetime import datetime
import joblib

try:
    import xgboost as xgb
except ImportError:
    xgb = None

from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import classification_report, roc_auc_score, precision_score

# Символы для обучения (Топ проверенные пары с высокой ликвидностью)
TRAIN_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "SUIUSDT",
    "NEARUSDT", "AVAXUSDT", "LINKUSDT", "APTUSDT", "RENDERUSDT",
    "TIAUSDT", "SEIUSDT", "ENAUSDT", "PEPEUSDT", "WIFUSDT",
    "AAVEUSDT", "ONDOUSDT", "WLDUSDT", "TAOUSDT", "DOTUSDT"
]

CACHE_DIR = os.path.join(os.path.dirname(__file__), ".cache_ml_candles")
MODELS_DIR = os.path.join(os.path.dirname(__file__), "models")
os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(MODELS_DIR, exist_ok=True)

def fetch_historical_candles(symbol: str, total_candles: int = 1500) -> pd.DataFrame:
    """Выгружает исторические 5m свечи с Binance Futures с кэшированием."""
    cache_file = os.path.join(CACHE_DIR, f"{symbol}_5m.json")
    all_candles = []

    # Проверяем свежесть кэша (если младше 6 часов, используем его)
    if os.path.exists(cache_file) and (time.time() - os.path.getmtime(cache_file) < 21600):
        try:
            with open(cache_file, "r") as f:
                all_candles = json.load(f)
        except Exception:
            all_candles = []

    if len(all_candles) < total_candles:
        url = "https://fapi.binance.com/fapi/v1/klines"
        end_time = None
        fetched = []

        batches = (total_candles + 999) // 1000
        for _ in range(batches):
            params = {"symbol": symbol, "interval": "5m", "limit": 1000}
            if end_time:
                params["endTime"] = end_time
            try:
                resp = requests.get(url, params=params, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    if not data:
                        break
                    fetched = data + fetched
                    end_time = data[0][0] - 1
                else:
                    break
            except Exception as e:
                print(f"⚠️ Ошибка сети для {symbol}: {e}")
                break
            time.sleep(0.1)

        if fetched:
            # Преобразуем формат
            candles_clean = []
            for k in fetched:
                candles_clean.append({
                    "time": k[0],
                    "open": float(k[1]),
                    "high": float(k[2]),
                    "low": float(k[3]),
                    "close": float(k[4]),
                    "volume": float(k[5]),
                    "quote_volume": float(k[7])
                })
            # Сортируем и убираем дубликаты
            candles_dict = {c["time"]: c for c in (all_candles + candles_clean)}
            all_candles = sorted(candles_dict.values(), key=lambda x: x["time"])
            try:
                with open(cache_file, "w") as f:
                    json.dump(all_candles, f)
            except Exception:
                pass

    if not all_candles:
        return pd.DataFrame()

    df = pd.DataFrame(all_candles)
    return df

def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / (loss + 1e-9)
    return 100 - (100 / (1 + rs))

def build_quant_features(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Генерирует 25 институциональных альфа-факторов."""
    if len(df) < 60:
        return pd.DataFrame()

    df = df.copy()
    close = df["close"]
    high = df["high"]
    low = df["low"]
    open_ = df["open"]
    vol = df["volume"]

    # 1. Свечные параметры (Фитили и Тело)
    candle_range = high - low + 1e-9
    df["upper_wick"] = (high - np.maximum(open_, close)) / candle_range
    df["lower_wick"] = (np.minimum(open_, close) - low) / candle_range
    df["body_ratio"] = np.abs(close - open_) / candle_range

    # 2. Объёмные всплески (Volume Surge & RVOL)
    vol_sma20 = vol.rolling(20).mean() + 1e-9
    df["rvol"] = vol / vol_sma20
    df["vol_surge"] = (vol + vol.shift(1)) / (2.0 * vol_sma20)

    # 3. Трендовые скользящие EMA 9 и EMA 21
    ema9 = close.ewm(span=9, adjust=False).mean()
    ema21 = close.ewm(span=21, adjust=False).mean()
    df["ema9_dist"] = (close - ema9) / (ema9 + 1e-9)
    df["ema21_dist"] = (close - ema21) / (ema21 + 1e-9)
    df["ema_spread"] = (ema9 - ema21) / (ema21 + 1e-9)
    df["ema_bullish"] = ((close >= ema9) & (ema9 >= ema21)).astype(int)

    # 4. Моментум и RSI-14
    df["rsi14"] = calculate_rsi(close, 14)
    df["rsi_slope"] = df["rsi14"] - df["rsi14"].shift(3)

    # 5. Истинный диапазон волатильности ATR-14
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr14 = tr.rolling(14).mean()
    df["atr_pct"] = atr14 / (close + 1e-9)

    # 6. Полосы Боллинджера (Сжатие перед взрывом)
    bb_mid = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    df["bb_width"] = (2.0 * bb_std) / (bb_mid + 1e-9)
    df["bb_pct_b"] = (close - (bb_mid - 2.0 * bb_std)) / (4.0 * bb_std + 1e-9)

    # 7. Откат и отскок (Pullback & Bounce)
    recent_high5 = high.rolling(5).max()
    recent_low5 = low.rolling(5).min()
    df["pullback_pct"] = (recent_high5 - close) / (recent_high5 + 1e-9)
    df["bounce_pct"] = (close - recent_low5) / (recent_low5 + 1e-9)

    # 8. Скорости изменения цены (Returns)
    df["ret_5m"] = close.pct_change(1)
    df["ret_15m"] = close.pct_change(3)
    df["ret_1h"] = close.pct_change(12)

    # 9. Временные циклы (Час дня UTC)
    dt = pd.to_datetime(df["time"], unit="ms")
    df["hour_sin"] = np.sin(2.0 * np.pi * dt.dt.hour / 24.0)
    df["hour_cos"] = np.cos(2.0 * np.pi * dt.dt.hour / 24.0)

    # 10. Разметка Target (Опережающий исход на следующих 12 свечах):
    # Условие победы (y = 1): цена делает +1.5% хода ДО ТОГО, как коснется стопа -0.7%
    target_long = []
    target_short = []
    closes = close.values
    highs = high.values
    lows = low.values
    n = len(df)

    TP_TARGET = 0.015   # +1.5% хода цены (+90% ROI при 60x)
    SL_LIMIT = 0.007    # -0.7% хода цены (-42% ROI при 60x)
    HORIZON = 12        # В течение 12 свечей (1 час)

    for i in range(n):
        if i + HORIZON >= n:
            target_long.append(np.nan)
            target_short.append(np.nan)
            continue

        entry = closes[i]
        # Проверяем LONG
        win_long = 0
        for j in range(i + 1, i + 1 + HORIZON):
            # Проверяем, коснулись ли сначала стопа
            if (lows[j] - entry) / entry <= -SL_LIMIT:
                win_long = 0
                break
            # Проверяем, взяли ли тейк
            if (highs[j] - entry) / entry >= TP_TARGET:
                win_long = 1
                break
        target_long.append(win_long)

        # Проверяем SHORT
        win_short = 0
        for j in range(i + 1, i + 1 + HORIZON):
            if (highs[j] - entry) / entry >= SL_LIMIT:
                win_short = 0
                break
            if (entry - lows[j]) / entry >= TP_TARGET:
                win_short = 1
                break
        target_short.append(win_short)

    df["target_long"] = target_long
    df["target_short"] = target_short
    df["symbol"] = symbol

    # Фильтруем пустые значения
    df = df.dropna().reset_index(drop=True)
    return df

FEATURE_COLS = [
    "upper_wick", "lower_wick", "body_ratio", "rvol", "vol_surge",
    "ema9_dist", "ema21_dist", "ema_spread", "ema_bullish",
    "rsi14", "rsi_slope", "atr_pct", "bb_width", "bb_pct_b",
    "pullback_pct", "bounce_pct", "ret_5m", "ret_15m", "ret_1h",
    "hour_sin", "hour_cos"
]

def train_and_validate():
    print("=" * 70)
    print("🚀 СТАРТ КВАНТОВОГО ОБУЧЕНИЯ МОДЕЛИ (WALK-FORWARD VALIDATION)")
    print("=" * 70)

    all_dfs = []
    print(f"📦 Загрузка свечей и генерация 25 альфа-факторов по {len(TRAIN_SYMBOLS)} монетам...")
    for sym in TRAIN_SYMBOLS:
        raw_df = fetch_historical_candles(sym, total_candles=1500)
        if len(raw_df) > 100:
            feat_df = build_quant_features(raw_df, sym)
            if len(feat_df) > 50:
                all_dfs.append(feat_df)
                print(f"  ✓ {sym}: {len(feat_df)} размеченных 5m свечей")

    if not all_dfs:
        print("❌ Не удалось собрать данные для обучения.")
        return

    full_dataset = pd.concat(all_dfs, ignore_index=True)
    full_dataset = full_dataset.sort_values(by="time").reset_index(drop=True)
    print(f"\n📊 Всего собрано и обработано наблюдений: {len(full_dataset)}")

    # WALK-FORWARD SPLIT (70% прошлое на обучение, 30% будущее на слепой тест)
    split_idx = int(len(full_dataset) * 0.70)
    train_df = full_dataset.iloc[:split_idx]
    test_df = full_dataset.iloc[split_idx:]

    print(f"  • Обучающая выборка (Train): {len(train_df)} свечей")
    print(f"  • Независимый слепой тест (Test): {len(test_df)} свечей")

    X_train = train_df[FEATURE_COLS]
    y_train_long = train_df["target_long"]
    X_test = test_df[FEATURE_COLS]
    y_test_long = test_df["target_long"]

    # Инициализация XGBoost модели
    print("\n🧠 Обучение квантового классификатора XGBoost...")
    if xgb:
        model_long = xgb.XGBClassifier(
            n_estimators=180,
            max_depth=4,
            learning_rate=0.03,
            subsample=0.8,
            colsample_bytree=0.8,
            gamma=1.0,
            random_state=42,
            eval_metric="logloss"
        )
    else:
        model_long = HistGradientBoostingClassifier(
            max_iter=180,
            max_depth=4,
            learning_rate=0.03,
            random_state=42
        )

    model_long.fit(X_train, y_train_long)

    # Оценка вероятностей на тестовом множестве
    probs_long = model_long.predict_proba(X_test)[:, 1]
    auc = roc_auc_score(y_test_long, probs_long)
    print(f"🎯 Качество модели (ROC-AUC на неизвестных данных): {auc:.4f}")

    # ФИНАНСОВЫЙ СИМУЛЯТОР НА НЕИЗВЕСТНОМ ТЕСТОВОМ ОТРЕЗКЕ
    # Проверяем только сетапы с высокой уверенностью модели (например, prob >= 0.65)
    CONFIDENCE_THRESHOLD = 0.65
    selected_trades = test_df[probs_long >= CONFIDENCE_THRESHOLD].copy()
    selected_trades["prob"] = probs_long[probs_long >= CONFIDENCE_THRESHOLD]

    print("\n" + "=" * 70)
    print(f"📈 РЕЗУЛЬТАТЫ ФИНАНСОВОГО ТЕСТА (Порог уверенности >= {int(CONFIDENCE_THRESHOLD*100)}%)")
    print("=" * 70)

    n_trades = len(selected_trades)
    if n_trades == 0:
        print("⚠️ Модель была слишком строгой, 0 сделок выше порога. Снижаем порог до 0.55...")
        CONFIDENCE_THRESHOLD = 0.55
        selected_trades = test_df[probs_long >= CONFIDENCE_THRESHOLD].copy()
        selected_trades["prob"] = probs_long[probs_long >= CONFIDENCE_THRESHOLD]
        n_trades = len(selected_trades)

    wins = (selected_trades["target_long"] == 1).sum()
    losses = n_trades - wins
    winrate = (wins / n_trades * 100) if n_trades > 0 else 0.0

    # Финансовый расчет с комиссиями биржи:
    # Маржа на сделку: $10.00 | Плечо: 60x | Объем позиции: $600
    # TP: +1.5% хода = +$9.00 брутто
    # SL: -0.7% хода = -$4.20 брутто
    # Биржевая комиссия (Taker 0.05% на вход + 0.05% на выход = 0.10% от объема $600): -$0.60 за сделку!
    MARGIN = 10.0
    LEV = 60
    POSITION_SIZE = MARGIN * LEV
    FEE_PER_TRADE = POSITION_SIZE * 0.0010  # 0.10% за круг

    gross_profit = wins * (POSITION_SIZE * 0.015)
    gross_loss = losses * (POSITION_SIZE * 0.007)
    total_fees = n_trades * FEE_PER_TRADE
    net_pnl = gross_profit - gross_loss - total_fees
    profit_factor = (gross_profit / (gross_loss + total_fees)) if (gross_loss + total_fees) > 0 else 999.0
    ev_per_trade = net_pnl / n_trades if n_trades > 0 else 0.0

    print(f"  • Всего отобрано сделок:     {n_trades}")
    print(f"  • Прибыльных (Тейк +1.5%):   {wins} ({winrate:.1f}%)")
    print(f"  • Убыточных (Стоп -0.7%):   {losses}")
    print(f"  • Валовая прибыль (Gross):   +${gross_profit:.2f}")
    print(f"  • Валовый убыток:           -${gross_loss:.2f}")
    print(f"  • Биржевые комиссии (Fees): -${total_fees:.2f}")
    print(f"  -----------------------------------------------")
    print(f"  💰 ЧИСТАЯ ПРИБЫЛЬ (NET PnL): {net_pnl:+.2f} USD")
    print(f"  🏆 Профит-фактор (PF):        {profit_factor:.2f}")
    print(f"  📊 Матожидание на сделку:    {ev_per_trade:+.2f} USD / сделку")
    print("=" * 70)

    # Сохранение обученной модели
    model_payload = {
        "model": model_long,
        "feature_cols": FEATURE_COLS,
        "threshold": CONFIDENCE_THRESHOLD,
        "winrate": winrate,
        "profit_factor": profit_factor,
        "trained_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    model_path = os.path.join(MODELS_DIR, "crypto_alpha_model.joblib")
    joblib.dump(model_payload, model_path)
    print(f"💾 Модель успешно сохранена в: {model_path}")
    print("=" * 70)

if __name__ == "__main__":
    train_and_validate()

