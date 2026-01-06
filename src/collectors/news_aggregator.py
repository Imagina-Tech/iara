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
            keywords: Lista de keywords para filtrar nos títulos (earnings, FDA, merger, etc.)

        Returns:
            Lista de NewsArticle com catalisadores
        """
        if keywords is None:
            # Keywords para filtrar nos títulos/descrições
            keywords = ["earnings", "FDA", "approval", "merger", "acquisition",
                        "partnership", "breakthrough", "guidance", "buyback", "announces"]

        catalyst_news = []

        try:
            from gnews import GNews
            import re

            google_news = GNews(language='en', max_results=10)

            # TÓPICOS VÁLIDOS do GNews (não keywords!)
            # Usar apenas tópicos financeiros/business relevantes
            topics = ["BUSINESS", "FINANCE", "TECHNOLOGY"]
            total_topics = len(topics)

            for topic_idx, topic in enumerate(topics, 1):
                try:
                    logger.info(f"[CATALYST] {topic_idx}/{total_topics} - Buscando em {topic}...")

                    # Buscar notícias por TÓPICO válido
                    news = google_news.get_news_by_topic(topic)
                    articles_to_scan = news[:10]  # Top 10 de cada tópico
                    total_articles = len(articles_to_scan)

                    logger.info(f"[CATALYST] {topic}: {total_articles} artigos encontrados, analisando...")

                    for article_idx, item in enumerate(articles_to_scan, 1):
                        title = item.get("title", "")
                        description = item.get("description", "")
                        full_text = f"{title} {description}".lower()

                        # Log progress every article
                        article_progress = (article_idx / total_articles) * 100
                        logger.debug(f"[CATALYST] {topic} - Artigo {article_idx}/{total_articles} ({article_progress:.0f}%): {title[:60]}...")

                        # Filtrar por keywords nos títulos/descrições
                        has_catalyst = any(keyword.lower() in full_text for keyword in keywords)

                        if has_catalyst:
                            # Extrair tickers mencionados do título
                            # Buscar padrões comuns: (TICKER), TICKER:, ou TICKER isolado
                            ticker_patterns = [
                                r'\(([A-Z]{2,5})\)',  # (AAPL)
                                r'([A-Z]{2,5})(?:\s+stock|\s+shares)',  # AAPL stock
                                r'\b([A-Z]{2,5})\b'  # AAPL (qualquer palavra maiúscula)
                            ]
                            potential_tickers = []
                            for pattern in ticker_patterns:
                                potential_tickers.extend(re.findall(pattern, title))

                            # Lista expandida de não-tickers (siglas, eventos, mídias, palavras comuns)
                            non_tickers = {
                                # Corporate
                                "CEO", "CFO", "CTO", "COO", "CMO", "CIO", "IPO", "M&A",
                                # Government/Regulatory
                                "SEC", "FDA", "FTC", "FCC", "EPA", "IRS", "DOJ", "FBI",
                                # Financial Terms
                                "ETF", "ESG", "NYSE", "NASDAQ", "DOW", "S&P", "GDP", "CPI",
                                # Geography
                                "USA", "UK", "EU", "US", "UAE", "UAE", "APAC",
                                # Media/Events
                                "CES", "NBC", "CBS", "ABC", "CNN", "BBC", "FOX", "HBO", "MTV",
                                "NFL", "NBA", "MLB", "NHL", "UFC", "FIFA", "NCAA", "PGA", "WWE",
                                # International Orgs
                                "NATO", "UN", "WHO", "WTO", "OPEC", "IMF", "ASEAN", "BRICS",
                                # Tech/Trends
                                "AI", "ML", "AR", "VR", "IOT", "API", "SDK", "OS", "IT",
                                # Common Words
                                "THE", "AND", "FOR", "WITH", "FROM", "TO", "AT", "ON", "IN",
                                "NEW", "SAYS", "AMID", "AFTER", "BEFORE", "JUST", "LIVE", "NEWS",
                                "HERE", "WHAT", "WHY", "HOW", "WHEN", "WHERE", "WHO",
                                # Energy/Commodities (not stocks)
                                "OIL", "GAS", "GOLD"
                            }

                            # Filtrar e validar
                            tickers = [
                                t for t in set(potential_tickers)  # Remove duplicados
                                if t not in non_tickers and 2 <= len(t) <= 5
                            ]

                            if tickers:
                                logger.info(f"[CATALYST] ✓ Encontrado: {tickers} em '{title[:50]}...'")
                                catalyst_news.append(NewsArticle(
                                    title=title,
                                    url=item.get("url", ""),
                                    published_date=None,
                                    source=f"GNews-{topic}",
                                    summary=description,
                                    tickers_mentioned=tickers,
                                    sentiment=None,
                                    relevance_score=8.0  # Alto score para catalysts
                                ))

                    await asyncio.sleep(2)  # Rate limiting entre tópicos

                except Exception as e:
                    logger.debug(f"Error fetching topic '{topic}': {e}")
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
