"""
IARA Debug CLI - Sistema de Inspeção de JSONs
Executa comandos de diagnóstico sem precisar inicializar o sistema completo
"""

import asyncio
import sys
from pathlib import Path
import yaml

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.collectors.buzz_factory import BuzzFactory
from src.collectors.market_data import MarketDataCollector
from src.collectors.news_scraper import NewsScraper
from src.collectors.earnings_checker import EarningsChecker
from src.decision.screener import Screener
from src.decision.ai_gateway import AIGateway
from src.analysis.technical import TechnicalAnalyzer
from src.core.state_manager import StateManager
from src.core.database import Database
import json
from datetime import datetime

print("=" * 80)
print("IARA DEBUG CLI - Sistema de Inspeção de JSONs")
print("=" * 80)
print()

# Load config
config_path = Path(__file__).parent / "config" / "settings.yaml"
with open(config_path, "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

# Output directory
output_dir = Path("data/debug_outputs")
output_dir.mkdir(parents=True, exist_ok=True)

def save_json(data, filename):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = output_dir / f"{filename}_{timestamp}.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)
    return str(filepath)

def print_json(data, title=""):
    if title:
        print(f"
{chr(61)*80}")
        print(f"  {title}")
        print(f"{chr(61)*80}
")
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
    print(f"
{chr(61)*80}
")

async def cmd_buzz():
    print("
[1/3] Inicializando componentes...")
    market_data = MarketDataCollector(config)
    news_scraper = NewsScraper(config)
    buzz_factory = BuzzFactory(config, market_data, news_scraper)
    print("[2/3] Executando Buzz Factory (Phase 0)...")
    candidates = await buzz_factory.generate_daily_buzz()
    print("[3/3] Aplicando filtros...")
    earnings_checker = EarningsChecker(config)
    filtered = await buzz_factory.apply_filters(candidates)
    result = {
        "timestamp": datetime.now().isoformat(),
        "total_candidates_raw": len(candidates),
        "total_candidates_filtered": len(filtered),
        "candidates": [
            {
                "ticker": c.ticker,
                "source": c.source,
                "buzz_score": c.buzz_score,
                "tier": c.tier,
                "market_cap": c.market_cap,
                "reason": c.reason,
                "detected_at": c.detected_at.isoformat()
            }
            for c in filtered
        ]
    }
    filepath = save_json(result, "buzz_factory")
    print_json(result, "BUZZ FACTORY OUTPUT (Phase 0)")
    print(f"💾 Salvo em: {filepath}
")
    return result

async def cmd_technical(ticker):
    print(f"
[1/2] Buscando dados de mercado para {ticker}...")
    market_data = MarketDataCollector(config)
    print(f"[2/2] Analisando indicadores técnicos...")
    data = market_data.get_stock_data(ticker)
    if not data:
        print(f"❌ Erro: Não foi possível obter dados para {ticker}
")
        return None
    result = {
        "timestamp": datetime.now().isoformat(),
        "ticker": ticker,
        "market_data": {
            "price": data.price if hasattr(data, 'price') else None,
            "volume": data.volume if hasattr(data, 'volume') else None,
            "market_cap": data.market_cap if hasattr(data, 'market_cap') else None,
            "beta": data.beta if hasattr(data, 'beta') else None
        }
    }
    filepath = save_json(result, f"technical_{ticker}")
    print_json(result, f"TECHNICAL DATA for {ticker}")
    print(f"💾 Salvo em: {filepath}
")
    return result

async def cmd_portfolio():
    print("
[1/1] Carregando estado do portfolio...")
    state_manager = StateManager(config)
    positions = state_manager.get_open_positions()
    result = {
        "timestamp": datetime.now().isoformat(),
        "capital": state_manager.capital,
        "current_drawdown": state_manager.get_current_drawdown(),
        "defensive_mode": state_manager.is_defensive_mode(),
        "kill_switch_active": state_manager.kill_switch_active,
        "total_positions": len(positions),
        "positions": [
            {
                "ticker": p.ticker,
                "direction": p.direction,
                "entry_price": p.entry_price,
                "quantity": p.quantity,
                "unrealized_pnl": p.unrealized_pnl
            }
            for p in positions
        ]
    }
    filepath = save_json(result, "portfolio_state")
    print_json(result, "PORTFOLIO STATE")
    print(f"💾 Salvo em: {filepath}
")
    return result

def cmd_config():
    print("
[1/1] Carregando configurações...")
    result = {
        "timestamp": datetime.now().isoformat(),
        "config": config
    }
    filepath = save_json(result, "system_config")
    print_json(result, "SYSTEM CONFIGURATION")
    print(f"💾 Salvo em: {filepath}
")
    return result

async def cmd_database():
    print("
[1/2] Inicializando banco de dados...")
    db = Database("data/iara.db")
    print("[2/2] Consultando histórico...")
    decisions = db.get_decisions_history(limit=10)
    trades = db.get_trade_history(limit=10)
    result = {
        "timestamp": datetime.now().isoformat(),
        "database": {
            "path": "data/iara.db",
            "recent_decisions": len(decisions),
            "recent_trades": len(trades),
            "decisions": decisions,
            "trades": trades
        }
    }
    filepath = save_json(result, "database_state")
    print_json(result, "DATABASE STATE")
    print(f"💾 Salvo em: {filepath}
")
    return result

def show_help():
    print("""
COMANDOS DISPONÍVEIS:

Phase 0 - Buzz Factory:
  /buzz                    Ver candidatos gerados (watchlist, volume, gaps, news)

Phase 1 - Screener:
  /technical TICKER        Ver dados técnicos de mercado

Estado do Sistema:
  /portfolio               Ver estado do portfolio
  /config                  Ver configurações carregadas
  /database                Ver status do banco de dados

Geral:
  /help                    Mostrar esta ajuda

EXEMPLOS:
  python debug_cli.py /buzz
  python debug_cli.py /technical AAPL
  python debug_cli.py /portfolio

NOTA: Todos os JSONs são salvos em: data/debug_outputs/
""")

async def main():
    if len(sys.argv) < 2:
        show_help()
        return
    command = sys.argv[1].lower()
    args = sys.argv[2:] if len(sys.argv) > 2 else []
    try:
        if command == "/help":
            show_help()
        elif command == "/buzz":
            await cmd_buzz()
        elif command == "/technical":
            if not args:
                print("⚠️  Uso: python debug_cli.py /technical TICKER
")
                return
            await cmd_technical(args[0].upper())
        elif command == "/portfolio":
            await cmd_portfolio()
        elif command == "/config":
            cmd_config()
        elif command == "/database":
            await cmd_database()
        else:
            print(f"⚠️  Comando desconhecido: {command}")
            print("Use /help para ver comandos disponíveis.
")
    except Exception as e:
        print(f"
❌ Erro ao executar comando: {e}
")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
