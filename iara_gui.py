"""
IARA GUI - Entry Point
Launches the dashboard + async trading engine in parallel.

Usage:
    python iara_gui.py
    (or run the .exe built with build_exe.py)
"""

import asyncio
import logging
import queue
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv

from src.gui.dashboard import IaraDashboard
from src.gui.log_handler import setup_gui_logging
from src.decision.judge import set_judge_audit_callback

# ─── Project Root ─────────────────────────────────────────────────────
# Find project root by searching for config/settings.yaml
# Works from: python script, .exe in dist/IARA/, .exe copied elsewhere
import os

def _find_project_root() -> Path:
    """Search for project root containing config/settings.yaml."""
    candidates = []

    if getattr(sys, "frozen", False):
        # .exe mode: try exe dir, parent, grandparent (dist/IARA/ -> dist/ -> project root)
        exe_dir = Path(sys.executable).resolve().parent
        candidates = [exe_dir, exe_dir.parent, exe_dir.parent.parent]
    else:
        # Script mode: script dir is project root
        candidates = [Path(__file__).resolve().parent]

    # Also try current working directory
    candidates.append(Path.cwd())

    for candidate in candidates:
        if (candidate / "config" / "settings.yaml").exists():
            return candidate

    # Fallback: script/exe dir (will show clear error later)
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent

PROJECT_ROOT = _find_project_root()
os.chdir(PROJECT_ROOT)

# ─── Logging Setup ───────────────────────────────────────────────────
# Create data dirs if needed
(PROJECT_ROOT / "data" / "logs").mkdir(parents=True, exist_ok=True)
(PROJECT_ROOT / "data" / "outputs").mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)-25s | %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(PROJECT_ROOT / "data" / "logs" / f'{datetime.now().strftime("%Y-%m-%d")}_iara.log')),
    ],
)

logger = logging.getLogger("IARA")


# ─── Engine Controller ───────────────────────────────────────────────


class EngineController:
    """
    Bridge between the GUI (main thread) and the async trading engine (daemon thread).

    Manages:
    - Engine lifecycle (start/stop/restart)
    - Exposes state_manager, orchestrator, etc. for GUI reads
    - Thread-safe communication
    """

    def __init__(self):
        self.is_running = False
        self.state_manager = None
        self.orchestrator = None
        self.ai_gateway = None
        self.macro_data = None
        self.broker_provider = "paper_local"

        self._thread = None
        self._loop = None
        self._tasks = []
        self._stop_event = threading.Event()

    def start(self) -> None:
        """Start the engine in a background thread."""
        if self._thread and self._thread.is_alive():
            logger.warning("Engine already running")
            return

        self._stop_event.clear()
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_engine, daemon=True, name="IARA-Engine")
        self._thread.start()

    def stop(self) -> None:
        """Stop the engine gracefully."""
        logger.info("Stopping engine...")
        self._stop_event.set()

        if self._loop and self._loop.is_running():
            # Cancel all tasks
            for task in self._tasks:
                try:
                    self._loop.call_soon_threadsafe(task.cancel)
                except RuntimeError:
                    pass  # Loop already closed

            # Schedule cleanup
            future = asyncio.run_coroutine_threadsafe(self._cleanup(), self._loop)
            try:
                future.result(timeout=15)
            except Exception as e:
                logger.warning(f"Cleanup timeout: {e}")

            # Stop the event loop (guard against already-closed)
            try:
                if self._loop.is_running():
                    self._loop.call_soon_threadsafe(self._loop.stop)
            except RuntimeError:
                pass  # Loop already closed

        if self._thread:
            self._thread.join(timeout=10)

        self.is_running = False
        logger.info("Engine stopped")

    def restart(self) -> None:
        """Restart the engine."""
        logger.info("Restarting engine...")
        self.stop()
        time.sleep(2)
        self.start()

    async def _cleanup(self) -> None:
        """Async cleanup of engine components."""
        try:
            if self.orchestrator:
                await self.orchestrator.stop()
            if hasattr(self, "_watchdog") and self._watchdog:
                await self._watchdog.stop()
            if hasattr(self, "_sentinel") and self._sentinel:
                await self._sentinel.stop()
            if hasattr(self, "_broker") and self._broker:
                await self._broker.disconnect()
            if self.state_manager:
                # Persist guardian + unified state before shutdown (Problem 6)
                if hasattr(self, "_watchdog") and self._watchdog:
                    if hasattr(self, "_sentinel") and self._sentinel:
                        self.state_manager.save_guardian_state(
                            watchdog_state=self._watchdog.get_state_snapshot(),
                            sentinel_state=self._sentinel.get_state_snapshot()
                        )
                self.state_manager.save_state()
                logger.info("Unified state saved to disk")
        except Exception as e:
            logger.error(f"Cleanup error: {e}")

    def _run_engine(self) -> None:
        """Thread entry: sets up event loop and runs engine."""
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._engine_main())
        except Exception as e:
            logger.error(f"Engine fatal error: {e}")
        finally:
            # Cancel any remaining pending tasks to avoid "Task was destroyed but it is pending" warnings
            try:
                pending = asyncio.all_tasks(self._loop)
                for task in pending:
                    task.cancel()
                if pending:
                    self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            except Exception:
                pass
            try:
                self._loop.close()
            except Exception:
                pass
            self.is_running = False

    async def _engine_main(self) -> None:
        """Async main: initialize all components and start tasks."""
        logger.info("=" * 60)
        logger.info("IARA ENGINE STARTING")
        logger.info("=" * 60)

        # Load env
        load_dotenv(PROJECT_ROOT / ".env")

        # Load config
        config_path = PROJECT_ROOT / "config" / "settings.yaml"
        if not config_path.exists():
            logger.error(f"config/settings.yaml not found! (looked in: {config_path})")
            return

        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        # Initialize components via DI container
        from src.core.app_container import AppContainer

        logger.info("Initializing components...")
        container = AppContainer(config)

        # Connect broker (async operation with fallback logic)
        connected = await container.connect_broker()
        if not connected:
            logger.error("Cannot start engine - broker connection failed")
            return

        # Expose key components to EngineController for GUI reads
        self.state_manager = container.state_manager
        self.orchestrator = container.orchestrator
        self.ai_gateway = container.ai_gateway
        self.macro_data = container.macro_data
        self.broker_provider = container.broker_provider
        self._broker = container.broker
        self._watchdog = container.watchdog
        self._sentinel = container.sentinel

        # Local references for task creation below
        watchdog = container.watchdog
        sentinel = container.sentinel
        poison_pill = container.poison_pill
        telegram = container.telegram
        order_manager = container.order_manager
        orchestrator = container.orchestrator

        # Restore guardian state from unified file (Problem 6)
        guardian_state = self.state_manager.get_guardian_state()
        if guardian_state:
            watchdog.restore_state(guardian_state.get("watchdog"))
            sentinel.restore_state(guardian_state.get("sentinel"))

        logger.info("=" * 60)
        logger.info("IARA ENGINE INITIALIZED")
        logger.info(f"Capital: ${self.state_manager.capital:,.2f}")
        logger.info(f"Broker: {self.broker_provider}")
        logger.info(f"AI Providers: {self.ai_gateway.get_available_providers()}")
        logger.info("=" * 60)

        self.is_running = True

        # Alert handlers
        async def send_telegram_alert(alert):
            await telegram.send_alert(
                alert_type=alert.level.value if hasattr(alert, "level") else "info",
                ticker=alert.ticker,
                message=alert.message if hasattr(alert, "message") else str(alert),
            )

        watchdog.add_alert_handler(send_telegram_alert)
        sentinel.add_alert_handler(send_telegram_alert)

        # Background loops
        async def poison_pill_loop():
            while not self._stop_event.is_set():
                try:
                    if poison_pill.should_run_scan():
                        events = await poison_pill.run_nightly_scan()
                        if events:
                            critical = poison_pill.get_critical_events()
                            if critical:
                                logger.critical(f"POISON PILL: {len(critical)} critical events!")
                    await asyncio.sleep(1800)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Poison pill error: {e}")
                    await asyncio.sleep(300)

        state_manager = self.state_manager  # local ref for state_saver_loop

        async def state_saver_loop():
            while not self._stop_event.is_set():
                try:
                    await asyncio.sleep(300)
                    # Save guardian state before main state save (Problem 6)
                    state_manager.save_guardian_state(
                        watchdog_state=watchdog.get_state_snapshot(),
                        sentinel_state=sentinel.get_state_snapshot()
                    )
                    state_manager.save_state()
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"State save error: {e}")

        # Start tasks
        logger.info("Starting services...")
        self._tasks = [
            asyncio.create_task(orchestrator.start()),
            asyncio.create_task(watchdog.start()),
            asyncio.create_task(sentinel.start()),
            asyncio.create_task(poison_pill_loop()),
            asyncio.create_task(state_saver_loop()),
        ]

        try:
            await asyncio.gather(*self._tasks)
        except asyncio.CancelledError:
            logger.info("Engine tasks cancelled")
        except Exception as e:
            logger.error(f"Engine error: {e}")
        finally:
            await self._cleanup()
            self.is_running = False
            logger.info("IARA ENGINE STOPPED")


# ─── Entry Point ─────────────────────────────────────────────────────


def main():
    """Launch IARA with GUI dashboard."""

    # Print banner to console
    print("""
    ==================================================================

         ___    _     ____       _        _____   ____
        |_ _|  / \\   |  _ \\     / \\      |_   _| |  _ \\
         | |  / _ \\  | |_) |   / _ \\       | |   | |_) |
         | | / ___ \\ |  _ <   / ___ \\      | |   |  _ <
        |___/_/   \\_\\|_| \\_\\ /_/   \\_\\     |_|   |_| \\_\\

           Intelligent Automated Risk-Aware Trader
                     v29.0 - GUI Mode

    ==================================================================
    """)

    # Create log queue (bridge between engine thread and GUI thread)
    log_queue = queue.Queue(maxsize=5000)

    # Create audit queue (bridge between Judge thread and GUI thread)
    audit_queue = queue.Queue(maxsize=500)

    # Install GUI log handler on root logger
    setup_gui_logging(log_queue)

    # Set up Judge audit callback (puts entries into the queue for the GUI)
    def _audit_callback(entry):
        try:
            audit_queue.put_nowait(entry)
        except queue.Full:
            pass  # Drop if queue is full

    set_judge_audit_callback(_audit_callback)

    # Create engine controller
    engine = EngineController()

    # Create dashboard (engine starts manually via START button)
    app = IaraDashboard(log_queue=log_queue, engine_controller=engine, audit_queue=audit_queue)

    # Run GUI mainloop (blocks until window closed)
    try:
        app.mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        # Stop engine on exit
        logger.info("GUI closed, stopping engine...")
        engine.stop()
        print("\nIARA shut down.")


if __name__ == "__main__":
    main()
