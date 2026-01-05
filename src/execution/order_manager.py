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

    def calculate_stop_loss(self, ticker: str, entry_price: float, atr: float,
                            direction: str, has_earnings: bool = False,
                            swing_low: Optional[float] = None) -> float:
        """
        Calcula stop loss inteligente (WS5).

        Lógica:
        - Se earnings < 5 dias: Entry * 0.995 (tight 0.5%)
        - Senão: MAX(Entry - 2.5*ATR, SwingLow)

        Args:
            ticker: Símbolo do ativo
            entry_price: Preço de entrada
            atr: ATR atual
            direction: "LONG" ou "SHORT"
            has_earnings: Se earnings está próximo
            swing_low: Swing low recente (opcional)

        Returns:
            Preço do stop loss
        """
        technical_config = self.config.get("technical", {})
        atr_multiplier = technical_config.get("atr_stop_multiplier", 2.5)

        if has_earnings:
            # Earnings próximo - stop tight de 0.5%
            if direction == "LONG":
                stop = entry_price * 0.995
            else:  # SHORT
                stop = entry_price * 1.005

            logger.info(f"{ticker}: Earnings proximity - tight stop at {stop:.2f} (0.5% from entry)")
            return round(stop, 2)

        # Stop normal baseado em ATR
        if direction == "LONG":
            atr_stop = entry_price - (atr_multiplier * atr)

            # Se tem swing low, usar o MAIOR entre ATR stop e swing low
            if swing_low and swing_low > atr_stop:
                stop = swing_low
                logger.info(f"{ticker}: Using swing low ${swing_low:.2f} (> ATR stop ${atr_stop:.2f})")
            else:
                stop = atr_stop
                logger.info(f"{ticker}: Using ATR stop ${stop:.2f} ({atr_multiplier}x ATR)")

        else:  # SHORT
            atr_stop = entry_price + (atr_multiplier * atr)

            # Para SHORT, swing high seria o teto
            if swing_low and swing_low < atr_stop:  # swing_low aqui seria swing_high semanticamente
                stop = swing_low
                logger.info(f"{ticker}: Using swing high ${swing_low:.2f} (< ATR stop ${atr_stop:.2f})")
            else:
                stop = atr_stop
                logger.info(f"{ticker}: Using ATR stop ${stop:.2f} ({atr_multiplier}x ATR)")

        # Backup safety: nunca mais de 10% de perda
        max_loss_pct = 0.10
        if direction == "LONG":
            min_stop = entry_price * (1 - max_loss_pct)
            if stop < min_stop:
                logger.warning(f"{ticker}: Stop ${stop:.2f} exceeds 10% loss, capping at ${min_stop:.2f}")
                stop = min_stop
        else:
            max_stop = entry_price * (1 + max_loss_pct)
            if stop > max_stop:
                logger.warning(f"{ticker}: Stop ${stop:.2f} exceeds 10% loss, capping at ${max_stop:.2f}")
                stop = max_stop

        return round(stop, 2)

    async def place_entry_order(self, ticker: str, direction: str, entry_price: float,
                                quantity: int) -> Optional[Order]:
        """
        Coloca ordem de entrada STOP-LIMIT (WS5).

        Tipo: STOP_LIMIT com limit +0.5% do trigger (evita slippage).

        Args:
            ticker: Símbolo do ativo
            direction: "LONG" ou "SHORT"
            entry_price: Preço trigger (stop price)
            quantity: Quantidade de ações

        Returns:
            Order ou None se falhar
        """
        try:
            # Calcula limit price (+0.5% do trigger)
            if direction == "LONG":
                side = OrderSide.BUY
                limit_price = entry_price * 1.005  # +0.5%
            else:
                side = OrderSide.SELL
                limit_price = entry_price * 0.995  # -0.5%

            # Cria ordem STOP-LIMIT
            order = Order(
                id=str(uuid.uuid4()),
                ticker=ticker,
                side=side,
                order_type=OrderType.STOP_LIMIT,
                quantity=quantity,
                stop_price=entry_price,
                limit_price=limit_price,
                notes=f"Entry {direction} - Stop: ${entry_price:.2f}, Limit: ${limit_price:.2f}"
            )

            self.pending_orders[order.id] = order

            # Submete ao broker
            success = await self.submit_order(order)

            if success:
                logger.info(f"Entry order placed: {ticker} {direction} {quantity} @ stop ${entry_price:.2f} / limit ${limit_price:.2f}")
                return order
            else:
                logger.error(f"Failed to place entry order for {ticker}")
                return None

        except Exception as e:
            logger.error(f"Error placing entry order for {ticker}: {e}")
            return None

    async def place_stop_orders(self, ticker: str, direction: str, physical_stop: float,
                                backup_stop: float, quantity: int) -> Dict[str, Optional[Order]]:
        """
        Coloca sistema de stops DUPLO (WS5).

        - Physical stop: Enviado ao broker
        - Backup stop: Tracked localmente (-10% como fallback)

        Args:
            ticker: Símbolo do ativo
            direction: "LONG" ou "SHORT"
            physical_stop: Stop principal (enviado ao broker)
            backup_stop: Stop backup (monitorado localmente)
            quantity: Quantidade

        Returns:
            Dict com "physical" e "backup" orders
        """
        try:
            side = OrderSide.SELL if direction == "LONG" else OrderSide.BUY

            # 1. Physical stop (broker)
            physical_order = Order(
                id=str(uuid.uuid4()),
                ticker=ticker,
                side=side,
                order_type=OrderType.STOP,
                quantity=quantity,
                stop_price=physical_stop,
                notes=f"Physical Stop {direction}"
            )

            self.pending_orders[physical_order.id] = physical_order
            physical_success = await self.submit_order(physical_order)

            # 2. Backup stop (local tracking)
            backup_order = Order(
                id=str(uuid.uuid4()),
                ticker=ticker,
                side=side,
                order_type=OrderType.STOP,
                quantity=quantity,
                stop_price=backup_stop,
                status=OrderStatus.PENDING,  # Não submete, apenas monitora
                notes=f"Backup Stop {direction} (local tracking)"
            )

            self.pending_orders[backup_order.id] = backup_order

            logger.info(f"Dual stop system: Physical ${physical_stop:.2f} (broker) + Backup ${backup_stop:.2f} (local)")

            return {
                "physical": physical_order if physical_success else None,
                "backup": backup_order
            }

        except Exception as e:
            logger.error(f"Error placing stop orders for {ticker}: {e}")
            return {"physical": None, "backup": None}

    async def place_take_profit_orders(self, ticker: str, direction: str, tp1: float,
                                       tp2: float, quantity: int) -> Dict[str, Optional[Order]]:
        """
        Coloca ordens de Take Profit MULTI-TARGET (WS5).

        - TP1: 50% da posição no primeiro alvo
        - TP2: 50% restante no segundo alvo

        Args:
            ticker: Símbolo do ativo
            direction: "LONG" ou "SHORT"
            tp1: Primeiro take profit
            tp2: Segundo take profit
            quantity: Quantidade total

        Returns:
            Dict com "tp1" e "tp2" orders
        """
        try:
            side = OrderSide.SELL if direction == "LONG" else OrderSide.BUY

            # Divide quantidade 50/50
            qty_tp1 = quantity // 2
            qty_tp2 = quantity - qty_tp1  # Restante (evita arredondamento)

            # TP1 (50%)
            tp1_order = Order(
                id=str(uuid.uuid4()),
                ticker=ticker,
                side=side,
                order_type=OrderType.LIMIT,
                quantity=qty_tp1,
                limit_price=tp1,
                notes=f"Take Profit 1 (50%) @ ${tp1:.2f}"
            )

            self.pending_orders[tp1_order.id] = tp1_order
            tp1_success = await self.submit_order(tp1_order)

            # TP2 (50%)
            tp2_order = Order(
                id=str(uuid.uuid4()),
                ticker=ticker,
                side=side,
                order_type=OrderType.LIMIT,
                quantity=qty_tp2,
                limit_price=tp2,
                notes=f"Take Profit 2 (50%) @ ${tp2:.2f}"
            )

            self.pending_orders[tp2_order.id] = tp2_order
            tp2_success = await self.submit_order(tp2_order)

            logger.info(f"Multi-target TP: {qty_tp1} @ ${tp1:.2f} + {qty_tp2} @ ${tp2:.2f}")

            return {
                "tp1": tp1_order if tp1_success else None,
                "tp2": tp2_order if tp2_success else None
            }

        except Exception as e:
            logger.error(f"Error placing TP orders for {ticker}: {e}")
            return {"tp1": None, "tp2": None}
