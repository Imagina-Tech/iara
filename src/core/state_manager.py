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
        # WS3: Track capital history for weekly DD calculation
        self.capital_history: List[Dict[str, Any]] = []

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

    def update_capital_history(self) -> None:
        """
        Atualiza histórico de capital para tracking de DD semanal.
        Deve ser chamado ao final de cada dia de trading.
        """
        self.capital_history.append({
            "date": datetime.now().strftime("%Y-%m-%d"),
            "capital": self.capital,
            "realized_pnl": self.daily_stats.realized_pnl if self.daily_stats else 0,
            "unrealized_pnl": self.daily_stats.unrealized_pnl if self.daily_stats else 0
        })

        # Manter apenas últimos 30 dias
        if len(self.capital_history) > 30:
            self.capital_history = self.capital_history[-30:]

        logger.debug(f"Capital history updated: {len(self.capital_history)} days tracked")

    def get_weekly_drawdown(self) -> float:
        """
        Calcula drawdown semanal (últimos 5 dias úteis).

        Returns:
            Drawdown semanal como percentual (0.0-1.0)
        """
        if len(self.capital_history) < 2:
            return 0.0

        # Pegar capital de 5 dias atrás (ou início se menor)
        lookback = min(5, len(self.capital_history))
        week_start_capital = self.capital_history[-lookback]["capital"]
        current_capital = self.capital

        # Calcular DD semanal
        weekly_dd = (week_start_capital - current_capital) / week_start_capital if week_start_capital > 0 else 0.0

        return max(0, weekly_dd)  # DD é sempre positivo

    def is_defensive_mode(self) -> bool:
        """
        Verifica se sistema deve entrar em modo defensivo.

        Critérios WS3:
        - Weekly DD >= 5% OU
        - Daily DD >= 3%

        Returns:
            True se deve ativar defensive mode
        """
        phase2_config = self.config.get("phase2", {})
        weekly_threshold = phase2_config.get("weekly_dd_defensive", 0.05)
        daily_threshold = phase2_config.get("daily_dd_defensive", 0.03)

        weekly_dd = self.get_weekly_drawdown()
        daily_dd = self.get_current_drawdown()

        if weekly_dd >= weekly_threshold:
            logger.warning(f"DEFENSIVE MODE: Weekly DD {weekly_dd:.2%} >= {weekly_threshold:.2%}")
            return True

        if daily_dd >= daily_threshold:
            logger.warning(f"DEFENSIVE MODE: Daily DD {daily_dd:.2%} >= {daily_threshold:.2%}")
            return True

        return False

    def get_defensive_multiplier(self) -> float:
        """
        Retorna multiplicador de posição para modo defensivo.

        Returns:
            0.5 se defensive mode ativo, 1.0 caso contrário
        """
        if self.is_defensive_mode():
            logger.info("Defensive mode active - reducing position size to 50%")
            return 0.5
        return 1.0

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

    @property
    def kill_switch_active(self) -> bool:
        """Propriedade para acesso direto ao estado do Kill Switch."""
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
        """
        Calcula exposição por setor do portfolio atual.

        Returns:
            Dict[setor, valor_total_exposto]
        """
        import yfinance as yf

        sector_exposure: Dict[str, float] = {}

        for position in self.positions.values():
            try:
                # Fetch sector via yfinance
                ticker_obj = yf.Ticker(position.ticker)
                info = ticker_obj.info

                sector = info.get("sector", "Unknown")
                position_value = position.current_price * position.quantity if position.current_price > 0 else position.entry_price * position.quantity

                # Agregar por setor
                if sector in sector_exposure:
                    sector_exposure[sector] += position_value
                else:
                    sector_exposure[sector] = position_value

                logger.debug(f"{position.ticker}: ${position_value:,.2f} in sector '{sector}'")

            except Exception as e:
                logger.error(f"Error fetching sector for {position.ticker}: {e}")
                # Usar "Unknown" como fallback
                sector_exposure["Unknown"] = sector_exposure.get("Unknown", 0) + (position.entry_price * position.quantity)

        return sector_exposure

    def check_sector_exposure(self, ticker: str, position_value: float) -> tuple[bool, Optional[str]]:
        """
        Verifica se nova posição excede limite de exposição setorial (20%).

        Args:
            ticker: Ticker do novo ativo
            position_value: Valor da posição a adicionar

        Returns:
            Tuple (is_allowed, sector_name)
            - is_allowed: True se pode entrar, False se excede limite
            - sector_name: Nome do setor (ou None se erro)
        """
        import yfinance as yf

        phase2_config = self.config.get("phase2", {})
        max_sector_exposure = phase2_config.get("sector_exposure_max", 0.20)

        try:
            # Fetch sector do novo ticker
            ticker_obj = yf.Ticker(ticker)
            info = ticker_obj.info
            new_sector = info.get("sector", "Unknown")

            # Calcular exposição atual por setor
            current_exposure = self.get_exposure_by_sector()
            current_sector_exposure = current_exposure.get(new_sector, 0)

            # Calcular nova exposição do setor
            new_sector_exposure = current_sector_exposure + position_value
            sector_exposure_pct = new_sector_exposure / self.capital if self.capital > 0 else 0

            if sector_exposure_pct > max_sector_exposure:
                logger.warning(f"SECTOR EXPOSURE LIMIT: {new_sector} would be {sector_exposure_pct:.2%} "
                               f"(max {max_sector_exposure:.2%}) with {ticker} - REJECTING")
                return False, new_sector

            logger.debug(f"Sector exposure check passed: {new_sector} = {sector_exposure_pct:.2%} "
                         f"(max {max_sector_exposure:.2%})")
            return True, new_sector

        except Exception as e:
            logger.error(f"Error checking sector exposure for {ticker}: {e}")
            # Fail-safe: permitir entrada em caso de erro
            return True, None

    def to_dict(self) -> Dict[str, Any]:
        """Serializa o estado para persistência."""
        return {
            "state": self.state.value,
            "capital": self.capital,
            "positions": [p.__dict__ for p in self.positions.values()],
            "daily_stats": self.daily_stats.__dict__ if self.daily_stats else None,
            "kill_switch_active": self._kill_switch_active
        }
