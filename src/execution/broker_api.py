"""
BROKER API - Conector de Corretora
Suporta ccxt e MetaTrader
"""

import logging
from typing import Dict, Optional, Any, List
from dataclasses import dataclass
from abc import ABC, abstractmethod
from datetime import datetime
import os

logger = logging.getLogger(__name__)


@dataclass
class BrokerBalance:
    """Saldo da conta."""
    total: float
    available: float
    margin_used: float
    currency: str


@dataclass
class BrokerPosition:
    """Posição na corretora."""
    ticker: str
    quantity: int
    avg_entry_price: float
    current_price: float
    unrealized_pnl: float
    side: str  # "long" ou "short"


class BaseBrokerAPI(ABC):
    """Interface base para APIs de corretoras."""

    @abstractmethod
    async def connect(self) -> bool:
        """Conecta à corretora."""
        pass

    @abstractmethod
    async def get_balance(self) -> BrokerBalance:
        """Obtém saldo da conta."""
        pass

    @abstractmethod
    async def get_positions(self) -> List[BrokerPosition]:
        """Obtém posições abertas."""
        pass

    @abstractmethod
    async def place_order(self, order: Any) -> Dict:
        """Envia ordem."""
        pass

    @abstractmethod
    async def cancel_order(self, order_id: str) -> Dict:
        """Cancela ordem."""
        pass

    @abstractmethod
    async def get_order_status(self, order_id: str) -> Dict:
        """Obtém status de ordem."""
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Desconecta da corretora."""
        pass


class CCXTBroker(BaseBrokerAPI):
    """
    Implementação usando CCXT para exchanges de crypto.
    Pode ser adaptado para outros brokers.
    """

    def __init__(self, config: Dict[str, Any], exchange: str = "binance"):
        """
        Inicializa broker CCXT.

        Args:
            config: Configurações
            exchange: Nome da exchange
        """
        self.config = config
        self.exchange_name = exchange
        self.exchange = None
        self._connected = False

    async def connect(self) -> bool:
        """Conecta à exchange."""
        try:
            import ccxt.async_support as ccxt

            exchange_class = getattr(ccxt, self.exchange_name)

            self.exchange = exchange_class({
                "apiKey": os.getenv("BROKER_API_KEY"),
                "secret": os.getenv("BROKER_API_SECRET"),
                "enableRateLimit": True,
                "options": {
                    "defaultType": "spot"
                }
            })

            # Testa conexão
            await self.exchange.load_markets()
            self._connected = True
            logger.info(f"Conectado à {self.exchange_name}")
            return True

        except Exception as e:
            logger.error(f"Erro ao conectar à {self.exchange_name}: {e}")
            return False

    async def disconnect(self) -> None:
        """Desconecta da exchange."""
        if self.exchange:
            await self.exchange.close()
            self._connected = False

    async def get_balance(self) -> BrokerBalance:
        """Obtém saldo."""
        if not self._connected or self.exchange is None:
            raise RuntimeError("Não conectado")

        balance = await self.exchange.fetch_balance()
        total = balance.get("total", {}).get("USDT", 0)
        free = balance.get("free", {}).get("USDT", 0)
        used = balance.get("used", {}).get("USDT", 0)

        return BrokerBalance(
            total=total,
            available=free,
            margin_used=used,
            currency="USDT"
        )

    async def get_positions(self) -> List[BrokerPosition]:
        """Obtém posições abertas."""
        if not self._connected or self.exchange is None:
            raise RuntimeError("Não conectado")

        positions = []

        try:
            balance = await self.exchange.fetch_balance()

            for symbol, amount in balance.get("total", {}).items():
                if amount > 0 and symbol != "USDT":
                    ticker = f"{symbol}/USDT"
                    try:
                        current = await self.exchange.fetch_ticker(ticker)
                        positions.append(BrokerPosition(
                            ticker=ticker,
                            quantity=amount,
                            avg_entry_price=0,  # CCXT não fornece
                            current_price=current["last"],
                            unrealized_pnl=0,
                            side="long"
                        ))
                    except Exception:
                        pass

        except Exception as e:
            logger.error(f"Erro ao obter posições: {e}")

        return positions

    async def place_order(self, order: Any) -> Dict:
        """Envia ordem."""
        if not self._connected or self.exchange is None:
            return {"success": False, "error": "Não conectado"}

        try:
            # Converte order para parâmetros CCXT
            symbol = order.ticker
            order_type = order.order_type.value
            side = order.side.value
            amount = order.quantity
            price = order.limit_price

            if order_type == "market":
                result = await self.exchange.create_market_order(symbol, side, amount)
            elif order_type == "limit":
                result = await self.exchange.create_limit_order(symbol, side, amount, price)
            else:
                return {"success": False, "error": f"Tipo de ordem não suportado: {order_type}"}

            return {
                "success": True,
                "broker_order_id": result["id"],
                "status": result["status"]
            }

        except Exception as e:
            logger.error(f"Erro ao enviar ordem: {e}")
            return {"success": False, "error": str(e)}

    async def cancel_order(self, order_id: str) -> Dict:
        """Cancela ordem."""
        if not self._connected or self.exchange is None:
            return {"success": False, "error": "Não conectado"}

        try:
            await self.exchange.cancel_order(order_id)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def get_order_status(self, order_id: str) -> Dict:
        """Obtém status de ordem."""
        if not self._connected or self.exchange is None:
            return {"success": False, "error": "Não conectado"}

        try:
            order = await self.exchange.fetch_order(order_id)
            return {
                "success": True,
                "status": order["status"],
                "filled": order["filled"],
                "remaining": order["remaining"],
                "avg_price": order.get("average")
            }
        except Exception as e:
            return {"success": False, "error": str(e)}


class PaperBroker(BaseBrokerAPI):
    """
    Broker simulado para paper trading.
    """

    def __init__(self, config: Dict[str, Any], initial_balance: float = 100000):
        """
        Inicializa paper broker.

        Args:
            config: Configurações
            initial_balance: Saldo inicial
        """
        self.config = config
        self.balance = initial_balance
        self.positions: Dict[str, BrokerPosition] = {}
        self.orders: Dict[str, Dict] = {}
        self._connected = False

    async def connect(self) -> bool:
        """Simula conexão."""
        self._connected = True
        logger.info("Paper Broker conectado")
        return True

    async def get_balance(self) -> BrokerBalance:
        """Retorna saldo simulado."""
        return BrokerBalance(
            total=self.balance,
            available=self.balance,
            margin_used=0,
            currency="USD"
        )

    async def get_positions(self) -> List[BrokerPosition]:
        """Retorna posições simuladas."""
        return list(self.positions.values())

    async def place_order(self, order: Any) -> Dict:
        """Simula envio de ordem."""
        order_id = f"PAPER_{datetime.now().timestamp()}"

        # Simula preenchimento imediato para ordens market
        if order.order_type.value == "market":
            # TODO: Obter preço atual real
            fill_price = order.limit_price or 100.0

            if order.side.value == "buy":
                self.balance -= fill_price * order.quantity
                if order.ticker in self.positions:
                    pos = self.positions[order.ticker]
                    pos.quantity += order.quantity
                else:
                    self.positions[order.ticker] = BrokerPosition(
                        ticker=order.ticker,
                        quantity=order.quantity,
                        avg_entry_price=fill_price,
                        current_price=fill_price,
                        unrealized_pnl=0,
                        side="long"
                    )
            else:
                if order.ticker in self.positions:
                    pos = self.positions[order.ticker]
                    pos.quantity -= order.quantity
                    self.balance += fill_price * order.quantity
                    if pos.quantity <= 0:
                        del self.positions[order.ticker]

        self.orders[order_id] = {
            "id": order_id,
            "status": "filled",
            "filled": order.quantity
        }

        return {"success": True, "broker_order_id": order_id}

    async def cancel_order(self, order_id: str) -> Dict:
        """Cancela ordem simulada."""
        if order_id in self.orders:
            self.orders[order_id]["status"] = "cancelled"
            return {"success": True}
        return {"success": False, "error": "Ordem não encontrada"}

    async def get_order_status(self, order_id: str) -> Dict:
        """Obtém status de ordem simulada."""
        order = self.orders.get(order_id)
        if order:
            return {"success": True, **order}
        return {"success": False, "error": "Ordem não encontrada"}

    async def disconnect(self) -> None:
        """Simula desconexão."""
        self._connected = False
        logger.info("Paper Broker desconectado")


class BrokerAPI:
    """
    Factory para criar o broker apropriado.
    """

    @staticmethod
    def create(config: Dict[str, Any], broker_type: str = "paper") -> BaseBrokerAPI:
        """
        Cria instância do broker.

        Args:
            config: Configurações
            broker_type: Tipo de broker (paper, ccxt, etc)

        Returns:
            Instância do broker
        """
        if broker_type == "paper":
            return PaperBroker(config)
        elif broker_type == "ccxt":
            exchange = config.get("exchange", "binance")
            return CCXTBroker(config, exchange)
        else:
            raise ValueError(f"Tipo de broker não suportado: {broker_type}")
