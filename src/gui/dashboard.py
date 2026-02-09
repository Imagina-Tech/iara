"""
IARA DASHBOARD - Interface visual principal do sistema de trading.

Layout:
  +--[HEADER: Title + Clock + Market Status]--+
  +--[PHASE BAR: Phase 0..4 progress]--------+
  +--[LOG GRID 2x2]---------------------------+
  |  [PIPELINE]         [MARKET DATA]         |
  |  [AI ENGINE]         [GUARDIAN]            |
  +--[METRICS BAR: Capital, P&L, DD, etc.]---+
  +--[STATUS BAR: Engine, APIs, Broker]-------+
  +--[ACTION BAR: Buttons]--------------------+
"""

import logging
import queue
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import customtkinter as ctk

from src.gui import theme
from src.gui.judge_audit import JudgeAuditStore, JudgeAuditPanel
from src.gui.log_handler import GUILogRecord

# Configure CustomTkinter
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

ET = ZoneInfo("America/New_York")


class LogPanel(ctk.CTkFrame):
    """A single log panel with header, scrolling text, and line counter."""

    def __init__(self, master, panel_config: dict, **kwargs):
        super().__init__(
            master,
            corner_radius=theme.PANEL_CORNER_RADIUS,
            fg_color=theme.BG_PANEL,
            border_color=panel_config["accent"],
            border_width=1,
            **kwargs,
        )
        self.accent = panel_config["accent"]
        self.line_count = 0

        # Header (padx/pady must exceed corner_radius to avoid clipping into rounded parent)
        header = ctk.CTkFrame(self, fg_color=theme.BG_PANEL_HEADER, corner_radius=6, height=32)
        header.pack(fill="x", padx=2, pady=(2, 0))
        header.pack_propagate(False)

        icon_label = ctk.CTkLabel(
            header,
            text=panel_config["icon"],
            font=("Consolas", 11, "bold"),
            text_color=self.accent,
        )
        icon_label.pack(side="left", padx=(10, 4))

        title_label = ctk.CTkLabel(
            header,
            text=panel_config["title"],
            font=theme.FONT_PANEL_TITLE,
            text_color=self.accent,
        )
        title_label.pack(side="left")

        desc_label = ctk.CTkLabel(
            header,
            text=f"  {panel_config['description']}",
            font=("Segoe UI", 9),
            text_color=theme.COLOR_TEXT_DIM,
        )
        desc_label.pack(side="left", padx=(4, 0))

        self.line_label = ctk.CTkLabel(
            header,
            text="0 lines",
            font=("Segoe UI", 9),
            text_color=theme.COLOR_TEXT_MUTED,
        )
        self.line_label.pack(side="right", padx=10)

        clear_btn = ctk.CTkButton(
            header,
            text="CLR",
            width=35,
            height=20,
            font=("Consolas", 9),
            fg_color="transparent",
            hover_color=theme.BG_CARD,
            text_color=theme.COLOR_TEXT_DIM,
            corner_radius=3,
            command=self.clear,
        )
        clear_btn.pack(side="right", padx=2)

        # Text area (corner_radius matches parent so bottom corners align cleanly)
        self.textbox = ctk.CTkTextbox(
            self,
            font=theme.FONT_LOG,
            fg_color=theme.BG_INPUT,
            text_color=theme.COLOR_TEXT,
            corner_radius=6,
            wrap="word",
            activate_scrollbars=True,
            state="disabled",
        )
        self.textbox.pack(fill="both", expand=True, padx=2, pady=(2, 2))

        # Configure tags for log level coloring
        text_widget = self.textbox._textbox
        for level, color in theme.LOG_COLORS.items():
            weight = "bold" if level in ("ERROR", "CRITICAL") else "normal"
            text_widget.tag_configure(level, foreground=color, font=("Consolas", 10, weight))
        text_widget.tag_configure("TIMESTAMP", foreground=theme.COLOR_TEXT_MUTED)

    def append(self, record: GUILogRecord) -> None:
        """Append a log record to the panel."""
        text_widget = self.textbox._textbox
        was_at_bottom = self.textbox.yview()[1] >= 0.98

        self.textbox.configure(state="normal")

        # Timestamp
        text_widget.insert("end", f"{record.timestamp} ", "TIMESTAMP")
        # Level tag (short)
        level_short = record.level[:4]
        text_widget.insert("end", f"[{level_short}] ", record.level)
        # Message
        text_widget.insert("end", f"{record.message}\n", record.level)

        self.line_count += 1

        # Trim if too many lines
        if self.line_count > theme.LOG_MAX_LINES:
            excess = self.line_count - theme.LOG_MAX_LINES
            text_widget.delete("1.0", f"{excess + 1}.0")
            self.line_count = theme.LOG_MAX_LINES

        self.textbox.configure(state="disabled")

        if was_at_bottom:
            self.textbox.see("end")

        self.line_label.configure(text=f"{self.line_count} lines")

    def clear(self) -> None:
        """Clear the log panel."""
        self.textbox.configure(state="normal")
        self.textbox._textbox.delete("1.0", "end")
        self.textbox.configure(state="disabled")
        self.line_count = 0
        self.line_label.configure(text="0 lines")


class MetricCard(ctk.CTkFrame):
    """A small metric display card."""

    def __init__(self, master, label: str, value: str = "--", color: str = theme.COLOR_TEXT, **kwargs):
        super().__init__(
            master,
            corner_radius=theme.CARD_CORNER_RADIUS,
            fg_color=theme.BG_CARD,
            border_color=theme.BORDER,
            border_width=1,
            **kwargs,
        )
        self._label_text = label
        self.value_color = color

        self.label_widget = ctk.CTkLabel(
            self,
            text=label,
            font=theme.FONT_METRIC_LABEL,
            text_color=theme.COLOR_TEXT_DIM,
        )
        self.label_widget.pack(pady=(6, 0), padx=10)

        self.value_widget = ctk.CTkLabel(
            self,
            text=value,
            font=theme.FONT_METRIC_VALUE,
            text_color=color,
        )
        self.value_widget.pack(pady=(0, 6), padx=10)

    def set_value(self, value: str, color: Optional[str] = None) -> None:
        self.value_widget.configure(text=value)
        if color:
            self.value_widget.configure(text_color=color)


class StatusDot(ctk.CTkFrame):
    """A small colored status dot with label."""

    def __init__(self, master, label: str, active: bool = False, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self._dot = ctk.CTkLabel(
            self,
            text="●",
            font=("Segoe UI", 10),
            text_color=theme.COLOR_SUCCESS if active else theme.COLOR_TEXT_MUTED,
            width=14,
        )
        self._dot.pack(side="left")

        self._label = ctk.CTkLabel(
            self,
            text=label,
            font=theme.FONT_STATUS,
            text_color=theme.COLOR_TEXT_DIM,
        )
        self._label.pack(side="left", padx=(2, 8))

    def set_active(self, active: bool) -> None:
        self._dot.configure(text_color=theme.COLOR_SUCCESS if active else theme.COLOR_TEXT_MUTED)


class IaraDashboard(ctk.CTk):
    """
    Main IARA Dashboard Window.

    Displays 4 log panels, financial metrics, system status, and action buttons.
    """

    def __init__(
        self,
        log_queue: queue.Queue,
        engine_controller: Any = None,
        audit_queue: Optional[queue.Queue] = None,
    ):
        super().__init__()

        self.log_queue = log_queue
        self._audit_queue = audit_queue
        self.engine = engine_controller
        self.panels: Dict[str, LogPanel] = {}
        self.metric_cards: Dict[str, MetricCard] = {}
        self.status_dots: Dict[str, StatusDot] = {}
        self._startup_time = datetime.now()

        # Replay integration: set by ReplayConfigDialog
        self._replay_state = None  # ReplayState or None
        self._replay_engine = None  # ReplayEngine ref for cancel

        # Audit store (loads persisted entries from disk)
        self._audit_store = JudgeAuditStore()

        # View toggle state
        self._current_view = "dashboard"  # "dashboard" | "audit"

        # Window config
        self.title("IARA - Intelligent Automated Risk-Aware Trader")
        self.minsize(theme.WINDOW_MIN_W, theme.WINDOW_MIN_H)
        self.configure(fg_color=theme.BG_DARK)

        # Try to set window icon
        try:
            self.iconbitmap(default="")
        except Exception:
            pass

        # Build UI - header stays outside frames (always visible)
        self._create_header()

        # Dashboard content frame (everything below header)
        self._dashboard_frame = ctk.CTkFrame(self, fg_color="transparent")
        self._dashboard_frame.pack(fill="both", expand=True)

        self._create_phase_bar()
        self._create_replay_bar()
        self._create_log_grid()
        self._create_metrics_bar()
        self._create_status_bar()
        self._create_action_bar()

        # Audit panel (hidden by default)
        self._audit_panel = JudgeAuditPanel(self, store=self._audit_store)
        # Don't pack yet - toggled via _toggle_view

        # Start update loops
        self._poll_logs()
        self._poll_audit()
        self._update_clock()
        self._update_metrics()

        # True fullscreen (no title bar, no borders, no taskbar)
        self.after(100, lambda: self.attributes("-fullscreen", True))

    # ─── HEADER ──────────────────────────────────────────────────────

    def _create_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color=theme.BG_PANEL, corner_radius=0, height=60)
        header.pack(fill="x", padx=0, pady=0)
        header.pack_propagate(False)

        # Left: Title
        title_frame = ctk.CTkFrame(header, fg_color="transparent")
        title_frame.pack(side="left", padx=16)

        title = ctk.CTkLabel(
            title_frame,
            text="IARA",
            font=theme.FONT_TITLE,
            text_color=theme.COLOR_NEON_BLUE,
        )
        title.pack(side="left")

        subtitle = ctk.CTkLabel(
            title_frame,
            text="  Intelligent Automated Risk-Aware Trader",
            font=theme.FONT_SUBTITLE,
            text_color=theme.COLOR_TEXT_DIM,
        )
        subtitle.pack(side="left", pady=(4, 0))

        version = ctk.CTkLabel(
            title_frame,
            text="  v30.0",
            font=("Segoe UI", 9),
            text_color=theme.COLOR_TEXT_MUTED,
        )
        version.pack(side="left", pady=(6, 0))

        # Right: Minimize + Audit Toggle + Clock + Market Status
        right_frame = ctk.CTkFrame(header, fg_color="transparent")
        right_frame.pack(side="right", padx=16)

        # Minimize button (exit fullscreen -> iconify -> restore fullscreen on map)
        minimize_btn = ctk.CTkButton(
            right_frame,
            text="_",
            font=("Consolas", 14, "bold"),
            fg_color="transparent",
            hover_color=theme.BG_CARD,
            text_color=theme.COLOR_TEXT_DIM,
            width=32,
            height=28,
            corner_radius=4,
            command=self._minimize_window,
        )
        minimize_btn.pack(side="right", padx=(8, 0))

        self.market_label = ctk.CTkLabel(
            right_frame,
            text="MARKET: --",
            font=theme.FONT_STATUS,
            text_color=theme.COLOR_TEXT_DIM,
        )
        self.market_label.pack(side="right", padx=(12, 0))

        self.clock_label = ctk.CTkLabel(
            right_frame,
            text="--:--:-- ET",
            font=theme.FONT_CLOCK,
            text_color=theme.COLOR_TEXT,
        )
        self.clock_label.pack(side="right")

        # Judge Audit toggle button
        self._audit_toggle_btn = ctk.CTkButton(
            right_frame,
            text="JUDGE AUDIT",
            font=("Segoe UI Semibold", 11),
            fg_color=theme.ACCENT_AI,
            hover_color="#9b6fdf",
            text_color="#ffffff",
            width=120,
            height=30,
            corner_radius=6,
            command=self._toggle_view,
        )
        self._audit_toggle_btn.pack(side="right", padx=(0, 12))

    def _minimize_window(self) -> None:
        """Minimize from true fullscreen: exit fullscreen, iconify, restore on map."""
        self.attributes("-fullscreen", False)
        self.iconify()

        def _restore_fullscreen(event):
            self.attributes("-fullscreen", True)
            self.unbind("<Map>")

        self.bind("<Map>", _restore_fullscreen)

    # ─── PHASE BAR ──────────────────────────────────────────────────

    def _create_phase_bar(self) -> None:
        bar = ctk.CTkFrame(self._dashboard_frame, fg_color=theme.BG_PANEL, corner_radius=0, height=36)
        bar.pack(fill="x", padx=0, pady=(1, 0))
        bar.pack_propagate(False)
        self._phase_bar = bar  # ref for replay bar insertion

        label = ctk.CTkLabel(
            bar,
            text="PHASES:",
            font=theme.FONT_PHASE,
            text_color=theme.COLOR_TEXT_DIM,
        )
        label.pack(side="left", padx=(16, 8))

        self.phase_labels = []
        phase_names = [
            "0: Buzz Factory",
            "1: Screener",
            "2: The Vault",
            "3: The Judge",
            "4: Execution",
            "5: Guardian",
        ]

        for i, name in enumerate(phase_names):
            fg = theme.BG_CARD
            text_color = theme.COLOR_TEXT_MUTED
            border_color = theme.BORDER

            frame = ctk.CTkFrame(
                bar,
                fg_color=fg,
                corner_radius=4,
                height=24,
                border_color=border_color,
                border_width=1,
            )
            frame.pack(side="left", padx=3, pady=6)
            frame.pack_propagate(False)

            lbl = ctk.CTkLabel(
                frame,
                text=f"  {name}  ",
                font=("Segoe UI", 9),
                text_color=text_color,
            )
            lbl.pack(fill="both", expand=True)

            self.phase_labels.append((frame, lbl))

        # Uptime label
        self.uptime_label = ctk.CTkLabel(
            bar,
            text="Uptime: 0m",
            font=("Segoe UI", 9),
            text_color=theme.COLOR_TEXT_MUTED,
        )
        self.uptime_label.pack(side="right", padx=16)

    def set_phase(self, active_phase: int, completed_phases: Optional[List[int]] = None) -> None:
        """Update phase bar visualization."""
        completed = completed_phases or []
        for i, (frame, lbl) in enumerate(self.phase_labels):
            if i == active_phase:
                # Currently running
                frame.configure(fg_color=theme.ACCENT_PIPELINE, border_color=theme.ACCENT_PIPELINE)
                lbl.configure(text_color="#ffffff")
            elif i in completed:
                # Completed
                frame.configure(fg_color="#1a3a2a", border_color=theme.COLOR_SUCCESS)
                lbl.configure(text_color=theme.COLOR_SUCCESS)
            else:
                # Pending
                frame.configure(fg_color=theme.BG_CARD, border_color=theme.BORDER)
                lbl.configure(text_color=theme.COLOR_TEXT_MUTED)

    # ─── REPLAY BAR (hidden by default) ──────────────────────────────

    def _create_replay_bar(self) -> None:
        """Create a replay progress bar (hidden until replay starts)."""
        self._replay_bar = ctk.CTkFrame(self._dashboard_frame, fg_color=theme.BG_PANEL, corner_radius=0, height=44)
        # Don't pack yet - shown/hidden dynamically
        self._replay_bar.pack_propagate(False)

        # Left: REPLAY badge
        self._replay_badge = ctk.CTkLabel(
            self._replay_bar,
            text=" REPLAY ",
            font=("Segoe UI", 10, "bold"),
            text_color="#ffffff",
            fg_color=theme.ACCENT_AI,
            corner_radius=4,
        )
        self._replay_badge.pack(side="left", padx=(12, 8), pady=8)

        # Date label
        self._replay_date_label = ctk.CTkLabel(
            self._replay_bar,
            text="--",
            font=("Consolas", 10),
            text_color=theme.COLOR_TEXT_DIM,
        )
        self._replay_date_label.pack(side="left", padx=(0, 8))

        # Progress bar
        self._replay_progress = ctk.CTkProgressBar(
            self._replay_bar,
            width=300,
            height=14,
            fg_color=theme.BG_CARD,
            progress_color=theme.ACCENT_AI,
            corner_radius=4,
        )
        self._replay_progress.set(0)
        self._replay_progress.pack(side="left", padx=(0, 8), pady=8)

        # Progress text
        self._replay_progress_label = ctk.CTkLabel(
            self._replay_bar,
            text="0 / 0 days (0%)",
            font=("Consolas", 10),
            text_color=theme.COLOR_TEXT,
        )
        self._replay_progress_label.pack(side="left", padx=(0, 12))

        # Quick stats (compact)
        self._replay_equity_label = ctk.CTkLabel(
            self._replay_bar,
            text="Equity: --",
            font=("Consolas", 10),
            text_color=theme.COLOR_TEXT,
        )
        self._replay_equity_label.pack(side="left", padx=(8, 0))

        self._replay_trades_label = ctk.CTkLabel(
            self._replay_bar,
            text="| Trades: -- | AI: --",
            font=("Consolas", 10),
            text_color=theme.COLOR_TEXT_DIM,
        )
        self._replay_trades_label.pack(side="left", padx=(6, 0))

        # Stop button (right side)
        self._replay_stop_btn = ctk.CTkButton(
            self._replay_bar,
            text="STOP",
            font=("Segoe UI Semibold", 10),
            fg_color=theme.COLOR_KILL_SWITCH,
            hover_color="#ff2222",
            text_color="#ffffff",
            width=70,
            height=26,
            corner_radius=4,
            command=self._on_stop_replay,
        )
        self._replay_stop_btn.pack(side="right", padx=12, pady=8)

        self._replay_bar_visible = False

    def _show_replay_bar(self) -> None:
        """Show the replay progress bar."""
        if not self._replay_bar_visible:
            self._replay_bar.pack(fill="x", padx=0, pady=(1, 0), after=self._phase_bar)
            self._replay_bar_visible = True

    def _hide_replay_bar(self) -> None:
        """Hide the replay progress bar."""
        if self._replay_bar_visible:
            self._replay_bar.pack_forget()
            self._replay_bar_visible = False

    def _on_stop_replay(self) -> None:
        """Stop the running replay."""
        if self._replay_engine:
            self._replay_engine.stop()
            self._replay_stop_btn.configure(text="STOPPING...", state="disabled")

    # ─── LOG GRID ────────────────────────────────────────────────────

    def _create_log_grid(self) -> None:
        grid_frame = ctk.CTkFrame(self._dashboard_frame, fg_color="transparent")
        grid_frame.pack(fill="both", expand=True, padx=8, pady=6)
        grid_frame.grid_rowconfigure(0, weight=1)
        grid_frame.grid_rowconfigure(1, weight=1)
        grid_frame.grid_columnconfigure(0, weight=1)
        grid_frame.grid_columnconfigure(1, weight=1)

        for idx, panel_cfg in enumerate(theme.PANELS):
            row = idx // 2
            col = idx % 2
            panel = LogPanel(grid_frame, panel_cfg)
            panel.grid(row=row, column=col, padx=4, pady=4, sticky="nsew")
            self.panels[panel_cfg["id"]] = panel

    # ─── METRICS BAR ─────────────────────────────────────────────────

    def _create_metrics_bar(self) -> None:
        bar = ctk.CTkFrame(self._dashboard_frame, fg_color=theme.BG_PANEL, corner_radius=0, height=70)
        bar.pack(fill="x", padx=0, pady=(2, 0))
        bar.pack_propagate(False)

        metrics = [
            ("capital", "CAPITAL", "$100,000", theme.COLOR_TEXT),
            ("daily_pnl", "DAILY P&L", "$0.00", theme.COLOR_TEXT_DIM),
            ("total_pnl", "TOTAL P&L", "$0.00", theme.COLOR_TEXT_DIM),
            ("drawdown", "DRAWDOWN", "0.0%", theme.COLOR_SUCCESS),
            ("positions", "POSITIONS", "0 / 5", theme.COLOR_TEXT),
            ("vix", "VIX", "--", theme.COLOR_TEXT_DIM),
            ("trades_today", "TRADES TODAY", "0", theme.COLOR_TEXT_DIM),
            ("win_rate", "WIN RATE", "--%", theme.COLOR_TEXT_DIM),
        ]

        container = ctk.CTkFrame(bar, fg_color="transparent")
        container.pack(expand=True)

        for key, label, default, color in metrics:
            card = MetricCard(container, label=label, value=default, color=color)
            card.pack(side="left", padx=6, pady=8)
            self.metric_cards[key] = card

    # ─── STATUS BAR ──────────────────────────────────────────────────

    def _create_status_bar(self) -> None:
        bar = ctk.CTkFrame(self._dashboard_frame, fg_color=theme.BG_PANEL_HEADER, corner_radius=0, height=32)
        bar.pack(fill="x", padx=0, pady=(1, 0))
        bar.pack_propagate(False)

        # Engine status
        self.engine_status_label = ctk.CTkLabel(
            bar,
            text="  ENGINE: STOPPED",
            font=theme.FONT_STATUS,
            text_color=theme.COLOR_TEXT_MUTED,
        )
        self.engine_status_label.pack(side="left", padx=(12, 0))

        self._spinning_chars = ["|", "/", "-", "\\"]
        self._spin_idx = 0
        self.spinner_label = ctk.CTkLabel(
            bar,
            text="|",
            font=("Consolas", 11, "bold"),
            text_color=theme.COLOR_NEON_BLUE,
            width=16,
        )
        self.spinner_label.pack(side="left", padx=(4, 12))

        # Separator
        sep = ctk.CTkLabel(bar, text="|", text_color=theme.BORDER, font=("Segoe UI", 10))
        sep.pack(side="left")

        # API status dots
        apis = [
            ("openai", "OpenAI"),
            ("gemini", "Gemini"),
            ("anthropic", "Anthropic"),
        ]
        api_label = ctk.CTkLabel(
            bar, text="  APIs:", font=theme.FONT_STATUS, text_color=theme.COLOR_TEXT_DIM
        )
        api_label.pack(side="left", padx=(8, 4))

        for key, name in apis:
            dot = StatusDot(bar, name)
            dot.pack(side="left")
            self.status_dots[key] = dot

        # Separator
        sep2 = ctk.CTkLabel(bar, text=" | ", text_color=theme.BORDER, font=("Segoe UI", 10))
        sep2.pack(side="left")

        # Broker mode selector
        broker_label = ctk.CTkLabel(
            bar,
            text="Mode:",
            font=theme.FONT_STATUS,
            text_color=theme.COLOR_TEXT_DIM,
        )
        broker_label.pack(side="left", padx=(4, 2))

        self._broker_modes = ["paper_local", "alpaca_paper", "alpaca_live"]
        self._broker_var = ctk.StringVar(value="paper_local")
        self.broker_selector = ctk.CTkOptionMenu(
            bar,
            values=self._broker_modes,
            variable=self._broker_var,
            width=130,
            height=22,
            font=("Consolas", 10),
            dropdown_font=("Consolas", 10),
            fg_color=theme.BG_CARD,
            button_color=theme.BORDER,
            button_hover_color=theme.COLOR_BUTTON_HOVER,
            dropdown_fg_color=theme.BG_PANEL,
            dropdown_hover_color=theme.BG_CARD,
            text_color=theme.COLOR_TEXT,
            corner_radius=4,
            command=self._on_broker_mode_changed,
        )
        self.broker_selector.pack(side="left", padx=2)

        # Separator
        sep3 = ctk.CTkLabel(bar, text=" | ", text_color=theme.BORDER, font=("Segoe UI", 10))
        sep3.pack(side="left")

        # Kill switch status
        self.kill_switch_label = ctk.CTkLabel(
            bar,
            text="Kill Switch: OFF",
            font=theme.FONT_STATUS,
            text_color=theme.COLOR_SUCCESS,
        )
        self.kill_switch_label.pack(side="left", padx=4)

    # ─── ACTION BAR ──────────────────────────────────────────────────

    def _create_action_bar(self) -> None:
        bar = ctk.CTkFrame(self._dashboard_frame, fg_color=theme.BG_PANEL, corner_radius=0, height=50)
        bar.pack(fill="x", padx=0, pady=(1, 0))
        bar.pack_propagate(False)

        container = ctk.CTkFrame(bar, fg_color="transparent")
        container.pack(expand=True)

        # START/STOP toggle (special - wider, colored)
        self._engine_btn = ctk.CTkButton(
            container,
            text="START ENGINE",
            font=theme.FONT_BUTTON,
            fg_color=theme.COLOR_SUCCESS,
            text_color="#ffffff",
            hover_color="#2ea043",
            corner_radius=theme.BUTTON_CORNER_RADIUS,
            height=34,
            width=150,
            command=self._on_engine_toggle,
        )
        self._engine_btn.pack(side="left", padx=6, pady=8)

        buttons = [
            ("TEST PIPELINE", self._on_test_pipeline, theme.COLOR_BUTTON, theme.ACCENT_PIPELINE, None),
            ("REPLAY", self._on_replay, theme.COLOR_BUTTON, theme.ACCENT_AI, None),
            ("POSITIONS", self._on_show_positions, theme.COLOR_BUTTON, theme.COLOR_TEXT, None),
            ("CAPITAL DETAIL", self._on_show_capital, theme.COLOR_BUTTON, theme.ACCENT_MARKET, None),
            ("CLEAR LOGS", self._on_clear_all_logs, theme.COLOR_BUTTON, theme.COLOR_TEXT_DIM, None),
            ("KILL SWITCH", self._on_kill_switch, theme.COLOR_KILL_SWITCH, "#ffffff", theme.COLOR_ERROR),
        ]

        for text, cmd, fg, text_color, hover_color in buttons:
            btn = ctk.CTkButton(
                container,
                text=text,
                font=theme.FONT_BUTTON,
                fg_color=fg,
                text_color=text_color,
                hover_color=hover_color or theme.COLOR_BUTTON_HOVER,
                corner_radius=theme.BUTTON_CORNER_RADIUS,
                height=34,
                width=140,
                command=cmd,
            )
            btn.pack(side="left", padx=6, pady=8)

    # ─── UPDATE LOOPS ────────────────────────────────────────────────

    def _poll_logs(self) -> None:
        """Poll the log queue and dispatch records to panels."""
        batch = 0
        while batch < 50:  # Process up to 50 records per poll
            try:
                record: GUILogRecord = self.log_queue.get_nowait()
                panel = self.panels.get(record.panel_id)
                if panel:
                    panel.append(record)
                batch += 1
            except queue.Empty:
                break

        self.after(100, self._poll_logs)

    def _poll_audit(self) -> None:
        """Poll the audit queue and add entries to the store (file + memory)."""
        if self._audit_queue:
            batch = 0
            while batch < 20:
                try:
                    entry = self._audit_queue.get_nowait()
                    self._audit_store.add(entry)
                except queue.Empty:
                    break
                batch += 1
        self.after(500, self._poll_audit)

    def _toggle_view(self) -> None:
        """Toggle between dashboard and audit views."""
        if self._current_view == "dashboard":
            # Switch to audit view - refresh to show entries added while on dashboard
            self._dashboard_frame.pack_forget()
            self._audit_panel.refresh()
            self._audit_panel.pack(fill="both", expand=True)
            self._audit_toggle_btn.configure(text="DASHBOARD")
            self._current_view = "audit"
        else:
            # Switch to dashboard view
            self._audit_panel.pack_forget()
            self._dashboard_frame.pack(fill="both", expand=True)
            self._audit_toggle_btn.configure(text="JUDGE AUDIT")
            self._current_view = "dashboard"

    def _update_clock(self) -> None:
        """Update clock, market status, spinner, and uptime."""
        now_et = datetime.now(ET)
        self.clock_label.configure(text=now_et.strftime("%I:%M:%S %p ET"))

        # Market status
        weekday = now_et.weekday()
        hour = now_et.hour
        minute = now_et.minute
        time_mins = hour * 60 + minute

        if weekday >= 5:
            self.market_label.configure(text="MARKET: CLOSED (Weekend)", text_color=theme.COLOR_TEXT_MUTED)
        elif 570 <= time_mins <= 960:  # 9:30 - 16:00
            self.market_label.configure(text="MARKET: OPEN", text_color=theme.COLOR_SUCCESS)
        elif 480 <= time_mins < 570:  # 8:00 - 9:30
            self.market_label.configure(text="PRE-MARKET", text_color=theme.COLOR_WARNING)
        elif 960 < time_mins <= 1080:  # 16:00 - 18:00
            self.market_label.configure(text="AFTER-HOURS", text_color=theme.COLOR_WARNING)
        else:
            self.market_label.configure(text="MARKET: CLOSED", text_color=theme.COLOR_TEXT_MUTED)

        # Spinner
        self._spin_idx = (self._spin_idx + 1) % len(self._spinning_chars)
        if self.engine and self.engine.is_running:
            self.spinner_label.configure(text=self._spinning_chars[self._spin_idx])
        else:
            self.spinner_label.configure(text=" ")

        # Uptime
        elapsed = datetime.now() - self._startup_time
        hours, remainder = divmod(int(elapsed.total_seconds()), 3600)
        minutes = remainder // 60
        if hours > 0:
            self.uptime_label.configure(text=f"Uptime: {hours}h {minutes}m")
        else:
            self.uptime_label.configure(text=f"Uptime: {minutes}m")

        self.after(1000, self._update_clock)

    def _update_metrics(self) -> None:
        """Poll engine state and update metric cards."""
        # Keep START/STOP button in sync
        self._update_engine_btn()

        # Replay mode takes priority over live metrics
        if self._replay_state and self._replay_state.is_active:
            try:
                self._sync_replay_metrics()
            except Exception:
                pass
        elif self.engine and self.engine.is_running:
            try:
                self._hide_replay_bar()
                self._sync_metrics()
            except Exception:
                pass
        else:
            # Engine not running - show idle state
            self._hide_replay_bar()
            self.engine_status_label.configure(
                text="  ENGINE: STOPPED", text_color=theme.COLOR_TEXT_MUTED
            )
            self.spinner_label.configure(text=" ")

        self.after(2000, self._update_metrics)

    def _sync_metrics(self) -> None:
        """Read state from engine and update UI."""
        if not self.engine:
            return

        sm = self.engine.state_manager
        if not sm:
            return

        # Restore label names that replay mode may have changed
        self.metric_cards["daily_pnl"].label_widget.configure(text="DAILY P&L")
        self.metric_cards["total_pnl"].label_widget.configure(text="TOTAL P&L")
        self.metric_cards["trades_today"].label_widget.configure(text="TRADES TODAY")
        self.metric_cards["vix"].label_widget.configure(text="VIX")

        # Capital
        capital = sm.capital
        self.metric_cards["capital"].set_value(f"${capital:,.0f}")

        # Daily P&L
        daily_pnl = 0.0
        if sm.daily_stats:
            daily_pnl = sm.daily_stats.realized_pnl + sm.daily_stats.unrealized_pnl
        pnl_color = theme.COLOR_SUCCESS if daily_pnl >= 0 else theme.COLOR_ERROR
        sign = "+" if daily_pnl >= 0 else ""
        self.metric_cards["daily_pnl"].set_value(f"{sign}${abs(daily_pnl):,.2f}", pnl_color)

        # Total P&L
        starting = getattr(sm, "starting_capital", 100000)
        total_pnl = capital - starting
        total_color = theme.COLOR_SUCCESS if total_pnl >= 0 else theme.COLOR_ERROR
        sign_t = "+" if total_pnl >= 0 else ""
        self.metric_cards["total_pnl"].set_value(f"{sign_t}${abs(total_pnl):,.2f}", total_color)

        # Drawdown
        dd = sm.get_current_drawdown() * 100  # ratio -> percentage
        dd_color = theme.COLOR_SUCCESS
        if dd > 3:
            dd_color = theme.COLOR_WARNING
        if dd > 5:
            dd_color = theme.COLOR_ERROR
        self.metric_cards["drawdown"].set_value(f"{dd:.1f}%", dd_color)

        # Positions
        positions = sm.get_open_positions() if hasattr(sm, "get_open_positions") else []
        max_pos = sm.config.get("risk", {}).get("max_positions", 5) if hasattr(sm, "config") else 5
        pos_count = len(positions)
        self.metric_cards["positions"].set_value(f"{pos_count} / {max_pos}")

        # Trades today & win rate
        if sm.daily_stats:
            trades = sm.daily_stats.trades_count
            wins = sm.daily_stats.wins
            self.metric_cards["trades_today"].set_value(str(trades))
            if trades > 0:
                wr = (wins / trades) * 100
                wr_color = theme.COLOR_SUCCESS if wr >= 50 else theme.COLOR_WARNING
                self.metric_cards["win_rate"].set_value(f"{wr:.0f}%", wr_color)

        # VIX (from macro data if available)
        macro = self.engine.macro_data
        if macro and hasattr(macro, "_last_snapshot") and macro._last_snapshot:
            vix = macro._last_snapshot.vix
            vix_color = theme.COLOR_SUCCESS
            if vix >= 20:
                vix_color = theme.COLOR_WARNING
            if vix >= 30:
                vix_color = theme.COLOR_ERROR
            self.metric_cards["vix"].set_value(f"{vix:.1f}", vix_color)

        # Engine status
        if self.engine.is_running:
            self.engine_status_label.configure(text="  ENGINE: RUNNING", text_color=theme.COLOR_SUCCESS)
        else:
            self.engine_status_label.configure(text="  ENGINE: STOPPED", text_color=theme.COLOR_ERROR)

        # Kill switch
        if sm.is_kill_switch_active():
            self.kill_switch_label.configure(text="Kill Switch: ACTIVE", text_color=theme.COLOR_CRITICAL)
        else:
            self.kill_switch_label.configure(text="Kill Switch: OFF", text_color=theme.COLOR_SUCCESS)

        # Broker - sync selector with engine's actual mode
        broker_provider = self.engine.broker_provider or "paper_local"
        if self._broker_var.get() != broker_provider:
            self._broker_var.set(broker_provider)

        # API dots
        if self.engine.ai_gateway:
            providers = self.engine.ai_gateway.get_available_providers()
            provider_names = [str(p) for p in providers] if providers else []
            self.status_dots["openai"].set_active(
                any("openai" in p.lower() or "gpt" in p.lower() for p in provider_names)
            )
            self.status_dots["gemini"].set_active(
                any("gemini" in p.lower() or "google" in p.lower() for p in provider_names)
            )
            self.status_dots["anthropic"].set_active(
                any("anthropic" in p.lower() or "claude" in p.lower() for p in provider_names)
            )

        # Phase indicator
        orchestrator = self.engine.orchestrator
        if orchestrator:
            current = getattr(orchestrator, "current_phase", -1)
            completed = []
            # Determine completed phases from pipeline state
            last_done = -1
            if sm and hasattr(sm, "get_last_completed_phase"):
                last_done = sm.get_last_completed_phase()
            completed = list(range(last_done + 1))

            # Phase 5 (Guardian) is always active when engine runs
            if self.engine.is_running:
                if current < 0:
                    current = 5  # Guardian active by default
            self.set_phase(current, completed)

    def _sync_replay_metrics(self) -> None:
        """Read replay state and update UI with replay metrics."""
        if not self._replay_state:
            return

        snap = self._replay_state.snapshot()
        is_running = snap.get("is_running", False)
        finished = snap.get("finished", False)

        # Show/update replay progress bar
        self._show_replay_bar()

        day_cur = snap.get("day_current", 0)
        day_tot = snap.get("day_total", 0) or 1
        pct = day_cur / day_tot
        sim_date = snap.get("date", "")

        self._replay_progress.set(pct)
        self._replay_progress_label.configure(
            text=f"{day_cur} / {day_tot} days ({pct * 100:.0f}%)"
        )
        self._replay_date_label.configure(text=sim_date)

        # Equity display on progress bar
        equity = snap.get("equity", 0)
        initial = snap.get("initial_capital", 100_000) or 100_000
        ret_pct = ((equity / initial) - 1.0) * 100 if initial > 0 else 0
        eq_color = theme.COLOR_SUCCESS if ret_pct >= 0 else theme.COLOR_ERROR
        self._replay_equity_label.configure(
            text=f"Equity: ${equity:,.0f} ({ret_pct:+.1f}%)",
            text_color=eq_color,
        )

        # Trades + AI stats on progress bar
        trades = snap.get("trades_count", 0)
        scr_calls = snap.get("screener_calls", 0)
        judge_calls = snap.get("judge_calls", 0)
        self._replay_trades_label.configure(
            text=f"| Trades: {trades} | AI: S={scr_calls} J={judge_calls}"
        )

        # Stop button state
        if finished:
            self._replay_stop_btn.configure(text="DONE", state="disabled",
                                            fg_color=theme.COLOR_SUCCESS)
            self._replay_badge.configure(text=" REPLAY DONE ", fg_color=theme.COLOR_SUCCESS)
        elif is_running:
            self._replay_stop_btn.configure(text="STOP", state="normal",
                                            fg_color=theme.COLOR_KILL_SWITCH)

        # Override main metric cards with replay data
        self.metric_cards["capital"].set_value(f"${equity:,.0f}")

        # Daily P&L (not tracked per-day in replay, show total return)
        total_pnl = equity - initial
        pnl_color = theme.COLOR_SUCCESS if total_pnl >= 0 else theme.COLOR_ERROR
        sign = "+" if total_pnl >= 0 else ""
        self.metric_cards["daily_pnl"].set_value(f"{sign}${abs(total_pnl):,.2f}", pnl_color)
        self.metric_cards["daily_pnl"].label_widget.configure(text="TOTAL P&L")

        # Total P&L as percentage
        self.metric_cards["total_pnl"].set_value(f"{ret_pct:+.2f}%", pnl_color)
        self.metric_cards["total_pnl"].label_widget.configure(text="RETURN")

        # Drawdown
        dd_total = snap.get("drawdown_total", 0) * 100
        dd_color = theme.COLOR_SUCCESS
        if dd_total > 3:
            dd_color = theme.COLOR_WARNING
        if dd_total > 5:
            dd_color = theme.COLOR_ERROR
        self.metric_cards["drawdown"].set_value(f"{dd_total:.1f}%", dd_color)

        # Positions
        pos_count = snap.get("positions_count", 0)
        tickers = snap.get("positions_tickers", [])
        pos_text = f"{pos_count}"
        if tickers:
            pos_text += f" ({', '.join(tickers[:3])})"
        self.metric_cards["positions"].set_value(pos_text)

        # Trades today -> Total trades in replay
        self.metric_cards["trades_today"].set_value(str(trades))
        self.metric_cards["trades_today"].label_widget.configure(text="TRADES")

        # Win rate
        wins = snap.get("wins", 0)
        losses = snap.get("losses", 0)
        total_wl = wins + losses
        if total_wl > 0:
            wr = (wins / total_wl) * 100
            wr_color = theme.COLOR_SUCCESS if wr >= 50 else theme.COLOR_WARNING
            self.metric_cards["win_rate"].set_value(f"{wr:.0f}% ({wins}W/{losses}L)", wr_color)
        else:
            self.metric_cards["win_rate"].set_value("--%", theme.COLOR_TEXT_DIM)

        # VIX -> show day progress
        self.metric_cards["vix"].set_value(f"Day {day_cur}", theme.ACCENT_AI)
        self.metric_cards["vix"].label_widget.configure(text="SIM DAY")

        # Engine status
        if is_running:
            self.engine_status_label.configure(
                text=f"  REPLAY: Day {day_cur}/{day_tot} ({pct * 100:.0f}%)",
                text_color=theme.ACCENT_AI,
            )
            # Spinner active during replay
            self._spin_idx = (self._spin_idx + 1) % len(self._spinning_chars)
            self.spinner_label.configure(text=self._spinning_chars[self._spin_idx])
        elif finished:
            sharpe = snap.get("sharpe_ratio", 0)
            max_dd = snap.get("max_drawdown_pct", 0)
            self.engine_status_label.configure(
                text=f"  REPLAY DONE: {ret_pct:+.1f}% | Sharpe {sharpe:.2f} | MaxDD {max_dd:.1f}%",
                text_color=theme.COLOR_SUCCESS if ret_pct >= 0 else theme.COLOR_ERROR,
            )
            self.spinner_label.configure(text=" ")

        # Kill switch from replay
        if snap.get("kill_switch", False):
            self.kill_switch_label.configure(text="Kill Switch: ACTIVE (Replay)", text_color=theme.COLOR_CRITICAL)

    # ─── BUTTON HANDLERS ─────────────────────────────────────────────

    def _on_broker_mode_changed(self, new_mode: str) -> None:
        """Handle broker mode change from dropdown."""
        import yaml as _yaml
        from pathlib import Path

        config_path = Path.cwd() / "config" / "settings.yaml"

        # For alpaca_live, require explicit confirmation
        if new_mode == "alpaca_live":
            dialog = ctk.CTkToplevel(self)
            dialog.title("LIVE TRADING")
            dialog.geometry("420x200")
            dialog.configure(fg_color=theme.BG_DARK)
            dialog.transient(self)
            dialog.grab_set()

            ctk.CTkLabel(
                dialog,
                text="SWITCH TO LIVE TRADING?",
                font=("Segoe UI", 16, "bold"),
                text_color=theme.COLOR_CRITICAL,
            ).pack(pady=(20, 8))

            ctk.CTkLabel(
                dialog,
                text="This will use REAL MONEY via Alpaca.",
                font=theme.FONT_STATUS,
                text_color=theme.COLOR_WARNING,
            ).pack()

            ctk.CTkLabel(
                dialog,
                text="Make sure ALPACA_API_KEY and ALPACA_SECRET_KEY are set in .env",
                font=("Segoe UI", 9),
                text_color=theme.COLOR_TEXT_DIM,
            ).pack(pady=(4, 0))

            btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
            btn_frame.pack(pady=15)

            def cancel():
                # Revert selector to current mode
                current = self.engine.broker_provider if self.engine else "paper_local"
                self._broker_var.set(current)
                dialog.destroy()

            ctk.CTkButton(
                btn_frame,
                text="Cancel",
                fg_color=theme.COLOR_BUTTON,
                hover_color=theme.COLOR_BUTTON_HOVER,
                width=120,
                command=cancel,
            ).pack(side="left", padx=8)

            def confirm_live():
                dialog.destroy()
                self._apply_broker_mode("alpaca_live", config_path)

            ctk.CTkButton(
                btn_frame,
                text="CONFIRM",
                fg_color=theme.COLOR_KILL_SWITCH,
                hover_color="#ff2222",
                text_color="#ffffff",
                width=120,
                command=confirm_live,
            ).pack(side="left", padx=8)

            return

        # For paper modes, apply directly
        self._apply_broker_mode(new_mode, config_path)

    def _apply_broker_mode(self, mode: str, config_path) -> None:
        """Write new broker mode to settings.yaml. Restart engine only if running."""
        import yaml as _yaml

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = _yaml.safe_load(f)

            config["broker"]["provider"] = mode

            with open(config_path, "w", encoding="utf-8") as f:
                _yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

            logging.getLogger("IARA").info(f"Broker mode changed to: {mode}")

            if self.engine and self.engine.is_running:
                # Engine is running - restart with new config
                self.engine_status_label.configure(
                    text=f"  ENGINE: SWITCHING TO {mode.upper()}...",
                    text_color=theme.COLOR_WARNING,
                )
                threading.Thread(
                    target=self.engine.restart, daemon=True, name="IARA-ModeSwitch"
                ).start()
            else:
                # Engine stopped - just save, will use new mode on next start
                self.engine_status_label.configure(
                    text=f"  MODE: {mode.upper()} (click START)",
                    text_color=theme.COLOR_TEXT_DIM,
                )

        except Exception as e:
            logging.getLogger("IARA").error(f"Failed to switch broker mode: {e}")
            # Revert selector
            current = self.engine.broker_provider if self.engine else "paper_local"
            self._broker_var.set(current)

    def _on_engine_toggle(self) -> None:
        """Start or stop the engine based on current state."""
        if not self.engine:
            return

        if self.engine.is_running:
            # Stop engine
            self._engine_btn.configure(text="STOPPING...", state="disabled",
                                       fg_color=theme.COLOR_WARNING)
            self.engine_status_label.configure(
                text="  ENGINE: STOPPING...", text_color=theme.COLOR_WARNING
            )

            def do_stop():
                self.engine.stop()
                # Update button on main thread
                self.after(0, self._update_engine_btn)

            threading.Thread(target=do_stop, daemon=True, name="IARA-Stop").start()
        else:
            # Start engine
            self._engine_btn.configure(text="STARTING...", state="disabled",
                                       fg_color=theme.COLOR_WARNING)
            self.engine_status_label.configure(
                text="  ENGINE: STARTING...", text_color=theme.COLOR_WARNING
            )
            self.engine.start()
            # Button will be updated by _update_engine_btn in the metrics loop

    def _update_engine_btn(self) -> None:
        """Sync the START/STOP button with actual engine state."""
        if not self.engine:
            return
        if self.engine.is_running:
            self._engine_btn.configure(
                text="STOP ENGINE", state="normal",
                fg_color=theme.COLOR_KILL_SWITCH, hover_color="#ff2222",
                text_color="#ffffff",
            )
        else:
            self._engine_btn.configure(
                text="START ENGINE", state="normal",
                fg_color=theme.COLOR_SUCCESS, hover_color="#2ea043",
                text_color="#ffffff",
            )

    def _on_test_pipeline(self) -> None:
        """Run full pipeline test."""
        if not self.engine or not self.engine.is_running:
            self.engine_status_label.configure(
                text="  ENGINE: NOT RUNNING", text_color=theme.COLOR_ERROR
            )
            return
        if self.engine.orchestrator:
            import asyncio

            loop = self.engine._loop
            if loop and loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self.engine.orchestrator.run_full_pipeline(force=True), loop
                )
                self.engine_status_label.configure(
                    text="  ENGINE: TESTING PIPELINE...", text_color=theme.COLOR_WARNING
                )

    def _on_replay(self) -> None:
        """Open the Replay Mode configuration dialog."""
        from src.gui.replay_dialog import ReplayConfigDialog
        ReplayConfigDialog(self, engine_controller=self.engine)

    def _on_show_positions(self) -> None:
        """Show positions dialog."""
        dialog = ctk.CTkToplevel(self)
        dialog.title("Active Positions")
        dialog.geometry("800x450")
        dialog.configure(fg_color=theme.BG_DARK)
        dialog.transient(self)

        # Header
        ctk.CTkLabel(
            dialog,
            text="Active Positions",
            font=theme.FONT_HEADER,
            text_color=theme.COLOR_NEON_BLUE,
        ).pack(pady=(12, 8))

        # Table frame
        table = ctk.CTkScrollableFrame(dialog, fg_color=theme.BG_PANEL)
        table.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        # Headers
        headers = ["Ticker", "Direction", "Entry", "Current", "Qty", "P&L", "Stop", "TP1"]
        for i, h in enumerate(headers):
            ctk.CTkLabel(
                table,
                text=h,
                font=("Segoe UI Semibold", 10),
                text_color=theme.ACCENT_PIPELINE,
            ).grid(row=0, column=i, padx=8, pady=4, sticky="w")

        # Data
        positions = []
        if self.engine and self.engine.state_manager:
            positions = self.engine.state_manager.get_open_positions()

        if not positions:
            ctk.CTkLabel(
                table,
                text="No open positions",
                font=theme.FONT_STATUS,
                text_color=theme.COLOR_TEXT_DIM,
            ).grid(row=1, column=0, columnspan=len(headers), pady=20)
        else:
            for row_idx, pos in enumerate(positions, start=1):
                ticker = getattr(pos, "ticker", "?")
                direction = getattr(pos, "direction", "?")
                entry = getattr(pos, "entry_price", 0)
                current = getattr(pos, "current_price", entry)
                qty = getattr(pos, "quantity", 0)
                stop = getattr(pos, "stop_loss", 0)
                tp1 = getattr(pos, "take_profit", 0)

                if direction == "LONG":
                    pnl = (current - entry) * qty
                else:
                    pnl = (entry - current) * qty

                pnl_color = theme.COLOR_SUCCESS if pnl >= 0 else theme.COLOR_ERROR
                sign = "+" if pnl >= 0 else ""

                values = [
                    (ticker, theme.COLOR_TEXT),
                    (direction, theme.ACCENT_PIPELINE if direction == "LONG" else theme.COLOR_WARNING),
                    (f"${entry:.2f}", theme.COLOR_TEXT),
                    (f"${current:.2f}", theme.COLOR_TEXT),
                    (str(qty), theme.COLOR_TEXT),
                    (f"{sign}${abs(pnl):,.2f}", pnl_color),
                    (f"${stop:.2f}", theme.COLOR_ERROR),
                    (f"${tp1:.2f}", theme.COLOR_SUCCESS),
                ]

                for col_idx, (val, color) in enumerate(values):
                    ctk.CTkLabel(
                        table,
                        text=val,
                        font=theme.FONT_LOG,
                        text_color=color,
                    ).grid(row=row_idx, column=col_idx, padx=8, pady=2, sticky="w")

    def _on_show_capital(self) -> None:
        """Show capital detail dialog."""
        dialog = ctk.CTkToplevel(self)
        dialog.title("Capital Details")
        dialog.geometry("500x400")
        dialog.configure(fg_color=theme.BG_DARK)
        dialog.transient(self)

        ctk.CTkLabel(
            dialog,
            text="Capital & Risk Overview",
            font=theme.FONT_HEADER,
            text_color=theme.COLOR_NEON_BLUE,
        ).pack(pady=(12, 8))

        info_frame = ctk.CTkFrame(dialog, fg_color=theme.BG_PANEL, corner_radius=8)
        info_frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        sm = self.engine.state_manager if self.engine else None
        if not sm:
            ctk.CTkLabel(info_frame, text="Engine not running", text_color=theme.COLOR_TEXT_DIM).pack(pady=20)
            return

        capital = sm.capital
        starting = getattr(sm, "starting_capital", 100000)
        total_pnl = capital - starting
        total_pnl_pct = ((capital / starting) - 1) * 100 if starting > 0 else 0
        dd_daily = sm.get_current_drawdown() * 100  # ratio -> percentage
        dd_total = dd_daily  # same calculation (current DD covers both)
        positions = sm.get_open_positions() if hasattr(sm, "get_open_positions") else []
        total_exposure = sum(
            getattr(p, "entry_price", 0) * getattr(p, "quantity", 0) for p in positions
        )
        exposure_pct = (total_exposure / capital * 100) if capital > 0 else 0

        rows = [
            ("Starting Capital", f"${starting:,.2f}", theme.COLOR_TEXT),
            ("Current Capital", f"${capital:,.2f}", theme.COLOR_TEXT),
            ("Total P&L", f"${total_pnl:+,.2f} ({total_pnl_pct:+.2f}%)",
             theme.COLOR_SUCCESS if total_pnl >= 0 else theme.COLOR_ERROR),
            ("", "", theme.COLOR_TEXT),
            ("Daily Drawdown", f"{dd_daily:.2f}% / 2.0% max",
             theme.COLOR_SUCCESS if dd_daily < 1.5 else theme.COLOR_WARNING),
            ("Total Drawdown", f"{dd_total:.2f}% / 6.0% max",
             theme.COLOR_SUCCESS if dd_total < 4 else theme.COLOR_ERROR),
            ("", "", theme.COLOR_TEXT),
            ("Open Positions", str(len(positions)), theme.COLOR_TEXT),
            ("Total Exposure", f"${total_exposure:,.2f} ({exposure_pct:.1f}%)", theme.COLOR_TEXT),
            ("Kill Switch", "ACTIVE" if sm.is_kill_switch_active() else "OFF",
             theme.COLOR_CRITICAL if sm.is_kill_switch_active() else theme.COLOR_SUCCESS),
        ]

        for i, (label, value, color) in enumerate(rows):
            if not label:
                ctk.CTkFrame(info_frame, fg_color=theme.BORDER, height=1).pack(fill="x", padx=16, pady=4)
                continue
            row_frame = ctk.CTkFrame(info_frame, fg_color="transparent")
            row_frame.pack(fill="x", padx=16, pady=3)
            ctk.CTkLabel(
                row_frame, text=label, font=theme.FONT_STATUS, text_color=theme.COLOR_TEXT_DIM, anchor="w",
            ).pack(side="left")
            ctk.CTkLabel(
                row_frame, text=value, font=("Segoe UI Semibold", 11), text_color=color, anchor="e",
            ).pack(side="right")

    def _on_clear_all_logs(self) -> None:
        """Clear all log panels."""
        for panel in self.panels.values():
            panel.clear()

    def _on_kill_switch(self) -> None:
        """Activate kill switch with confirmation."""
        dialog = ctk.CTkToplevel(self)
        dialog.title("KILL SWITCH")
        dialog.geometry("400x180")
        dialog.configure(fg_color=theme.BG_DARK)
        dialog.transient(self)
        dialog.grab_set()

        ctk.CTkLabel(
            dialog,
            text="ACTIVATE KILL SWITCH?",
            font=("Segoe UI", 16, "bold"),
            text_color=theme.COLOR_CRITICAL,
        ).pack(pady=(20, 8))

        ctk.CTkLabel(
            dialog,
            text="This will CLOSE ALL POSITIONS and HALT trading.",
            font=theme.FONT_STATUS,
            text_color=theme.COLOR_WARNING,
        ).pack()

        ctk.CTkLabel(
            dialog,
            text="This action requires manual reset to resume.",
            font=("Segoe UI", 9),
            text_color=theme.COLOR_TEXT_DIM,
        ).pack()

        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack(pady=15)

        ctk.CTkButton(
            btn_frame,
            text="Cancel",
            fg_color=theme.COLOR_BUTTON,
            hover_color=theme.COLOR_BUTTON_HOVER,
            width=120,
            command=dialog.destroy,
        ).pack(side="left", padx=8)

        def do_kill():
            dialog.destroy()
            if self.engine and self.engine.state_manager:
                self.engine.state_manager.activate_kill_switch("Manual GUI kill switch")
                self.kill_switch_label.configure(
                    text="Kill Switch: ACTIVE", text_color=theme.COLOR_CRITICAL
                )

        ctk.CTkButton(
            btn_frame,
            text="ACTIVATE",
            fg_color=theme.COLOR_KILL_SWITCH,
            hover_color="#ff2222",
            text_color="#ffffff",
            width=120,
            command=do_kill,
        ).pack(side="left", padx=8)
