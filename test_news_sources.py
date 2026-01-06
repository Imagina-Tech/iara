"""
Teste dos dois métodos de busca de notícias:
1. Google Custom Search API (primário)
2. GNews API (fallback)
"""

import asyncio
import logging
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

logger = logging.getLogger("NewsTest")


async def test_google_search():
    """Testa Google Custom Search API."""
    logger.info("=" * 60)
    logger.info("TESTE 1: Google Custom Search API")
    logger.info("=" * 60)

    try:
        from src.collectors.news_scraper import NewsScraper

        # Load config
        config_path = Path("config/settings.yaml")
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        # Initialize scraper
        scraper = NewsScraper(config)

        # Test search
        ticker = "AAPL"
        logger.info(f"Buscando notícias para {ticker} via Google Search API...")

        articles = await scraper.search_news(ticker, max_results=5)

        logger.info(f"[OK] Google Search retornou {len(articles)} artigos")

        # Display results
        for i, article in enumerate(articles[:3], 1):
            logger.info(f"\nArtigo {i}:")
            logger.info(f"  Título: {article.title[:80]}...")
            logger.info(f"  Fonte: {article.source}")
            logger.info(f"  URL: {article.url[:60]}...")
            logger.info(f"  Resumo: {article.summary[:100]}..." if article.summary else "  Resumo: N/A")

        # Check rate limiter status
        status = scraper.rate_limiter.get_status()
        logger.info(f"\n[STATS] Rate Limiter: {status['count']}/{status['limit']} queries usadas")
        logger.info(f"[STATS] Restam: {status['remaining']} queries hoje")

        return len(articles) > 0

    except Exception as e:
        logger.error(f"[ERROR] Erro no teste Google Search: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_gnews_fallback():
    """Testa GNews API (fallback)."""
    logger.info("\n" + "=" * 60)
    logger.info("TESTE 2: GNews API (Fallback)")
    logger.info("=" * 60)

    try:
        from src.collectors.news_aggregator import NewsAggregator

        # Load config
        config_path = Path("config/settings.yaml")
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        # Initialize aggregator
        aggregator = NewsAggregator(config)

        # Test GNews
        ticker = "TSLA"
        logger.info(f"Buscando notícias para {ticker} via GNews API...")

        articles = await aggregator.get_gnews(ticker, max_results=5)

        logger.info(f"[OK] GNews retornou {len(articles)} artigos")

        # Display results
        for i, article in enumerate(articles[:3], 1):
            logger.info(f"\nArtigo {i}:")
            logger.info(f"  Titulo: {article.get('title', 'N/A')[:80]}...")
            logger.info(f"  Fonte: {article.get('source', 'N/A')}")
            logger.info(f"  URL: {article.get('url', 'N/A')[:60]}...")
            logger.info(f"  Descricao: {article.get('description', 'N/A')[:100]}...")

        return len(articles) > 0

    except Exception as e:
        logger.error(f"[ERROR] Erro no teste GNews: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_automatic_fallback():
    """Testa fallback automático quando Google Search atinge limite."""
    logger.info("\n" + "=" * 60)
    logger.info("TESTE 3: Fallback Automático")
    logger.info("=" * 60)

    try:
        from src.collectors.news_scraper import NewsScraper

        # Load config
        config_path = Path("config/settings.yaml")
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        # Initialize scraper
        scraper = NewsScraper(config)

        # Simular limite atingido forçando contador
        logger.info("Simulando limite diário atingido...")
        scraper.rate_limiter.count = 95
        scraper.rate_limiter._save_counter()

        # Test search (deve usar fallback)
        ticker = "MSFT"
        logger.info(f"Buscando notícias para {ticker} (deve usar fallback)...")

        articles = await scraper.search_news(ticker, max_results=5)

        logger.info(f"[OK] Fallback retornou {len(articles)} artigos")

        # Reset counter
        scraper.rate_limiter.count = 0
        scraper.rate_limiter._save_counter()
        logger.info("[OK] Contador resetado para testes futuros")

        return len(articles) > 0

    except Exception as e:
        logger.error(f"[ERROR] Erro no teste de fallback: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Executa todos os testes."""
    # Load environment
    load_dotenv()

    logger.info("\n")
    logger.info("============================================================")
    logger.info("        TESTE DE FONTES DE NOTICIAS - IARA TRADER")
    logger.info("============================================================")
    logger.info("\n")

    results = {}

    # Test 1: Google Search
    results['google_search'] = await test_google_search()
    await asyncio.sleep(2)

    # Test 2: GNews
    results['gnews'] = await test_gnews_fallback()
    await asyncio.sleep(2)

    # Test 3: Automatic Fallback
    results['fallback'] = await test_automatic_fallback()

    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("RESUMO DOS TESTES")
    logger.info("=" * 60)
    logger.info(f"Google Search API:    {'[OK] PASSOU' if results['google_search'] else '[FALHOU]'}")
    logger.info(f"GNews API (Fallback): {'[OK] PASSOU' if results['gnews'] else '[FALHOU]'}")
    logger.info(f"Fallback Automático:  {'[OK] PASSOU' if results['fallback'] else '[FALHOU]'}")
    logger.info("=" * 60)

    all_passed = all(results.values())
    if all_passed:
        logger.info("\n[OK] Todos os testes passaram! Sistema de notícias funcionando corretamente.")
    else:
        logger.error("\n[ERROR] Alguns testes falharam. Verifique os logs acima.")

    return 0 if all_passed else 1


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("\nTeste interrompido pelo usuário.")
        sys.exit(1)
    except Exception as e:
        logger.exception(f"Erro fatal: {e}")
        sys.exit(1)
