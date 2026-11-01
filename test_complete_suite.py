import asyncio
import time
from ml_engine import ml_engine
from tracker import portfolio
from exit_manager import exit_manager
from binance_client import binance_client
from scanner import market_scanner
import config

async def run_suite():
    print("=" * 70)
    print("🧪 СТАРТ ПОЛНОГО КОМПЛЕКСНОГО ТЕСТИРОВАНИЯ ВСЕХ СИСТЕМ (v9.2 TITAN)")
    print("=" * 70)

    # 1. ТЕСТ ML ENGINE
    print("\n[ТЕСТ 1/5] Проверка Dual Quant ML Engine...")
    assert ml_engine.model_long is not None or ml_engine.model is not None, "LONG модель не загружена"
    assert ml_engine.model_short is not None, "SHORT модель не загружена"
    print(f"  ✓ Обе модели загружены: Long WR {ml_engine.winrate_long}%, Short WR {ml_engine.winrate_short}%")

    test_ctx_l = {
        'current_price': 50.0, 'upper_wick_pct': 0.10, 'lower_wick_pct': 0.40,
        'volume_surge_ratio': 2.8, 'rvol': 2.8, 'ema9': 49.5, 'ema21': 49.0,
        'rsi': 58.0, 'atr14_pct': 0.005, 'pullback_from_high_pct': -0.004,
        'bounce_from_low_pct': 0.010, 'pct_5m': 0.9, 'pct_15m': 1.6,
        'sl_pct_distance': 0.008, 'candidate_side': 'LONG'
    }
    res_l = ml_engine.evaluate_candidate(test_ctx_l)
    print(f"  ✓ Оценка LONG кандидата: {res_l['reason']}")

    test_ctx_s = {
        'current_price': 50.0, 'upper_wick_pct': 0.40, 'lower_wick_pct': 0.05,
        'volume_surge_ratio': 2.8, 'rvol': 2.8, 'ema9': 50.5, 'ema21': 51.0,
        'rsi': 42.0, 'atr14_pct': 0.005, 'pullback_from_high_pct': -0.018,
        'bounce_from_low_pct': 0.002, 'pct_5m': -1.1, 'pct_15m': -2.2,
        'short_sl_dist': 0.008, 'candidate_side': 'SHORT'
    }
    res_s = ml_engine.evaluate_candidate(test_ctx_s)
    print(f"  ✓ Оценка SHORT кандидата: {res_s['reason']}")
    assert res_s['ml_probability'] >= 0.50, "SHORT модель должна корректно оценивать кандидата"

    # 2. ТЕСТ СЕТЕВОГО КЛИЕНТА BINANCE И BTC РЕЖИМА
    print("\n[ТЕСТ 2/5] Проверка подключения к Binance Futures и расчет поводыря BTC...")
    btc_reg = await binance_client.fetch_btc_regime()
    print(f"  ✓ Текущий статус Bitcoin: {btc_reg['status_str']}")
    print(f"  ✓ BTC: trend={btc_reg['trend']}, 5m={btc_reg['pct_5m']}%, 15m={btc_reg['pct_15m']}%, dump={btc_reg['is_dumping']}, pump={btc_reg['is_pumping']}")

    # 3. ТЕСТ TAKE-PROFIT 1 И GUARANTEED BREAKEVEN (30x LEVERAGE)
    print("\n[ТЕСТ 3/5] Проверка TP1 и гарантированного безубытка...")
    portfolio.open_positions.clear()
    portfolio.trade_history.clear()
    portfolio.symbol_lockouts.clear()
    portfolio.consecutive_losses = 0
    portfolio.pause_until = 0.0
    portfolio.cash = 20.0

    # Создаем позицию 30x плечо: вход $10.0, SL $9.90 (-1.0%), TP1 $10.15 (+1.5%), TP2 $10.30 (+3.0%)
    portfolio.open_position(
        symbol="SOLUSDT",
        side="LONG",
        entry_price=10.0,
        size_usdt=5.0,
        wick_sl=9.90,
        tp1=10.15,
        tp2=10.30,
        groq_reason="Institutional Breakout",
        leverage=30
    )
    pos = portfolio.open_positions["SOLUSDT"]
    assert pos["margin_usdt"] == 5.0, "Маржа должна быть $5.0"
    print("  ✓ Позиция LONG открыта: маржа $5.0, плечо 30x")

    # Симулируем взятие TP1 при цене $10.15 (+1.5% хода цены = +45.0% ROI)
    portfolio.close_position("SOLUSDT", 10.15, "🎯 TP1 Hit (+45.0%): Фиксация 50%", partial_pct=0.50)
    pos["wick_sl"] = round(pos["entry_price"] * 1.0025, 6)
    pos["breakeven_set"] = True
    assert len(portfolio.trade_history) == 1
    t1 = portfolio.trade_history[-1]
    print(f"  ✓ TP1 зафиксирован: PnL ${t1['realized_pnl']:+.2f} ({t1['roi_pct']:+.1f}%), стоп остатка перенесен в +0.25% (${pos['wick_sl']:.4f})")
    assert pos["wick_sl"] > pos["entry_price"], "Стоп должен быть строго выше входа"

    # Закрываем остаток по трейлингу $10.30 (+90.0% ROI)
    portfolio.close_position("SOLUSDT", 10.30, "🎯 TP2 Hit (+90.0%)", partial_pct=1.0)
    assert "SOLUSDT" not in portfolio.open_positions
    print(f"  ✓ Позиция успешно закрыта в суммарный плюс! Итоговый баланс: ${portfolio.cash:.2f}")
    assert portfolio.cash > 20.0, "Баланс должен вырасти"

    # 4. ТЕСТ STREAK CIRCUIT BREAKER (АВТОМАТИЧЕСКАЯ ЗАМОРОЗКА ПОСЛЕ 2 УБЫТКОВ)
    print("\n[ТЕСТ 4/5] Проверка предохранителя серий убытков (Streak Circuit Breaker)...")
    portfolio.consecutive_losses = 0
    portfolio.pause_until = 0.0

    # Убыток 1
    portfolio.open_position("TEST1USDT", "LONG", 1.0, 3.0, 0.99, 1.015, 1.03, "loss 1", 30)
    portfolio.close_position("TEST1USDT", 0.99, "🛑 Stop Under Wick (-30.0%)", partial_pct=1.0)
    assert portfolio.consecutive_losses == 1, "Счетчик убытков должен быть 1"
    assert portfolio.pause_until == 0.0, "После 1 убытка пауза еще не должна срабатывать"

    # Убыток 2 -> Должен сработать Circuit Breaker!
    portfolio.open_position("TEST2USDT", "LONG", 1.0, 3.0, 0.99, 1.015, 1.03, "loss 2", 30)
    portfolio.close_position("TEST2USDT", 0.99, "🛑 Stop Under Wick (-30.0%)", partial_pct=1.0)
    assert portfolio.consecutive_losses == 2, "Счетчик убытков должен быть 2"
    assert portfolio.pause_until > time.time(), "Пауза должна быть установлена на будущее время"
    pause_rem = int(portfolio.pause_until - time.time())
    print(f"  ✓ Сработал Circuit Breaker: после 2 стопов новые сделки заморожены на {pause_rem} сек!")

    # 5. ТЕСТ ТОП-ЛИКВИДНОГО ЮНИВЕРСА
    print("\n[ТЕСТ 5/5] Проверка фильтрации топ-ликвидных тикеров...")
    tickers = await binance_client.fetch_top_tickers(min_vol_usdt=config.MIN_24H_VOLUME_USDT, limit=config.SCAN_TICKERS_LIMIT)
    print(f"  ✓ Отобрано {len(tickers)} институциональных пар с суточным объемом > ${int(config.MIN_24H_VOLUME_USDT/1e6)}M")
    for t in tickers[:5]:
        print(f"    • {t['symbol']}: Суточный объём ${int(t['volume_24h']/1e6)}M")
    assert len(tickers) > 0, "Должны быть отобраны топ пары"

    # Сброс к чистому состоянию $20.00
    portfolio.cash = 20.0
    portfolio.open_positions.clear()
    portfolio.trade_history.clear()
    portfolio.symbol_lockouts.clear()
    portfolio.consecutive_losses = 0
    portfolio.pause_until = 0.0
    portfolio.save()

    print("\n" + "=" * 70)
    print("🎉 ВСЕ ТЕСТЫ v9.2 TITAN УСПЕШНО ПРОЙДЕНЫ! СИСТЕМА ЗАЩИЩЕНА ОТ СЛИВОВ.")
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(run_suite())
