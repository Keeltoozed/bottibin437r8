import os
import json
import time
from datetime import datetime
from typing import Dict, Any, List, Optional

class ObsidianVaultManager:
    """
    Интеграция с базой знаний и 'Вторым мозгом' Obsidian.
    Автоматически:
      1. Синхронизирует торговый журнал в Markdown с YAML Frontmatter.
      2. Ведет 'Досье' (Dossiers) на каждую криптовалюту с памятью ее повадок и ловушек.
      3. Формирует торговые плейбуки (Playbooks) и аудит отклонённых сетапов (Shadow Audits).
      4. Извлекает контекстную память перед каждой новой сделкой, исключая повторение ошибок!
    """

    def __init__(self, custom_path: Optional[str] = None):
        # Приоритет 1: iCloud Obsidian (если Mac пользователя)
        icloud_dir = os.path.expanduser("~/Library/Mobile Documents/iCloud~md~obsidian/Documents/Binance_AI_Trader")
        # Приоритет 2: Локальная папка проекта (для Render / Linux)
        local_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "obsidian_vault"))

        if custom_path:
            self.vault_path = custom_path
        elif os.path.exists(os.path.expanduser("~/Library/Mobile Documents/iCloud~md~obsidian/Documents")):
            self.vault_path = icloud_dir
            self.secondary_path = local_dir
        else:
            self.vault_path = local_dir
            self.secondary_path = None

        self._init_vault_structure()

    def _init_vault_structure(self):
        """Создает структуру папок Obsidian Vault и базовые плейбуки."""
        targets = [self.vault_path]
        if getattr(self, "secondary_path", None):
            targets.append(self.secondary_path)

        for base in targets:
            try:
                for sub in ["Journal", "Token_Dossiers", "Playbooks", "Shadow_Audits"]:
                    os.makedirs(os.path.join(base, sub), exist_ok=True)
                self._create_default_playbooks(base)
                self._create_dashboard_if_missing(base)
            except Exception as e:
                print(f"⚠️ [Obsidian Init Warning] {base}: {e}")

    def _create_default_playbooks(self, base_path: str):
        """Создает институциональные торговые плейбуки в Markdown."""
        playbooks = {
            "Rocket_Long_Playbook.md": """---
type: playbook
strategy: Rocket Momentum Breakout
side: LONG
target_rr: 2.5R - 3.5R
tags: [playbook, long, scalp, momentum]
---
# 🚀 Плейбук: Институциональный LONG (Ракета)

## Критерии идеального входа (A+ Setup):
1. **Всплеск объёма (Volume Surge):** $\ge 2.0x$ от 20-периодной средней.
2. **Откат к поддержке (Pullback):** Вход на откате $-0.2\% \dots -1.5\%$ от локального максимума к EMA-9. *Никогда не покупать пик зелёной свечи (Anti-FOMO).*
3. **Фитиль свечи (Upper Wick):** Не более $25\%$. Если верхний фитиль $>30\%$, это ловушка распределения китов (Bull Trap) — **пропускать**.
4. **Структура тренда:** Цена $\ge$ EMA9 $\ge$ EMA21.
5. **Bitcoin Regime:** BTC стабилен или в бычьем тренде. Запрещено лонговать альты при резком проливе BTC.

## Правило выхода:
- **Стоп-лосс:** за локальный экстремум фитиля + фильтр шума ATR-14 (дистанция $\le 1.2\%$).
- **Тейк 1:** $+1.5\% \dots +2.0\%$ хода цены ($+90\% \dots +120\%$ ROI при 60x плече) — закрыть $50\%$ объема.
- **Тейк 2:** $+3.0\% \dots +4.5\%$ хода цены — закрыть остаток.
""",
            "Breakdown_Short_Playbook.md": """---
type: playbook
strategy: Breakdown Flush
side: SHORT
target_rr: 2.0R - 3.0R
tags: [playbook, short, breakdown, dump]
---
# 🔻 Плейбук: Институциональный SHORT (Пробой уровня вниз)

## Критерии идеального входа:
1. **Всплеск объёма продаж:** Всплеск $\ge 2.0x$ при пробое локальной поддержки.
2. **Микро-отскок в сопротивление (Bounce):** Вход на тесте снизу $+0.2\% \dots +1.2\%$ в EMA-9.
3. **Фитиль свечи (Lower Wick):** Не более $25\%$. Если нижний фитиль длинный ($>30\%$), покупатели откупают пролив (Bear Trap) — **пропускать**.
4. **Структура тренда:** Цена $\le$ EMA9 $\le$ EMA21, RSI $\le 55$.
""",
            "Trap_Detection_Matrix.md": """---
type: guide
title: Матрица распознавания рыночных ловушек
tags: [knowledge, traps, risk-management]
---
# 🛡️ Матрица ловушек (Trap Detection Matrix)

1. **Bull Trap (Ложный пробой вверх):**
   - Симптом: Свеча пробила хай, но закрылась с верхним фитилём $>35\%$.
   - Причина: Маркет-мейкер собрал ликвидность покупателей и разгрузил позицию.
   - Действие ИИ: Категорический SKIP.

2. **Liquidation Cascade Exhaustion:**
   - Симптом: Резкий объём 4x-6x, но свеча имеет огромный нижний фитиль.
   - Причина: Ликвидации продавцов поглощены крупным лимитным покупателем.
   - Действие ИИ: Запрет на SHORT.
"""
        }

        for fname, content in playbooks.items():
            fpath = os.path.join(base_path, "Playbooks", fname)
            if not os.path.exists(fpath):
                try:
                    with open(fpath, "w", encoding="utf-8") as f:
                        f.write(content)
                except Exception:
                    pass

    def _create_dashboard_if_missing(self, base_path: str):
        """Создает главный дашборд-файл в корне Vault."""
        dash_path = os.path.join(base_path, "00_Dashboard.md")
        if not os.path.exists(dash_path):
            content = """---
type: dashboard
title: AI Trading Second Brain
updated: {now}
---
# 🧠 AI Quant Trader — Главный пульт базы знаний

Добро пожаловать во «Второй мозг» автономного торгового робота.
Здесь хранятся все сделки, уроки из ошибок и профили поведения криптовалют.

## Быстрые разделы:
- 📖 [[Playbooks/Rocket_Long_Playbook|Плейбук LONG (Ракета)]]
- 🔻 [[Playbooks/Breakdown_Short_Playbook|Плейбук SHORT (Пробой)]]
- 🛡️ [[Playbooks/Trap_Detection_Matrix|Матрица распознавания ловушек]]
- 📂 Папка `Journal/` — история каждой сделки с разбором ошибок.
- 📂 Папка `Token_Dossiers/` — досье и винрейт по каждой отдельной монете.
- 📂 Папка `Shadow_Audits/` — аудит отклонённых сетапов (доказывает спасение от ловушек).

*Заметки обновляются ботом в режиме реального времени.*
""".format(now=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            try:
                with open(dash_path, "w", encoding="utf-8") as f:
                    f.write(content)
            except Exception:
                pass

    def _write_file_to_targets(self, relative_path: str, content: str):
        """Записывает файл как в iCloud, так и в локальную папку."""
        targets = [self.vault_path]
        if getattr(self, "secondary_path", None):
            targets.append(self.secondary_path)

        for base in targets:
            try:
                full_path = os.path.join(base, relative_path)
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                with open(full_path, "w", encoding="utf-8") as f:
                    f.write(content)
            except Exception as e:
                print(f"⚠️ [Obsidian Write Error] {full_path}: {e}")

    def log_trade_entry(self, trade: Dict[str, Any]):
        """Записывает открытие новой сделки в Obsidian Journal."""
        sym = trade.get("symbol", "UNKNOWN")
        side = trade.get("side", "LONG")
        entry_p = trade.get("entry_price", 0.0)
        sl_p = trade.get("stop_loss", 0.0)
        tp1_p = trade.get("tp1", 0.0)
        tp2_p = trade.get("tp2", 0.0)
        margin = trade.get("margin", 0.0)
        lev = trade.get("leverage", 60)
        ts_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        filename = f"Journal/{ts_str}_{sym}_{side}.md"
        content = f"""---
date: {date_str}
symbol: {sym}
side: {side}
status: OPEN
entry_price: {entry_p}
stop_loss: {sl_p}
tp1: {tp1_p}
tp2: {tp2_p}
margin_usd: {margin}
leverage: {lev}x
tags: [trade, {side.lower()}, {sym.lower()}, open]
---
# ⚡ Сделка: {sym} ({side} {lev}x)

- **Время входа:** `{date_str}`
- **Цена входа:** `${entry_p}`
- **Стоп-лосс:** `${sl_p}` (защита за фитилём)
- **Цели:** TP1 `${tp1_p}` | TP2 `${tp2_p}`
- **Выделенная маржа:** `${margin:.2f}`

## 🧠 Торговый тезис ИИ:
> {trade.get('reason', 'Вход по институциональному скальп-сетапу.')}

## 📊 Рыночный контекст:
- **Всплеск объёма:** `{trade.get('volume_surge', 1.0)}x`
- **RSI (14):** `{trade.get('rsi', 50)}`
- **Откат:** `{trade.get('pullback', 0)}%`
- **Режим BTC:** `{trade.get('btc_regime', 'Neutral')}`

---
*Статус сделки будет автоматически обновлен при закрытии по TP или SL.*
"""
        self._write_file_to_targets(filename, content)
        # Обновляем досье токена
        self._append_token_history(sym, f"[{date_str}] Открыт {side} по ${entry_p}. Тезис: {trade.get('reason', '')[:80]}...")

    def log_trade_exit(self, trade: Dict[str, Any]):
        """Обновляет заметку сделки результатами, PnL и выводами (Post-Mortem)."""
        sym = trade.get("symbol", "UNKNOWN")
        side = trade.get("side", "LONG")
        entry_p = trade.get("entry_price", 0.0)
        exit_p = trade.get("exit_price", 0.0)
        pnl_usd = trade.get("realized_pnl", 0.0)
        pnl_pct = trade.get("realized_pnl_pct", 0.0)
        exit_reason = trade.get("exit_reason", "MANUAL")
        is_win = pnl_usd > 0
        date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Автоматический анализ ошибки/успеха (Post-Mortem):
        if is_win:
            lesson = f"✅ Сетап отработал по плану ({exit_reason}). Всплеск объема и фитильная защита дали импульс."
        else:
            if "Stop Loss" in exit_reason or "SL" in exit_reason:
                lesson = f"🛑 Выбит стоп-лосс. Вероятная причина: ложный пробой (Bull/Bear Trap) или локальное истощение покупателей. Учесть в досье {sym}."
            else:
                lesson = f"⚠️ Закрыто с убытком ({exit_reason}). Проанализировать динамику BTC в момент сделки."

        filename = f"Journal/CLOSED_{sym}_{side}_{int(time.time())}.md"
        content = f"""---
date_closed: {date_str}
symbol: {sym}
side: {side}
status: CLOSED
result: {"WIN" if is_win else "LOSS"}
entry_price: {entry_p}
exit_price: {exit_p}
pnl_usd: {pnl_usd:+.2f}
pnl_pct: {pnl_pct:+.2f}%
exit_reason: {exit_reason}
tags: [trade, closed, {"win" if is_win else "loss"}, {sym.lower()}]
---
# 🏁 Завершение сделки: {sym} ({side}) — {"🟢 ПРИБЫЛЬ" if is_win else "🔴 УБЫТОК"}

- **Результат:** `{pnl_usd:+.2f} USD` (`{pnl_pct:+.2f}% ROI`)
- **Причина закрытия:** `{exit_reason}`
- **Вход:** `${entry_p}` ➔ **Выход:** `${exit_p}`

## 🎓 Пост-мортем анализ и урок:
> **{lesson}**

---
*Заметка сохранена во 'Втором мозге' Obsidian для предотвращения аналогичных ошибок в будущем.*
"""
        self._write_file_to_targets(filename, content)
        self._update_token_dossier(sym, is_win, pnl_usd, lesson)

    def log_shadow_decision(self, eval_entry: Dict[str, Any]):
        """Записывает отклонённый сетап в Shadow_Audits."""
        sym = eval_entry.get("symbol", "UNKNOWN")
        side = eval_entry.get("side", "LONG")
        price = eval_entry.get("price", 0.0)
        reason = eval_entry.get("reason", "SKIP")
        outcome = eval_entry.get("outcome", "В процессе проверки")
        date_str = datetime.now().strftime("%Y-%m-%d %H:%M")

        filename = f"Shadow_Audits/{sym}_{side}_{int(time.time())}.md"
        content = f"""---
date: {date_str}
symbol: {sym}
side: {side}
price_at_rejection: {price}
decision: SKIP
outcome: {outcome}
tags: [shadow, rejected, {sym.lower()}]
---
# 🛡️ Аудит отсева: {sym} ({side})

- **Цена на момент отсева:** `${price}`
- **Причина отклонения ИИ:**  
> "{reason}"

- **Фактический исход на рынке:**  
> **{outcome}**
"""
        self._write_file_to_targets(filename, content)

    def _append_token_history(self, symbol: str, entry_line: str):
        """Добавляет строку в историю досье токена."""
        pass  # Логика досье реализована ниже в _update_token_dossier

    def _update_token_dossier(self, symbol: str, is_win: bool, pnl_usd: float, lesson: str):
        """Обновляет персональное досье монеты в папке Token_Dossiers/."""
        fname = f"Token_Dossiers/{symbol}.md"
        dpath = os.path.join(self.vault_path, fname)

        # Считываем текущие показатели, если файл есть
        wins = 0
        losses = 0
        total_pnl = 0.0
        past_notes = []

        if os.path.exists(dpath):
            try:
                with open(dpath, "r", encoding="utf-8") as f:
                    text = f.read()
                    # Простой парсинг статистики
                    import re
                    w_match = re.search(r"wins:\s*(\d+)", text)
                    l_match = re.search(r"losses:\s*(\d+)", text)
                    p_match = re.search(r"total_pnl:\s*([-\d\.]+)", text)
                    if w_match: wins = int(w_match.group(1))
                    if l_match: losses = int(l_match.group(1))
                    if p_match: total_pnl = float(p_match.group(1))
            except Exception:
                pass

        if is_win:
            wins += 1
        else:
            losses += 1
        total_pnl += pnl_usd
        total = wins + losses
        winrate = round((wins / total * 100), 1) if total > 0 else 0.0

        content = f"""---
symbol: {symbol}
total_trades: {total}
wins: {wins}
losses: {losses}
winrate_pct: {winrate}%
total_pnl: {total_pnl:+.2f}
updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
tags: [dossier, crypto, {symbol.lower()}]
---
# 📁 Досье актива: {symbol}

## 📊 Показатели эффективности:
- **Винрейт бота:** `{winrate}%` ({wins} побед / {losses} стопов)
- **Накопленный PnL:** `{total_pnl:+.2f} USD`
- **Всего сделок:** `{total}`

## ⚠️ Память повадок и ключевые уроки (Memory):
- *Последний урок:* {lesson}
- При анализе {symbol} всегда учитывать:
  - Реакцию на проливы Bitcoin (Beta к BTC).
  - Наличие ложных верхних/нижних фитилей перед началом истинного движения.

---
*Досье автоматически запрашивается моделью ИИ перед каждой новой сделкой по {symbol}.*
"""
        self._write_file_to_targets(fname, content)

    def get_token_memory(self, symbol: str, side: str = "LONG") -> str:
        """
        Извлекает контекстную память по активу из Obsidian Vault.
        Передается в промпт ИИ, чтобы модель не повторяла прошлых ошибок!
        """
        fname = f"Token_Dossiers/{symbol}.md"
        dpath = os.path.join(self.vault_path, fname)

        if not os.path.exists(dpath) and getattr(self, "secondary_path", None):
            dpath = os.path.join(self.secondary_path, fname)

        if not os.path.exists(dpath):
            return f"Досье {symbol}: актив ранее не торговался, строгий базовый отбор."

        try:
            with open(dpath, "r", encoding="utf-8") as f:
                lines = f.readlines()
            # Извлекаем последние уроки и винрейт
            winrate = "N/A"
            lessons = []
            for line in lines:
                if "winrate_pct:" in line:
                    winrate = line.split(":", 1)[1].strip()
                if "Последний урок:" in line:
                    lessons.append(line.split(":", 1)[1].strip())

            lesson_str = "; ".join(lessons[-2:]) if lessons else "соблюдать фильтр фитилей"
            return f"Память Obsidian по {symbol}: винрейт {winrate}. Прошлый опыт: {lesson_str}."
        except Exception as e:
            return f"Память по {symbol}: базовый риск-контроль."

# Синглтон для вызова из других модулей
obsidian_vault = ObsidianVaultManager()

