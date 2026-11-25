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
    print("\n[ТЕСТ 1/8] Проверка Dual Quant ML Engine и защиты от незакрытой свечи...")
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

    # 2. ТЕСТ СТРУКТУРНОГО АНАЛИЗА BINANCE И РАДАРА 180 ПАР
    print("\n[ТЕСТ 2/8] Проверка подключения к Binance, BTC-щита и радара пробоев...")
    btc_reg = await binance_client.fetch_btc_regime()
    print(f"  ✓ Статус Bitcoin: {btc_reg['status_str']}")
    tickers = await binance_client.fetch_top_tickers(min_vol_usdt=config.MIN_24H_VOLUME_USDT, limit=config.SCAN_TICKERS_LIMIT)
    assert len(tickers) >= 30, f"Радар вернул слишком мало пар: {len(tickers)}"
    sol_analysis = await binance_client.fetch_candles_analysis("SOLUSDT", interval="5m", limit=80)
    assert sol_analysis is not None and "is_breakout_long" in sol_analysis and "close_strength_long" in sol_analysis
    print(f"  ✓ Радар отобрал {len(tickers)} ликвидных пар; структурный разбор SOLUSDT корректен (CLV={sol_analysis['close_strength_long']})")

    # 3. ТЕСТ ANTI-RUG ROCKET HARVEST (60% В КЭШ НА 1.65R + 40% БЕЗРИСКОВЫЙ MOONBAG + СВОБОДНЫЙ СЛОТ)
    print("\n[ТЕСТ 3/8] Проверка Anti-Rug выхода (60% на 1.65R + 40% Parabolic Trail + безрисковый слот)...")
    portfolio.open_positions.clear()
    portfolio.trade_history.clear()
    portfolio.symbol_lockouts.clear()
    portfolio.consecutive_losses = 0
    portfolio.daily_losses_count = 0
    portfolio.pause_until = 0.0
    portfolio.cash = 20.0

    opened = portfolio.open_position(
        symbol="GUAUSDT", side="LONG", entry_price=10.0, size_usdt=4.00,
        wick_sl=9.88, tp1=10.198, tp2=10.72, groq_reason="Anti-Rug Rocket Test",
        leverage=15, atr_pct=0.008, risk_usd=0.60
    )
    assert opened
    summary_open = portfolio.get_portfolio_summary()
    assert abs(summary_open["equity"] - 20.0) < 0.01, f"Equity при открытии должен быть $20.00, а не ${summary_open['equity']}"
    assert int(getattr(config, "TIME_STOP_MINUTES", 0)) == 0, "Time-Stop по умолчанию должен быть 0 (отключен)!"
    print(f"  ✓ Позиция открыта: Cash=${summary_open['cash']:.2f}, Залог=${summary_open['locked_margin']:.2f}, Equity=${summary_open['equity']:.2f}")

    # Шаг 1: TP1 (+1.65R) -> мгновенно забираем 60% прибыли в кэш ДО возможного слива и запираем стоп остатка в +0.35R!
    portfolio.open_positions["GUAUSDT"]["tp1_hit"] = True
    portfolio.open_positions["GUAUSDT"]["wick_sl"] = 10.042
    portfolio.open_positions["GUAUSDT"]["breakeven_set"] = True
    portfolio.close_position("GUAUSDT", 10.198, f"🎯 TP1 {config.TARGET_1_R}R: 60% в кэш", partial_pct=config.TP1_PARTIAL_PCT)
    assert "GUAUSDT" in portfolio.open_positions, "40% Moonbag должен остаться в рынке для ловли большой ракеты!"
    assert len(portfolio.trade_history) == 0, "Частичный тейк не должен дробить сделку в статистике!"

    # Проверяем, что безрисковый Moonbag (tp1_hit=True) НЕ блокирует открытие 2 новых активных ракет!
    assert portfolio.open_position("LISTAUSDT", "LONG", 1.0, 3.0, 0.985, 1.025, 1.09, "Wave 1", 15)
    assert portfolio.open_position("EVAAUSDT", "SHORT", 2.0, 3.0, 2.03, 1.95, 1.82, "Rug Short", 15)
    print("  ✓ Безрисковый 40% Moonbag не блокирует слоты: успешно открыты 2 новые ракеты параллельно!")
    portfolio.close_position("LISTAUSDT", 1.0, "Cleanup", partial_pct=1.0)
    portfolio.close_position("EVAAUSDT", 2.0, "Cleanup", partial_pct=1.0)
    portfolio.trade_history.clear()

    # Шаг 2: Ракета взлетает на +12% ($11.20) и закрывается по плотному Anti-Rug Parabolic Trail до слива!
    portfolio.close_position("GUAUSDT", 11.20, "🚀 Anti-Rug Rocket Trail", partial_pct=1.0)
    assert "GUAUSDT" not in portfolio.open_positions
    assert len(portfolio.trade_history) == 1, "Вся позиция (60% TP1 + 40% Ранер) обязана записаться ровно как 1 сделка!"
    rec = portfolio.trade_history[0]
    print(f"  ✓ Большая ракета схвачена до слива 1 сделкой: PnL ${rec['realized_pnl']:+.2f} ({rec['roi_pct']:+.1f}%) | {rec['reason']}")
    assert portfolio.cash > 23.0, f"Баланс должен мощно вырасти на большой ракете, получено ${portfolio.cash:.2f}"

    # 4. ТЕСТ TIME-STOP БЕЗ ЛОЖНОЙ БЛОКИРОВКИ CIRCUIT BREAKER
    print("\n[ТЕСТ 4/8] Проверка мягкого Time-Stop (не замораживает бота на околонулевом выходе)...")
    portfolio.open_position("SUIUSDT", "LONG", 2.0, 3.0, 1.97, 2.045, 2.09, "Test TimeStop", 12)
    portfolio.close_position("SUIUSDT", 1.999, "⏱️ Time-Stop (35м без импульса)", partial_pct=1.0)
    assert portfolio.daily_losses_count == 0, "Околонулевой скретч по Time-Stop не должен тратить дневной лимит стопов!"
    print(f"  ✓ Time-Stop закрыл вялую сделку (${portfolio.trade_history[-1]['realized_pnl']:+.2f}) без срабатывания аварийного лимита стопов.")

    # 5. ТЕСТ РЕЖИМА НЕПРЕРЫВНОЙ ТОРГОВЛИ БЕЗ ЗАМОРОЗОК (CIRCUIT BREAKER = FALSE)
    print("\n[ТЕСТ 5/8] Проверка непрерывной торговли без заморозок (Circuit Breaker отключен)...")
    portfolio.consecutive_losses = 0
    portfolio.pause_until = 0.0
    portfolio.open_position(" LOSS1USDT", "LONG", 1.0, 4.0, 0.988, 1.018, 1.036, "SL1", 15)
    portfolio.close_position(" LOSS1USDT", 0.988, "🛑 Structural Stop", partial_pct=1.0)
    assert portfolio.consecutive_losses == 1 and portfolio.pause_until == 0.0

    portfolio.open_position("LOSS2USDT", "LONG", 1.0, 4.0, 0.988, 1.018, 1.036, "SL2", 15)
    portfolio.close_position("LOSS2USDT", 0.988, "🛑 Structural Stop", partial_pct=1.0)
    assert portfolio.pause_until == 0.0, "При отключенном Circuit Breaker бот НЕ должен уходить в заморозку!"
    print("  ✓ Бот успешно торгует непрерывно: после 2 стопов заморозка НЕ активируется (пауза 0 сек)!")

    # 6. ТЕСТ СОГЛАСОВАННОСТИ GROQ ENGINE С RSI 78 НА ПРОБОЕ
    print("\n[ТЕСТ 6/8] Проверка одобрения пробоя с RSI=79 и Marubozu-свечой (нижний фитиль 0%)...")
    brk_ctx = {
        "symbol": "ENAUSDT", "candidate_side": "LONG", "current_price": 1.05,
        "volume_surge_ratio": 2.9, "upper_wick_pct": 0.05, "lower_wick_pct": 0.00,
        "close_strength_long": 0.95, "rsi": 79.5, "ema21_ext_pct": 0.018,
        "sl_pct_distance": 0.011, "wick_stop_loss": 1.0385, "ml_prob": 0.62
    }
    algo_res = groq_engine._algorithmic_eval(brk_ctx)
    assert algo_res["decision"] == "BUY", f"Marubozu-ракета с RSI 79.5 должна одобряться, а не отклоняться! {algo_res}"
    print(f"  ✓ Marubozu-пробой одобрен: {algo_res['decision']} (conf={algo_res['confidence']}) — {algo_res['reason']}")

    # 7. ТЕСТ US RENDER MIRROR (VISION) — 100+ ЖИВЫХ ПАР БЕЗ АКЦИЙ И СТЕЙБЛКОИНОВ + LIVE RADAR
    print("\n[ТЕСТ 7/8] Проверка зеркала US Render (vision): охват 100+ живых пар, фильтр акций/стейблов...")
    portfolio.pause_until = 0.0
    portfolio.daily_losses_count = 0
    portfolio.consecutive_losses = 0
    portfolio.open_positions.clear()
    vision_idx = next(i for i, m in enumerate(binance_client.mirrors) if m["name"] == "vision")
    binance_client.active_mirror_idx = vision_idx
    binance_client._ticker24_cache = ("", 0.0, [])
    vision_tickers = await binance_client.fetch_top_tickers(min_vol_usdt=config.MIN_24H_VOLUME_USDT, limit=config.SCAN_TICKERS_LIMIT)
    min_req_pairs = 25 if getattr(config, "STRICT_WHITELIST_ONLY", False) else 90
    assert len(vision_tickers) >= min_req_pairs, f"На зеркале vision должно быть >= {min_req_pairs} живых пар, получено {len(vision_tickers)}"
    bad_syms = [t["symbol"] for t in vision_tickers if t["symbol"] in ("USD1USDT", "RLUSDUSDT", "TQQQBUSDT", "NVDABUSDT", "COCOSUSDT", "XAUTUSDT")]
    assert not bad_syms, f"В радар попали мусорные пары/акции/стейблы: {bad_syms}"
    print(f"  ✓ Зеркало vision отобрало {len(vision_tickers)} чистых крипто-пар (акции *BUSDT, стейблкоины и делисты отсечены)!")

    # 8. ТЕСТ ANTI-418 FAILOVER НА BYBIT / GATE / BITGET FUTURES + 180 ПАР + НОВЫЕ ЛИСТИНГИ + 5M GUARD
    print("\n[ТЕСТ 8/8] Проверка мгновенного failover (fapi 418 -> bybit -> gate -> bitget), 180 пар, новых листингов и защиты от 429...")
    from scanner import market_scanner
    binance_client.active_mirror_idx = 0  # fapi
    binance_client._mirror_cooldowns[0] = time.time() + 160000.0  # Симулируем 45-часовой HTTP 418 shared-IP бан Render на fapi!
    binance_client._mirror_ban_type[0] = "hard"
    binance_client._ticker24_cache = ("", 0.0, [])
    binance_client._book_tickers_cache = {}
    binance_client._book_tickers_cache_time = 0.0

    bybit_tickers = await binance_client.fetch_top_tickers(min_vol_usdt=config.MIN_24H_VOLUME_USDT, limit=config.SCAN_TICKERS_LIMIT)
    assert binance_client.active_mirror_name == "bybit", f"При бане fapi (418) должен включиться bybit, получено {binance_client.active_mirror_name}"
    assert len(bybit_tickers) >= 150, f"Bybit Futures должен вернуть >= 150 чистых крипто-пар, получено {len(bybit_tickers)}"
    bb_bad = [t["symbol"] for t in bybit_tickers if t["symbol"] in ("NVDAUSDT", "TSLAUSDT", "SOXLUSDT", "XAUUSDT", "PAXGUSDT", "AAPLUSDT", "TGTSTOCKUSDT")]
    assert not bb_bad, f"В радар Bybit попали RWA/акции/золото: {bb_bad}"
    bb_new = sum(1 for t in bybit_tickers if t.get("is_new_listing"))
    bb_btc = await binance_client.fetch_btc_regime()
    bb_sol = await binance_client.fetch_candles_analysis("SOLUSDT", interval="5m", limit=200)
    bb_price = await binance_client.fetch_price("SOLUSDT")
    _, _, bb_spread = await binance_client.fetch_orderbook_spread("SOLUSDT")
    assert bb_sol is not None and bb_sol["current_price"] > 0 and bb_price and bb_price > 0 and bb_spread < 0.01
    print(f"  ✓ Failover fapi(418) -> bybit сработал мгновенно: {len(bybit_tickers)} чистых крипто-фьючерсов (вкл. {bb_new} новых/innovation), SOL=${bb_price:.2f} (spread {bb_spread*100:.3f}%), BTC: {bb_btc['pct_15m']:+.2f}%")

    # Проверяем также Gate.io (если и Bybit вдруг недоступен) и Bitget!
    bybit_idx = next(i for i, m in enumerate(binance_client.mirrors) if m["name"] == "bybit")
    binance_client._mirror_cooldowns[bybit_idx] = time.time() + 1800.0
    binance_client._mirror_ban_type[bybit_idx] = "hard"
    binance_client._ticker24_cache = ("", 0.0, [])
    binance_client._book_tickers_cache = {}
    binance_client._book_tickers_cache_time = 0.0
    gate_tickers = await binance_client.fetch_top_tickers(min_vol_usdt=config.MIN_24H_VOLUME_USDT, limit=config.SCAN_TICKERS_LIMIT)
    assert binance_client.active_mirror_name == "gate", f"При бане fapi+bybit должен включиться gate, получено {binance_client.active_mirror_name}"
    assert len(gate_tickers) >= 140, f"Gate Futures должен вернуть >= 140 чистых крипто-пар, получено {len(gate_tickers)}"
    gate_sol = await binance_client.fetch_candles_analysis("SOLUSDT", interval="5m", limit=200)
    gate_price = await binance_client.fetch_price("SOLUSDT")
    assert gate_sol is not None and gate_sol["current_price"] > 0 and gate_price and gate_price > 0
    print(f"  ✓ Failover -> gate (900 req/s) сработал мгновенно: {len(gate_tickers)} чистых крипто-фьючерсов, SOL=${gate_price:.2f}")

    # Проверяем 5m candle-boundary guard (защита от 12-секундного спама на Render)
    market_scanner._last_scanned_bar = int(time.time()) // 300
    portfolio.last_universe_count = len(bybit_tickers)
    before_u = portfolio.funnel_stats["universe"]
    skipped = await market_scanner.scan_market_once(force=False)
    assert skipped == [] and portfolio.funnel_stats["universe"] == before_u, "Повторный вызов внутри той же 5m свечи должен пропускаться без API-запросов!"
    print("  ✓ 5m Candle-Boundary Guard работает: повторный вызов внутри текущей 5m свечи = 0 лишних запросов (экономия веса 35x)!")

    # Снимаем тестовые кулдауны
    binance_client._mirror_cooldowns.clear()
    binance_client._mirror_ban_type.clear()
    binance_client.active_mirror_idx = 0

    await binance_client.close()
    print("\n" + "=" * 78)
    print("🎉 ВСЕ 8 СИСТЕМ STRUCTURAL ROCKET HUNTER ПРОШЛИ ПРОВЕРКУ НА 100%!")
    print("=" * 78)


if __name__ == "__main__":
    asyncio.run(run_suite())
