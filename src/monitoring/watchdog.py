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
        self.flash_crash_threshold = self.alert_config.get("flash_crash_threshold", 0.05)

        self._running = False
        self._alert_handlers: List[Callable] = []
        self._last_prices: Dict[str, float] = {}
        self._check_interval = 60  # segundos

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
        last_price = self._last_prices.get(ticker, position.entry_price)

        # 1. Verifica Flash Crash
        if last_price > 0:
            change = (current_price - last_price) / last_price

            if abs(change) >= self.flash_crash_threshold:
                alerts.append(PriceAlert(
                    ticker=ticker,
                    alert_type="flash_crash",
                    level=AlertLevel.EMERGENCY,
                    message=f"FLASH {'CRASH' if change < 0 else 'SPIKE'}: {change*100:.1f}%",
                    current_price=current_price,
                    reference_price=last_price,
                    change_pct=change * 100,
                    timestamp=datetime.now()
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
