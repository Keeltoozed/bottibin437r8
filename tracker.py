import os
import json
import time
from typing import Dict, List, Any, Optional
import config

PORTFOLIO_FILE = "portfolio.json"

class PortfolioTracker:
    """
    Управление состоянием портфеля, открытыми позициями и статистикой воронки.
    Поддерживает:
      - Работу с реальным или симулированным балансом (старт с $20.00).
      - Расчет нереализованного и реализованного PnL.
      - Персистентное сохранение в portfolio.json (переживает перезапуски сервера на Render).
      - Журнал оценок Groq в реальном времени для веб-интерфейса.
      - Теневой трекер отклонённых сетапов (Shadow Tracker).
    """
    def __init__(self):
        self.initial_balance = config.INITIAL_BALANCE
        self.cash = self.initial_balance
        self.open_positions: Dict[str, Dict[str, Any]] = {}
        self.trade_history: List[Dict[str, Any]] = []
        self.funnel_stats: Dict[str, int] = {
            "universe": 0,
            "hard_gates": 0,
            "groq_evaluated": 0,
            "passed": 0,
            "filled": 0
        }
        self.recent_evaluations: List[Dict[str, Any]] = []
        self.shadow_trades: List[Dict[str, Any]] = []
        self.is_paused = False
        self.load()

    def save(self):
        """Сохраняет текущее состояние на диск в portfolio.json."""
        state = {
            "cash": round(self.cash, 4),
            "initial_balance": self.initial_balance,
            "open_positions": self.open_positions,
            "trade_history": self.trade_history[-100:],  # последние 100 сделок
            "funnel_stats": self.funnel_stats,
            "recent_evaluations": self.recent_evaluations[-30:],  # последние 30 оценок
            "shadow_trades": self.shadow_trades[-50:],
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
                self.is_paused = state.get("is_paused", False)
                print(f"✅ Портфель загружен: баланс ${self.cash:.2f}, открытых позиций: {len(self.open_positions)}", flush=True)
        except Exception as e:
            print(f"⚠️ Ошибка чтения portfolio.json: {e}", flush=True)

    def add_evaluation(self, eval_data: Dict[str, Any]):
        """Добавляет свежую оценку Groq в ленту радара."""
        self.recent_evaluations.insert(0, eval_data)
        if len(self.recent_evaluations) > 50:
            self.recent_evaluations = self.recent_evaluations[:50]
        self.save()

    def open_position(self, symbol: str, side: str, entry_price: float, size_usdt: float,
                      wick_sl: float, tp1: float, tp2: float, groq_reason: str, leverage: int = config.LEVERAGE) -> bool:
        """
        Открывает новую позицию.
        При балансе $20 резервирует сумму маржи ($5).
        """
        if symbol in self.open_positions:
            return False
        if len(self.open_positions) >= config.MAX_CONCURRENT_POSITIONS:
            return False
        if self.cash < size_usdt:
            return False

        margin_usdt = size_usdt
        notional_value = margin_usdt * leverage
        coins_qty = round(notional_value / entry_price, 6)

        self.cash -= margin_usdt

        pos = {
            "id": f"{symbol}_{int(time.time())}",
            "symbol": symbol,
            "side": side,
            "entry_price": entry_price,
            "current_price": entry_price,
            "margin_usdt": margin_usdt,
            "notional_value": notional_value,
            "coins_qty": coins_qty,
            "leverage": leverage,
            "wick_sl": wick_sl,
            "original_sl": wick_sl,
            "tp1": tp1,
            "tp2": tp2,
            "tp1_hit": False,
            "tp2_hit": False,
            "breakeven_set": False,
            "highest_price": entry_price,
            "unrealized_pnl": 0.0,
            "pnl_pct": 0.0,
            "groq_reason": groq_reason,
            "opened_at": time.time(),
            "opened_at_str": time.strftime("%Y-%m-%d %H:%M:%S")
        }

        self.open_positions[symbol] = pos
        self.funnel_stats["filled"] += 1
        self.save()
        print(f"🟢 [TRADE OPEN] {side} {symbol} по ${entry_price:.4f} (Маржа: ${margin_usdt:.2f}, Плечо: {leverage}x)", flush=True)
        return True

    def update_position_prices(self, price_map: Dict[str, float]):
        """Обновляет текущие цены открытых позиций и рассчитывает PnL."""
        for symbol, pos in list(self.open_positions.items()):
            cur_price = price_map.get(symbol)
            if not cur_price or cur_price <= 0:
                continue

            pos["current_price"] = cur_price
            if cur_price > pos["highest_price"]:
                pos["highest_price"] = cur_price

            entry = pos["entry_price"]
            lev = pos["leverage"]

            if pos["side"] == "LONG":
                raw_pct = (cur_price - entry) / entry
            else:
                raw_pct = (entry - cur_price) / entry

            pos["pnl_pct"] = round(raw_pct * lev * 100, 2)
            pos["unrealized_pnl"] = round(pos["margin_usdt"] * (raw_pct * lev), 3)

    def close_position(self, symbol: str, exit_price: float, reason: str, partial_pct: float = 1.0):
        """
        Закрывает позицию (полностью или частично) и фиксирует PnL.
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

        closed_margin = pos["margin_usdt"] * partial_pct
        realized_pnl = round(closed_margin * (raw_pct * lev), 3)
        return_to_cash = round(closed_margin + realized_pnl, 3)

        self.cash += max(return_to_cash, 0.0)

        trade_record = {
            "symbol": symbol,
            "side": pos["side"],
            "entry_price": entry,
            "exit_price": exit_price,
            "margin_usdt": round(closed_margin, 2),
            "leverage": lev,
            "realized_pnl": realized_pnl,
            "roi_pct": round(raw_pct * lev * 100, 2),
            "reason": reason,
            "opened_at": pos["opened_at_str"],
            "closed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "duration_sec": int(time.time() - pos["opened_at"])
        }
        self.trade_history.append(trade_record)

        if partial_pct >= 0.99:
            del self.open_positions[symbol]
        else:
            pos["margin_usdt"] -= closed_margin
            pos["coins_qty"] *= (1.0 - partial_pct)

        self.save()
        print(f"🔴 [TRADE CLOSED] {symbol} по ${exit_price:.4f} | PnL: ${realized_pnl:+.2f} ({trade_record['roi_pct']:+.1f}%) | Причина: {reason}", flush=True)

    def close_all(self, reason: str = "Ручное закрытие (Panic Close)"):
        """Экстренно закрывает все открытые позиции."""
        for symbol, pos in list(self.open_positions.items()):
            self.close_position(symbol, pos.get("current_price", pos["entry_price"]), reason)

    def get_daily_loss(self) -> float:
        """Суммарный убыток за сегодня (для правила Circuit Breaker из day-trader-skill)."""
        today_str = time.strftime("%Y-%m-%d")
        daily_losses = [abs(t["realized_pnl"]) for t in self.trade_history if t.get("closed_at", "").startswith(today_str) and t["realized_pnl"] < 0]
        return round(sum(daily_losses), 2)

    def get_portfolio_summary(self) -> Dict[str, Any]:
        """Возвращает агрегированную сводку для веб-дашборда."""
        unrealized_sum = sum(p["unrealized_pnl"] for p in self.open_positions.values())
        equity = round(self.cash + unrealized_sum, 2)
        total_realized_pnl = sum(t["realized_pnl"] for t in self.trade_history)

        total_trades = len(self.trade_history)
        wins = sum(1 for t in self.trade_history if t["realized_pnl"] > 0)
        win_rate = round((wins / total_trades * 100), 1) if total_trades > 0 else 0.0
        daily_loss = self.get_daily_loss()

        return {
            "cash": round(self.cash, 2),
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
            "circuit_breaker": daily_loss >= config.MAX_DAILY_LOSS_USD,
            "is_paused": self.is_paused
        }

# Глобальный инстанс
portfolio = PortfolioTracker()

