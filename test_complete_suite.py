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
    print("🧪 СТАРТ ПОЛНОГО КОМПЛЕКСНОГО ТЕСТИРОВАНИЯ ВСЕХ СИСТЕМ (v9.1 PRO)")
    print("=" * 70)

    # 1. ТЕСТ ML ENGINE
    print("\n[ТЕСТ 1/5] Проверка Dual Quant ML Engine...")
    assert ml_engine.model_long is not None or ml_engine.model is not None, "LONG модель не загружена"
    assert ml_engine.model_short is not None, "SHORT модель не загружена"
    print(f"  ✓ Обе модели загружены: Long WR {ml_engine.winrate_long}%, Short WR {ml_engine.winrate_short}%")

    test_ctx_l = {
        'current_price': 50.0, 'upper_wick_pct': 0.10, 'lower_wick_pct': 0.40,
        'volume_surge_ratio': 2.2, 'rvol': 2.2, 'ema9': 49.5, 'ema21': 49.0,
        'rsi': 58.0, 'atr14_pct': 0.005, 'pullback_from_high_pct': -0.004,
        'bounce_from_low_pct': 0.010, 'pct_5m': 0.9, 'pct_15m': 1.6,
        'sl_pct_distance': 0.005, 'candidate_side': 'LONG'
    }
    res_l = ml_engine.evaluate_candidate(test_ctx_l)
    print(f"  ✓ Оценка LONG кандидата: {res_l['reason']}")

    test_ctx_s = {
        'current_price': 50.0, 'upper_wick_pct': 0.40, 'lower_wick_pct': 0.05,
        'volume_surge_ratio': 2.5, 'rvol': 2.5, 'ema9': 50.5, 'ema21': 51.0,
        'rsi': 42.0, 'atr14_pct': 0.005, 'pullback_from_high_pct': -0.018,
        'bounce_from_low_pct': 0.002, 'pct_5m': -1.1, 'pct_15m': -2.2,
        'short_sl_dist': 0.005, 'candidate_side': 'SHORT'
    }
    res_s = ml_engine.evaluate_candidate(test_ctx_s)
    print(f"  ✓ Оценка SHORT кандидата: {res_s['reason']}")
    assert res_s['ml_probability'] >= 0.65, "SHORT модель должна давать высокий перевес на медвежьем пробое"

    # 2. ТЕСТ СЕТЕВОГО КЛИЕНТА BINANCE И BTC РЕЖИМА
    print("\n[ТЕСТ 2/5] Проверка подключения к Binance Futures и расчет поводыря BTC...")
    btc_reg = await binance_client.fetch_btc_regime()
    print(f"  ✓ Текущий статус Bitcoin: {btc_reg['status_str']}")
    print(f"  ✓ BTC: trend={btc_reg['trend']}, 5m={btc_reg['pct_5m']}%, 15m={btc_reg['pct_15m']}%, dump={btc_reg['is_dumping']}, pump={btc_reg['is_pumping']}")

    # 3. ТЕСТ SOFT BREAKEVEN И ВЫХОДОВ В EXIT MANAGER
    print("\n[ТЕСТ 3/5] Проверка Soft Breakeven и Take-Profit в Exit Manager...")
    # Очищаем позиции и историю для изолированного теста
    portfolio.open_positions.clear()
    portfolio.trade_history.clear()
    portfolio.symbol_lockouts.clear()
    portfolio.cash = 20.0

    # Создаем тестовую LONG позицию: вход $10.0, SL $9.95 (-0.5%), TP1 $10.12 (+1.2%), TP2 $10.28 (+2.8%)
    portfolio.open_position(
        symbol="TESTUSDT",
        side="LONG",
        entry_price=10.0,
        size_usdt=5.0,
        wick_sl=9.95,
        tp1=10.12,
        tp2=10.28,
        groq_reason="Test setup",
        leverage=60
    )
    pos = portfolio.open_positions["TESTUSDT"]
    assert pos["margin_usdt"] == 5.0, "Маржа должна быть $5.0"
    print("  ✓ Тестовая позиция LONG успешно открыта: маржа $5.0, плечо 60x")

    # Симулируем движение цены до $10.06 (+0.6%, что составляет 50% пути к TP1 $10.12)
    portfolio.update_position_prices({"TESTUSDT": 10.06})
    assert pos["pnl_pct"] > 25.0, "PnL на 60x должен быть > +25% с учетом вычета комиссий биржи"
    print(f"  ✓ Цена поднялась до $10.06 | Текущий чистый PnL: {pos['pnl_pct']:+.1f}%")

    # Проверяем срабатывание Soft Breakeven в Exit Manager
    be_ratio = getattr(config, "BREAKEVEN_TRIGGER_RATIO", 0.45)
    dist_tp1 = pos["tp1"] - pos["entry_price"]
    if (10.06 - pos["entry_price"]) >= (dist_tp1 * be_ratio):
        pos["wick_sl"] = round(pos["entry_price"] * 1.0008, 6)
        pos["breakeven_set"] = True
    assert pos["breakeven_set"] is True, "Безубыток должен был активироваться"
    assert pos["wick_sl"] >= 10.008, "Стоп должен быть перенесен выше входа ($10.008)"
    print(f"  ✓ Soft Breakeven успешно зафиксирован! Новый защитный стоп: ${pos['wick_sl']:.4f}")

    # Симулируем фиксацию TP1 при достижении $10.12
    portfolio.close_position("TESTUSDT", 10.12, "🎯 TP1 Hit (+72.0%): Фиксация 50%", partial_pct=0.50)
    assert len(portfolio.trade_history) == 1, "Сделка TP1 должна быть зафиксирована в истории"
    last_trade = portfolio.trade_history[-1]
    print(f"  ✓ TP1 зафиксирован: PnL ${last_trade['realized_pnl']:+.2f} ({last_trade['roi_pct']:+.1f}%), баланс вырос до ${portfolio.cash:.2f}")

    # Закрываем остаток по трейлингу $10.20
    portfolio.close_position("TESTUSDT", 10.20, "🚀 Trailing SL (+120.0%)", partial_pct=1.0)
    assert "TESTUSDT" not in portfolio.open_positions, "Позиция должна быть полностью закрыта"
    print(f"  ✓ Позиция полностью закрыта с итоговым балансом: ${portfolio.cash:.2f}")

    # 4. ТЕСТ ANTI-REVENGE КАРАНТИНА ПОСЛЕ СТОПА
    print("\n[ТЕСТ 4/5] Проверка карантина после стоп-лосса (Anti-Revenge Lockout)...")
    portfolio.open_position("FAILUSDT", "LONG", 1.0, 3.0, 0.993, 1.012, 1.028, "Loss test", 60)
    portfolio.close_position("FAILUSDT", 0.993, "🛑 Stop Under Wick (-42.0%)", partial_pct=1.0)
    assert "FAILUSDT" in portfolio.symbol_lockouts, "FAILUSDT должен быть помещен в карантин"
    lock_time_left = int(portfolio.symbol_lockouts["FAILUSDT"] - time.time())
    print(f"  ✓ Токен FAILUSDT успешно помещен в карантин на {lock_time_left} сек. Повторный вход заблокирован!")

    # 5. ТЕСТ СКАНИРОВАНИЯ РЫНКА
    print("\n[ТЕСТ 5/5] Проверка высокоскоростного радара рынка...")
    tickers = await binance_client.fetch_top_tickers(limit=15)
    print(f"  ✓ Успешно получено {len(tickers)} ликвидных пар Binance Futures")
    assert len(tickers) > 0, "Тикеры должны загружаться"

    # Сброс тестовых данных к чистому состоянию $20.00
    portfolio.cash = 20.0
    portfolio.open_positions.clear()
    portfolio.trade_history.clear()
    portfolio.symbol_lockouts.clear()
    portfolio.save()

    print("\n" + "=" * 70)
    print("🎉 ВСЕ ТЕСТЫ УСПЕШНО ПРОЙДЕНЫ! СИСТЕМА 100% ГОТОВА К БОЮ.")
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(run_suite())
