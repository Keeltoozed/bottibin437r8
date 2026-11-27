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
    sol_analysis = await binance_client.fetch_candles_analysis("SOLUSDT", interval="5m", limit=200)
    assert sol_analysis is not None and "is_breakout_long" in sol_analysis and "close_strength_long" in sol_analysis
    assert "adx14" in sol_analysis and "ema200" in sol_analysis and "has_fvg_bull" in sol_analysis and "ema63" in sol_analysis
    assert "high_12h" in sol_analysis and "anti_wall_long_ok" in sol_analysis and "min_recent_5m_qvol" in sol_analysis
    assert config.ALT_FUTURES_MIN_AVG_5M_VOL >= 2500.0 and config.ENABLE_12H_WALL_GUARD is True
    assert config.INITIAL_BALANCE == 100.0 and config.LEVERAGE == 50 and config.MAX_CONCURRENT_POSITIONS == 15 and config.MAX_SAME_SIDE_POSITIONS == 15 and config.TTL_HOURS == 24
    assert binance_client.last_full_market_count >= 250, f"Полный скринер должен покрывать >= 250 пар, получено {binance_client.last_full_market_count}"
    print(f"  ✓ Скринер охватил {binance_client.last_full_market_count} пар рынка → топ-{len(tickers)} в разборе; SOLUSDT корректен (CLV={sol_analysis['close_strength_long']}, ADX={sol_analysis['adx14']}, 50x/15slots)")

    # 3. ТЕСТ ДИНАМИЧЕСКОГО 3-STAGE ВЫХОДА (TP1 + TP2 + TRAIL + СВОБОДНЫЙ СЛОТ)
    print("\n[ТЕСТ 3/8] Проверка динамического 3-ступенчатого выхода (TP1 + TP2 + Parabolic Trail + 4 слота)...")
    portfolio.open_positions.clear()
    portfolio.trade_history.clear()
    portfolio.symbol_lockouts.clear()
    portfolio.consecutive_losses = 0
    portfolio.daily_losses_count = 0
    portfolio.pause_until = 0.0
    portfolio.cash = 100.0
    portfolio.peak_equity = 100.0

    from scanner import market_scanner
    assert config.FULL_HOLD_MODE is True, "Основная стратегия по умолчанию должна быть FULL_HOLD_MODE=True (100% без вытаскиваний)!"
    fh_plan = market_scanner.compute_dynamic_exit_plan(
        {"breakout_type": "SQUEEZE_80M", "atr14_pct": 0.008, "adx14": 24.0, "has_fvg_bull": True},
        side="LONG", sl_dist=0.012
    )
    assert fh_plan["profile"] == "EXPLOSIVE_FVG" and fh_plan["tp1_r"] == 1.62 and fh_plan["tp2_r"] == 2.55 and fh_plan["tp1_share"] == 0.0 and fh_plan["tp2_share"] == 0.0

    # Проверяем основную стратегию Full-Hold 100% (Lock1 -> Lock2 -> все 100% объема ловят ракету +12%!)
    assert portfolio.open_position("FULLHOLDUSDT", "LONG", 10.0, 3.00, 9.88, 10.228, 10.360, "FullHold 100% Test", leverage=50, atr_pct=0.008, risk_usd=1.80, exit_plan=fh_plan)
    portfolio.open_positions["FULLHOLDUSDT"]["tp1_hit"] = True
    portfolio.open_positions["FULLHOLDUSDT"]["wick_sl"] = 10.048
    portfolio.open_positions["FULLHOLDUSDT"]["breakeven_set"] = True
    portfolio.open_positions["FULLHOLDUSDT"].setdefault("partial_notes", []).append("Lock1(БУ+)")
    portfolio.open_positions["FULLHOLDUSDT"]["tp2_hit"] = True
    portfolio.open_positions["FULLHOLDUSDT"]["wick_sl"] = 10.186
    portfolio.open_positions["FULLHOLDUSDT"]["partial_notes"].append("Lock2(Профит)")
    assert abs(portfolio.open_positions["FULLHOLDUSDT"]["margin_usdt"] - 3.00) < 1e-6, "В Full-Hold 100% маржи ($3.00) обязаны оставаться в сделке!"
    portfolio.close_position("FULLHOLDUSDT", 11.20, "🚀 Big-Runner Rocket Trail", partial_pct=1.0)
    fh_rec = portfolio.trade_history.pop()
    assert fh_rec["realized_pnl"] > 17.5 and "Lock1(БУ+)" in fh_rec["reason"] and "Lock2(Профит)" in fh_rec["reason"]
    print(f"  ✓ Основная стратегия Full-Hold 100% подтверждена: $3.00 @ 50x на +12% дали ${fh_rec['realized_pnl']:+.2f} ({fh_rec['roi_pct']:+.1f}%) целиком без резки объема!")
    portfolio.cash = 100.0

    # Проверяем также альтернативный режим Partial-Split (FULL_HOLD_MODE=False: 35% + 25% + 40%)
    config.FULL_HOLD_MODE = False
    dyn_plan = market_scanner.compute_dynamic_exit_plan(
        {"breakout_type": "SQUEEZE_80M", "atr14_pct": 0.008, "adx14": 24.0, "has_fvg_bull": True},
        side="LONG", sl_dist=0.012
    )
    assert dyn_plan["profile"] == "EXPLOSIVE_FVG" and dyn_plan["tp1_r"] == 1.62 and dyn_plan["tp2_r"] == 2.55 and dyn_plan["tp1_share"] == 0.35
    rug_plan = market_scanner.compute_dynamic_exit_plan(
        {"breakout_type": "RUG_SHORT", "atr14_pct": 0.015, "adx14": 22.0, "has_fvg_bear": True},
        side="SHORT", sl_dist=0.025
    )
    assert rug_plan["profile"] == "FAST_RUG_DUMP" and rug_plan["tp1_r"] == 1.25 and rug_plan["tp2_r"] == 1.95
    config.FULL_HOLD_MODE = True

    opened = portfolio.open_position(
        symbol="GUAUSDT", side="LONG", entry_price=10.0, size_usdt=16.00,
        wick_sl=9.88, tp1=10.228, tp2=10.360, groq_reason="Dynamic 3-TP BigRunner Test",
        leverage=25, atr_pct=0.008, risk_usd=4.00, exit_plan=dyn_plan
    )
    assert opened
    summary_open = portfolio.get_portfolio_summary()
    assert abs(summary_open["equity"] - 100.0) < 0.01, f"Equity при открытии должен быть $100.00, а не ${summary_open['equity']}"
    assert int(getattr(config, "TIME_STOP_MINUTES", 0)) == 0, "Time-Stop по умолчанию должен быть 0 (отключен)!"
    print(f"  ✓ Позиция открыта ({dyn_plan['profile']}): Cash=${summary_open['cash']:.2f}, Залог=${summary_open['locked_margin']:.2f}, Equity=${summary_open['equity']:.2f}")

    # Шаг 1: TP1 (+1.90R) -> забираем 35% в кэш, SL -> +0.40R
    portfolio.open_positions["GUAUSDT"]["tp1_hit"] = True
    portfolio.open_positions["GUAUSDT"]["wick_sl"] = 10.048
    portfolio.open_positions["GUAUSDT"]["breakeven_set"] = True
    portfolio.close_position("GUAUSDT", 10.228, f"🎯 TP1 {dyn_plan['tp1_r']:.2f}R: 35% в кэш", partial_pct=dyn_plan["tp1_share"])
    assert "GUAUSDT" in portfolio.open_positions and abs(portfolio.open_positions["GUAUSDT"]["margin_usdt"] - 10.40) < 0.05

    # Шаг 2: TP2 (+3.00R) -> забираем еще 25% от старта (rem_frac = 0.25/0.65) -> в ранере остается 40% ($6.40)!
    portfolio.open_positions["GUAUSDT"]["tp2_hit"] = True
    rem_frac = dyn_plan["tp2_share"] / (1.0 - dyn_plan["tp1_share"])
    portfolio.close_position("GUAUSDT", 10.360, f"🚀 TP2 {dyn_plan['tp2_r']:.2f}R: еще 25% в кэш", partial_pct=rem_frac)
    assert "GUAUSDT" in portfolio.open_positions and abs(portfolio.open_positions["GUAUSDT"]["margin_usdt"] - 6.40) < 0.05
    assert len(portfolio.trade_history) == 0, "Частичные TP1+TP2 не должны дробить сделку в статистике!"

    # Проверяем, что безрисковый Moonbag (tp1_hit=True) НЕ блокирует открытие до 4 активных ракет параллельно!
    assert portfolio.open_position("LISTAUSDT", "LONG", 1.0, 10.0, 0.985, 1.025, 1.09, "Wave 1", 25)
    assert portfolio.open_position("EVAAUSDT", "SHORT", 2.0, 10.0, 2.03, 1.95, 1.82, "Rug Short", 25)
    assert portfolio.open_position("BTWUSDT", "LONG", 0.5, 10.0, 0.492, 0.514, 0.545, "Wave 2", 25)
    assert portfolio.open_position("MMTUSDT", "LONG", 1.5, 10.0, 1.47, 1.54, 1.65, "Wave 3", 25)
    print("  ✓ Безрисковый 30% Moonbag не блокирует слоты: успешно открыты 4 активные ракеты параллельно (4+1)!")
    for s_c, p_c in [("LISTAUSDT", 1.0), ("EVAAUSDT", 2.0), ("BTWUSDT", 0.5), ("MMTUSDT", 1.5)]:
        portfolio.close_position(s_c, p_c, "Cleanup", partial_pct=1.0)
    portfolio.trade_history.clear()
    portfolio.symbol_lockouts.clear()
    portfolio.daily_losses_count = 0
    portfolio.consecutive_losses = 0

    # Шаг 3: Ракета взлетает на +12% ($11.20) и закрывается по Parabolic Trail!
    portfolio.close_position("GUAUSDT", 11.20, "🚀 Anti-Rug Rocket Trail", partial_pct=1.0)
    assert "GUAUSDT" not in portfolio.open_positions
    assert len(portfolio.trade_history) == 1, "Вся позиция (TP1 + TP2 + Trail) обязана записаться ровно как 1 сделка!"
    rec = portfolio.trade_history[0]
    assert "TP1(35%)" in rec["reason"] and "TP2(25%)" in rec["reason"], f"Неожиданная метка истории: {rec['reason']}"
    print(f"  ✓ Большая ракета схвачена 3-шаговым выходом 1 сделкой: PnL ${rec['realized_pnl']:+.2f} ({rec['roi_pct']:+.1f}%) | {rec['reason']}")
    assert portfolio.cash > 118.0, f"Баланс $100 должен мощно вырасти на большой ракете, получено ${portfolio.cash:.2f}"

    # 3B. ТЕСТ ЧЕСТНОГО CROSS MARGIN (3.5% = $3.50 @ 50x, ПОТОЛОК РИСКА <=3.8%, 15 СЛОТОВ) + LIVE PNL
    assert config.SIZING_MODE == "equal_margin" and abs(config.FIXED_MARGIN_PCT - 0.035) < 1e-6 and abs(config.STOP_LOSS_MAX_PCT - 0.045) < 1e-6
    from exit_manager import exit_manager
    saved_cash = portfolio.cash
    portfolio.cash = 100.0
    portfolio.open_positions.clear()
    eq_m = round((portfolio.cash) * config.FIXED_MARGIN_PCT, 2)
    assert eq_m == 3.50, f"Equal margin от $100 должен быть ровно $3.50 (15 слотов), получено {eq_m}"
    portfolio.open_position("POPCATUSDT", "LONG", 0.02775, eq_m, 0.027198, 0.028661, 0.029197, "EqualMargin Test", leverage=50)
    portfolio.update_position_prices({"POPCATUSDT": 0.02775 * 1.0010})  # +0.10% (+5.0% грязными @ 50x - 2.5% комиссия входа = +2.5%!)
    pop_pos = portfolio.open_positions["POPCATUSDT"]
    assert pop_pos["margin_usdt"] == 3.50 and pop_pos["pnl_pct"] > 2.0, f"При +0.10% на 50x нереализованный PnL должен быть зеленым (>+2%), получено {pop_pos['pnl_pct']}%"
    assert exit_manager._compute_big_runner_trail("LONG", 1.028, 1.00, 0.015, 0.006, 2.3, 1.006, trail_start_r=2.8) == 1.006, "До 2.8R трейл не должен душить позицию!"
    portfolio.open_positions.clear()

    # Проверяем честное Cross-Margin списание при стопе -3.0% на 50x ($3 маржа -> -$4.50 убытка - $0.177 комиссии = -$4.677, т.е. с кэша $100 списывается > $3.00!)
    portfolio.cash = 100.0
    portfolio.open_position("CROSSSLUSDT", "LONG", 1.00, 3.00, 0.97, 1.05, 1.10, "Honest Cross SL Test", leverage=50)
    portfolio.close_position("CROSSSLUSDT", 0.97, "🛑 Structural Stop (-3%)", partial_pct=1.0)
    assert abs(portfolio.cash - 95.3227) < 0.02, f"На честном Cross Margin стоп -3% при $150 объеме обязан оставить ~$95.32 (а не $97.00!), получено ${portfolio.cash:.4f}"
    portfolio.trade_history.pop()
    portfolio.symbol_lockouts.pop("CROSSSLUSDT", None)
    portfolio.daily_losses_count = max(0, portfolio.daily_losses_count - 1)
    portfolio.consecutive_losses = 0
    portfolio.cash = saved_cash
    print(f"  ✓ Честный Cross Margin ($3.00 / $150 @ 50x, стоп -3% списывает полные -$4.68 без читов) и live PnL (+{pop_pos['pnl_pct']:.2f}%) подтверждены!")

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
    assert config.MAX_CONCURRENT_POSITIONS == 15 and len(bybit_tickers) >= 220 and binance_client.last_full_market_count >= 350, f"Bybit должен мониторить >= 350 пар и вернуть >= 220 в разбор, получено market={binance_client.last_full_market_count}, top={len(bybit_tickers)}"
    bb_bad = [t["symbol"] for t in bybit_tickers if t["symbol"] in ("NVDAUSDT", "TSLAUSDT", "SOXLUSDT", "XAUUSDT", "PAXGUSDT", "AAPLUSDT", "TGTSTOCKUSDT")]
    assert not bb_bad, f"В радар Bybit попали RWA/акции/золото: {bb_bad}"
    bb_new = sum(1 for t in bybit_tickers if t.get("is_new_listing"))
    bb_btc = await binance_client.fetch_btc_regime()
    bb_sol = await binance_client.fetch_candles_analysis("SOLUSDT", interval="15m", limit=200)
    bb_price = await binance_client.fetch_price("SOLUSDT")
    _, _, bb_spread = await binance_client.fetch_orderbook_spread("SOLUSDT")
    assert bb_sol is not None and bb_sol["current_price"] > 0 and bb_price and bb_price > 0 and bb_spread < 0.01
    print(f"  ✓ Failover fapi(418) -> bybit сработал мгновенно: {len(bybit_tickers)} чистых крипто-фьючерсов (вкл. {bb_new} новых/innovation), SOL 15m=${bb_price:.2f} (spread {bb_spread*100:.3f}%), BTC: {bb_btc['pct_5m']:+.2f}%")

    # Проверяем цепочку резервов: Bitget (500+ перпов) -> OKX (топ-2 ликвидности + кросс-цена AKT) -> Gate (350+ перпов вместо 158!)
    bybit_idx = next(i for i, m in enumerate(binance_client.mirrors) if m["name"] == "bybit")
    binance_client._mirror_cooldowns[bybit_idx] = time.time() + 1800.0
    binance_client._mirror_ban_type[bybit_idx] = "hard"
    binance_client._ticker24_cache = ("", 0.0, [])
    binance_client._book_tickers_cache = {}
    binance_client._book_tickers_cache_time = 0.0

    bg_tickers = await binance_client.fetch_top_tickers(min_vol_usdt=config.MIN_24H_VOLUME_USDT, limit=config.SCAN_TICKERS_LIMIT)
    assert binance_client.active_mirror_name == "bitget", f"При бане fapi+bybit должен включиться bitget, получено {binance_client.active_mirror_name}"
    assert binance_client.last_full_market_count >= 330 and len(bg_tickers) >= 220, f"Bitget должен мониторить >= 330 чистых крипто-пар и вернуть 240, получено market={binance_client.last_full_market_count}, top={len(bg_tickers)}"
    bg_sol = await binance_client.fetch_candles_analysis("SOLUSDT", interval="15m", limit=200)
    assert bg_sol is not None and bg_sol["current_price"] > 0 and bg_sol["volume_surge_ratio"] > 0.05
    print(f"  ✓ Failover -> bitget сработал мгновенно: мониторинг {binance_client.last_full_market_count} пар (в разборе {len(bg_tickers)}), SOL 15m=${bg_sol['current_price']:.2f} (RVOL={bg_sol['volume_surge_ratio']}x)")

    bg_idx = next(i for i, m in enumerate(binance_client.mirrors) if m["name"] == "bitget")
    binance_client._mirror_cooldowns[bg_idx] = time.time() + 1800.0
    binance_client._mirror_ban_type[bg_idx] = "hard"
    binance_client._ticker24_cache = ("", 0.0, [])
    okx_tickers = await binance_client.fetch_top_tickers(min_vol_usdt=config.MIN_24H_VOLUME_USDT, limit=config.SCAN_TICKERS_LIMIT)
    assert binance_client.active_mirror_name == "okx", f"При бане bitget должен включиться okx, получено {binance_client.active_mirror_name}"
    assert binance_client.last_full_market_count >= 210 and len(okx_tickers) >= 200, f"OKX должен вернуть >= 210 чистых крипто-пар, получено market={binance_client.last_full_market_count}, top={len(okx_tickers)}"
    okx_sol = await binance_client.fetch_candles_analysis("SOLUSDT", interval="15m", limit=200)
    akt_cross_p = await binance_client.fetch_price("AKTUSDT")
    assert okx_sol is not None and okx_sol["current_price"] > 0 and akt_cross_p is not None and akt_cross_p > 0
    print(f"  ✓ Failover -> okx (instCategory=1) сработал: мониторинг {binance_client.last_full_market_count} пар (разбор {len(okx_tickers)}), кросс-цена AKT=${akt_cross_p:.4f}")

    okx_idx = next(i for i, m in enumerate(binance_client.mirrors) if m["name"] == "okx")
    binance_client._mirror_cooldowns[okx_idx] = time.time() + 1800.0
    binance_client._mirror_ban_type[okx_idx] = "hard"
    binance_client._ticker24_cache = ("", 0.0, [])
    gate_tickers = await binance_client.fetch_top_tickers(min_vol_usdt=config.MIN_24H_VOLUME_USDT, limit=config.SCAN_TICKERS_LIMIT)
    assert binance_client.active_mirror_name == "gate", f"При бане okx должен включиться gate, получено {binance_client.active_mirror_name}"
    assert binance_client.last_full_market_count >= 250 and len(gate_tickers) >= 220, f"Gate Futures должен мониторить >= 250 пар и вернуть 240 (вместо старых 158!), получено market={binance_client.last_full_market_count}, top={len(gate_tickers)}"
    gate_sol = await binance_client.fetch_candles_analysis("SOLUSDT", interval="15m", limit=200)
    gate_akt_p = await binance_client.fetch_price("AKTUSDT")
    assert gate_sol is not None and gate_sol["current_price"] > 0 and gate_akt_p and gate_akt_p > 0
    print(f"  ✓ Failover -> gate (900 req/s) сработал: мониторинг {binance_client.last_full_market_count} пар (разбор {len(gate_tickers)}), живой mid AKT=${gate_akt_p:.4f}")

    # Проверяем 15m candle-boundary guard (защита от 12-секундного спама на Render)
    bar_s = 900 if config.SCAN_TIMEFRAME == "15m" else 300
    market_scanner._last_scanned_bar = int(time.time()) // bar_s
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
