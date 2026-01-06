"""
IARA TRADER - Sistema Automatizado de Trading com IA
Ponto de Entrada Principal
"""

import asyncio
import logging
import sys
from pathlib import Path
from datetime import datetime

import yaml
from dotenv import load_dotenv

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(f'data/logs/{datetime.now().strftime("%Y-%m-%d")}_iara.log')
    ]
)

logger = logging.getLogger("IARA")


def load_config() -> dict:
    """Carrega configurações do arquivo YAML."""
    config_path = Path("config/settings.yaml")

    if not config_path.exists():
        logger.error("Arquivo de configuração não encontrado: config/settings.yaml")
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def print_banner():
    """Exibe banner de inicialização."""
    banner = """
    ==================================================================

         ___    _     ____       _        _____   ____
        |_ _|  / \\   |  _ \\     / \\      |_   _| |  _ \\
         | |  / _ \\  | |_) |   / _ \\       | |   | |_) |
         | | / ___ \\ |  _ <   / ___ \\      | |   |  _ <
        |___/_/   \\_\\|_| \\_\\ /_/   \\_\\     |_|   |_| \\_\\

           Intelligent Automated Risk-Aware Trader
                        v1.0.0

    ==================================================================
    """
    print(banner)


async def main():
    """Função principal."""
    print_banner()

    # Carrega variáveis de ambiente
    load_dotenv()

    # Carrega configurações
    logger.info("Carregando configurações...")
    config = load_config()

    # Importa módulos
    from src.core.orchestrator import Orchestrator
    from src.core.state_manager import StateManager
    from src.collectors.market_data import MarketDataCollector
    from src.collectors.news_scraper import NewsScraper
    from src.collectors.buzz_factory import BuzzFactory
    from src.collectors.macro_data import MacroDataCollector
    from src.analysis.technical import TechnicalAnalyzer
    from src.analysis.risk_math import RiskCalculator
    from src.analysis.correlation import CorrelationAnalyzer
    from src.decision.ai_gateway import AIGateway
    from src.decision.screener import Screener
    from src.decision.judge import Judge
    from src.execution.position_sizer import PositionSizer
    from src.execution.order_manager import OrderManager
    from src.execution.broker_api import BrokerAPI
    from src.monitoring.watchdog import Watchdog
    from src.monitoring.sentinel import Sentinel
    from src.monitoring.poison_pill import PoisonPillScanner
    from src.monitoring.telegram_bot import TelegramBot

    # Inicializa componentes
    logger.info("Inicializando componentes...")

    # Core
    state_manager = StateManager(config)
    state_manager.initialize(starting_capital=100000)  # Capital inicial

    # Collectors
    market_data = MarketDataCollector(config)
    news_scraper = NewsScraper(config)
    macro_data = MacroDataCollector(config)
    buzz_factory = BuzzFactory(config, market_data, news_scraper)

    # Analysis
    technical = TechnicalAnalyzer(config)
    risk_calc = RiskCalculator(config)
    correlation = CorrelationAnalyzer(config)

    # Decision
    ai_gateway = AIGateway(config)
    screener = Screener(config, ai_gateway)
    judge = Judge(config, ai_gateway)

    # Execution
    broker = BrokerAPI.create(config, broker_type="paper")  # Paper trading
    await broker.connect()
    position_sizer = PositionSizer(config)
    order_manager = OrderManager(config, broker)

    # Monitoring
    watchdog = Watchdog(config, market_data, state_manager)
    sentinel = Sentinel(config, news_scraper, ai_gateway, state_manager)
    poison_pill = PoisonPillScanner(config, news_scraper, ai_gateway, state_manager)
    telegram = TelegramBot(config, state_manager)

    # Earnings Checker (required by orchestrator)
    from src.collectors.earnings_checker import EarningsChecker
    earnings_checker = EarningsChecker(config)

    # Orchestrator (passa todos os componentes)
    orchestrator = Orchestrator(
        config=config,
        buzz_factory=buzz_factory,
        screener=screener,
        risk_calculator=risk_calc,
        correlation_analyzer=correlation,
        judge=judge,
        order_manager=order_manager,
        position_sizer=position_sizer,
        state_manager=state_manager,
        earnings_checker=earnings_checker,
        market_data=market_data
    )

    logger.info("=" * 60)
    logger.info("IARA TRADER inicializado com sucesso!")
    logger.info(f"Capital inicial: ${state_manager.capital:,.2f}")
    logger.info(f"Modo: Paper Trading")
    logger.info(f"Providers de IA: {ai_gateway.get_available_providers()}")
    logger.info("=" * 60)

    # Conecta handlers de alerta ao Telegram
    async def send_telegram_alert(alert):
        await telegram.send_alert(
            alert_type=alert.level.value if hasattr(alert, 'level') else "info",
            ticker=alert.ticker,
            message=alert.message if hasattr(alert, 'message') else str(alert)
        )

    watchdog.add_alert_handler(send_telegram_alert)
    sentinel.add_alert_handler(send_telegram_alert)

    # Inicia tasks em paralelo
    logger.info("Iniciando serviços...")

    tasks = [
        asyncio.create_task(orchestrator.start()),
        asyncio.create_task(watchdog.start()),
        asyncio.create_task(sentinel.start()),
        # asyncio.create_task(telegram.start()),  # Descomente para ativar Telegram
    ]

    try:
        # Roda até ser interrompido
        await asyncio.gather(*tasks)

    except KeyboardInterrupt:
        logger.info("Interrupção recebida, encerrando...")

    finally:
        # Cleanup
        logger.info("Encerrando serviços...")
        await orchestrator.stop()
        await watchdog.stop()
        await sentinel.stop()
        await telegram.stop()
        await broker.disconnect()

        logger.info("IARA TRADER encerrado.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nEncerrando...")
    except Exception as e:
        logger.exception(f"Erro fatal: {e}")
        sys.exit(1)
