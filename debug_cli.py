"""
IARA Debug CLI - Sistema de Inspeção de JSONs
Executa comandos de diagnóstico sem precisar inicializar o sistema completo
"""

import asyncio
import sys
import logging
from pathlib import Path
import yaml
import json
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables FIRST
load_dotenv()

# Configurar logging para exibir na console
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    datefmt='%H:%M:%S',
    handlers=[logging.StreamHandler(sys.stdout)]
)

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.collectors.buzz_factory import BuzzFactory
from src.collectors.market_data import MarketDataCollector
from src.collectors.news_scraper import NewsScraper
from src.collectors.earnings_checker import EarningsChecker
from src.core.state_manager import StateManager
from src.core.database import Database

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
        print(f"\n{'='*80}")
        print(f"  {title}")
        print(f"{'='*80}\n")
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
    print(f"\n{'='*80}\n")

async def cmd_buzz():
    """
    Executa Buzz Factory (Phase 0) com TODAS as fontes.
    FORÇA execução completa independente do horário (simula horário de mercado).
    Mostra exatamente o que será passado para Screener e Judge.
    """
    print("\n" + "=" * 80)
    print("  BUZZ FACTORY - PHASE 0 (MODO TESTE COMPLETO)")
    print("=" * 80)
    print("\n[AVISO] Simulando horário de mercado - TODAS as fontes serão executadas:")
    print("  - Watchlist (sempre ativo)")
    print("  - Volume Spikes (sempre ativo)")
    print("  - Gap Scanner (FORCADO - normalmente só pré-mercado 08:00-09:30)")
    print("  - News Catalysts (sempre ativo)\n")

    print("[1/4] Inicializando componentes...")
    market_data = MarketDataCollector(config)
    news_scraper = NewsScraper(config)
    buzz_factory = BuzzFactory(config, market_data, news_scraper)

    print("[2/4] Executando Buzz Factory com force_all=True...")
    candidates = await buzz_factory.generate_daily_buzz(force_all=True)

    print("[3/4] Aplicando filtros (liquidity, market cap, earnings, Friday)...")
    earnings_checker = EarningsChecker(config)
    filtered = await buzz_factory.apply_filters(candidates)

    # Group by source
    by_source = {}
    for c in filtered:
        by_source[c.source] = by_source.get(c.source, [])
        by_source[c.source].append(c)

    print("[4/4] Serializando para JSON...\n")

    # Simular busca de notícias como aconteceria no orchestrator
    from src.collectors.news_aggregator import NewsAggregator
    news_aggregator = NewsAggregator(config)

    # Buscar notícias para top 5 candidatos (simulando Phase 1 e 3)
    print("=" * 80)
    print("  SIMULANDO BUSCA DE NOTICIAS (como acontece em Phase 1 e 3)")
    print("=" * 80)

    news_for_candidates = {}
    top_candidates = filtered[:3]  # Reduzido para 3 (scraping é lento)

    for c in top_candidates:
        ticker = c.ticker
        print(f"\n--- Buscando noticias para {ticker} ---")

        # SCREENER (Phase 1) - apenas títulos, rápido
        gnews_simple = await news_aggregator.get_gnews(ticker, max_results=3, fetch_full_content=False)

        # JUDGE (Phase 3) - conteúdo completo, mais lento
        print(f"    Fazendo scrape do conteudo completo (para o Judge)...")
        gnews_full = await news_aggregator.get_gnews(ticker, max_results=2, fetch_full_content=True)

        if gnews_simple:
            # Formato para SCREENER (Phase 1) - resumido
            news_summary_parts = [f"Recent news for {ticker}:"]
            for art in gnews_simple[:3]:
                news_summary_parts.append(f"- {art.get('title', 'No title')}")
            news_summary = "\n".join(news_summary_parts)

            # Formato para JUDGE (Phase 3) - conteúdo completo
            news_details_parts = [f"=== DETAILED NEWS FOR {ticker} ==="]
            for i, art in enumerate(gnews_full[:2], 1):
                news_details_parts.append(f"\n{'='*60}")
                news_details_parts.append(f"[ARTICLE {i}] {art.get('title', 'No title')}")
                news_details_parts.append(f"Source: {art.get('source', 'Unknown')}")
                news_details_parts.append(f"Published: {art.get('published', 'Unknown')}")
                news_details_parts.append(f"\nCONTENT:")
                if art.get('full_content'):
                    news_details_parts.append(art['full_content'])
                else:
                    news_details_parts.append(f"[Scrape failed - using description]")
                    news_details_parts.append(art.get('description', 'No description'))
            news_details = "\n".join(news_details_parts)

            news_for_candidates[ticker] = {
                "screener_format": news_summary,
                "judge_format": news_details,
                "raw_articles": gnews_simple
            }

            print(f"\n[SCREENER INPUT] O que Phase 1 recebe:")
            print("-" * 40)
            print(news_summary)

            print(f"\n[JUDGE INPUT] O que Phase 3 recebe:")
            print("-" * 40)
            print(news_details[:1500] + "..." if len(news_details) > 1500 else news_details)
        else:
            print(f"  Nenhuma noticia encontrada para {ticker}")
            news_for_candidates[ticker] = None

    result = {
        "generated_at": datetime.now().isoformat(),
        "test_mode": True,
        "forced_all_sources": True,
        "summary": {
            "total_candidates_raw": len(candidates),
            "total_candidates_filtered": len(filtered),
            "by_source": {source: len(items) for source, items in by_source.items()},
            "candidates_with_news": sum(1 for c in filtered if hasattr(c, 'news_content') and c.news_content)
        },
        "candidates": [
            {
                "ticker": c.ticker,
                "source": c.source,
                "buzz_score": c.buzz_score,
                "tier": c.tier,
                "market_cap": c.market_cap,
                "market_cap_billions": round(c.market_cap / 1e9, 2) if c.market_cap > 0 else 0,
                "reason": c.reason,
                "detected_at": c.detected_at.isoformat(),
                "news_content": c.news_content if hasattr(c, 'news_content') else "",
                "news_for_screener": (news_for_candidates.get(c.ticker) or {}).get("screener_format", "") if c.ticker in [x.ticker for x in top_candidates] else "",
                "news_for_judge": (news_for_candidates.get(c.ticker) or {}).get("judge_format", "") if c.ticker in [x.ticker for x in top_candidates] else ""
            }
            for c in filtered
        ]
    }

    # Save to data/outputs (não debug_outputs)
    output_path = Path("data/outputs/buzz_candidates.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    # Display summary
    print("\n" + "=" * 80)
    print("  RESUMO DOS CANDIDATOS")
    print("=" * 80)
    for source, items in by_source.items():
        print(f"  {source:20s}: {len(items):3d} candidatos")
    print(f"\n  TOTAL FILTRADO      : {len(filtered):3d} candidatos")
    print(f"  TOTAL RAW           : {len(candidates):3d} candidatos")
    candidates_with_news = sum(1 for c in filtered if hasattr(c, 'news_content') and c.news_content)
    print(f"  COM NEWS_CATALYST   : {candidates_with_news:3d} candidatos")
    print(f"  COM GNEWS BUSCADO   : {len([t for t in news_for_candidates if news_for_candidates[t]])} candidatos (top 5)")
    print("=" * 80)

    # Display top 10
    print("\n" + "=" * 80)
    print("  TOP 10 CANDIDATOS (por buzz_score)")
    print("=" * 80)
    for i, c in enumerate(filtered[:10], 1):
        market_cap_b = c.market_cap / 1e9 if c.market_cap > 0 else 0
        print(f"\n{i}. {c.ticker} (Score: {c.buzz_score:.1f})")
        print(f"   Fonte: {c.source}")
        print(f"   Tier: {c.tier}")
        print(f"   Market Cap: ${market_cap_b:.2f}B")
        print(f"   Razao: {c.reason[:80]}")
        # Mostrar news_content se disponível (do catalyst scan)
        if hasattr(c, 'news_content') and c.news_content:
            print(f"   [NEWS CATALYST]:")
            for line in c.news_content.split('\n')[:3]:
                print(f"      {line}")

    print("\n" + "=" * 80)
    print(f"[SAVED] {output_path.absolute()}")
    print("=" * 80 + "\n")

    return result

async def cmd_technical(ticker):
    print(f"\n[1/2] Buscando dados de mercado para {ticker}...")
    market_data = MarketDataCollector(config)
    print(f"[2/2] Analisando indicadores técnicos...")
    data = market_data.get_stock_data(ticker)
    if not data:
        print(f"[ERROR] Não foi possível obter dados para {ticker}\n")
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
    print(f"[SAVED] {filepath}\n")
    return result

async def cmd_portfolio():
    print("\n[1/1] Carregando estado do portfolio...")
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
    print(f"[SAVED] {filepath}\n")
    return result

def cmd_config():
    print("\n[1/1] Carregando configurações...")
    result = {
        "timestamp": datetime.now().isoformat(),
        "config": config
    }
    filepath = save_json(result, "system_config")
    print_json(result, "SYSTEM CONFIGURATION")
    print(f"[SAVED] {filepath}\n")
    return result

async def cmd_database():
    print("\n[1/2] Inicializando banco de dados...")
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
    print(f"[SAVED] {filepath}\n")
    return result

def show_help():
    help_text = """
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
"""
    print(help_text)

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
                print("[WARNING] Uso: python debug_cli.py /technical TICKER\n")
                return
            await cmd_technical(args[0].upper())
        elif command == "/portfolio":
            await cmd_portfolio()
        elif command == "/config":
            cmd_config()
        elif command == "/database":
            await cmd_database()
        else:
            print(f"[WARNING] Comando desconhecido: {command}")
            print("Use /help para ver comandos disponíveis.\n")
    except Exception as e:
        print(f"\n[ERROR] Erro ao executar comando: {e}\n")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
