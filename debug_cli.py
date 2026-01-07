"""
IARA Debug CLI - Sistema de Inspeção de JSONs
Executa comandos de diagnóstico sem precisar inicializar o sistema completo

Suporta output colorido para melhor visualizacao do progresso paralelo.
"""

import asyncio
import sys
import os
import logging
from pathlib import Path
import yaml
import json
from datetime import datetime
from dotenv import load_dotenv

# =============================================================================
# HABILITAR CORES ANSI NO WINDOWS
# =============================================================================
# Esse hack ativa suporte a escape sequences ANSI no cmd.exe e PowerShell
# Necessario para exibir cores no terminal Windows
if sys.platform == "win32":
    os.system("")  # Ativa ANSI escape sequences

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

    # Buscar notícias para TODOS os candidatos (o Judge precisa de contexto completo)
    print("=" * 80)
    print("  BUSCANDO NOTICIAS PARA TODOS OS CANDIDATOS (12 em paralelo)")
    print("  (O Judge precisa de contexto de notícias para TODOS os tickers)")
    print("=" * 80)

    news_for_candidates = {}
    total_candidates = len(filtered)
    completed_count = 0
    news_semaphore = asyncio.Semaphore(12)  # 12 requisicoes em paralelo

    async def fetch_news_for_ticker(candidate):
        """Busca noticias para um ticker com controle de concorrencia."""
        nonlocal completed_count
        ticker = candidate.ticker

        async with news_semaphore:
            try:
                # Buscar notícias com scoring (mesmo método usado na produção)
                gnews_articles = await news_aggregator.get_gnews(ticker, max_results=5, fetch_full_content=False)

                completed_count += 1
                if gnews_articles:
                    # USA METODOS CENTRALIZADOS - EXATAMENTE o mesmo formato usado no orchestrator.py
                    result = {
                        "screener_format": news_aggregator.format_news_for_screener(ticker, gnews_articles),
                        "judge_format": news_aggregator.format_news_for_judge(ticker, gnews_articles),
                        "raw_articles": gnews_articles
                    }
                    print(f"[NEWS] {completed_count}/{total_candidates} - {ticker}: {len(gnews_articles)} artigos")
                    return ticker, result
                else:
                    print(f"[NEWS] {completed_count}/{total_candidates} - {ticker}: sem noticias")
                    return ticker, None

            except Exception as e:
                completed_count += 1
                print(f"[NEWS] {completed_count}/{total_candidates} - {ticker}: Erro - {str(e)[:50]}")
                return ticker, None

    # Executar todas as buscas em paralelo (limitado pelo semaphore)
    tasks = [fetch_news_for_ticker(c) for c in filtered]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Processar resultados
    for result in results:
        if isinstance(result, tuple):
            ticker, news_data = result
            news_for_candidates[ticker] = news_data
        elif isinstance(result, Exception):
            print(f"[NEWS] Erro inesperado: {result}")

    print(f"\n[NEWS] Completo: {sum(1 for v in news_for_candidates.values() if v)}/{total_candidates} tickers com noticias")
    print()

    # Função para formatar notícias de forma legível (quebra em linhas)
    def format_news_readable(news_text):
        """Formata notícia como lista de linhas para melhor leitura no JSON."""
        if not news_text:
            return []
        # Quebra por linhas e remove vazias
        lines = [line.strip() for line in news_text.split('\n') if line.strip()]
        return lines

    # Função para estruturar artigos de forma organizada
    def structure_articles(ticker):
        """Retorna artigos estruturados para um ticker."""
        news_data = news_for_candidates.get(ticker)
        if not news_data or not news_data.get("raw_articles"):
            return []

        articles = []
        for art in news_data.get("raw_articles", []):
            articles.append({
                "titulo": art.get("title", ""),
                "fonte": art.get("source", ""),
                "data": art.get("published", ""),
                "resumo": art.get("description", ""),
                "conteudo_completo": art.get("full_content", "")[:500] + "..." if art.get("full_content") and len(art.get("full_content", "")) > 500 else art.get("full_content", "")
            })
        return articles

    # Contar quantos têm notícias
    candidates_with_news_count = sum(1 for c in filtered if news_for_candidates.get(c.ticker))

    result = {
        "generated_at": datetime.now().isoformat(),
        "test_mode": True,
        "forced_all_sources": True,
        "summary": {
            "total_candidates_raw": len(candidates),
            "total_candidates_filtered": len(filtered),
            "by_source": {source: len(items) for source, items in by_source.items()},
            "candidates_with_news": candidates_with_news_count
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
                "news_content": format_news_readable(c.news_content) if hasattr(c, 'news_content') else [],
                "news_articles": structure_articles(c.ticker),
                "news_for_screener": format_news_readable((news_for_candidates.get(c.ticker) or {}).get("screener_format", "")),
                "news_for_judge": format_news_readable((news_for_candidates.get(c.ticker) or {}).get("judge_format", ""))
            }
            for c in filtered
        ]
    }

    # Save to data/outputs (não debug_outputs)
    output_path = Path("data/outputs/buzz_candidates.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    # Display summary por fonte
    print("\n" + "=" * 80)
    print("  RESUMO DOS CANDIDATOS POR FONTE")
    print("=" * 80)

    # Definir ícones para cada fonte
    source_icons = {
        "watchlist": "[W]",
        "volume_spike": "[V]",
        "gap": "[G]",
        "news_catalyst": "[N]"
    }

    for source, items in sorted(by_source.items()):
        icon = source_icons.get(source, "[?]")
        print(f"\n  {icon} {source.upper()} ({len(items)} candidatos):")
        print(f"  " + "-" * 40)
        for c in items[:5]:  # Mostrar top 5 de cada fonte
            market_cap_b = c.market_cap / 1e9 if c.market_cap > 0 else 0
            print(f"      {c.ticker:8s} | Score: {c.buzz_score:5.1f} | ${market_cap_b:7.1f}B | {c.reason[:40]}")
        if len(items) > 5:
            print(f"      ... e mais {len(items) - 5} candidatos")

    print(f"\n  " + "=" * 60)
    print(f"  TOTAIS:")
    print(f"  " + "-" * 60)
    print(f"  [W] Watchlist      : {len(by_source.get('watchlist', [])):3d} (ativos fixos monitorados)")
    print(f"  [V] Volume Spikes  : {len(by_source.get('volume_spike', [])):3d} (volume > 2x media projetado)")
    print(f"  [G] Gaps           : {len(by_source.get('gap', [])):3d} (gap > 3% na abertura)")
    print(f"  [N] News Catalysts : {len(by_source.get('news_catalyst', [])):3d} (noticias com keywords)")
    print(f"  " + "-" * 60)
    print(f"  TOTAL ENCONTRADOS  : {len(candidates):3d}")
    print(f"  TOTAL FILTRADOS    : {len(filtered):3d} (max 25)")
    print("=" * 80)

    # Display TODOS os candidatos
    print("\n" + "=" * 80)
    print(f"  TODOS OS {len(filtered)} CANDIDATOS (ordenados por buzz_score)")
    print("=" * 80)
    print(f"  {'#':>2} | {'TICKER':8s} | {'FONTE':14s} | {'SCORE':>5} | {'MKT CAP':>10} | {'NEWS':>4} | RAZAO")
    print("  " + "-" * 90)
    for i, c in enumerate(filtered, 1):
        market_cap_b = c.market_cap / 1e9 if c.market_cap > 0 else 0
        icon = source_icons.get(c.source, "[?]")
        has_news = "SIM" if news_for_candidates.get(c.ticker) else "NAO"
        print(f"  {i:2d} | {c.ticker:8s} | {icon} {c.source:10s} | {c.buzz_score:5.1f} | ${market_cap_b:8.1f}B | {has_news:>4} | {c.reason[:30]}")

    # Mostrar resumo de notícias
    print(f"\n  " + "-" * 90)
    tickers_with_news = [c.ticker for c in filtered if news_for_candidates.get(c.ticker)]
    tickers_without_news = [c.ticker for c in filtered if not news_for_candidates.get(c.ticker)]
    print(f"  NOTICIAS: {len(tickers_with_news)}/{len(filtered)} candidatos com cobertura de noticias")
    if tickers_without_news:
        print(f"  SEM NOTICIAS: {', '.join(tickers_without_news[:10])}" + ("..." if len(tickers_without_news) > 10 else ""))

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
