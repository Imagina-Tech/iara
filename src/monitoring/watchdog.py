"""
WATCHDOG - Monitor de Preços em Tempo Real
Loop de 1 minuto: Preço, Gap, Flash Crash
"""

import logging
import asyncio
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

logger = logging.getLogger(__name__)


class AlertLevel(Enum):
    """Níveis de alerta."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


@dataclass
class PriceAlert:
    """Alerta de preço."""
    ticker: str
    alert_type: str
    level: AlertLevel
    message: str
    current_price: float
    reference_price: float
    change_pct: float
    timestamp: datetime


class Watchdog:
    """
    Monitor de preços em tempo real.
    Detecta gaps, flash crashes e violações de stop.
    """

    def __init__(self, config: Dict[str, Any], market_data, state_manager):
        """
        Inicializa o watchdog.

        Args:
            config: Configurações
            market_data: Coletor de dados de mercado
            state_manager: Gerenciador de estado
        """
        self.config = config
        self.market_data = market_data
        self.state_manager = state_manager

        self.alert_config = config.get("alerts", {})
        self.phase5_config = config.get("phase5", {})
        self.flash_crash_threshold = self.alert_config.get("flash_crash_threshold", 0.03)  # WS6: 3%
        self.flash_crash_window = self.phase5_config.get("flash_crash_window", 300)  # WS6: 5 min
        self.panic_dd_threshold = 0.04  # WS6: 4% intraday DD

        self._running = False
        self._alert_handlers: List[Callable] = []
        self._last_prices: Dict[str, float] = {}
        self._price_history: Dict[str, List[Dict]] = {}  # WS6: Track price history for 5min window
        self._check_interval = self.phase5_config.get("watchdog_interval", 60)  # segundos

    def add_alert_handler(self, handler: Callable[[PriceAlert], None]) -> None:
        """Adiciona handler de alertas."""
        self._alert_handlers.append(handler)

    async def start(self) -> None:
        """Inicia o watchdog."""
        logger.info("Iniciando Watchdog...")
        self._running = True

        while self._running:
            try:
                await self._check_positions()
                await asyncio.sleep(self._check_interval)
            except Exception as e:
                logger.error(f"Erro no watchdog: {e}")
                await asyncio.sleep(5)

    async def stop(self) -> None:
        """Para o watchdog."""
        logger.info("Parando Watchdog...")
        self._running = False

    async def _check_positions(self) -> None:
        """Verifica todas as posições abertas."""
        # WS6: Check intraday DD panic ANTES de verificar posições
        await self._check_intraday_dd_panic()

        positions = self.state_manager.get_open_positions()

        for position in positions:
            alerts = await self._check_position(position)

            for alert in alerts:
                await self._handle_alert(alert)

    async def _check_position(self, position) -> List[PriceAlert]:
        """
        Verifica uma posição específica.

        Args:
            position: Posição a verificar

        Returns:
            Lista de alertas
        """
        alerts = []
        ticker = position.ticker

        # Obtém preço atual
        data = self.market_data.get_stock_data(ticker)
        if not data:
            logger.warning(f"Não foi possível obter dados de {ticker}")
            return alerts

        current_price = data.price

        # WS6: Atualiza price history (5min window)
        now = datetime.now()
        if ticker not in self._price_history:
            self._price_history[ticker] = []

        self._price_history[ticker].append({
            "price": current_price,
            "timestamp": now
        })

        # Remove entradas antigas (> 5 min)
        cutoff_time = now - timedelta(seconds=self.flash_crash_window)
        self._price_history[ticker] = [
            p for p in self._price_history[ticker]
            if p["timestamp"] >= cutoff_time
        ]

        # 1. WS6: Verifica Flash Crash (5min window)
        if len(self._price_history[ticker]) >= 2:
            oldest_price = self._price_history[ticker][0]["price"]
            change_5min = (current_price - oldest_price) / oldest_price if oldest_price > 0 else 0

            if abs(change_5min) >= self.flash_crash_threshold:
                # WS6: Validar se é market-wide crash (VIX/SPY check)
                is_market_wide = await self._check_market_wide_crash()

                alert_level = AlertLevel.EMERGENCY if not is_market_wide else AlertLevel.CRITICAL
                alert_msg = f"FLASH {'CRASH' if change_5min < 0 else 'SPIKE'}: {change_5min*100:.1f}% (5min)"

                if is_market_wide:
                    alert_msg += " [MARKET-WIDE]"
                else:
                    alert_msg += " [ISOLATED]"

                alerts.append(PriceAlert(
                    ticker=ticker,
                    alert_type="flash_crash",
                    level=alert_level,
                    message=alert_msg,
                    current_price=current_price,
                    reference_price=oldest_price,
                    change_pct=change_5min * 100,
                    timestamp=now
                ))

        # 2. Verifica violação de Stop Loss
        if position.direction == "LONG":
            if current_price <= position.stop_loss:
                alerts.append(PriceAlert(
                    ticker=ticker,
                    alert_type="stop_violated",
                    level=AlertLevel.CRITICAL,
                    message=f"STOP LOSS VIOLADO: ${current_price} <= ${position.stop_loss}",
                    current_price=current_price,
                    reference_price=position.stop_loss,
                    change_pct=((current_price - position.entry_price) / position.entry_price) * 100,
                    timestamp=datetime.now()
                ))
        else:  # SHORT
            if current_price >= position.stop_loss:
                alerts.append(PriceAlert(
                    ticker=ticker,
                    alert_type="stop_violated",
                    level=AlertLevel.CRITICAL,
                    message=f"STOP LOSS VIOLADO: ${current_price} >= ${position.stop_loss}",
                    current_price=current_price,
                    reference_price=position.stop_loss,
                    change_pct=((position.entry_price - current_price) / position.entry_price) * 100,
                    timestamp=datetime.now()
                ))

        # 3. Verifica Take Profit atingido
        if position.direction == "LONG":
            if current_price >= position.take_profit:
                alerts.append(PriceAlert(
                    ticker=ticker,
                    alert_type="take_profit_hit",
                    level=AlertLevel.INFO,
                    message=f"TAKE PROFIT ATINGIDO: ${current_price}",
                    current_price=current_price,
                    reference_price=position.take_profit,
                    change_pct=((current_price - position.entry_price) / position.entry_price) * 100,
                    timestamp=datetime.now()
                ))

        # Atualiza último preço
        self._last_prices[ticker] = current_price

        return alerts

    async def _check_market_wide_crash(self) -> bool:
        """
        Verifica se crash é market-wide via VIX/SPY (WS6).

        Returns:
            True se market-wide, False se isolado
        """
        try:
            # Fetch VIX e SPY
            import yfinance as yf

            vix = yf.Ticker("^VIX")
            vix_hist = vix.history(period="1d", interval="5m")

            spy = yf.Ticker("SPY")
            spy_hist = spy.history(period="1d", interval="5m")

            if vix_hist.empty or spy_hist.empty:
                logger.warning("Could not fetch VIX/SPY data for market-wide validation")
                return False

            # Check VIX spike (>+10% em 5min)
            if len(vix_hist) >= 2:
                vix_current = vix_hist["Close"].iloc[-1]
                vix_5min_ago = vix_hist["Close"].iloc[-2]
                vix_change = (vix_current - vix_5min_ago) / vix_5min_ago if vix_5min_ago > 0 else 0

                if vix_change > 0.10:  # +10%
                    logger.warning(f"Market-wide crash detected: VIX +{vix_change*100:.1f}%")
                    return True

            # Check SPY drop (<-2% em 5min)
            if len(spy_hist) >= 2:
                spy_current = spy_hist["Close"].iloc[-1]
                spy_5min_ago = spy_hist["Close"].iloc[-2]
                spy_change = (spy_current - spy_5min_ago) / spy_5min_ago if spy_5min_ago > 0 else 0

                if spy_change < -0.02:  # -2%
                    logger.warning(f"Market-wide crash detected: SPY {spy_change*100:.1f}%")
                    return True

            return False

        except Exception as e:
            logger.error(f"Error checking market-wide crash: {e}")
            return False

    async def _check_intraday_dd_panic(self) -> None:
        """
        WS6: Verifica intraday DD >4% e ativa PANIC PROTOCOL.
        """
        current_dd = self.state_manager.get_current_drawdown()

        if current_dd >= self.panic_dd_threshold:
            logger.critical(f"🚨 PANIC PROTOCOL: Intraday DD {current_dd:.2%} >= {self.panic_dd_threshold:.2%}")

            # 1. Fechar todas as posições imediatamente
            positions = self.state_manager.get_open_positions()
            for position in positions:
                logger.critical(f"PANIC: Closing position {position.ticker} at market")
                # TODO: Implementar close_position_at_market()

            # 2. Ativar Kill Switch
            self.state_manager.activate_kill_switch(f"Intraday DD {current_dd:.2%} >= 4%")

            # 3. Alert crítico
            # TODO: Send Telegram alert

    async def _handle_alert(self, alert: PriceAlert) -> None:
        """Processa um alerta."""
        # Log
        if alert.level == AlertLevel.EMERGENCY:
            logger.critical(f"[{alert.ticker}] {alert.message}")
        elif alert.level == AlertLevel.CRITICAL:
            logger.error(f"[{alert.ticker}] {alert.message}")
        else:
            logger.warning(f"[{alert.ticker}] {alert.message}")

        # Notifica handlers
        for handler in self._alert_handlers:
            try:
                await handler(alert) if asyncio.iscoroutinefunction(handler) else handler(alert)
            except Exception as e:
                logger.error(f"Erro no handler de alerta: {e}")

        # Ação automática para emergências
        if alert.level == AlertLevel.EMERGENCY:
            await self._handle_emergency(alert)

    async def _handle_emergency(self, alert: PriceAlert) -> None:
        """Trata situação de emergência."""
        logger.critical(f"EMERGÊNCIA: {alert.message}")

        # Considera ativar kill switch para flash crashes severos
        if alert.alert_type == "flash_crash" and abs(alert.change_pct) > 10:
            self.state_manager.activate_kill_switch(f"Flash crash de {alert.change_pct:.1f}%")

    def get_status(self) -> Dict[str, Any]:
        """Retorna status do watchdog."""
        return {
            "running": self._running,
            "monitored_positions": len(self._last_prices),
            "check_interval": self._check_interval,
            "flash_crash_threshold": f"{self.flash_crash_threshold*100}%"
        }
