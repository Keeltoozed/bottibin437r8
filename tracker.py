import os
import json
import time
from typing import Dict, List, Any, Optional
import config
from obsidian_vault import obsidian_vault

PORTFOLIO_FILE = "portfolio.json"

class PortfolioTracker:
    """
    Управление состоянием портфеля, открытыми позициями и статистикой воронки (Rocket Hunter Edition).
    Ключевые улучшения учета:
      - Корректный расчет Equity = Свободный Cash + Залоговая маржа в сделках + Нереализованный PnL.
      - Честный институциональный учет сделок: частичные тейки (TP1 30%, TP2 30%) сразу зачисляют деньги в Cash,
        но агрегируются в ОДНУ итоговую сделку в истории при полном закрытии позиции (без раздувания винрейта 3 к 1!).
      - Умный карантин: легкий выход по Time-Stop в околонулевой брейкивен не блокирует торговлю Circuit Breaker'ом.
    """
    def __init__(self):
        self.persist_enabled: bool = True
        self.initial_balance = config.INITIAL_BALANCE
        self.cash = self.initial_balance
        self.open_positions: Dict[str, Dict[str, Any]] = {}
        self.trade_history: List[Dict[str, Any]] = []
        self.funnel_stats: Dict[str, int] = {
            "universe": 0,
            "gate_failed": 0,
            "cooldown_blocked": 0,
            "btc_blocked": 0,
            "hard_gates": 0,
            "groq_evaluated": 0,
            "groq_skip": 0,
            "low_conf": 0,
            "passed": 0,
            "filled": 0
        }
        self.recent_evaluations: List[Dict[str, Any]] = []
        self.shadow_trades: List[Dict[str, Any]] = []
        self.live_ml_ranking: List[Dict[str, Any]] = []
        self.symbol_lockouts: Dict[str, float] = {}
        self.consecutive_losses: int = 0
        self.daily_losses_count: int = 0
        self.daily_loss_day: str = time.strftime('%Y-%m-%d', time.gmtime())
        self.pause_until: float = 0.0
        self.is_paused = False
        self.current_leverage = getattr(config, "LEVERAGE", 12)
        self.last_universe_count: int = 0
        self.btc_regime_str = "🟡 Анализ рынка BTC..."
        self.last_scan_str = "Ожидание..."
        self.load()

    def save(self):
        """Сохраняет текущее состояние на диск в portfolio.json (если включена персистентность)."""
        if not getattr(self, "persist_enabled", True):
            return
        state = {
            "cash": round(self.cash, 4),
            "initial_balance": self.initial_balance,
            "current_leverage": self.current_leverage,
            "open_positions": self.open_positions,
            "trade_history": self.trade_history[-100:],
            "funnel_stats": self.funnel_stats,
            "recent_evaluations": self.recent_evaluations[-30:],
            "shadow_trades": self.shadow_trades[-50:],
            "symbol_lockouts": self.symbol_lockouts,
            "consecutive_losses": self.consecutive_losses,
            "daily_losses_count": self.daily_losses_count,
            "daily_loss_day": self.daily_loss_day,
            "pause_until": self.pause_until,
            "is_paused": self.is_paused,
            "last_updated": time.time()
        }
        try:
            with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"⚠️ Ошибка сохранения portfolio.json: {e}", flush=True)

    def load(self):
        """Загружает сохраненное состояние из portfolio.json."""
        if not os.path.exists(PORTFOLIO_FILE):
            return
        try:
            with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
                self.cash = float(state.get("cash", self.initial_balance))
                self.open_positions = state.get("open_positions", {})
                self.trade_history = state.get("trade_history", [])
                self.funnel_stats = state.get("funnel_stats", self.funnel_stats)
                self.recent_evaluations = state.get("recent_evaluations", [])
                self.shadow_trades = state.get("shadow_trades", [])
                self.symbol_lockouts = state.get("symbol_lockouts", {})
                self.consecutive_losses = state.get("consecutive_losses", 0)
                self.daily_losses_count = state.get("daily_losses_count", 0)
                self.daily_loss_day = state.get("daily_loss_day", time.strftime('%Y-%m-%d', time.gmtime()))
                self.pause_until = state.get("pause_until", 0.0)
                self.is_paused = state.get("is_paused", False)
                if not getattr(config, "ENABLE_CIRCUIT_BREAKER", False):
                    self.pause_until = 0.0
                    self.is_paused = False
                raw_lev = int(state.get("current_leverage", getattr(config, "LEVERAGE", 15)))
                self.current_leverage = raw_lev if 5 <= raw_lev <= 25 else getattr(config, "LEVERAGE", 15)
                print(f"✅ Портфель загружен: кэш ${self.cash:.2f}, открытых позиций: {len(self.open_positions)}, плечо: {self.current_leverage}x", flush=True)
        except Exception as e:
            print(f"⚠️ Ошибка чтения portfolio.json: {e}", flush=True)

    def is_daily_limit_reached(self) -> bool:
        """Проверяет дневной лимит убыточных сделок (Circuit Breaker)."""
        if not getattr(config, "ENABLE_CIRCUIT_BREAKER", False):
            return False
        if getattr(self, "circuit_breaker_override", False):
            return False
        today_utc = time.strftime('%Y-%m-%d', time.gmtime())
        if self.daily_loss_day != today_utc:
            self.daily_loss_day = today_utc
            self.daily_losses_count = 0
            self.save()
        limit = getattr(config, "DAILY_LOSS_LIMIT", 999)
        return self.daily_losses_count >= limit

    def add_evaluation(self, eval_data: Dict[str, Any]):
        """Добавляет свежую оценку Groq в ленту радара."""
        self.recent_evaluations.insert(0, eval_data)
        if len(self.recent_evaluations) > 50:
            self.recent_evaluations = self.recent_evaluations[:50]
        self.save()

    def update_live_ml_ranking(self, ranked_items: List[Dict[str, Any]]):
        """Обновляет живой рейтинг структурных кандидатов по оценке квантовой модели ML."""
        self.live_ml_ranking = ranked_items[:25]

    def open_position(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        size_usdt: float,
        wick_sl: float,
        tp1: float,
        tp2: float,
        groq_reason: str,
        leverage: int = config.LEVERAGE,
        atr_pct: float = 0.006,
        risk_usd: float = 0.50
    ) -> bool:
        """Открывает новую позицию с параметрами структурного стопа и ATR для Chandelier-трейлинга."""
        if symbol in self.open_positions:
            return False
        if len(self.open_positions) >= config.MAX_CONCURRENT_POSITIONS:
            return False
        if self.cash < size_usdt or size_usdt <= 0:
            return False

        margin_usdt = round(size_usdt, 4)
        notional_value = round(margin_usdt * leverage, 4)
        coins_qty = round(notional_value / max(entry_price, 1e-9), 6)
        risk_dist = max(abs(entry_price - wick_sl), entry_price * config.STOP_LOSS_MIN_PCT)

        self.cash -= margin_usdt

        pos = {
            "id": f"{symbol}_{int(time.time())}",
            "symbol": symbol,
            "side": side,
            "entry_price": entry_price,
            "current_price": entry_price,
            "margin_usdt": margin_usdt,
            "initial_margin_usdt": margin_usdt,
            "notional_value": notional_value,
            "coins_qty": coins_qty,
            "leverage": leverage,
            "wick_sl": wick_sl,
            "original_sl": wick_sl,
            "risk_dist": risk_dist,
            "risk_usd": risk_usd,
            "atr_pct": atr_pct,
            "tp1": tp1,
            "tp2": tp2,
            "tp1_hit": False,
            "tp2_hit": False,
            "breakeven_set": False,
            "highest_price": entry_price,
            "lowest_price": entry_price,
            "unrealized_pnl": 0.0,
            "pnl_pct": 0.0,
            "realized_pnl_accum": 0.0,
            "gross_pnl_accum": 0.0,
            "fees_accum": 0.0,
            "weighted_exit_num": 0.0,
            "weighted_exit_den": 0.0,
            "partial_notes": [],
            "groq_reason": groq_reason,
            "opened_at": time.time(),
            "opened_at_str": time.strftime("%Y-%m-%d %H:%M:%S")
        }

        self.open_positions[symbol] = pos
        self.funnel_stats["filled"] += 1
        self.save()

        try:
            obsidian_vault.log_trade_entry({
                "symbol": symbol,
                "side": side,
                "entry_price": entry_price,
                "stop_loss": wick_sl,
                "tp1": tp1,
                "tp2": tp2,
                "margin": margin_usdt,
                "leverage": leverage,
                "reason": groq_reason
            })
        except Exception as e:
            print(f"⚠️ [Obsidian Log Error] {e}", flush=True)

        return True

    def update_leverage(self, new_leverage: int):
        """Обновляет плечо для открытых позиций."""
        for symbol, pos in self.open_positions.items():
            pos["leverage"] = new_leverage
            pos["notional_value"] = round(pos["margin_usdt"] * new_leverage, 2)
            pos["coins_qty"] = round(pos["notional_value"] / max(pos["entry_price"], 1e-9), 6)

            entry = pos["entry_price"]
            cur_price = pos.get("current_price", entry)
            raw_pct = (cur_price - entry) / entry if pos["side"] == "LONG" else (entry - cur_price) / entry
            pos["pnl_pct"] = round(raw_pct * new_leverage * 100, 2)
            pos["unrealized_pnl"] = round(pos["margin_usdt"] * (raw_pct * new_leverage), 3)
        self.save()

    def update_position_prices(self, price_map: Dict[str, float]):
        """Обновляет текущие цены открытых позиций, экстремумы MFE и чистый нереализованный PnL."""
        for symbol, pos in list(self.open_positions.items()):
            cur_price = price_map.get(symbol)
            if not cur_price or cur_price <= 0:
                continue

            pos["current_price"] = cur_price
            entry = pos["entry_price"]
            lev = pos["leverage"]

            if cur_price > pos.get("highest_price", entry):
                pos["highest_price"] = cur_price
            if cur_price < pos.get("lowest_price", entry):
                pos["lowest_price"] = cur_price

            if pos["side"] == "LONG":
                raw_pct = (cur_price - entry) / entry
            else:
                raw_pct = (entry - cur_price) / entry

            gross_unrealized = pos["margin_usdt"] * (raw_pct * lev)
            est_fees = pos["margin_usdt"] * lev * 0.0012
            net_unrealized = gross_unrealized - est_fees
            pos["pnl_pct"] = round((net_unrealized / max(pos["margin_usdt"], 1e-9)) * 100, 2)
            pos["unrealized_pnl"] = round(net_unrealized, 3)

    def close_position(self, symbol: str, exit_price: float, reason: str, partial_pct: float = 1.0):
        """
        Закрывает позицию (частично на TP1/TP2 или полностью).
        Частичные фиксации мгновенно возвращают маржу и прибыль в Cash, а итоговая запись
        в trade_history создается как ЕДИНАЯ консолидированная сделка при окончательном выходе!
        """
        if symbol not in self.open_positions:
            return

        pos = self.open_positions[symbol]
        lev = pos["leverage"]
        entry = pos["entry_price"]

        if pos["side"] == "LONG":
            raw_pct = (exit_price - entry) / entry
        else:
            raw_pct = (entry - exit_price) / entry

        partial_pct = min(max(partial_pct, 0.01), 1.0)
        closed_margin = pos["margin_usdt"] * partial_pct
        gross_pnl = closed_margin * (raw_pct * lev)

        # Честный учет комиссий и проскальзывания (0.06% на вход + 0.06% на выход = 0.12% от закрываемого номинала)
        notional_entry = closed_margin * lev
        notional_exit = (pos["coins_qty"] * partial_pct) * exit_price
        fees_and_slippage = round((notional_entry * 0.0006) + (notional_exit * 0.0006), 4)

        realized_pnl = round(gross_pnl - fees_and_slippage, 4)
        return_to_cash = round(closed_margin + realized_pnl, 4)
        self.cash += max(return_to_cash, 0.0)

        # Накапливаем финансовый итог внутри позиции
        pos["realized_pnl_accum"] = pos.get("realized_pnl_accum", 0.0) + realized_pnl
        pos["gross_pnl_accum"] = pos.get("gross_pnl_accum", 0.0) + gross_pnl
        pos["fees_accum"] = pos.get("fees_accum", 0.0) + fees_and_slippage
        pos["weighted_exit_num"] = pos.get("weighted_exit_num", 0.0) + (closed_margin * exit_price)
        pos["weighted_exit_den"] = pos.get("weighted_exit_den", 0.0) + closed_margin

        # ЧАСТИЧНОЕ ЗАКРЫТИЕ (TP1 / TP2): оставляем позицию открытой для ранера!
        if partial_pct < 0.99:
            pos["margin_usdt"] = round(max(pos["margin_usdt"] - closed_margin, 0.0001), 4)
            pos["notional_value"] = round(pos["margin_usdt"] * lev, 4)
            pos["coins_qty"] = round(pos["coins_qty"] * (1.0 - partial_pct), 6)

            short_tag = "TP1(30%)" if "TP1" in reason else ("TP2(30%)" if "TP2" in reason else f"Part({int(partial_pct*100)}%)")
            notes = pos.setdefault("partial_notes", [])
            notes.append(short_tag)

            if realized_pnl > 0 or "TP" in reason:
                self.consecutive_losses = 0

            self.save()
            slice_roi = round((realized_pnl / max(closed_margin, 1e-9)) * 100, 1)
            print(
                f"🎯 [PARTIAL FILL] {symbol} по ${exit_price:.4f} | Зафиксировано в кэш: ${realized_pnl:+.2f} ({slice_roi:+.1f}%) | "
                f"В ранере осталось маржи: ${pos['margin_usdt']:.2f} | {reason}",
                flush=True
            )
            return

        # ПОЛНОЕ (ФИНАЛЬНОЕ) ЗАКРЫТИЕ ПОЗИЦИИ -> 1 СДЕЛКА В СТАТИСТИКЕ!
        initial_mg = max(pos.get("initial_margin_usdt", closed_margin), 1e-9)
        total_realized = round(pos["realized_pnl_accum"], 3)
        total_gross = round(pos["gross_pnl_accum"], 3)
        total_fees = round(pos["fees_accum"], 4)
        w_den = max(pos.get("weighted_exit_den", closed_margin), 1e-9)
        blended_exit = round(pos.get("weighted_exit_num", closed_margin * exit_price) / w_den, 6)
        total_roi_pct = round((total_realized / initial_mg) * 100, 2)

        notes = pos.get("partial_notes", [])
        full_reason = f"{' + '.join(notes)} ➔ {reason}" if notes else reason

        trade_record = {
            "symbol": symbol,
            "side": pos["side"],
            "entry_price": entry,
            "exit_price": blended_exit,
            "last_exit_price": exit_price,
            "margin_usdt": round(initial_mg, 2),
            "initial_margin_usdt": round(initial_mg, 2),
            "partial_pct": 1.0,
            "leverage": lev,
            "gross_pnl": total_gross,
            "fees_paid": total_fees,
            "realized_pnl": total_realized,
            "roi_pct": total_roi_pct,
            "reason": full_reason,
            "opened_at": pos["opened_at_str"],
            "closed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "duration_sec": int(time.time() - pos["opened_at"])
        }
        self.trade_history.append(trade_record)
        del self.open_positions[symbol]

        # Умная защита от тильта и серийных убытков:
        # Околонулевой выход по Time-Stop (например -$0.04) не считается за аварийный стоп-лосс,
        # а реальный стоп-лосс (<= -$0.20 или Structural Stop) активирует 3-часовой карантин монеты и Circuit Breaker!
        is_full_stop = (total_realized <= -0.20) or ("Structural Stop" in full_reason)
        
        if is_full_stop:
            self.consecutive_losses += 1
            today_utc = time.strftime('%Y-%m-%d', time.gmtime())
            if self.daily_loss_day != today_utc:
                self.daily_loss_day = today_utc
                self.daily_losses_count = 0
            self.daily_losses_count += 1
            self.circuit_breaker_override = False

            # Жесткий 3-часовой (180 минут) карантин на монету после полного стопа:
            # Защищает от повторного входа в тот же раздающий/сливающий актив (устраняет ошибку двойного стопа RUNE)!
            self.symbol_lockouts[symbol] = time.time() + (180 * 60)
            print(
                f"🔒 [КАРАНТИН 3 ЧАСА] {symbol} после полного стопа ${total_realized:+.2f}. "
                f"(Дневных стопов: {self.daily_losses_count}/{getattr(config, 'DAILY_LOSS_LIMIT', 3)})",
                flush=True
            )

            if getattr(config, "ENABLE_CIRCUIT_BREAKER", False):
                if self.is_daily_limit_reached():
                    print(f"🛑 [CIRCUIT BREAKER] Дневной лимит ({config.DAILY_LOSS_LIMIT} стопа) достигнут! Защита капитала до завтра.", flush=True)

                max_streak = getattr(config, "MAX_CONSECUTIVE_LOSSES", 2)
                if self.consecutive_losses >= max_streak:
                    pause_sec = getattr(config, "CONSECUTIVE_LOSS_PAUSE_SECONDS", 2700)
                    if pause_sec > 0:
                        self.pause_until = time.time() + pause_sec
                        print(f"🛑 [CIRCUIT BREAKER] {self.consecutive_losses} стопа подряд! Пауза на {pause_sec // 60} мин.", flush=True)
            else:
                self.pause_until = 0.0
        elif total_realized <= -0.08:
            # Промежуточный минус: 45 минут карантина на монету
            self.symbol_lockouts[symbol] = time.time() + (45 * 60)
        elif total_realized <= 0.0:
            # Легкий околонулевой скретч / Time-Stop: 20 минут паузы только по этой монете
            self.symbol_lockouts[symbol] = time.time() + (20 * 60)
        else:
            self.consecutive_losses = 0

        self.save()

        try:
            obsidian_vault.log_trade_exit({
                "symbol": symbol,
                "side": pos["side"],
                "entry_price": entry,
                "exit_price": blended_exit,
                "realized_pnl": total_realized,
                "realized_pnl_pct": total_roi_pct,
                "exit_reason": full_reason
            })
        except Exception as e:
            print(f"⚠️ [Obsidian Exit Log Error] {e}", flush=True)

        print(
            f"🏁 [POSITION CLOSED] {symbol} (средний выход ${blended_exit:.4f}) | "
            f"Итоговый PnL: ${total_realized:+.2f} ({total_roi_pct:+.1f}%) | {full_reason}",
            flush=True
        )

    def close_all(self, reason: str = "Ручное закрытие (Panic Close)"):
        """Экстренно закрывает все открытые позиции."""
        for symbol, pos in list(self.open_positions.items()):
            self.close_position(symbol, pos.get("current_price", pos["entry_price"]), reason, partial_pct=1.0)

    def reset_daily_loss(self):
        """Сбрасывает блокировку Circuit Breaker по запросу пользователя."""
        self.circuit_breaker_override = True
        self.daily_losses_count = 0
        self.consecutive_losses = 0
        self.pause_until = 0.0
        self.save()
        print("🔓 [CIRCUIT BREAKER] Блокировка снята пользователем. Торговля разблокирована!", flush=True)

    def get_daily_loss(self) -> float:
        """Суммарный убыток за сегодня в USD."""
        if getattr(self, "circuit_breaker_override", False):
            return 0.0
        today_str = time.strftime("%Y-%m-%d")
        daily_losses = [abs(t["realized_pnl"]) for t in self.trade_history if t.get("closed_at", "").startswith(today_str) and t["realized_pnl"] < 0]
        return round(sum(daily_losses), 2)

    def update_shadow_outcomes(self, shadow_data: Dict[str, Any]):
        """Отслеживает MFE/MAE отклонённых сетапов в Shadow Tracker."""
        now = time.time()
        for item in self.shadow_trades:
            sym = item.get("symbol")
            rej_p = item.get("rejected_at_price", 0.0)
            if not sym or rej_p <= 0 or sym not in shadow_data:
                continue

            val = shadow_data[sym]
            if isinstance(val, dict):
                cur_p = val.get("current", rej_p)
                max_h = val.get("high", cur_p)
                min_l = val.get("low", cur_p)
            else:
                cur_p = float(val)
                max_h = cur_p
                min_l = cur_p

            side = item.get("side", "LONG")
            ts = item.get("timestamp", now)
            elapsed_min = int((now - ts) / 60)
            item["elapsed_min"] = elapsed_min

            if side == "LONG":
                cur_delta = (cur_p - rej_p) / rej_p * 100.0
                peak_favorable = (max_h - rej_p) / rej_p * 100.0
                peak_adverse = (min_l - rej_p) / rej_p * 100.0
            else:
                cur_delta = (rej_p - cur_p) / rej_p * 100.0
                peak_favorable = (rej_p - min_l) / rej_p * 100.0
                peak_adverse = (rej_p - max_h) / rej_p * 100.0

            item["current_price"] = cur_p
            item["price_change_pct"] = round(cur_delta, 2)
            item["max_profit_pct"] = round(max(item.get("max_profit_pct", 0.0), peak_favorable), 2)
            item["max_loss_pct"] = round(min(item.get("max_loss_pct", 0.0), peak_adverse), 2)

            if elapsed_min >= 10 and "change_15m_pct" not in item:
                item["change_15m_pct"] = round(cur_delta, 2)
            if elapsed_min >= 50 and "change_1h_pct" not in item:
                item["change_1h_pct"] = round(cur_delta, 2)
            if elapsed_min >= 110 and "change_2h_pct" not in item:
                item["change_2h_pct"] = round(cur_delta, 2)
            if elapsed_min >= 170 and "change_3h_pct" not in item:
                item["change_3h_pct"] = round(cur_delta, 2)
            if elapsed_min >= 230 and "change_4h_pct" not in item:
                item["change_4h_pct"] = round(cur_delta, 2)
            if elapsed_min >= 290 and "change_5h_pct" not in item:
                item["change_5h_pct"] = round(cur_delta, 2)

            if item["max_loss_pct"] <= -1.0:
                item["outcome"] = f"🛡️ Спас от стопа ({item['max_loss_pct']:.2f}%)"
            elif item["max_profit_pct"] >= 2.0:
                item["outcome"] = f"⚠️ Упущена ракета (пик {item['max_profit_pct']:+.2f}%)"
            elif cur_delta <= -0.4:
                item["outcome"] = f"🛡️ Спас от минуса ({cur_delta:+.2f}%)"
            else:
                item["outcome"] = f"⚖️ Флэт (пик: {item['max_profit_pct']:+.2f}%, спад: {item['max_loss_pct']:.2f}%)"

        self.save()

    def get_shadow_stats(self) -> Dict[str, Any]:
        total = len(self.shadow_trades)
        if total == 0:
            return {"total": 0, "saved": 0, "missed": 0, "flat": 0, "accuracy": 0.0}

        saved = sum(1 for t in self.shadow_trades if t.get("max_loss_pct", 0) <= -1.0 or t.get("price_change_pct", 0) <= -0.4)
        missed = sum(1 for t in self.shadow_trades if t.get("max_profit_pct", 0) >= 2.0 and t.get("max_loss_pct", 0) > -1.0)
        flat = total - saved - missed
        decided = saved + missed
        acc = round((saved / decided * 100), 1) if decided > 0 else 100.0

        return {
            "total": total,
            "saved": saved,
            "missed": missed,
            "flat": flat,
            "accuracy": acc
        }

    def get_portfolio_summary(self) -> Dict[str, Any]:
        """Возвращает агрегированную сводку (с честным учетом залоговой маржи в Equity!)."""
        locked_margin = sum(p.get("margin_usdt", 0.0) for p in self.open_positions.values())
        unrealized_sum = sum(p.get("unrealized_pnl", 0.0) for p in self.open_positions.values())
        realized_open_partials = sum(p.get("realized_pnl_accum", 0.0) for p in self.open_positions.values())
        equity = round(self.cash + locked_margin + unrealized_sum, 2)
        total_realized_pnl = sum(t["realized_pnl"] for t in self.trade_history) + realized_open_partials

        total_trades = len(self.trade_history)
        wins = sum(1 for t in self.trade_history if t["realized_pnl"] > 0)
        win_rate = round((wins / total_trades * 100), 1) if total_trades > 0 else 0.0
        daily_loss = self.get_daily_loss()

        return {
            "cash": round(self.cash, 2),
            "locked_margin": round(locked_margin, 2),
            "equity": equity,
            "unrealized_pnl": round(unrealized_sum, 2),
            "total_realized_pnl": round(total_realized_pnl, 2),
            "open_positions_count": len(self.open_positions),
            "max_positions": config.MAX_CONCURRENT_POSITIONS,
            "total_trades": total_trades,
            "wins": wins,
            "losses": total_trades - wins,
            "win_rate": win_rate,
            "daily_loss": daily_loss,
            "circuit_breaker": (daily_loss >= config.MAX_DAILY_LOSS_USD) or self.is_daily_limit_reached(),
            "is_paused": self.is_paused
        }

portfolio = PortfolioTracker()
