"""
STATE MANAGER - Memória RAM do Sistema IARA
Controla Drawdown Global, Kill Switch e Estado das Posições
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any
from enum import Enum

logger = logging.getLogger(__name__)


class SystemState(Enum):
    """Estados possíveis do sistema."""
    RUNNING = "running"
    PAUSED = "paused"
    KILLED = "killed"
    MAINTENANCE = "maintenance"


@dataclass
class Position:
    """Representa uma posição aberta."""
    ticker: str
    direction: str  # "LONG" ou "SHORT"
    entry_price: float
    quantity: int
    stop_loss: float
    take_profit: float
    entry_time: datetime
    current_price: float = 0.0
    unrealized_pnl: float = 0.0


@dataclass
class DailyStats:
    """Estatísticas diárias."""
    date: str
    starting_capital: float
    current_capital: float
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    trades_count: int = 0
    wins: int = 0
    losses: int = 0


class StateManager:
    """
    Gerenciador de estado global do sistema IARA.
    Mantém controle sobre capital, posições, e limites de risco.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Inicializa o gerenciador de estado.

        Args:
            config: Configurações do sistema
        """
        self.config = config
        self.state = SystemState.RUNNING
        self.positions: Dict[str, Position] = {}
        self.daily_stats: Optional[DailyStats] = None
        self.capital = 0.0
        self._kill_switch_active = False

    def initialize(self, starting_capital: float) -> None:
        """Inicializa o estado com capital inicial."""
        self.capital = starting_capital
        self.daily_stats = DailyStats(
            date=datetime.now().strftime("%Y-%m-%d"),
            starting_capital=starting_capital,
            current_capital=starting_capital
        )
        logger.info(f"StateManager inicializado com capital: ${starting_capital:,.2f}")

    def get_current_drawdown(self) -> float:
        """Calcula o drawdown atual do dia."""
        if not self.daily_stats:
            return 0.0

        pnl = self.daily_stats.realized_pnl + self.daily_stats.unrealized_pnl
        return abs(min(0, pnl)) / self.daily_stats.starting_capital

    def check_drawdown_limits(self) -> bool:
        """
        Verifica se os limites de drawdown foram atingidos.

        Returns:
            True se dentro dos limites, False se excedeu
        """
        risk_config = self.config.get("risk", {})
        max_daily = risk_config.get("max_drawdown_daily", 0.02)
        max_total = risk_config.get("max_drawdown_total", 0.06)

        current_dd = self.get_current_drawdown()

        if current_dd >= max_daily:
            logger.warning(f"DRAWDOWN DIÁRIO ATINGIDO: {current_dd:.2%}")
            return False

        if current_dd >= max_total:
            logger.critical(f"DRAWDOWN TOTAL ATINGIDO: {current_dd:.2%}")
            self.activate_kill_switch("Drawdown máximo excedido")
            return False

        return True

    def activate_kill_switch(self, reason: str) -> None:
        """Ativa o Kill Switch de emergência."""
        logger.critical(f"KILL SWITCH ATIVADO: {reason}")
        self._kill_switch_active = True
        self.state = SystemState.KILLED
        # TODO: Fechar todas as posições
        # TODO: Enviar alerta via Telegram

    def deactivate_kill_switch(self) -> None:
        """Desativa o Kill Switch (requer confirmação manual)."""
        logger.info("Kill Switch desativado manualmente")
        self._kill_switch_active = False
        self.state = SystemState.RUNNING

    def is_kill_switch_active(self) -> bool:
        """Retorna o estado do Kill Switch."""
        return self._kill_switch_active

    def add_position(self, position: Position) -> bool:
        """Adiciona uma nova posição."""
        max_positions = self.config.get("risk", {}).get("max_positions", 5)

        if len(self.positions) >= max_positions:
            logger.warning(f"Máximo de posições atingido: {max_positions}")
            return False

        self.positions[position.ticker] = position
        logger.info(f"Posição adicionada: {position.ticker} {position.direction}")
        return True

    def remove_position(self, ticker: str) -> Optional[Position]:
        """Remove uma posição."""
        return self.positions.pop(ticker, None)

    def get_open_positions(self) -> List[Position]:
        """Retorna lista de posições abertas."""
        return list(self.positions.values())

    def get_exposure_by_sector(self) -> Dict[str, float]:
        """Calcula exposição por setor."""
        # TODO: Implementar cálculo de exposição setorial
        return {}

    def to_dict(self) -> Dict[str, Any]:
        """Serializa o estado para persistência."""
        return {
            "state": self.state.value,
            "capital": self.capital,
            "positions": [p.__dict__ for p in self.positions.values()],
            "daily_stats": self.daily_stats.__dict__ if self.daily_stats else None,
            "kill_switch_active": self._kill_switch_active
        }
