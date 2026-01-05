"""
NEWS AGGREGATOR - Agregação e Tratamento de Notícias
Combina GNews API + newspaper3k + Gemini NLP para extração de tickers
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class NewsArticle:
    """Artigo de notícia tratado."""
    title: str
    url: str
    published_date: Optional[datetime]
    source: str
    summary: Optional[str]
    tickers_mentioned: List[str]  # Extraído via Gemini
    sentiment: Optional[str]  # "positive", "negative", "neutral"
    relevance_score: float  # 0-10


class NewsAggregator:
    """
    Agregador de notícias com múltiplas fontes e tratamento com IA.
    """

    def __init__(self, config: Dict[str, Any], ai_gateway=None):
        """
        Inicializa o agregador.

        Args:
            config: Configurações do sistema
            ai_gateway: Gateway de IA para processamento (opcional)
        """
        self.config = config
        self.ai_gateway = ai_gateway

    async def get_gnews(self, ticker: str, max_results: int = 5) -> List[Dict[str, Any]]:
        """
        Busca notícias do GNews API.

        Args:
            ticker: Ticker do ativo
            max_results: Número máximo de resultados

        Returns:
            Lista de artigos (dicts)
        """
        try:
            from gnews import GNews

            google_news = GNews(language='en', max_results=max_results)
            news = google_news.get_news(ticker)

            articles = []
            for item in news:
                articles.append({
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "published": item.get("published date", ""),
                    "description": item.get("description", ""),
                    "source": "GNews"
                })

            logger.info(f"GNews: Found {len(articles)} articles for {ticker}")
            return articles

        except Exception as e:
            logger.error(f"Error fetching GNews for {ticker}: {e}")
            return []

    async def extract_tickers_and_sentiment(
        self,
        articles: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Extrai tickers mencionados e sentiment usando Gemini NLP.

        Args:
            articles: Lista de artigos raw

        Returns:
            Lista de artigos tratados com tickers e sentiment
        """
        if not self.ai_gateway:
            logger.warning("AI Gateway not available, skipping NLP extraction")
            return []

        treated_articles = []

        for article in articles:
            try:
                title = article.get("title", "")
                description = article.get("description", "")
                text = f"{title}. {description}"

                # Prompt para Gemini
                prompt = f"""
Analise a seguinte notícia financeira e extraia:
1. Todos os tickers de ações mencionados (formato: AAPL, MSFT, etc.)
2. Sentiment geral (positive, negative, neutral)
3. Score de relevância (0-10) para trading

Notícia: "{text}"

Responda APENAS em JSON formato:
{{
  "tickers": ["TICKER1", "TICKER2"],
  "sentiment": "positive/negative/neutral",
  "relevance_score": 7.5,
  "key_points": "Resumo dos pontos principais"
}}
"""

                # Chamar Gemini com rate limiting (4s)
                from src.decision.ai_gateway import AIProvider

                response = await self.ai_gateway.complete(
                    prompt=prompt,
                    preferred_provider=AIProvider.GEMINI,
                    temperature=0.3,
                    max_tokens=300
                )

                # Sleep para rate limiting (Gemini Free Tier)
                await asyncio.sleep(4)

                if response.success and response.parsed_json:
                    analysis = response.parsed_json

                    treated_articles.append({
                        "title": title,
                        "url": article.get("url", ""),
                        "published": article.get("published", ""),
                        "source": article.get("source", ""),
                        "tickers": analysis.get("tickers", []),
                        "sentiment": analysis.get("sentiment", "neutral"),
                        "relevance_score": analysis.get("relevance_score", 5.0),
                        "key_points": analysis.get("key_points", "")
                    })

                    logger.debug(f"NLP extracted: {analysis.get('tickers', [])} from '{title[:50]}...'")

            except Exception as e:
                logger.error(f"Error processing article '{article.get('title', '')[:50]}...': {e}")
                continue

        logger.info(f"NLP extraction complete: {len(treated_articles)}/{len(articles)} articles processed")
        return treated_articles

    async def find_catalyst_news(
        self,
        keywords: List[str] = None
    ) -> List[NewsArticle]:
        """
        Busca notícias com catalisadores específicos.

        Args:
            keywords: Lista de keywords (earnings, FDA, merger, etc.)

        Returns:
            Lista de NewsArticle com catalisadores
        """
        if keywords is None:
            keywords = ["earnings", "FDA approval", "merger", "acquisition",
                        "partnership", "breakthrough", "guidance", "buyback"]

        catalyst_news = []

        try:
            from gnews import GNews

            google_news = GNews(language='en', max_results=20)

            for keyword in keywords:
                try:
                    # Buscar notícias por keyword
                    news = google_news.get_news_by_topic(keyword)

                    for item in news[:5]:  # Limitar a 5 por keyword
                        # Extrair tickers mencionados
                        title = item.get("title", "")

                        # Tentar extrair ticker do título (regex simples)
                        import re
                        ticker_pattern = r'\b([A-Z]{1,5})\b'
                        potential_tickers = re.findall(ticker_pattern, title)

                        # Filtrar tickers válidos (evitar palavras comuns)
                        common_words = {"CEO", "CFO", "IPO", "SEC", "FDA", "USA", "UK", "EU", "AI"}
                        tickers = [t for t in potential_tickers if t not in common_words and len(t) <= 5]

                        if tickers:
                            catalyst_news.append(NewsArticle(
                                title=title,
                                url=item.get("url", ""),
                                published_date=None,
                                source="GNews",
                                summary=item.get("description", ""),
                                tickers_mentioned=tickers,
                                sentiment=None,
                                relevance_score=8.0  # Alto score para catalysts
                            ))

                    await asyncio.sleep(2)  # Rate limiting

                except Exception as e:
                    logger.error(f"Error searching keyword '{keyword}': {e}")
                    continue

            logger.info(f"Catalyst scan: Found {len(catalyst_news)} relevant news")

        except Exception as e:
            logger.error(f"Error in catalyst news scan: {e}")

        return catalyst_news

    async def get_comprehensive_news(
        self,
        ticker: str,
        include_catalysts: bool = True
    ) -> Dict[str, Any]:
        """
        Busca notícias completas: GNews + tratamento NLP + catalysts.

        Args:
            ticker: Ticker do ativo
            include_catalysts: Incluir scan de catalisadores

        Returns:
            Dict com todas as notícias tratadas
        """
        result = {
            "ticker": ticker,
            "timestamp": datetime.now().isoformat(),
            "gnews_articles": [],
            "treated_articles": [],
            "catalyst_news": []
        }

        try:
            # 1. Buscar no GNews
            gnews_articles = await self.get_gnews(ticker, max_results=10)
            result["gnews_articles"] = gnews_articles

            # 2. Tratar com NLP (Gemini)
            if self.ai_gateway and gnews_articles:
                treated = await self.extract_tickers_and_sentiment(gnews_articles)
                result["treated_articles"] = treated

            # 3. Buscar catalisadores (opcional)
            if include_catalysts:
                catalysts = await self.find_catalyst_news()
                # Filtrar catalysts que mencionam o ticker
                ticker_catalysts = [
                    c for c in catalysts
                    if ticker in c.tickers_mentioned
                ]
                result["catalyst_news"] = [
                    {
                        "title": c.title,
                        "url": c.url,
                        "source": c.source,
                        "relevance_score": c.relevance_score
                    }
                    for c in ticker_catalysts
                ]

            logger.info(f"Comprehensive news for {ticker}: {len(result['gnews_articles'])} raw, "
                        f"{len(result['treated_articles'])} treated, "
                        f"{len(result['catalyst_news'])} catalysts")

        except Exception as e:
            logger.error(f"Error getting comprehensive news for {ticker}: {e}")

        return result
