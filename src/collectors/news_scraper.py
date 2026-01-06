"""
NEWS SCRAPER - Coleta de Notícias
Usa newspaper3k + Google Search API com rate limiting inteligente
"""

import logging
import os
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class NewsArticle:
    """Representa uma notícia."""
    title: str
    summary: str
    url: str
    source: str
    published_at: Optional[datetime]
    sentiment: Optional[str] = None
    relevance_score: float = 0.0


class GoogleSearchRateLimiter:
    """
    Rate limiter para Google Custom Search API.
    Limite: 95 queries/dia (deixa margem de 5 para segurança).
    """

    def __init__(self, daily_limit: int = 95):
        """
        Args:
            daily_limit: Limite diário de queries (default: 95)
        """
        self.daily_limit = daily_limit
        self.counter_file = Path("data/cache/google_search_counter.json")
        self.counter_file.parent.mkdir(parents=True, exist_ok=True)
        self._load_counter()

    def _load_counter(self) -> None:
        """Carrega contador do arquivo."""
        try:
            if self.counter_file.exists():
                with open(self.counter_file, "r") as f:
                    data = json.load(f)
                    self.count = data.get("count", 0)
                    self.date = data.get("date", "")

                    # Reset se mudou o dia
                    today = datetime.now().strftime("%Y-%m-%d")
                    if self.date != today:
                        logger.info(f"🔄 Google Search API: Novo dia detectado. Reset contador: {self.count} → 0")
                        self.count = 0
                        self.date = today
                        self._save_counter()
            else:
                self.count = 0
                self.date = datetime.now().strftime("%Y-%m-%d")
                self._save_counter()

        except Exception as e:
            logger.error(f"Erro ao carregar contador Google Search: {e}")
            self.count = 0
            self.date = datetime.now().strftime("%Y-%m-%d")

    def _save_counter(self) -> None:
        """Salva contador no arquivo."""
        try:
            with open(self.counter_file, "w") as f:
                json.dump({
                    "count": self.count,
                    "date": self.date
                }, f)
        except Exception as e:
            logger.error(f"Erro ao salvar contador Google Search: {e}")

    def can_query(self) -> bool:
        """Verifica se pode fazer query."""
        return self.count < self.daily_limit

    def increment(self) -> None:
        """Incrementa contador e salva."""
        self.count += 1
        self._save_counter()

        # Log a cada 10 queries
        if self.count % 10 == 0:
            remaining = self.daily_limit - self.count
            logger.info(f"📊 Google Search API: {self.count}/{self.daily_limit} queries usadas hoje (restam {remaining})")

    def get_status(self) -> Dict[str, Any]:
        """Retorna status atual."""
        remaining = self.daily_limit - self.count
        return {
            "count": self.count,
            "limit": self.daily_limit,
            "remaining": remaining,
            "date": self.date,
            "can_query": self.can_query()
        }


class NewsScraper:
    """
    Scraper de notícias para análise de catalisadores.
    Usa Google Custom Search API com fallback para news_aggregator.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Inicializa o scraper.

        Args:
            config: Configurações do sistema
        """
        self.config = config
        self._cache: Dict[str, List[NewsArticle]] = {}
        self._cache_expiry: Dict[str, datetime] = {}

        # Rate limiter para Google Search API
        self.rate_limiter = GoogleSearchRateLimiter(daily_limit=95)

        # Carrega credenciais
        self.google_api_key = os.getenv("GOOGLE_SEARCH_API_KEY")
        self.google_cse_id = os.getenv("GOOGLE_CSE_ID")

        # Log inicial
        if self.google_api_key and self.google_cse_id:
            status = self.rate_limiter.get_status()
            logger.info(f"[OK] Google Search API configurada: {status['remaining']}/{status['limit']} queries disponíveis hoje")
        else:
            logger.warning("[WARNING] Google Search API não configurada (GOOGLE_SEARCH_API_KEY ou GOOGLE_CSE_ID ausentes). Usando fallback GNews.")

    async def search_news(self, ticker: str, max_results: int = 10) -> List[NewsArticle]:
        """
        Busca notícias sobre um ticker.

        Args:
            ticker: Símbolo da ação
            max_results: Número máximo de resultados

        Returns:
            Lista de notícias
        """
        # Verifica cache
        if self._is_cached(ticker):
            return self._cache[ticker]

        try:
            articles = await self._fetch_from_google(ticker, max_results)
            self._update_cache(ticker, articles)
            return articles

        except Exception as e:
            logger.error(f"Erro ao buscar notícias de {ticker}: {e}")
            return []

    async def _fetch_from_google(self, ticker: str, max_results: int) -> List[NewsArticle]:
        """
        Busca notícias via Google Custom Search API com fallback inteligente.

        Args:
            ticker: Símbolo da ação
            max_results: Número máximo de resultados (limitado a 10 por query)

        Returns:
            Lista de NewsArticle
        """
        # Verifica se Google Search está configurado
        if not (self.google_api_key and self.google_cse_id):
            logger.info(f"🔄 Google Search não configurada para {ticker}. Usando fallback GNews...")
            return await self._fallback_to_gnews(ticker, max_results)

        # Verifica rate limit
        if not self.rate_limiter.can_query():
            status = self.rate_limiter.get_status()
            logger.warning(f"[WARNING] Google Search API: Limite diário atingido ({status['count']}/{status['limit']}). "
                           f"Usando fallback GNews para {ticker}...")
            return await self._fallback_to_gnews(ticker, max_results)

        try:
            from googleapiclient.discovery import build

            # Limitar a 10 resultados (máximo do Google por query)
            max_results = min(max_results, 10)

            # Build service
            service = build("customsearch", "v1", developerKey=self.google_api_key)

            # Query
            query = f"{ticker} stock news"
            logger.info(f"🔍 Google Search API: Buscando notícias para {ticker}...")

            result = service.cse().list(
                q=query,
                cx=self.google_cse_id,
                num=max_results,
                dateRestrict="d7",  # Últimos 7 dias
                sort="date"  # Ordenar por data
            ).execute()

            # Incrementar contador
            self.rate_limiter.increment()

            # Processar resultados
            articles = []
            items = result.get("items", [])

            logger.info(f"📰 Google Search API: {len(items)} resultados encontrados para {ticker}")

            for item in items:
                try:
                    # Tentar scrape completo do artigo
                    article = await self.scrape_article(item["link"])

                    if article:
                        articles.append(article)
                    else:
                        # Se scrape falhou, usar dados básicos do Google
                        articles.append(NewsArticle(
                            title=item.get("title", ""),
                            summary=item.get("snippet", ""),
                            url=item["link"],
                            source=item.get("displayLink", ""),
                            published_at=None
                        ))

                except Exception as e:
                    logger.debug(f"Erro ao processar item: {e}")
                    continue

            logger.info(f"[OK] Google Search API: {len(articles)} artigos processados para {ticker}")
            return articles

        except ImportError:
            logger.error("[ERROR] Biblioteca 'google-api-python-client' não instalada. "
                         "Instale com: pip install google-api-python-client")
            return await self._fallback_to_gnews(ticker, max_results)

        except Exception as e:
            logger.error(f"[ERROR] Erro ao buscar notícias via Google Search para {ticker}: {e}")
            return await self._fallback_to_gnews(ticker, max_results)

    async def _fallback_to_gnews(self, ticker: str, max_results: int) -> List[NewsArticle]:
        """
        Fallback para GNews quando Google Search não está disponível.

        Args:
            ticker: Símbolo da ação
            max_results: Número máximo de resultados

        Returns:
            Lista de NewsArticle
        """
        try:
            from src.collectors.news_aggregator import NewsAggregator

            logger.info(f"🔄 Fallback: Usando GNews API para {ticker}...")

            aggregator = NewsAggregator(self.config)
            gnews_articles = await aggregator.get_gnews(ticker, max_results)

            # Converter formato GNews para NewsArticle
            articles = []
            for item in gnews_articles:
                # Tentar scrape completo
                article = await self.scrape_article(item["url"])

                if article:
                    articles.append(article)
                else:
                    # Usar dados básicos do GNews
                    articles.append(NewsArticle(
                        title=item.get("title", ""),
                        summary=item.get("description", ""),
                        url=item.get("url", ""),
                        source=item.get("source", "GNews"),
                        published_at=None
                    ))

            logger.info(f"[OK] GNews API (fallback): {len(articles)} artigos para {ticker}")
            return articles

        except Exception as e:
            logger.error(f"[ERROR] Erro no fallback GNews para {ticker}: {e}")
            return []

    async def scrape_article(self, url: str) -> Optional[NewsArticle]:
        """
        Faz scraping de um artigo específico.

        Args:
            url: URL do artigo

        Returns:
            NewsArticle ou None
        """
        try:
            from newspaper import Article

            article = Article(url)
            article.download()
            article.parse()
            article.nlp()

            return NewsArticle(
                title=article.title,
                summary=article.summary,
                url=url,
                source=article.source_url,
                published_at=article.publish_date
            )

        except Exception as e:
            logger.error(f"Erro ao fazer scraping de {url}: {e}")
            return None

    def _is_cached(self, ticker: str) -> bool:
        """Verifica se há cache válido."""
        if ticker not in self._cache:
            return False

        expiry = self._cache_expiry.get(ticker)
        if not expiry:
            return False

        return datetime.now() < expiry

    def _update_cache(self, ticker: str, articles: List[NewsArticle]) -> None:
        """Atualiza o cache."""
        cache_hours = self.config.get("ai", {}).get("cache_expiry_hours", 4)
        self._cache[ticker] = articles
        self._cache_expiry[ticker] = datetime.now() + timedelta(hours=cache_hours)

    def get_sentiment_summary(self, articles: List[NewsArticle]) -> Dict[str, Any]:
        """
        Gera resumo de sentimento das notícias.

        Args:
            articles: Lista de artigos

        Returns:
            Resumo de sentimento
        """
        if not articles:
            return {"sentiment": "neutral", "score": 0.0, "article_count": 0}

        # TODO: Implementar análise de sentimento
        return {
            "sentiment": "neutral",
            "score": 0.0,
            "article_count": len(articles),
            "titles": [a.title for a in articles[:5]]
        }
