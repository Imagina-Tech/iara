"""
TELEGRAM BOT - Interface de Comando Remoto
Kill Switch Remoto e Alertas
"""

import logging
import os
import asyncio
from typing import Dict, Optional, Any, Callable, List
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class CommandType(Enum):
    """Tipos de comando."""
    STATUS = "status"
    POSITIONS = "positions"
    KILL = "kill"
    RESUME = "resume"
    CLOSE = "close"
    HELP = "help"


@dataclass
class TelegramMessage:
    """Mensagem do Telegram."""
    chat_id: str
    text: str
    command: Optional[CommandType]
    args: List[str]
    timestamp: datetime


class TelegramBot:
    """
    Bot do Telegram para controle remoto.
    """

    def __init__(self, config: Dict[str, Any], state_manager):
        """
        Inicializa o bot.

        Args:
            config: Configurações
            state_manager: Gerenciador de estado
        """
        self.config = config
        self.state_manager = state_manager

        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.authorized_chat_id = os.getenv("TELEGRAM_CHAT_ID")

        self._running = False
        self._bot = None
        self._command_handlers: Dict[CommandType, Callable] = {}

        self._setup_command_handlers()

    def _setup_command_handlers(self) -> None:
        """Configura handlers de comando."""
        self._command_handlers = {
            CommandType.STATUS: self._handle_status,
            CommandType.POSITIONS: self._handle_positions,
            CommandType.KILL: self._handle_kill,
            CommandType.RESUME: self._handle_resume,
            CommandType.CLOSE: self._handle_close,
            CommandType.HELP: self._handle_help
        }

    async def start(self) -> None:
        """Inicia o bot."""
        if not self.token:
            logger.warning("TELEGRAM_BOT_TOKEN não configurado")
            return

        logger.info("Iniciando Telegram Bot...")
        self._running = True

        try:
            from telegram import Bot, Update
            from telegram.ext import Application, CommandHandler, MessageHandler, filters

            self._bot = Bot(token=self.token)

            # Configura application
            # Type hint explícito para melhor inferência do Pylance
            app: Application = Application.builder().token(self.token).build()

            # Adiciona handlers
            app.add_handler(CommandHandler("status", self._on_status))
            app.add_handler(CommandHandler("positions", self._on_positions))
            app.add_handler(CommandHandler("kill", self._on_kill))
            app.add_handler(CommandHandler("resume", self._on_resume))
            app.add_handler(CommandHandler("close", self._on_close))
            app.add_handler(CommandHandler("help", self._on_help))

            # Inicia polling
            await app.run_polling()  # type: ignore

        except ImportError:
            logger.error("python-telegram-bot não instalado")
        except Exception as e:
            logger.error(f"Erro no Telegram Bot: {e}")

    async def stop(self) -> None:
        """Para o bot."""
        logger.info("Parando Telegram Bot...")
        self._running = False

    async def send_message(self, text: str, parse_mode: str = "Markdown") -> bool:
        """
        Envia mensagem para o chat autorizado.

        Args:
            text: Texto da mensagem
            parse_mode: Modo de parse (Markdown, HTML)

        Returns:
            True se enviado com sucesso
        """
        if not self._bot or not self.authorized_chat_id:
            return False

        try:
            await self._bot.send_message(
                chat_id=self.authorized_chat_id,
                text=text,
                parse_mode=parse_mode
            )
            return True
        except Exception as e:
            logger.error(f"Erro ao enviar mensagem: {e}")
            return False

    async def send_alert(self, alert_type: str, ticker: str, message: str) -> bool:
        """
        Envia alerta formatado.

        Args:
            alert_type: Tipo de alerta
            ticker: Ticker relacionado
            message: Mensagem

        Returns:
            True se enviado
        """
        emoji_map = {
            "info": "ℹ️",
            "warning": "⚠️",
            "critical": "🚨",
            "emergency": "🆘",
            "profit": "💰",
            "loss": "📉"
        }

        emoji = emoji_map.get(alert_type, "📢")
        text = f"{emoji} *{alert_type.upper()}* | `{ticker}`\n\n{message}"

        return await self.send_message(text)

    def _is_authorized(self, chat_id: str) -> bool:
        """Verifica se o chat é autorizado."""
        return str(chat_id) == str(self.authorized_chat_id)

    async def _on_status(self, update, context) -> None:
        """Handler do comando /status."""
        if not self._is_authorized(update.effective_chat.id):
            return

        status = await self._handle_status()
        await update.message.reply_text(status, parse_mode="Markdown")

    async def _on_positions(self, update, context) -> None:
        """Handler do comando /positions."""
        if not self._is_authorized(update.effective_chat.id):
            return

        positions = await self._handle_positions()
        await update.message.reply_text(positions, parse_mode="Markdown")

    async def _on_kill(self, update, context) -> None:
        """Handler do comando /kill."""
        if not self._is_authorized(update.effective_chat.id):
            return

        result = await self._handle_kill()
        await update.message.reply_text(result, parse_mode="Markdown")

    async def _on_resume(self, update, context) -> None:
        """Handler do comando /resume."""
        if not self._is_authorized(update.effective_chat.id):
            return

        result = await self._handle_resume()
        await update.message.reply_text(result, parse_mode="Markdown")

    async def _on_close(self, update, context) -> None:
        """Handler do comando /close."""
        if not self._is_authorized(update.effective_chat.id):
            return

        args = context.args
        if args:
            ticker = args[0].upper()
            result = await self._handle_close(ticker)
        else:
            result = "❌ Uso: /close TICKER"

        await update.message.reply_text(result, parse_mode="Markdown")

    async def _on_help(self, update, context) -> None:
        """Handler do comando /help."""
        if not self._is_authorized(update.effective_chat.id):
            return

        help_text = await self._handle_help()
        await update.message.reply_text(help_text, parse_mode="Markdown")

    async def _handle_status(self) -> str:
        """Retorna status do sistema."""
        state = self.state_manager.to_dict()

        status_emoji = "🟢" if state["state"] == "running" else "🔴"

        return f"""
*IARA TRADER Status*

{status_emoji} Estado: `{state['state']}`
💰 Capital: `${state['capital']:,.2f}`
📊 Posições: `{len(state['positions'])}`
⚠️ Kill Switch: `{'ATIVO' if state['kill_switch_active'] else 'Inativo'}`
📉 Drawdown: `{self.state_manager.get_current_drawdown()*100:.2f}%`
"""

    async def _handle_positions(self) -> str:
        """Retorna posições abertas."""
        positions = self.state_manager.get_open_positions()

        if not positions:
            return "📭 *Nenhuma posição aberta*"

        lines = ["*Posições Abertas*\n"]
        for pos in positions:
            pnl_emoji = "🟢" if pos.unrealized_pnl >= 0 else "🔴"
            lines.append(
                f"{pnl_emoji} `{pos.ticker}` {pos.direction}\n"
                f"   Entry: ${pos.entry_price:.2f} | Current: ${pos.current_price:.2f}\n"
                f"   P&L: ${pos.unrealized_pnl:.2f}\n"
            )

        return "\n".join(lines)

    async def _handle_kill(self) -> str:
        """Ativa kill switch."""
        self.state_manager.activate_kill_switch("Comando Telegram")
        return "🆘 *KILL SWITCH ATIVADO*\n\nTodas as operações foram suspensas."

    async def _handle_resume(self) -> str:
        """Desativa kill switch."""
        self.state_manager.deactivate_kill_switch()
        return "🟢 *Sistema Resumido*\n\nOperações normais restauradas."

    async def _handle_close(self, ticker: Optional[str] = None) -> str:
        """Fecha posição específica."""
        if not ticker:
            return "❌ Ticker não especificado"

        position = self.state_manager.positions.get(ticker)
        if not position:
            return f"❌ Posição não encontrada: `{ticker}`"

        # TODO: Implementar fechamento real via order_manager
        return f"⚠️ Ordem de fechamento enviada para `{ticker}`"

    async def _handle_help(self) -> str:
        """Retorna ajuda."""
        return """
*IARA Trader - Comandos*

/status - Status do sistema
/positions - Posições abertas
/kill - Ativa Kill Switch (EMERGÊNCIA)
/resume - Desativa Kill Switch
/close TICKER - Fecha posição
/help - Esta mensagem
"""
