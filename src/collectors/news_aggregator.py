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

    async def get_gnews(self, ticker: str, max_results: int = 5, fetch_full_content: bool = False) -> List[Dict[str, Any]]:
        """
        Busca notícias do GNews API.

        Args:
            ticker: Ticker do ativo
            max_results: Número máximo de resultados
            fetch_full_content: Se True, faz scrape completo do artigo (mais lento)

        Returns:
            Lista de artigos (dicts)
        """
        try:
            from gnews import GNews  # type: ignore

            google_news = GNews(language='en', max_results=max_results)
            news = google_news.get_news(ticker)

            articles = []
            for item in news:
                article_data = {
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "published": item.get("published date", ""),
                    "description": item.get("description", ""),
                    "source": "GNews",
                    "full_content": ""
                }

                # Scrape conteúdo completo se solicitado (para o Judge)
                if fetch_full_content and article_data["url"]:
                    full_content = await self._scrape_article_content(article_data["url"])
                    if full_content:
                        article_data["full_content"] = full_content

                articles.append(article_data)

            logger.info(f"GNews: Found {len(articles)} articles for {ticker}")
            return articles

        except Exception as e:
            logger.error(f"Error fetching GNews for {ticker}: {e}")
            return []

    async def _scrape_article_content(self, url: str, max_chars: int = 2000) -> str:
        """
        Faz scrape do conteúdo completo de um artigo usando newspaper3k.

        Args:
            url: URL do artigo
            max_chars: Máximo de caracteres a retornar

        Returns:
            Texto do artigo (truncado se necessário)
        """
        try:
            from newspaper import Article

            article = Article(url)
            article.download()
            article.parse()

            # Combinar título + texto
            content = article.text or ""

            # Truncar se muito longo
            if len(content) > max_chars:
                content = content[:max_chars] + "..."

            return content

        except Exception as e:
            logger.debug(f"Failed to scrape {url}: {e}")
            return ""

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
        keywords: Optional[List[str]] = None
    ) -> List[NewsArticle]:
        """
        Busca notícias com catalisadores específicos.

        Args:
            keywords: Lista de keywords para filtrar nos títulos (earnings, FDA, merger, etc.)

        Returns:
            Lista de NewsArticle com catalisadores
        """
        if keywords is None:
            # Keywords EXPANDIDAS - Inglês e Português
            keywords = [
                # === INGLÊS ===
                # Earnings/Resultados
                "earnings", "revenue", "profit", "loss", "quarterly", "annual",
                "beats", "misses", "outlook", "forecast", "guidance",
                # Regulatório
                "FDA", "approval", "SEC", "investigation", "regulatory",
                # M&A
                "merger", "acquisition", "deal", "buyout", "takeover", "bid",
                # Mercado - movimentos
                "surges", "plunges", "jumps", "drops", "rallies", "tumbles",
                "soars", "crashes", "spikes", "falls", "rises", "gains",
                # Analistas
                "upgrade", "downgrade", "target", "rating", "buy", "sell", "hold",
                # Corporativo
                "partnership", "breakthrough", "buyback", "announces", "launches",
                "dividend", "split", "IPO", "offering", "stake",
                # === PORTUGUÊS (Brasil) ===
                # Resultados
                "lucro", "prejuizo", "receita", "resultado", "trimestral", "anual",
                "balanço", "balanco", "dividendo", "proventos",
                # Mercado
                "dispara", "despenca", "sobe", "cai", "alta", "queda", "recorde",
                "valoriza", "desvaloriza", "avança", "recua",
                # Corporativo
                "fusão", "fusao", "aquisição", "aquisicao", "parceria", "acordo",
                "oferta", "compra", "venda", "ações", "acoes",
                # Regulatório BR
                "CVM", "Bacen", "BNDES", "Petrobras", "Vale", "Itau", "Bradesco",
                # Setores BR
                "Bovespa", "B3", "Ibovespa", "real", "dólar", "dolar"
            ]

        catalyst_news = []

        try:
            from gnews import GNews  # type: ignore
            import re

            # === BUSCA EM INGLÊS ===
            google_news_en = GNews(language='en', country='US', max_results=15)

            # === BUSCA EM PORTUGUÊS (Brasil) ===
            google_news_pt = GNews(language='pt', country='BR', max_results=15)

            # Configurações de busca por idioma
            search_configs = [
                {"gnews": google_news_en, "topics": ["BUSINESS", "TECHNOLOGY"], "lang": "EN"},
                {"gnews": google_news_pt, "topics": ["BUSINESS", "TECHNOLOGY"], "lang": "PT-BR"},
            ]

            total_configs = len(search_configs)

            total_scanned = 0
            total_found = 0

            for config_idx, config in enumerate(search_configs, 1):
                gnews = config["gnews"]
                topics = config["topics"]
                lang = config["lang"]

                for topic in topics:
                    try:
                        # Progress bar que sobrescreve a linha
                        print(f"\r[CATALYST] {lang}/{topic} - Buscando artigos...    ", end="", flush=True)

                        # Buscar notícias por TÓPICO válido
                        news = gnews.get_news_by_topic(topic)
                        articles_to_scan = news[:15]  # Top 15 de cada tópico
                        total_articles = len(articles_to_scan)

                        for article_idx, item in enumerate(articles_to_scan, 1):
                            total_scanned += 1
                            print(f"\r[CATALYST] {lang}/{topic} - {article_idx}/{total_articles} artigos | Total: {total_scanned} scanned, {total_found} found    ", end="", flush=True)

                            title = item.get("title", "")
                            description = item.get("description", "")
                            full_text = f"{title} {description}".lower()

                            # Filtrar por keywords nos títulos/descrições
                            has_catalyst = any(keyword.lower() in full_text for keyword in keywords)

                            if has_catalyst:
                                # Extrair tickers do TÍTULO E DESCRIÇÃO (não só título)
                                text_to_scan = f"{title} {description}"

                                # Padrões para extrair tickers
                                ticker_patterns = [
                                    r'\(([A-Z]{2,5})\)',  # (AAPL)
                                    r'([A-Z]{2,5})(?:\s+stock|\s+shares)',  # AAPL stock
                                    r'([A-Z]{3,5}[0-9])',  # PETR4, VALE3 (Brasil)
                                    r'\b([A-Z]{2,5})\b'  # AAPL (qualquer palavra maiúscula)
                                ]
                                potential_tickers = []
                                for pattern in ticker_patterns:
                                    potential_tickers.extend(re.findall(pattern, text_to_scan))

                                # Lista de não-tickers (siglas comuns)
                                non_tickers = {
                                    # Corporate
                                    "CEO", "CFO", "CTO", "COO", "CMO", "CIO", "IPO",
                                    # Government/Regulatory
                                    "SEC", "FDA", "FTC", "FCC", "EPA", "IRS", "DOJ", "FBI",
                                    "CVM", "BC", "PIB",
                                    # Financial Terms
                                    "ETF", "ESG", "NYSE", "NASDAQ", "DOW", "GDP", "CPI",
                                    # Geography
                                    "USA", "UK", "EU", "US", "UAE", "APAC", "BR", "EUA",
                                    # Media
                                    "CNN", "BBC", "FOX", "HBO", "UOL",
                                    # Sports
                                    "NFL", "NBA", "MLB", "NHL", "UFC", "FIFA",
                                    # International Orgs
                                    "NATO", "UN", "WHO", "WTO", "OPEC", "IMF",
                                    # Tech
                                    "AI", "ML", "AR", "VR", "IOT", "API", "SDK",
                                    # Common English
                                    "THE", "AND", "FOR", "WITH", "FROM", "AT", "ON", "IN",
                                    "NEW", "SAYS", "AMID", "AFTER", "JUST", "NEWS", "CEO",
                                    "WHY", "HOW", "WHEN", "WHERE", "WHO", "WHAT",
                                    # Common Portuguese
                                    "COM", "POR", "PARA", "QUE", "NAO", "MAIS", "COMO",
                                    "SOBRE", "APOS", "PODE", "DIZ", "VER", "SER", "TEM"
                                }

                                # Filtrar e validar
                                tickers = [
                                    t for t in set(potential_tickers)
                                    if t not in non_tickers and 2 <= len(t) <= 6
                                ]

                                if tickers:
                                    total_found += 1
                                    catalyst_news.append(NewsArticle(
                                        title=title,
                                        url=item.get("url", ""),
                                        published_date=None,
                                        source=f"GNews-{lang}-{topic}",
                                        summary=description,
                                        tickers_mentioned=tickers,
                                        sentiment=None,
                                        relevance_score=8.0
                                    ))

                        await asyncio.sleep(1)  # Rate limiting entre tópicos

                    except Exception as e:
                        logger.debug(f"Error fetching {lang}/{topic}: {e}")
                        continue

                await asyncio.sleep(2)  # Rate limiting entre idiomas

            print()  # Nova linha após progress bar
            logger.info(f"[CATALYST] Completo: {total_found} noticias de {total_scanned} artigos (EN + PT-BR)")

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
