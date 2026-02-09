"""
IARA GUI LOG HANDLER - Routes log messages to the correct dashboard panel.

Each logger is mapped to one of 4 panels:
  - pipeline: Orchestrator, BuzzFactory, phases
  - market: MarketData, MacroData, TechnicalAnalyzer, AlpacaData
  - ai: Screener, Judge, AIGateway, Grounding
  - guardian: Watchdog, Sentinel, PoisonPill, Risk, Correlation, Execution
"""

import logging
import queue
from datetime import datetime
from typing import Any

# Logger name -> panel ID mapping
LOGGER_ROUTING = {
    # Pipeline panel
    "src.core.orchestrator": "pipeline",
    "src.collectors.buzz_factory": "pipeline",
    "src.collectors.news_scraper": "pipeline",
    "src.collectors.news_aggregator": "pipeline",
    "src.collectors.earnings_checker": "pipeline",
    "src.backtesting.replay_engine": "pipeline",
    "IARA": "pipeline",
    "__main__": "pipeline",

    # Market panel
    "src.collectors.market_data": "market",
    "src.collectors.macro_data": "market",
    "src.collectors.alpaca_data": "market",
    "src.analysis.technical": "market",

    # AI panel
    "src.decision.screener": "ai",
    "src.decision.judge": "ai",
    "src.decision.ai_gateway": "ai",
    "src.decision.grounding": "ai",

    # Guardian panel
    "src.monitoring.watchdog": "guardian",
    "src.monitoring.sentinel": "guardian",
    "src.monitoring.poison_pill": "guardian",
    "src.monitoring.telegram_bot": "guardian",
    "src.analysis.risk_math": "guardian",
    "src.analysis.correlation": "guardian",
    "src.core.state_manager": "guardian",
    "src.execution.order_manager": "guardian",
    "src.execution.position_sizer": "guardian",
    "src.execution.broker_api": "guardian",
    "src.execution.paper_broker": "guardian",
    "src.execution.alpaca_broker": "guardian",
    "src.core.database": "guardian",
}


def classify_logger(logger_name: str) -> str:
    """
    Determine which panel a logger belongs to.

    Tries exact match first, then prefix matching.
    Falls back to 'pipeline' for unknown loggers.
    """
    # Exact match
    if logger_name in LOGGER_ROUTING:
        return LOGGER_ROUTING[logger_name]

    # Prefix match (e.g., "src.decision.judge.sub" -> "ai")
    for prefix, panel_id in LOGGER_ROUTING.items():
        if logger_name.startswith(prefix):
            return panel_id

    # Category-based fallback
    if "collector" in logger_name or "data" in logger_name:
        return "market"
    if "decision" in logger_name or "ai" in logger_name:
        return "ai"
    if "monitor" in logger_name or "risk" in logger_name or "execution" in logger_name:
        return "guardian"

    return "pipeline"


class GUILogRecord:
    """Lightweight log record for GUI consumption."""
    __slots__ = ("panel_id", "level", "message", "timestamp")

    def __init__(self, panel_id: str, level: str, message: str, timestamp: str):
        self.panel_id = panel_id
        self.level = level
        self.message = message
        self.timestamp = timestamp


class GUILogHandler(logging.Handler):
    """
    Custom logging handler that routes log records to a thread-safe queue.
    The GUI polls this queue periodically to update log panels.
    """

    def __init__(self, log_queue: queue.Queue, level=logging.DEBUG):
        super().__init__(level)
        self.log_queue = log_queue

    def emit(self, record: logging.LogRecord) -> None:
        try:
            panel_id = classify_logger(record.name)
            timestamp = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")

            # Format message (strip module prefix for cleaner display)
            msg = self.format(record) if self.formatter else record.getMessage()

            # Trim long messages
            if len(msg) > 300:
                msg = msg[:297] + "..."

            gui_record = GUILogRecord(
                panel_id=panel_id,
                level=record.levelname,
                message=msg,
                timestamp=timestamp,
            )

            # Non-blocking put (drop if queue full)
            try:
                self.log_queue.put_nowait(gui_record)
            except queue.Full:
                pass  # Drop oldest-style: GUI will catch up

        except Exception:
            self.handleError(record)


def setup_gui_logging(log_queue: queue.Queue) -> GUILogHandler:
    """
    Install the GUI log handler on the root logger.
    Returns the handler for later removal if needed.
    """
    handler = GUILogHandler(log_queue)
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.setLevel(logging.DEBUG)

    root_logger = logging.getLogger()
    root_logger.addHandler(handler)

    return handler
