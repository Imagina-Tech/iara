"""
IARA GUI THEME - Constantes visuais do dashboard.
Estilo: Dark tech, glassmorphism, trading terminal.
"""

# === COLORS ===
BG_DARK = "#0d1117"           # Main background (GitHub dark)
BG_PANEL = "#161b22"          # Panel background
BG_PANEL_HEADER = "#1c2333"   # Panel header slightly lighter
BG_CARD = "#1a2332"           # Metric cards
BG_INPUT = "#0d1117"          # Log text area background
BORDER = "#30363d"            # Subtle borders
BORDER_GLOW = "#1f6feb44"     # Glassmorphism glow (semi-transparent)

# Accent colors (per panel)
ACCENT_PIPELINE = "#58a6ff"   # Blue - Pipeline
ACCENT_MARKET = "#3fb950"     # Green - Market Data
ACCENT_AI = "#bc8cff"         # Purple - AI Engine
ACCENT_GUARDIAN = "#f0883e"   # Orange - Guardian

# Status colors
COLOR_SUCCESS = "#3fb950"     # Green
COLOR_WARNING = "#d29922"     # Amber
COLOR_ERROR = "#f85149"       # Red
COLOR_CRITICAL = "#ff3333"    # Bright red
COLOR_INFO = "#8b949e"        # Gray
COLOR_TEXT = "#e6edf3"        # Light text
COLOR_TEXT_DIM = "#8b949e"    # Dimmed text
COLOR_TEXT_MUTED = "#484f58"  # Very dim text

# Special
COLOR_NEON_BLUE = "#00d4ff"   # Neon accent
COLOR_KILL_SWITCH = "#da3633" # Kill switch red
COLOR_BUTTON = "#21262d"      # Button background
COLOR_BUTTON_HOVER = "#30363d"  # Button hover

# Audit panel colors
COLOR_AUDIT_APPROVE = "#3fb950"   # Green
COLOR_AUDIT_REJECT = "#f85149"    # Red
COLOR_AUDIT_WAIT = "#d29922"      # Yellow/Amber

# === FONTS ===
FONT_TITLE = ("Segoe UI", 24, "bold")
FONT_SUBTITLE = ("Segoe UI", 11)
FONT_HEADER = ("Segoe UI Semibold", 13)
FONT_PANEL_TITLE = ("Segoe UI Semibold", 12)
FONT_LOG = ("Consolas", 10)
FONT_METRIC_VALUE = ("Segoe UI", 18, "bold")
FONT_METRIC_LABEL = ("Segoe UI", 9)
FONT_STATUS = ("Segoe UI", 10)
FONT_BUTTON = ("Segoe UI Semibold", 11)
FONT_CLOCK = ("Consolas", 14, "bold")
FONT_PHASE = ("Segoe UI Semibold", 10)
FONT_AUDIT_PROMPT = ("Consolas", 11)
FONT_AUDIT_HEADER = ("Segoe UI Semibold", 11)

# === SIZES ===
WINDOW_MIN_W = 1280
WINDOW_MIN_H = 800
WINDOW_DEFAULT_W = 1440
WINDOW_DEFAULT_H = 920
LOG_MAX_LINES = 800           # Max lines per log panel
PANEL_CORNER_RADIUS = 8
BUTTON_CORNER_RADIUS = 6
CARD_CORNER_RADIUS = 6

# === LOG LEVEL COLORS ===
LOG_COLORS = {
    "DEBUG": "#484f58",
    "INFO": "#e6edf3",
    "WARNING": "#d29922",
    "ERROR": "#f85149",
    "CRITICAL": "#ff3333",
}

# === PANEL CONFIG ===
PANELS = [
    {
        "id": "pipeline",
        "title": "PIPELINE",
        "icon": "[>>]",
        "accent": ACCENT_PIPELINE,
        "description": "Orchestrator & Phase Activity",
    },
    {
        "id": "market",
        "title": "MARKET DATA",
        "icon": "[$]",
        "accent": ACCENT_MARKET,
        "description": "Prices, Technical & Macro",
    },
    {
        "id": "ai",
        "title": "AI ENGINE",
        "icon": "[AI]",
        "accent": ACCENT_AI,
        "description": "Screener, Judge & Grounding",
    },
    {
        "id": "guardian",
        "title": "GUARDIAN",
        "icon": "[!]",
        "accent": ACCENT_GUARDIAN,
        "description": "Watchdog, Sentinel & Risk",
    },
]
