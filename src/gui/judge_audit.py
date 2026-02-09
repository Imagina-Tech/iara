"""
JUDGE AUDIT - Store and Panel for auditing Judge (Phase 3) decisions.

JudgeAuditStore: Persists audit entries to data/judge_audit.jsonl (append-only).
JudgeAuditPanel: CTkFrame showing audit log with expandable prompt viewer.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import customtkinter as ctk

from src.gui import theme

logger = logging.getLogger(__name__)

# ─── PROJECT ROOT ─────────────────────────────────────────────────
import sys

if getattr(sys, "frozen", False):
    _PROJECT_ROOT = Path.cwd()
else:
    _PROJECT_ROOT = Path(__file__).parent.parent.parent

_AUDIT_FILE = _PROJECT_ROOT / "data" / "judge_audit.jsonl"

# Limits
_MAX_MEMORY = 500       # Max entries kept in memory
_MAX_RENDERED = 200     # Max entries rendered in UI


class JudgeAuditStore:
    """Thread-safe audit entry store with JSONL persistence."""

    def __init__(self):
        self._entries: List[Dict] = []
        self._load()

    def _load(self) -> None:
        """Load existing entries from JSONL file (most recent last)."""
        if not _AUDIT_FILE.exists():
            return
        try:
            lines = _AUDIT_FILE.read_text(encoding="utf-8").strip().splitlines()
            for line in lines[-_MAX_MEMORY:]:
                try:
                    self._entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            logger.info(f"[AUDIT] Loaded {len(self._entries)} entries from {_AUDIT_FILE.name}")
        except Exception as e:
            logger.warning(f"[AUDIT] Failed to load audit file: {e}")

    def add(self, entry: Dict) -> None:
        """Add an entry to memory and append to file."""
        self._entries.append(entry)
        # Trim memory
        if len(self._entries) > _MAX_MEMORY:
            self._entries = self._entries[-_MAX_MEMORY:]
        # Persist
        try:
            _AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(_AUDIT_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"[AUDIT] Failed to write audit entry: {e}")

    def clear(self) -> None:
        """Clear all entries (memory + file)."""
        self._entries.clear()
        try:
            if _AUDIT_FILE.exists():
                _AUDIT_FILE.write_text("", encoding="utf-8")
            logger.info("[AUDIT] Audit log cleared")
        except Exception as e:
            logger.warning(f"[AUDIT] Failed to clear audit file: {e}")

    @property
    def entries(self) -> List[Dict]:
        return self._entries

    def __len__(self) -> int:
        return len(self._entries)


# ─── Badge color mapping ─────────────────────────────────────────

_RESULT_COLORS = {
    "APROVAR": theme.COLOR_AUDIT_APPROVE,
    "REJEITAR": theme.COLOR_AUDIT_REJECT,
    "AGUARDAR": theme.COLOR_AUDIT_WAIT,
}


def _badge_color(result: str) -> str:
    return _RESULT_COLORS.get(result, theme.COLOR_TEXT_DIM)


# ─── Audit Entry Widget ──────────────────────────────────────────


class _AuditEntryWidget(ctk.CTkFrame):
    """A single audit entry with header and expandable prompt area."""

    def __init__(self, master, entry: Dict, **kwargs):
        super().__init__(
            master,
            fg_color=theme.BG_CARD,
            corner_radius=6,
            border_color=theme.BORDER,
            border_width=1,
            **kwargs,
        )
        self._expanded = False
        self._entry = entry

        # ── Header row ──
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=8, pady=(6, 2))

        # Timestamp
        ts_raw = entry.get("timestamp", "")
        try:
            dt = datetime.fromisoformat(ts_raw)
            ts_display = dt.strftime("%H:%M:%S")
        except Exception:
            ts_display = ts_raw[:8] if ts_raw else "--:--:--"

        ctk.CTkLabel(
            header,
            text=ts_display,
            font=("Consolas", 10),
            text_color=theme.COLOR_TEXT_MUTED,
        ).pack(side="left", padx=(0, 8))

        # Ticker
        ticker = entry.get("ticker", "???")
        ctk.CTkLabel(
            header,
            text=ticker,
            font=theme.FONT_AUDIT_HEADER,
            text_color=theme.COLOR_NEON_BLUE,
        ).pack(side="left", padx=(0, 8))

        # Origin
        origin = entry.get("origin", "")
        ctk.CTkLabel(
            header,
            text=origin,
            font=("Segoe UI", 9),
            text_color=theme.COLOR_TEXT_DIM,
        ).pack(side="left", padx=(0, 8))

        # Result badge
        result = entry.get("result", "?")
        badge_fg = _badge_color(result)
        ctk.CTkLabel(
            header,
            text=f" {result} ",
            font=("Segoe UI Semibold", 10),
            text_color="#ffffff",
            fg_color=badge_fg,
            corner_radius=4,
        ).pack(side="left", padx=(0, 6))

        # Score
        score = entry.get("score", 0)
        ctk.CTkLabel(
            header,
            text=f"{score}/10",
            font=("Consolas", 10),
            text_color=theme.COLOR_TEXT,
        ).pack(side="left", padx=(0, 6))

        # Direction
        direction = entry.get("direction", "")
        if direction:
            dir_color = theme.ACCENT_PIPELINE if direction == "LONG" else (
                theme.COLOR_WARNING if direction == "SHORT" else theme.COLOR_TEXT_DIM
            )
            ctk.CTkLabel(
                header,
                text=direction,
                font=("Segoe UI Semibold", 9),
                text_color=dir_color,
            ).pack(side="left", padx=(0, 6))

        # Expand/collapse button
        self._expand_btn = ctk.CTkButton(
            header,
            text="[+] PROMPT",
            font=("Consolas", 9),
            fg_color="transparent",
            hover_color=theme.BG_PANEL,
            text_color=theme.ACCENT_AI,
            width=80,
            height=20,
            corner_radius=3,
            command=self._toggle_expand,
        )
        self._expand_btn.pack(side="right")

        # ── Justificativa (always visible, compact) ──
        justificativa = entry.get("justificativa", "")
        if justificativa:
            ctk.CTkLabel(
                self,
                text=justificativa[:200],
                font=("Segoe UI", 9),
                text_color=theme.COLOR_TEXT_DIM,
                wraplength=700,
                anchor="w",
                justify="left",
            ).pack(fill="x", padx=12, pady=(0, 6))

        # ── Expandable prompt area (hidden by default) ──
        self._prompt_frame = ctk.CTkFrame(self, fg_color=theme.BG_INPUT, corner_radius=4)
        # Don't pack yet

        prompt_text = entry.get("prompt", "(no prompt)")
        self._prompt_textbox = ctk.CTkTextbox(
            self._prompt_frame,
            font=theme.FONT_AUDIT_PROMPT,
            fg_color=theme.BG_INPUT,
            text_color=theme.COLOR_TEXT,
            corner_radius=4,
            wrap="word",
            height=200,
            activate_scrollbars=True,
        )
        self._prompt_textbox.pack(fill="both", expand=True, padx=4, pady=4)
        self._prompt_textbox.insert("1.0", prompt_text)
        self._prompt_textbox.configure(state="disabled")

    def _toggle_expand(self) -> None:
        if self._expanded:
            self._prompt_frame.pack_forget()
            self._expand_btn.configure(text="[+] PROMPT")
        else:
            self._prompt_frame.pack(fill="x", padx=8, pady=(0, 6))
            self._expand_btn.configure(text="[-] PROMPT")
        self._expanded = not self._expanded


# ─── Audit Panel ─────────────────────────────────────────────────


class JudgeAuditPanel(ctk.CTkFrame):
    """Full audit view panel with toolbar and scrollable entry list."""

    def __init__(self, master, store: JudgeAuditStore, **kwargs):
        super().__init__(master, fg_color=theme.BG_DARK, **kwargs)
        self._store = store
        self._entry_widgets: List[_AuditEntryWidget] = []

        # ── Toolbar ──
        toolbar = ctk.CTkFrame(self, fg_color=theme.BG_PANEL, corner_radius=0, height=44)
        toolbar.pack(fill="x", padx=0, pady=(0, 4))
        toolbar.pack_propagate(False)

        ctk.CTkLabel(
            toolbar,
            text="JUDGE AUDIT LOG",
            font=("Segoe UI Semibold", 14),
            text_color=theme.ACCENT_AI,
        ).pack(side="left", padx=16)

        self._count_label = ctk.CTkLabel(
            toolbar,
            text=f"{len(store)} entries",
            font=("Consolas", 10),
            text_color=theme.COLOR_TEXT_DIM,
        )
        self._count_label.pack(side="left", padx=(8, 0))

        clear_btn = ctk.CTkButton(
            toolbar,
            text="CLEAR ALL",
            font=("Segoe UI Semibold", 10),
            fg_color=theme.COLOR_KILL_SWITCH,
            hover_color="#ff2222",
            text_color="#ffffff",
            width=100,
            height=28,
            corner_radius=4,
            command=self._on_clear,
        )
        clear_btn.pack(side="right", padx=16, pady=8)

        # ── Scrollable entry list ──
        self._scroll = ctk.CTkScrollableFrame(
            self,
            fg_color=theme.BG_DARK,
            corner_radius=0,
        )
        self._scroll.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        # Render existing entries (most recent on top)
        self._render_existing()

    def _render_existing(self) -> None:
        """Render entries already in the store (most recent first, up to _MAX_RENDERED)."""
        entries = self._store.entries[-_MAX_RENDERED:]
        for entry in reversed(entries):
            widget = _AuditEntryWidget(self._scroll, entry)
            widget.pack(fill="x", padx=4, pady=3)
            self._entry_widgets.append(widget)
        self._update_count()

    def add_entry(self, entry: Dict) -> None:
        """Add a new entry at the top of the list (real-time)."""
        # Insert at top
        widget = _AuditEntryWidget(self._scroll, entry)
        widget.pack(fill="x", padx=4, pady=3, before=self._entry_widgets[0] if self._entry_widgets else None)
        self._entry_widgets.insert(0, widget)

        # Trim rendered widgets
        while len(self._entry_widgets) > _MAX_RENDERED:
            old = self._entry_widgets.pop()
            old.destroy()

        self._update_count()

    def refresh(self) -> None:
        """Re-render all entries from the store (call when switching to audit view)."""
        for w in self._entry_widgets:
            w.destroy()
        self._entry_widgets.clear()
        self._render_existing()

    def _on_clear(self) -> None:
        """Clear all entries from store and UI."""
        self._store.clear()
        for w in self._entry_widgets:
            w.destroy()
        self._entry_widgets.clear()
        self._update_count()

    def _update_count(self) -> None:
        self._count_label.configure(text=f"{len(self._store)} entries")
