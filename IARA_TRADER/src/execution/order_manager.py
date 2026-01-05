"""
ORDER MANAGER - Gerenciador de Ordens
Monta ordens OCO, Stop-Limit e Backups
"""

import logging
from typing import Dict, Optional, Any, List
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import uuid

logger = logging.getLogger(__name__)


class OrderType(Enum):
    """Tipos de ordem."""
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"
    OCO = "oco"  # One Cancels Other


class OrderSide(Enum):
    """Lado da ordem."""
    BUY = "buy"
    SELL = "sell"


class OrderStatus(Enum):
    """Status da ordem."""
    PENDING = "pending"
    SUBMITTED = "submitted"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


@dataclass
class Order:
    """Representa uma ordem."""
    id: str
    ticker: str
    side: OrderSide
    order_type: OrderType
    quantity: int
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: int = 0
    avg_fill_price: float = 0.0
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    broker_order_id: Optional[str] = None
    parent_order_id: Optional[str] = None
    notes: str = ""


@dataclass
class OCOOrder:
    """Ordem OCO (One Cancels Other)."""
    id: str
    ticker: str
    take_profit_order: Order
    stop_loss_order: Order
    status: OrderStatus = OrderStatus.PENDING


class OrderManager:
    """
    Gerenciador de ordens do sistema IARA.
    """

    def __init__(self, config: Dict[str, Any], broker_api):
        """
        Inicializa o gerenciador.

        Args:
            config: Configurações do sistema
            broker_api: API do broker
        """
        self.config = config
        self.broker = broker_api
        self.pending_orders: Dict[str, Order] = {}
        self.oco_orders: Dict[str, OCOOrder] = {}

    def create_entry_order(self, ticker: str, side: OrderSide,
                           quantity: int, order_type: OrderType = OrderType.LIMIT,
                           limit_price: Optional[float] = None) -> Order:
        """
        Cria ordem de entrada.

        Args:
            ticker: Símbolo do ativo
            side: Lado (BUY/SELL)
            quantity: Quantidade
            order_type: Tipo de ordem
            limit_price: Preço limite

        Returns:
            Order
        """
        order = Order(
            id=str(uuid.uuid4()),
            ticker=ticker,
            side=side,
            order_type=order_type,
            quantity=quantity,
            limit_price=limit_price
        )

        self.pending_orders[order.id] = order
        logger.info(f"Ordem de entrada criada: {order.id} - {ticker} {side.value} {quantity}")

        return order

    def create_oco_exit(self, ticker: str, quantity: int,
                        take_profit_price: float, stop_loss_price: float,
                        is_long: bool = True) -> OCOOrder:
        """
        Cria ordem OCO de saída (Take Profit + Stop Loss).

        Args:
            ticker: Símbolo do ativo
            quantity: Quantidade
            take_profit_price: Preço do take profit
            stop_loss_price: Preço do stop loss
            is_long: True se posição long

        Returns:
            OCOOrder
        """
        oco_id = str(uuid.uuid4())

        # Define lados das ordens de saída
        exit_side = OrderSide.SELL if is_long else OrderSide.BUY

        # Ordem Take Profit (Limit)
        tp_order = Order(
            id=str(uuid.uuid4()),
            ticker=ticker,
            side=exit_side,
            order_type=OrderType.LIMIT,
            quantity=quantity,
            limit_price=take_profit_price,
            parent_order_id=oco_id,
            notes="Take Profit"
        )

        # Ordem Stop Loss (Stop)
        sl_order = Order(
            id=str(uuid.uuid4()),
            ticker=ticker,
            side=exit_side,
            order_type=OrderType.STOP,
            quantity=quantity,
            stop_price=stop_loss_price,
            parent_order_id=oco_id,
            notes="Stop Loss"
        )

        oco = OCOOrder(
            id=oco_id,
            ticker=ticker,
            take_profit_order=tp_order,
            stop_loss_order=sl_order
        )

        self.oco_orders[oco_id] = oco
        logger.info(f"OCO criada: {oco_id} - TP: ${take_profit_price} | SL: ${stop_loss_price}")

        return oco

    async def submit_order(self, order: Order) -> bool:
        """
        Submete ordem ao broker.

        Args:
            order: Ordem a submeter

        Returns:
            True se sucesso
        """
        try:
            result = await self.broker.place_order(order)

            if result.get("success"):
                order.status = OrderStatus.SUBMITTED
                order.broker_order_id = result.get("broker_order_id")
                order.updated_at = datetime.now()
                logger.info(f"Ordem submetida: {order.id}")
                return True
            else:
                order.status = OrderStatus.REJECTED
                order.notes = result.get("error", "Erro desconhecido")
                logger.error(f"Ordem rejeitada: {order.id} - {order.notes}")
                return False

        except Exception as e:
            logger.error(f"Erro ao submeter ordem {order.id}: {e}")
            order.status = OrderStatus.REJECTED
            return False

    async def submit_oco(self, oco: OCOOrder) -> bool:
        """
        Submete ordem OCO ao broker.

        Args:
            oco: Ordem OCO

        Returns:
            True se sucesso
        """
        try:
            # Tenta submeter via API OCO nativa do broker
            if hasattr(self.broker, "place_oco_order"):
                result = await self.broker.place_oco_order(
                    oco.ticker,
                    oco.take_profit_order.quantity,
                    oco.take_profit_order.limit_price,
                    oco.stop_loss_order.stop_price
                )

                if result.get("success"):
                    oco.status = OrderStatus.SUBMITTED
                    return True

            # Fallback: submete ordens separadas
            logger.warning("Broker não suporta OCO nativo, usando fallback")
            tp_success = await self.submit_order(oco.take_profit_order)
            sl_success = await self.submit_order(oco.stop_loss_order)

            if tp_success and sl_success:
                oco.status = OrderStatus.SUBMITTED
                return True

            return False

        except Exception as e:
            logger.error(f"Erro ao submeter OCO {oco.id}: {e}")
            return False

    async def cancel_order(self, order_id: str) -> bool:
        """
        Cancela uma ordem.

        Args:
            order_id: ID da ordem

        Returns:
            True se cancelada
        """
        order = self.pending_orders.get(order_id)
        if not order:
            logger.warning(f"Ordem não encontrada: {order_id}")
            return False

        try:
            result = await self.broker.cancel_order(order.broker_order_id)

            if result.get("success"):
                order.status = OrderStatus.CANCELLED
                order.updated_at = datetime.now()
                logger.info(f"Ordem cancelada: {order_id}")
                return True

            return False

        except Exception as e:
            logger.error(f"Erro ao cancelar ordem {order_id}: {e}")
            return False

    def get_pending_orders(self) -> List[Order]:
        """Retorna ordens pendentes."""
        return [o for o in self.pending_orders.values()
                if o.status in [OrderStatus.PENDING, OrderStatus.SUBMITTED, OrderStatus.PARTIAL]]

    def update_order_status(self, order_id: str, status: OrderStatus,
                            filled_qty: int = 0, avg_price: float = 0.0) -> None:
        """Atualiza status de uma ordem."""
        if order_id in self.pending_orders:
            order = self.pending_orders[order_id]
            order.status = status
            order.filled_quantity = filled_qty
            order.avg_fill_price = avg_price
            order.updated_at = datetime.now()

            # Se OCO e uma ordem foi preenchida, cancela a outra
            if order.parent_order_id and status == OrderStatus.FILLED:
                self._handle_oco_fill(order.parent_order_id, order_id)

    def _handle_oco_fill(self, oco_id: str, filled_order_id: str) -> None:
        """Trata preenchimento de OCO."""
        oco = self.oco_orders.get(oco_id)
        if not oco:
            return

        # Determina qual ordem foi preenchida e cancela a outra
        if oco.take_profit_order.id == filled_order_id:
            # TP preenchido, cancela SL
            logger.info(f"Take Profit preenchido, cancelando Stop Loss")
            # TODO: Implementar cancelamento assíncrono
        else:
            # SL preenchido, cancela TP
            logger.info(f"Stop Loss ativado, cancelando Take Profit")
            # TODO: Implementar cancelamento assíncrono

        oco.status = OrderStatus.FILLED
