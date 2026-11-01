import asyncio
import time
from ml_engine import ml_engine
from quant_features import extract_features_from_candles
from tracker import portfolio
from obsidian_vault import obsidian_vault
from binance_client import binance_client
from groq_engine import groq_engine
import config


async def run_suite():
    print("=" * 78)
    print("🧪 СТАРТ ПОЛНОГО КОМПЛЕКСНОГО ТЕСТИРОВАНИЯ STRUCTURAL ROCKET HUNTER (v9.4)")
    print("=" * 78)

    # Полная изоляция тестов от боевых файлов portfolio.json и Obsidian Vault!
    portfolio.persist_enabled = False
    obsidian_vault.enabled = False

    # 1. ТЕСТ CLOSED-CANDLE ML ENGINE (ЗАЩИТА ОТ 3-СЕКУНДНОЙ ПУСТОЙ СВЕЧИ)
    print("\n[ТЕСТ 1/6] Проверка Dual Quant ML Engine и защиты от незакрытой свечи...")
    assert ml_engine.model_long is not None or ml_engine.model is not None, "LONG модель не загружена"
    assert ml_engine.model_short is not None, "SHORT модель не загружена"

    now_ms = int(time.time() * 1000)
    synthetic_candles = []
    p = 100.0
    for i in range(25):
        p += 0.05
        synthetic_candles.append({
            "time": now_ms - (26 - i) * 300_000,
            "open": p - 0.05, "high": p + 0.05, "low": p - 0.06, "close": p,
            "volume": 1000.0, "quote_vol": 100_000.0
        })
    # Предпоследняя свеча [-2] — закрытый мощный Marubozu пробой на 3.5x объеме!
    synthetic_candles.append({
        "time": now_ms - 300_000,
        "open": p, "high": p * 1.015, "low": p * 0.9998, "close": p * 1.0145,
        "volume": 3500.0, "quote_vol": 350_000.0
    })
    # Последняя свеча [-1] — только что открылась 2 секунды назад с микро-объемом 50 USDT!
    synthetic_candles.append({
        "time": now_ms - 2_000,
        "open": p * 1.0145, "high": p * 1.0146, "low": p * 1.0144, "close": p * 1.0145,
        "volume": 0.5, "quote_vol": 50.0
    })

    feat_row = extract_features_from_candles(synthetic_candles, side="LONG")
    assert feat_row is not None and not feat_row.empty
    extracted_rvol = float(feat_row["rvol"].iloc[0])
    assert extracted_rvol > 2.5, f"Ожидался RVOL закрытой свечи > 2.5x, получено {extracted_rvol:.2f}x (баг незакрытой свечи!)"
    print(f"  ✓ ML оценивает закрытый сигнальный бар (RVOL={extracted_rvol:.2f}x), игнорируя пустую живую свечу!")

    # 2. ТЕСТ СТРУКТУРНОГО АНАЛИЗА BINANCE И РАДАРА 100 ПАР
    print("\n[ТЕСТ 2/6] Проверка подключения к Binance, BTC-щита и радара пробоев...")
    btc_reg = await binance_client.fetch_btc_regime()
    print(f"  ✓ Статус Bitcoin: {btc_reg['status_str']}")
    tickers = await binance_client.fetch_top_tickers(min_vol_usdt=config.MIN_24H_VOLUME_USDT, limit=config.SCAN_TICKERS_LIMIT)
    assert len(tickers) >= 30, f"Радар вернул слишком мало пар: {len(tickers)}"
    sol_analysis = await binance_client.fetch_candles_analysis("SOLUSDT", interval="5m", limit=80)
    assert sol_analysis is not None and "is_breakout_long" in sol_analysis and "close_strength_long" in sol_analysis
    print(f"  ✓ Радар отобрал {len(tickers)} ликвидных пар; структурный разбор SOLUSDT корректен (CLV={sol_analysis['close_strength_long']})")

    # 3. ТЕСТ АСИММЕТРИЧНОГО ВЫХОДА (30% / 30% / 40% RUNNER) И ЧЕСТНОГО УЧЕТА 1 ПОЗИЦИЯ = 1 СДЕЛКА
    print("\n[ТЕСТ 3/6] Проверка выхода 30%/30%/40% и консолидации 1 позиции в 1 сделку...")
    portfolio.open_positions.clear()
    portfolio.trade_history.clear()
    portfolio.symbol_lockouts.clear()
    portfolio.consecutive_losses = 0
    portfolio.daily_losses_count = 0
    portfolio.pause_until = 0.0
    portfolio.cash = 20.0

    # Вход $10.0, SL $9.88 (-1.2%), маржа $3.80, плечо 12x -> при открытии Equity ОБЯЗАН оставаться $20.00!
    opened = portfolio.open_position(
        symbol="PEPEUSDT", side="LONG", entry_price=10.0, size_usdt=3.80,
        wick_sl=9.88, tp1=10.18, tp2=10.36, groq_reason="Rocket Breakout Test",
        leverage=12, atr_pct=0.006, risk_usd=0.50
    )
    assert opened
    summary_open = portfolio.get_portfolio_summary()
    assert abs(summary_open["equity"] - 20.0) < 0.01, f"Equity при открытии должен быть $20.00, а не ${summary_open['equity']}"
    print(f"  ✓ Позиция открыта: Cash=${summary_open['cash']:.2f}, Залог=${summary_open['locked_margin']:.2f}, Equity=${summary_open['equity']:.2f}")

    # Шаг 1: TP1 (+1.8% = 1.5R) -> закрываем 30%
    portfolio.close_position("PEPEUSDT", 10.18, "🎯 TP1 1.5R: 30% в кэш", partial_pct=config.TP1_PARTIAL_PCT)
    assert len(portfolio.trade_history) == 0, "Частичный тейк НЕ должен раздувать историю сделок до закрытия позиции!"
    assert "PEPEUSDT" in portfolio.open_positions

    # Шаг 2: TP2 (+3.6% = 3.0R) -> закрываем еще 30% от исходной (42.86% от остатка), оставляя 40% ранера
    portfolio.close_position("PEPEUSDT", 10.36, "🎯 TP2 3.0R: еще 30% в кэш", partial_pct=config.TP2_PARTIAL_OF_REMAINING)
    assert len(portfolio.trade_history) == 0
    rem_mg = portfolio.open_positions["PEPEUSDT"]["margin_usdt"]
    assert abs(rem_mg - 3.80 * 0.40) < 0.02, f"Доля ранера должна быть 40% ($1.52), получено ${rem_mg:.2f}"

    # Шаг 3: Ранер 40% ловит ракету +7.5% ($10.75) и закрывается по ATR-трейлингу!
    portfolio.close_position("PEPEUSDT", 10.75, "🚀 ATR Runner Trail", partial_pct=1.0)
    assert "PEPEUSDT" not in portfolio.open_positions
    assert len(portfolio.trade_history) == 1, "Вся позиция (TP1+TP2+Runner) должна записаться ровно как 1 сделка!"
    rec = portfolio.trade_history[0]
    print(f"  ✓ Ракета закрыта 1 единой сделкой: PnL ${rec['realized_pnl']:+.2f} ({rec['roi_pct']:+.1f}%) | {rec['reason']}")
    assert portfolio.cash > 21.5, f"Баланс должен существенно вырасти на ракете, получено ${portfolio.cash:.2f}"

    # 4. ТЕСТ TIME-STOP БЕЗ ЛОЖНОЙ БЛОКИРОВКИ CIRCUIT BREAKER
    print("\n[ТЕСТ 4/6] Проверка мягкого Time-Stop (не замораживает бота на околонулевом выходе)...")
    portfolio.open_position("SUIUSDT", "LONG", 2.0, 3.0, 1.97, 2.045, 2.09, "Test TimeStop", 12)
    portfolio.close_position("SUIUSDT", 1.999, "⏱️ Time-Stop (35м без импульса)", partial_pct=1.0)
    assert portfolio.daily_losses_count == 0, "Околонулевой скретч по Time-Stop не должен тратить дневной лимит стопов!"
    print(f"  ✓ Time-Stop закрыл вялую сделку (${portfolio.trade_history[-1]['realized_pnl']:+.2f}) без срабатывания аварийного лимита стопов.")

    # 5. ТЕСТ CIRCUIT BREAKER НА РЕАЛЬНЫХ СТОП-ЛОССАХ
    print("\n[ТЕСТ 5/6] Проверка защиты капитала при 2 реальных стоп-лоссах подряд...")
    portfolio.consecutive_losses = 0
    portfolio.pause_until = 0.0
    portfolio.open_position(" LOSS1USDT", "LONG", 1.0, 4.0, 0.988, 1.018, 1.036, "SL1", 12)
    portfolio.close_position(" LOSS1USDT", 0.988, "🛑 Structural Stop", partial_pct=1.0)
    assert portfolio.consecutive_losses == 1 and portfolio.pause_until == 0.0

    portfolio.open_position("LOSS2USDT", "LONG", 1.0, 4.0, 0.988, 1.018, 1.036, "SL2", 12)
    portfolio.close_position("LOSS2USDT", 0.988, "🛑 Structural Stop", partial_pct=1.0)
    assert portfolio.consecutive_losses == 2 and portfolio.pause_until > time.time()
    print(f"  ✓ После 2 реальных стопов активирована пауза охлаждения на {int(portfolio.pause_until - time.time())} сек!")

    # 6. ТЕСТ СОГЛАСОВАННОСТИ GROQ ENGINE С RSI 78 НА ПРОБОЕ
    print("\n[ТЕСТ 6/6] Проверка одобрения пробоя с RSI=79 и Marubozu-свечой (нижний фитиль 0%)...")
    brk_ctx = {
        "symbol": "ENAUSDT", "candidate_side": "LONG", "current_price": 1.05,
        "volume_surge_ratio": 2.9, "upper_wick_pct": 0.05, "lower_wick_pct": 0.00,
        "close_strength_long": 0.95, "rsi": 79.5, "ema21_ext_pct": 0.018,
        "sl_pct_distance": 0.011, "wick_stop_loss": 1.0385, "ml_prob": 0.62
    }
    algo_res = groq_engine._algorithmic_eval(brk_ctx)
    assert algo_res["decision"] == "BUY", f"Marubozu-ракета с RSI 79.5 должна одобряться, а не отклоняться! {algo_res}"
    print(f"  ✓ Marubozu-пробой одобрен: {algo_res['decision']} (conf={algo_res['confidence']}) — {algo_res['reason']}")

    await binance_client.close()
    print("\n" + "=" * 78)
    print("🎉 ВСЕ 6 СИСТЕМ STRUCTURAL ROCKET HUNTER ПРОШЛИ ПРОВЕРКУ НА 100%!")
    print("=" * 78)


if __name__ == "__main__":
    asyncio.run(run_suite())
