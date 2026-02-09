"""
IARA REPLAY DIALOGS - Configuration and results dialogs for Replay Mode.

ReplayConfigDialog: Setup replay parameters and launch.
ReplayResultDialog: Display replay results with metrics and AI usage.
ReplayState: Thread-safe container for live replay progress (GUI integration).
"""

import asyncio
import json
import logging
import os
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import customtkinter as ctk

from src.gui import theme

logger = logging.getLogger(__name__)


class ReplayState:
    """Thread-safe container for live replay progress.

    Updated by the replay engine (background thread) and read by
    the dashboard's _update_metrics loop (main thread) every 2 seconds.
    Uses a threading.Lock for safe cross-thread reads/writes.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._data: Dict[str, Any] = {
            "is_running": False,
            "finished": False,
            "day_current": 0,
            "day_total": 0,
            "date": "",
            "equity": 0.0,
            "initial_capital": 100_000,
            "capital": 0.0,
            "positions_count": 0,
            "positions_tickers": [],
            "trades_count": 0,
            "wins": 0,
            "losses": 0,
            "drawdown_total": 0.0,
            "drawdown_daily": 0.0,
            "screener_calls": 0,
            "judge_calls": 0,
            "kill_switch": False,
            "start_date": "",
            "end_date": "",
            # Final result metrics (set when finished)
            "total_return_pct": 0.0,
            "sharpe_ratio": 0.0,
            "max_drawdown_pct": 0.0,
        }

    def update(self, data: Dict[str, Any]) -> None:
        """Update state from replay engine callback (called from background thread)."""
        with self._lock:
            self._data.update(data)

    def snapshot(self) -> Dict[str, Any]:
        """Get a safe copy of current state (called from main GUI thread)."""
        with self._lock:
            return dict(self._data)

    @property
    def is_active(self) -> bool:
        """True if replay is running or just finished (data still displayable)."""
        with self._lock:
            return self._data.get("is_running", False) or self._data.get("finished", False)

    def clear(self) -> None:
        """Reset state (called when user dismisses replay results)."""
        with self._lock:
            for key in self._data:
                if isinstance(self._data[key], bool):
                    self._data[key] = False
                elif isinstance(self._data[key], (int, float)):
                    self._data[key] = 0
                elif isinstance(self._data[key], str):
                    self._data[key] = ""
                elif isinstance(self._data[key], list):
                    self._data[key] = []


class ReplayConfigDialog(ctk.CTkToplevel):
    """Dialog for configuring and launching a replay simulation."""

    def __init__(self, master, engine_controller=None, **kwargs):
        super().__init__(master, **kwargs)

        self.dashboard = master  # IaraDashboard reference for replay state
        self.engine_controller = engine_controller
        self._replay_engine = None
        self._replay_thread = None

        self.title("IARA Replay Mode - Configuration")
        self.geometry("520x480")
        self.configure(fg_color=theme.BG_DARK)
        self.transient(master)
        self.grab_set()

        self._build_ui()

    def _build_ui(self) -> None:
        # Header
        ctk.CTkLabel(
            self,
            text="REPLAY MODE",
            font=("Segoe UI", 20, "bold"),
            text_color=theme.ACCENT_AI,
        ).pack(pady=(16, 4))

        ctk.CTkLabel(
            self,
            text="Full pipeline simulation with real AI calls",
            font=("Segoe UI", 10),
            text_color=theme.COLOR_TEXT_DIM,
        ).pack(pady=(0, 12))

        # Form frame
        form = ctk.CTkFrame(self, fg_color=theme.BG_PANEL, corner_radius=8)
        form.pack(fill="x", padx=16, pady=(0, 8))

        # Start date
        row1 = ctk.CTkFrame(form, fg_color="transparent")
        row1.pack(fill="x", padx=16, pady=(12, 4))
        ctk.CTkLabel(
            row1, text="Start Date:", font=theme.FONT_STATUS,
            text_color=theme.COLOR_TEXT_DIM, width=100, anchor="w",
        ).pack(side="left")
        self.start_entry = ctk.CTkEntry(
            row1, font=theme.FONT_LOG, width=160,
            fg_color=theme.BG_INPUT, text_color=theme.COLOR_TEXT,
        )
        self.start_entry.pack(side="left", padx=(8, 0))
        # Default: 1 year ago
        default_start = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
        self.start_entry.insert(0, default_start)

        # End date
        row2 = ctk.CTkFrame(form, fg_color="transparent")
        row2.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(
            row2, text="End Date:", font=theme.FONT_STATUS,
            text_color=theme.COLOR_TEXT_DIM, width=100, anchor="w",
        ).pack(side="left")
        self.end_entry = ctk.CTkEntry(
            row2, font=theme.FONT_LOG, width=160,
            fg_color=theme.BG_INPUT, text_color=theme.COLOR_TEXT,
        )
        self.end_entry.pack(side="left", padx=(8, 0))
        default_end = datetime.now().strftime("%Y-%m-%d")
        self.end_entry.insert(0, default_end)

        # Capital
        row3 = ctk.CTkFrame(form, fg_color="transparent")
        row3.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(
            row3, text="Capital ($):", font=theme.FONT_STATUS,
            text_color=theme.COLOR_TEXT_DIM, width=100, anchor="w",
        ).pack(side="left")
        self.capital_entry = ctk.CTkEntry(
            row3, font=theme.FONT_LOG, width=160,
            fg_color=theme.BG_INPUT, text_color=theme.COLOR_TEXT,
        )
        self.capital_entry.pack(side="left", padx=(8, 0))
        self.capital_entry.insert(0, "100000")

        # Threshold
        row4 = ctk.CTkFrame(form, fg_color="transparent")
        row4.pack(fill="x", padx=16, pady=(4, 12))
        ctk.CTkLabel(
            row4, text="Threshold:", font=theme.FONT_STATUS,
            text_color=theme.COLOR_TEXT_DIM, width=100, anchor="w",
        ).pack(side="left")
        self.threshold_entry = ctk.CTkEntry(
            row4, font=theme.FONT_LOG, width=80,
            fg_color=theme.BG_INPUT, text_color=theme.COLOR_TEXT,
        )
        self.threshold_entry.pack(side="left", padx=(8, 0))
        self.threshold_entry.insert(0, "7")

        # Info section
        info_frame = ctk.CTkFrame(self, fg_color=theme.BG_PANEL, corner_radius=8)
        info_frame.pack(fill="x", padx=16, pady=(0, 8))

        # Watchlist info
        watchlist_count = self._get_watchlist_count()
        ctk.CTkLabel(
            info_frame,
            text=f"Watchlist: {watchlist_count} tickers (from config/watchlist.json)",
            font=("Segoe UI", 9),
            text_color=theme.COLOR_TEXT_DIM,
        ).pack(padx=16, pady=(8, 2))

        # Estimated cost
        ctk.CTkLabel(
            info_frame,
            text="AI: Screener (Gemini 2.5 FREE) + Judge (GPT-5.2)",
            font=("Segoe UI", 9),
            text_color=theme.COLOR_TEXT_DIM,
        ).pack(padx=16, pady=2)

        ctk.CTkLabel(
            info_frame,
            text="News: SKIPPED | Entry: Next day's Open | Runtime: ~2-3h for 1 year",
            font=("Segoe UI", 9),
            text_color=theme.COLOR_TEXT_DIM,
        ).pack(padx=16, pady=(2, 8))

        # Error label (hidden by default)
        self.error_label = ctk.CTkLabel(
            self,
            text="",
            font=("Segoe UI", 10),
            text_color=theme.COLOR_ERROR,
        )
        self.error_label.pack(pady=(0, 4))

        # Buttons
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(pady=(4, 16))

        ctk.CTkButton(
            btn_frame,
            text="Cancel",
            fg_color=theme.COLOR_BUTTON,
            hover_color=theme.COLOR_BUTTON_HOVER,
            width=120,
            height=36,
            command=self.destroy,
        ).pack(side="left", padx=8)

        self.start_btn = ctk.CTkButton(
            btn_frame,
            text="START REPLAY",
            fg_color=theme.ACCENT_AI,
            hover_color="#9070dd",
            text_color="#ffffff",
            font=theme.FONT_BUTTON,
            width=160,
            height=36,
            command=self._on_start,
        )
        self.start_btn.pack(side="left", padx=8)

    def _get_watchlist_count(self) -> int:
        """Count tickers in watchlist.json."""
        try:
            from pathlib import Path
            import sys as _sys
            if getattr(_sys, 'frozen', False):
                root = Path.cwd()
            else:
                root = Path(__file__).parent.parent.parent
            watchlist_path = root / "config" / "watchlist.json"
            if watchlist_path.exists():
                with open(watchlist_path, "r", encoding="utf-8") as f:
                    watchlist = json.load(f)
                count = sum(len(v) for v in watchlist.values())
                return count
        except Exception:
            pass
        return 0

    def _on_start(self) -> None:
        """Validate inputs and start replay."""
        start_date = self.start_entry.get().strip()
        end_date = self.end_entry.get().strip()

        # Validate dates
        try:
            s = datetime.strptime(start_date, "%Y-%m-%d")
            e = datetime.strptime(end_date, "%Y-%m-%d")
            if e <= s:
                self.error_label.configure(text="End date must be after start date")
                return
        except ValueError:
            self.error_label.configure(text="Invalid date format. Use YYYY-MM-DD")
            return

        # Validate capital
        try:
            capital = float(self.capital_entry.get().strip())
            if capital <= 0:
                raise ValueError
        except ValueError:
            self.error_label.configure(text="Invalid capital amount")
            return

        # Validate threshold
        try:
            threshold = float(self.threshold_entry.get().strip())
            if not 0 <= threshold <= 10:
                raise ValueError
        except ValueError:
            self.error_label.configure(text="Threshold must be 0-10")
            return

        self.error_label.configure(text="")
        self.start_btn.configure(state="disabled", text="STOPPING ENGINE...")

        # Stop the live engine first (avoids Gemini rate limit conflicts)
        engine = self.engine_controller
        if engine and engine.is_running:
            logger.info("[REPLAY] Stopping live engine before replay...")
            threading.Thread(
                target=self._stop_engine_then_replay,
                args=(engine, start_date, end_date, capital, threshold),
                daemon=True,
                name="IARA-Replay",
            ).start()
        else:
            # Engine not running, start replay directly
            self._replay_thread = threading.Thread(
                target=self._run_replay,
                args=(start_date, end_date, capital, threshold),
                daemon=True,
                name="IARA-Replay",
            )
            self._replay_thread.start()

        # Close config dialog
        self.destroy()

    def _stop_engine_then_replay(
        self,
        engine,
        start_date: str,
        end_date: str,
        capital: float,
        threshold: float,
    ) -> None:
        """Stop the live engine, then start the replay."""
        try:
            engine.stop()
            logger.info("[REPLAY] Live engine stopped. Starting replay...")
        except Exception as e:
            logger.error(f"[REPLAY] Error stopping engine: {e}")
        # Now run the replay in the same thread
        self._run_replay(start_date, end_date, capital, threshold)

    def _restart_engine(self) -> None:
        """Restart the live engine after replay ends (error or cancel)."""
        engine = self.engine_controller
        if engine and not engine.is_running:
            logger.info("[REPLAY] Restarting live engine...")
            engine.start()

    def _run_replay(
        self,
        start_date: str,
        end_date: str,
        capital: float,
        threshold: float,
    ) -> None:
        """Run replay in a background thread with its own event loop."""
        import yaml as _yaml
        from pathlib import Path
        import sys as _sys

        logger.info(f"[REPLAY] Starting replay: {start_date} to {end_date}")

        # Create replay state and attach to dashboard for GUI integration
        replay_state = ReplayState()
        replay_state.update({
            "is_running": True,
            "start_date": start_date,
            "end_date": end_date,
            "initial_capital": capital,
            "equity": capital,
            "capital": capital,
        })

        # Attach state to dashboard so _update_metrics can read it
        dashboard = self.dashboard
        if dashboard and hasattr(dashboard, '_replay_state'):
            dashboard._replay_state = replay_state

        def progress_callback(data: dict) -> None:
            """Called by ReplayEngine from background thread."""
            replay_state.update(data)

        try:
            # Load config
            if getattr(_sys, 'frozen', False):
                root = Path.cwd()
            else:
                root = Path(__file__).parent.parent.parent
            config_path = root / "config" / "settings.yaml"
            with open(config_path, "r", encoding="utf-8") as f:
                config = _yaml.safe_load(f)

            # Load tickers from watchlist
            watchlist_path = root / "config" / "watchlist.json"
            tickers = []
            if watchlist_path.exists():
                with open(watchlist_path, "r", encoding="utf-8") as f:
                    watchlist = json.load(f)
                for tier_tickers in watchlist.values():
                    tickers.extend(tier_tickers)

            if not tickers:
                logger.error("[REPLAY] No tickers found in watchlist")
                replay_state.update({"is_running": False})
                self._restart_engine()
                return

            # Initialize AI gateway
            from dotenv import load_dotenv
            load_dotenv()
            from src.decision.ai_gateway import AIGateway
            ai_gateway = AIGateway(config)

            providers = ai_gateway.get_available_providers()
            if not providers:
                logger.error("[REPLAY] No AI providers available")
                replay_state.update({"is_running": False})
                self._restart_engine()
                return

            # Create replay engine with progress callback
            from src.backtesting.replay_engine import ReplayEngine
            self._replay_engine = ReplayEngine(
                config=config,
                ai_gateway=ai_gateway,
                start_date=start_date,
                end_date=end_date,
                initial_capital=capital,
                tickers=tickers,
                progress_callback=progress_callback,
                news_enabled=True,
            )
            self._replay_engine.screener_threshold = threshold

            # Store reference on dashboard for cancel button
            if dashboard and hasattr(dashboard, '_replay_engine'):
                dashboard._replay_engine = self._replay_engine

            # Run with new event loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(self._replay_engine.run())
            finally:
                loop.close()

            # Show results on the main thread
            logger.info(
                f"[REPLAY] Finished: {result.metrics.total_trades} trades | "
                f"Return: {result.metrics.total_return_pct:+.2f}% | "
                f"Sharpe: {result.metrics.sharpe_ratio:.2f}"
            )

            # Open results dialog on main thread
            if dashboard and dashboard.winfo_exists():
                engine_ref = self.engine_controller
                dashboard.after(100, lambda: ReplayResultDialog(
                    dashboard, result, replay_state, engine_controller=engine_ref
                ))

        except Exception as e:
            logger.error(f"[REPLAY] Failed: {e}", exc_info=True)
            replay_state.update({"is_running": False, "finished": False})
            # Restart live engine on failure (no results dialog to handle it)
            self._restart_engine()


class ReplayResultDialog(ctk.CTkToplevel):
    """Dialog displaying replay results."""

    def __init__(self, master, result, replay_state: Optional[ReplayState] = None,
                 engine_controller=None, **kwargs):
        super().__init__(master, **kwargs)

        self.result = result
        self._replay_state = replay_state
        self._dashboard = master
        self._engine_controller = engine_controller

        self.title("IARA Replay Results")
        self.geometry("650x600")
        self.configure(fg_color=theme.BG_DARK)
        self.transient(master)

        # Clear replay state from dashboard when results dialog closes
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_ui()

    def _build_ui(self) -> None:
        metrics = self.result.metrics
        config = self.result.config
        ai_stats = self.result.ai_stats

        # Header
        ctk.CTkLabel(
            self,
            text="REPLAY RESULTS",
            font=("Segoe UI", 20, "bold"),
            text_color=theme.ACCENT_AI,
        ).pack(pady=(12, 2))

        ctk.CTkLabel(
            self,
            text=f"{config.get('start_date', '?')} to {config.get('end_date', '?')} | "
                 f"${config.get('initial_capital', 100000):,.0f} capital | "
                 f"{config.get('ticker_count', 0)} tickers",
            font=("Segoe UI", 10),
            text_color=theme.COLOR_TEXT_DIM,
        ).pack(pady=(0, 10))

        # Scrollable content
        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        # Returns section
        self._add_section(scroll, "RETURNS", [
            ("Total Return", f"{metrics.total_return_pct:+.2f}%",
             theme.COLOR_SUCCESS if metrics.total_return_pct >= 0 else theme.COLOR_ERROR),
            ("Annualized Return", f"{metrics.annualized_return_pct:+.2f}%",
             theme.COLOR_SUCCESS if metrics.annualized_return_pct >= 0 else theme.COLOR_ERROR),
            ("SPY Benchmark", f"{metrics.benchmark_return_pct:+.2f}%", theme.COLOR_TEXT),
            ("Alpha", f"{metrics.alpha:+.2f}%",
             theme.COLOR_SUCCESS if metrics.alpha >= 0 else theme.COLOR_ERROR),
        ])

        # Risk section
        self._add_section(scroll, "RISK", [
            ("Sharpe Ratio", f"{metrics.sharpe_ratio:.2f}",
             theme.COLOR_SUCCESS if metrics.sharpe_ratio >= 1 else theme.COLOR_WARNING),
            ("Sortino Ratio", f"{metrics.sortino_ratio:.2f}",
             theme.COLOR_SUCCESS if metrics.sortino_ratio >= 1 else theme.COLOR_WARNING),
            ("Max Drawdown", f"{metrics.max_drawdown_pct:.2f}%",
             theme.COLOR_ERROR if metrics.max_drawdown_pct > 6 else theme.COLOR_WARNING),
            ("Max DD Duration", f"{metrics.max_drawdown_duration_days} days", theme.COLOR_TEXT),
        ])

        # Trades section
        pf_str = f"{metrics.profit_factor:.2f}" if metrics.profit_factor != float("inf") else "INF"
        self._add_section(scroll, "TRADES", [
            ("Total Trades", str(metrics.total_trades), theme.COLOR_TEXT),
            ("Win Rate", f"{metrics.win_rate:.1f}%",
             theme.COLOR_SUCCESS if metrics.win_rate >= 50 else theme.COLOR_WARNING),
            ("Avg Win", f"{metrics.avg_win_pct:+.2f}%", theme.COLOR_SUCCESS),
            ("Avg Loss", f"{metrics.avg_loss_pct:+.2f}%", theme.COLOR_ERROR),
            ("Profit Factor", pf_str,
             theme.COLOR_SUCCESS if metrics.profit_factor > 1 else theme.COLOR_WARNING),
            ("Best Trade", f"{metrics.best_trade_pct:+.2f}%", theme.COLOR_SUCCESS),
            ("Worst Trade", f"{metrics.worst_trade_pct:+.2f}%", theme.COLOR_ERROR),
            ("Avg Holding", f"{metrics.avg_holding_days:.1f} days", theme.COLOR_TEXT),
        ])

        # AI Usage section
        self._add_section(scroll, "AI USAGE", [
            ("Screener Calls", f"{ai_stats.get('screener_calls', 0)} (Gemini 2.5 FREE)",
             theme.COLOR_TEXT),
            ("Judge Calls", f"{ai_stats.get('judge_calls', 0)} (GPT-5.2)",
             theme.COLOR_TEXT),
            ("Estimated Cost", f"${ai_stats.get('estimated_cost_usd', 0):.2f}",
             theme.COLOR_WARNING),
        ])

        # Buttons
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(pady=(4, 12))

        ctk.CTkButton(
            btn_frame,
            text="Save JSON",
            fg_color=theme.COLOR_BUTTON,
            hover_color=theme.COLOR_BUTTON_HOVER,
            width=120,
            command=self._on_save,
        ).pack(side="left", padx=8)

        ctk.CTkButton(
            btn_frame,
            text="View Trades",
            fg_color=theme.COLOR_BUTTON,
            hover_color=theme.COLOR_BUTTON_HOVER,
            width=120,
            command=self._on_view_trades,
        ).pack(side="left", padx=8)

        ctk.CTkButton(
            btn_frame,
            text="Close",
            fg_color=theme.ACCENT_AI,
            hover_color="#9070dd",
            text_color="#ffffff",
            width=100,
            command=self._on_close,
        ).pack(side="left", padx=8)

    def _on_close(self) -> None:
        """Clear replay state, restart live engine, and close dialog."""
        if self._replay_state:
            self._replay_state.clear()
        if self._dashboard and hasattr(self._dashboard, '_replay_state'):
            self._dashboard._replay_state = None
            self._dashboard._replay_engine = None
        # Restart live engine (was stopped before replay)
        engine = self._engine_controller
        if engine and not engine.is_running:
            logger.info("[REPLAY] Restarting live engine after replay...")
            engine.start()
        self.destroy()

    def _add_section(self, parent, title: str, rows: list) -> None:
        """Add a section with title and key-value rows."""
        section = ctk.CTkFrame(parent, fg_color=theme.BG_PANEL, corner_radius=8)
        section.pack(fill="x", pady=(0, 8))

        # Section title
        ctk.CTkLabel(
            section,
            text=title,
            font=("Segoe UI Semibold", 11),
            text_color=theme.ACCENT_AI,
        ).pack(padx=16, pady=(8, 4), anchor="w")

        # Rows
        for label, value, color in rows:
            row_frame = ctk.CTkFrame(section, fg_color="transparent")
            row_frame.pack(fill="x", padx=16, pady=1)
            ctk.CTkLabel(
                row_frame, text=label, font=theme.FONT_STATUS,
                text_color=theme.COLOR_TEXT_DIM, anchor="w",
            ).pack(side="left")
            ctk.CTkLabel(
                row_frame, text=value, font=("Segoe UI Semibold", 11),
                text_color=color, anchor="e",
            ).pack(side="right")

        # Bottom padding
        ctk.CTkFrame(section, fg_color="transparent", height=4).pack()

    def _on_save(self) -> None:
        """Save results to JSON."""
        from src.backtesting.report import BacktestReport
        from pathlib import Path
        import sys as _sys

        if getattr(_sys, 'frozen', False):
            root = Path.cwd()
        else:
            root = Path(__file__).parent.parent.parent

        output_dir = root / "data" / "outputs"
        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = str(output_dir / f"replay_{timestamp}.json")

        BacktestReport.save_to_json(
            {
                "config": self.result.config,
                "metrics": self.result.metrics,
                "trades": self.result.trades,
                "equity_curve": self.result.equity_curve,
                "ai_stats": self.result.ai_stats,
            },
            filepath,
        )
        logger.info(f"[REPLAY] Results saved to {filepath}")

    def _on_view_trades(self) -> None:
        """Show trade log in a new dialog."""
        trades = self.result.trades
        if not trades:
            return

        dialog = ctk.CTkToplevel(self)
        dialog.title("Replay Trade Log")
        dialog.geometry("900x500")
        dialog.configure(fg_color=theme.BG_DARK)
        dialog.transient(self)

        ctk.CTkLabel(
            dialog,
            text=f"TRADE LOG ({len(trades)} trades)",
            font=theme.FONT_HEADER,
            text_color=theme.ACCENT_AI,
        ).pack(pady=(12, 8))

        table = ctk.CTkScrollableFrame(dialog, fg_color=theme.BG_PANEL)
        table.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        # Headers
        headers = ["Ticker", "Dir", "Entry$", "Exit$", "Shares", "P&L%", "Screener", "Judge", "Reason"]
        for i, h in enumerate(headers):
            ctk.CTkLabel(
                table, text=h, font=("Segoe UI Semibold", 10),
                text_color=theme.ACCENT_AI,
            ).grid(row=0, column=i, padx=6, pady=4, sticky="w")

        # Trade rows
        for row_idx, t in enumerate(trades, start=1):
            pnl_pct = t.get("pnl_pct", 0)
            pnl_color = theme.COLOR_SUCCESS if pnl_pct >= 0 else theme.COLOR_ERROR

            values = [
                (t.get("ticker", "?"), theme.COLOR_TEXT),
                (t.get("direction", "?")[:4], theme.ACCENT_PIPELINE),
                (f"${t.get('entry_price', 0):.2f}", theme.COLOR_TEXT),
                (f"${t.get('exit_price', 0):.2f}", theme.COLOR_TEXT),
                (str(t.get("shares", 0)), theme.COLOR_TEXT),
                (f"{pnl_pct:+.2f}%", pnl_color),
                (f"{t.get('screener_score', 0):.1f}", theme.COLOR_TEXT_DIM),
                (f"{t.get('judge_score', 0):.1f}", theme.COLOR_TEXT_DIM),
                (t.get("exit_reason", "?")[:12], theme.COLOR_TEXT_DIM),
            ]

            for col_idx, (val, color) in enumerate(values):
                ctk.CTkLabel(
                    table, text=val, font=theme.FONT_LOG, text_color=color,
                ).grid(row=row_idx, column=col_idx, padx=6, pady=1, sticky="w")
