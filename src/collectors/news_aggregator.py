"""
NEWS AGGREGATOR - Agregacao e Tratamento de Noticias
Combina GNews API + newspaper3k + Gemini NLP para extracao de tickers

Sistema de Scoring (2026-01-07):
- Fontes de investimento: score alto (1.0-1.5)
- Fontes de noticias gerais: score medio (0.8-1.0)
- Fontes desconhecidas: score baixo (0.5)
- Bonus para noticias do pais da empresa
- Penalidade para noticias antigas (>24h)
"""

import asyncio
import logging
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# === SISTEMA DE SCORING DE FONTES ===
# Fontes de investimento/financeiras premium (score 1.2-1.5)
# Fontes de noticias gerais (score 0.8-1.0)
# Fontes desconhecidas (score 0.5)

SOURCE_QUALITY_SCORES: Dict[str, float] = {
    # === TIER 1: FONTES PREMIUM DE INVESTIMENTO (1.3-1.5) ===
    # Global
    "reuters.com": 1.5,
    "bloomberg.com": 1.5,
    "wsj.com": 1.5,
    "ft.com": 1.4,  # Financial Times
    "cnbc.com": 1.4,
    "marketwatch.com": 1.4,
    "finance.yahoo.com": 1.3,
    "seekingalpha.com": 1.3,
    "investing.com": 1.3,
    "barrons.com": 1.3,
    "fool.com": 1.2,  # Motley Fool
    "benzinga.com": 1.2,
    "thestreet.com": 1.2,

    # === TIER 2: FONTES BRASILEIRAS DE INVESTIMENTO (1.3-1.5) ===
    "infomoney.com.br": 1.5,
    "valor.globo.com": 1.5,
    "exame.com": 1.4,
    "moneytimes.com.br": 1.4,
    "einvestidor.estadao.com.br": 1.3,
    "investnews.com.br": 1.3,
    "suno.com.br": 1.3,
    "seudinheiro.com": 1.2,
    "trademap.com.br": 1.2,
    "statusinvest.com.br": 1.2,
    "fundamentus.com.br": 1.2,
    "guiainvest.com.br": 1.2,
    "br.investing.com": 1.3,

    # === TIER 3: GRANDES PORTAIS DE NOTICIA (1.0-1.1) ===
    # Global
    "cnn.com": 1.1,
    "bbc.com": 1.1,
    "nytimes.com": 1.1,
    "forbes.com": 1.1,
    "businessinsider.com": 1.0,
    "techcrunch.com": 1.0,
    # Brasil
    "g1.globo.com": 1.1,
    "uol.com.br": 1.0,
    "folha.uol.com.br": 1.1,
    "estadao.com.br": 1.1,
    "oglobo.globo.com": 1.0,
    "terra.com.br": 0.9,
    "r7.com": 0.9,

    # === TIER 4: NOTICIAS GERAIS (0.7-0.9) ===
    "yahoo.com": 0.9,
    "google.com": 0.8,
    "msn.com": 0.8,
    "aol.com": 0.7,
}

# === MAPEAMENTO DE TICKERS PARA PAIS ===
# Usado para priorizar noticias do pais da empresa
TICKER_COUNTRY_MAP: Dict[str, str] = {
    # Brasil - B3
    "PETR4.SA": "BR", "PETR3.SA": "BR", "VALE3.SA": "BR", "ITUB4.SA": "BR",
    "BBDC4.SA": "BR", "WEGE3.SA": "BR", "B3SA3.SA": "BR", "RENT3.SA": "BR",
    "MGLU3.SA": "BR", "PRIO3.SA": "BR", "ABEV3.SA": "BR", "BBAS3.SA": "BR",
    "SUZB3.SA": "BR", "GGBR4.SA": "BR", "CSNA3.SA": "BR", "JBSS3.SA": "BR",
    # Brasil - ADRs
    "PBR": "BR", "VALE": "BR", "ITUB": "BR", "BBD": "BR", "NU": "BR", "XP": "BR",
    # USA - Default para tickers sem .SA
}

# Dominios por pais (para bonus de localizacao)
COUNTRY_DOMAINS: Dict[str, List[str]] = {
    "BR": [
        "infomoney.com.br", "valor.globo.com", "exame.com", "moneytimes.com.br",
        "g1.globo.com", "uol.com.br", "folha.uol.com.br", "estadao.com.br",
        "oglobo.globo.com", "br.investing.com", "suno.com.br", "investnews.com.br",
        "einvestidor.estadao.com.br", "seudinheiro.com", "trademap.com.br",
    ],
    "US": [
        "reuters.com", "bloomberg.com", "wsj.com", "cnbc.com", "marketwatch.com",
        "finance.yahoo.com", "seekingalpha.com", "benzinga.com", "thestreet.com",
        "cnn.com", "nytimes.com", "forbes.com", "businessinsider.com",
    ],
}

# === MAPEAMENTO DE NOMES DE EMPRESAS PARA TICKERS ===
# Permite detectar empresas mesmo quando o ticker não aparece no texto
COMPANY_TO_TICKER = {
    # Big Tech
    "apple": "AAPL", "microsoft": "MSFT", "google": "GOOGL", "alphabet": "GOOGL",
    "amazon": "AMZN", "meta": "META", "facebook": "META", "nvidia": "NVDA",
    "tesla": "TSLA",
    # Finance
    "jpmorgan": "JPM", "jp morgan": "JPM", "goldman": "GS", "goldman sachs": "GS",
    "bank of america": "BAC",
    # Healthcare
    "johnson & johnson": "JNJ", "j&j": "JNJ", "pfizer": "PFE", "eli lilly": "LLY",
    "unitedhealth": "UNH",
    # Consumer
    "walmart": "WMT", "home depot": "HD", "disney": "DIS", "nike": "NKE",
    "starbucks": "SBUX", "mcdonald": "MCD", "mcdonalds": "MCD",
    # Energy
    "exxon": "XOM", "exxonmobil": "XOM", "chevron": "CVX", "conocophillips": "COP",
    # Industrial
    "boeing": "BA", "caterpillar": "CAT", "general electric": "GE",
    # Semiconductors
    "amd": "AMD", "intel": "INTC", "qualcomm": "QCOM", "broadcom": "AVGO",
    "micron": "MU", "taiwan semi": "TSM", "tsmc": "TSM",
    # Software
    "salesforce": "CRM", "adobe": "ADBE", "oracle": "ORCL", "palantir": "PLTR",
    # Crypto/Popular
    "coinbase": "COIN", "microstrategy": "MSTR", "gamestop": "GME",
    # Brasil - ADRs
    "petrobras": "PBR", "vale": "VALE", "itau": "ITUB", "nubank": "NU", "xp inc": "XP",
    # Brasil - B3
    "magazine luiza": "MGLU3.SA", "magalu": "MGLU3.SA", "weg": "WEGE3.SA",
    "b3": "B3SA3.SA", "localiza": "RENT3.SA", "petro rio": "PRIO3.SA", "prio": "PRIO3.SA",
}

# === LISTA DE TICKERS VÁLIDOS PARA VALIDAÇÃO ===
# Tickers que podem ser extraídos de notícias (só aceita se estiver nesta lista)
VALID_TICKERS = {
    # USA - Big Tech
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "NVDA", "TSLA",
    # USA - Finance
    "JPM", "BAC", "GS", "WFC", "C", "MS",
    # USA - Healthcare
    "JNJ", "UNH", "PFE", "LLY", "ABBV", "MRK",
    # USA - Consumer
    "WMT", "HD", "DIS", "NKE", "SBUX", "MCD", "KO", "PEP",
    # USA - Energy
    "XOM", "CVX", "COP", "SLB", "EOG",
    # USA - Industrial
    "BA", "CAT", "GE", "HON", "UPS", "LMT",
    # USA - Tech/Semiconductors
    "AMD", "INTC", "QCOM", "AVGO", "MU", "TSM", "TXN", "AMAT",
    # USA - Software/Cloud
    "CRM", "ADBE", "ORCL", "NOW", "SNOW", "PLTR",
    # USA - Crypto/Volatil/Popular
    "COIN", "MSTR", "GME", "AMC", "HOOD",
    # USA - Other Large Cap
    "V", "MA", "PYPL", "SQ", "BRK.A", "BRK.B", "T", "VZ",
    # Brasil - ADRs
    "PBR", "VALE", "ITUB", "BBD", "NU", "XP",
    # Brasil - B3
    "PETR4.SA", "VALE3.SA", "ITUB4.SA", "BBDC4.SA", "WEGE3.SA",
    "B3SA3.SA", "RENT3.SA", "MGLU3.SA", "PRIO3.SA", "ABEV3.SA",
}


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
            config: Configuracoes do sistema
            ai_gateway: Gateway de IA para processamento (opcional)
        """
        self.config = config
        self.ai_gateway = ai_gateway

        # Configuracao de freshness (max idade em horas)
        self.max_news_age_hours = config.get("news", {}).get("max_age_hours", 48)

    def _extract_domain(self, url: str) -> str:
        """Extrai dominio de uma URL."""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            # Remover www.
            if domain.startswith("www."):
                domain = domain[4:]
            return domain
        except Exception:
            return ""

    def _get_source_score(self, url: str) -> float:
        """
        Retorna score de qualidade da fonte (0.5-1.5).
        Fontes premium de investimento: 1.3-1.5
        Fontes gerais: 0.8-1.0
        Desconhecidas: 0.5
        """
        domain = self._extract_domain(url)

        # Verificar score direto
        if domain in SOURCE_QUALITY_SCORES:
            return SOURCE_QUALITY_SCORES[domain]

        # Verificar subdomains (ex: economia.uol.com.br)
        for known_domain, score in SOURCE_QUALITY_SCORES.items():
            if domain.endswith(known_domain):
                return score

        # Fonte desconhecida
        return 0.5

    def _get_country_bonus(self, ticker: str, url: str) -> float:
        """
        Retorna bonus se noticia e do mesmo pais da empresa.
        Bonus: +0.3 se for do mesmo pais
        """
        # Determinar pais do ticker
        ticker_country = TICKER_COUNTRY_MAP.get(ticker.upper())
        if not ticker_country:
            # Default: BR se termina com .SA, senao US
            ticker_country = "BR" if ticker.upper().endswith(".SA") else "US"

        # Verificar se dominio e do pais do ticker
        domain = self._extract_domain(url)
        country_domains = COUNTRY_DOMAINS.get(ticker_country, [])

        for country_domain in country_domains:
            if domain.endswith(country_domain) or country_domain in domain:
                return 0.3  # Bonus de localizacao

        return 0.0

    def _parse_published_date(self, published_str: str) -> Optional[datetime]:
        """
        Parseia string de data de publicacao em varios formatos.
        """
        if not published_str:
            return None

        # Formatos comuns
        formats = [
            "%a, %d %b %Y %H:%M:%S %Z",  # "Mon, 06 Jan 2026 10:30:00 GMT"
            "%a, %d %b %Y %H:%M:%S %z",  # Com timezone offset
            "%Y-%m-%dT%H:%M:%SZ",         # ISO 8601
            "%Y-%m-%dT%H:%M:%S%z",        # ISO 8601 com timezone
            "%Y-%m-%d %H:%M:%S",          # Simples
            "%Y-%m-%d",                    # Apenas data
            "%d/%m/%Y %H:%M",             # BR format
            "%d/%m/%Y",                    # BR format sem hora
        ]

        for fmt in formats:
            try:
                return datetime.strptime(published_str.strip(), fmt)
            except ValueError:
                continue

        # Tentar parsear formatos relativos (ex: "2 hours ago")
        try:
            published_lower = published_str.lower()
            now = datetime.now()

            if "hour" in published_lower or "hora" in published_lower:
                match = re.search(r"(\d+)", published_str)
                if match:
                    hours = int(match.group(1))
                    return now - timedelta(hours=hours)

            if "minute" in published_lower or "minuto" in published_lower:
                match = re.search(r"(\d+)", published_str)
                if match:
                    minutes = int(match.group(1))
                    return now - timedelta(minutes=minutes)

            if "day" in published_lower or "dia" in published_lower:
                match = re.search(r"(\d+)", published_str)
                if match:
                    days = int(match.group(1))
                    return now - timedelta(days=days)

            if "yesterday" in published_lower or "ontem" in published_lower:
                return now - timedelta(days=1)

        except Exception:
            pass

        return None

    def _get_freshness_score(self, published_str: str) -> float:
        """
        Retorna score baseado na freshness da noticia.
        Noticias recentes: 1.0
        Noticias antigas: 0.3-0.8
        Sem data: 0.5
        """
        pub_date = self._parse_published_date(published_str)
        if not pub_date:
            return 0.5  # Sem data conhecida

        now = datetime.now()

        # Ajustar para timezone se necessario
        if pub_date.tzinfo:
            pub_date = pub_date.replace(tzinfo=None)

        age_hours = (now - pub_date).total_seconds() / 3600

        if age_hours < 0:
            # Data no futuro (provavelmente erro de parsing)
            return 0.5

        if age_hours <= 1:
            return 1.0  # Ultima hora
        elif age_hours <= 6:
            return 0.95  # Ultimas 6 horas
        elif age_hours <= 12:
            return 0.85  # Ultimas 12 horas
        elif age_hours <= 24:
            return 0.7  # Ultimo dia
        elif age_hours <= 48:
            return 0.5  # Ultimos 2 dias
        elif age_hours <= 72:
            return 0.3  # Ultimos 3 dias
        else:
            return 0.1  # Muito antiga

    def calculate_article_score(self, article: Dict[str, Any], ticker: str) -> float:
        """
        Calcula score total de um artigo combinando todos os fatores.

        Score = base_score * source_quality * freshness + country_bonus

        Args:
            article: Dicionario do artigo
            ticker: Ticker para verificar bonus de pais

        Returns:
            Score final (0-10)
        """
        url = article.get("url", "")
        published = article.get("published", "")
        title = article.get("title", "")[:50]

        # Componentes do score
        source_score = self._get_source_score(url)  # 0.5-1.5
        freshness_score = self._get_freshness_score(published)  # 0.1-1.0
        country_bonus = self._get_country_bonus(ticker, url)  # 0.0-0.3

        # Base score (5.0) * multipliers + bonus
        base = 5.0
        final_score = (base * source_score * freshness_score) + (country_bonus * 2)

        # Clamp entre 0 e 10
        final_score = max(0.0, min(10.0, final_score))

        # Log detalhado do scoring
        domain = self._extract_domain(url)
        logger.debug(
            f"[SCORE] {ticker} | {domain:25s} | "
            f"src={source_score:.2f} fresh={freshness_score:.2f} country={country_bonus:.1f} "
            f"-> FINAL={final_score:.2f} | {title}..."
        )

        return final_score

    def _is_news_fresh(self, published_str: str) -> bool:
        """Verifica se noticia esta dentro do limite de idade."""
        pub_date = self._parse_published_date(published_str)
        if not pub_date:
            return True  # Sem data, assume que e recente

        now = datetime.now()
        if pub_date.tzinfo:
            pub_date = pub_date.replace(tzinfo=None)

        age_hours = (now - pub_date).total_seconds() / 3600
        return age_hours <= self.max_news_age_hours

    async def get_gnews(self, ticker: str, max_results: int = 5, fetch_full_content: bool = False) -> List[Dict[str, Any]]:
        """
        Busca noticias do GNews API com scoring e filtragem inteligente.

        Funcionalidades:
        - Busca em ingles E no idioma do pais da empresa
        - Filtra noticias antigas (>48h por default)
        - Calcula score baseado em: fonte, freshness, pais
        - Ordena por score (melhores primeiro)

        Args:
            ticker: Ticker do ativo
            max_results: Numero maximo de resultados
            fetch_full_content: Se True, faz scrape completo do artigo (mais lento)

        Returns:
            Lista de artigos ordenados por score (dicts)
        """
        try:
            from gnews import GNews  # type: ignore

            # Determinar pais do ticker para busca localizada
            is_brazilian = ticker.upper().endswith(".SA") or ticker.upper() in ["PBR", "VALE", "ITUB", "BBD", "NU", "XP"]

            all_articles = []

            # Buscar mais do que o necessario (para filtrar depois)
            fetch_count = max_results * 3

            # Busca 1: Ingles (global)
            try:
                google_news_en = GNews(language='en', country='US', max_results=fetch_count)
                news_en = google_news_en.get_news(ticker) or []
                for item in news_en:
                    all_articles.append({
                        "title": item.get("title", ""),
                        "url": item.get("url", ""),
                        "published": item.get("published date", ""),
                        "description": item.get("description", ""),
                        "source": item.get("publisher", {}).get("title", "GNews"),
                        "language": "en"
                    })
            except Exception as e:
                logger.debug(f"GNews EN failed for {ticker}: {e}")

            # Busca 2: Portugues (se ticker brasileiro)
            if is_brazilian:
                try:
                    google_news_pt = GNews(language='pt', country='BR', max_results=fetch_count)
                    # Buscar por nome da empresa tambem
                    search_terms = [ticker]
                    if ticker == "PETR4.SA" or ticker == "PETR3.SA":
                        search_terms.append("Petrobras")
                    elif ticker == "VALE3.SA" or ticker == "VALE":
                        search_terms.append("Vale mineradora")
                    elif ticker == "ITUB4.SA" or ticker == "ITUB":
                        search_terms.append("Itau Unibanco")

                    for term in search_terms:
                        news_pt = google_news_pt.get_news(term) or []
                        for item in news_pt:
                            all_articles.append({
                                "title": item.get("title", ""),
                                "url": item.get("url", ""),
                                "published": item.get("published date", ""),
                                "description": item.get("description", ""),
                                "source": item.get("publisher", {}).get("title", "GNews-BR"),
                                "language": "pt"
                            })
                except Exception as e:
                    logger.debug(f"GNews PT failed for {ticker}: {e}")

            # Remover duplicatas (por URL)
            seen_urls = set()
            unique_articles = []
            for art in all_articles:
                url = art.get("url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    unique_articles.append(art)

            # Filtrar por freshness
            fresh_articles = [
                art for art in unique_articles
                if self._is_news_fresh(art.get("published", ""))
            ]

            # Calcular score para cada artigo
            scored_articles = []
            for art in fresh_articles:
                score = self.calculate_article_score(art, ticker)
                art["relevance_score"] = round(score, 2)
                art["source_quality"] = round(self._get_source_score(art.get("url", "")), 2)
                art["freshness_score"] = round(self._get_freshness_score(art.get("published", "")), 2)
                scored_articles.append(art)

            # Ordenar por score (maior primeiro)
            scored_articles.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)

            # Pegar top results
            top_articles = scored_articles[:max_results]

            # Buscar conteudo completo se solicitado
            if fetch_full_content:
                for art in top_articles:
                    if art.get("url"):
                        full_content = await self._scrape_article_content(art["url"])
                        art["full_content"] = full_content if full_content else ""

            # Log detalhado do resultado final
            if top_articles:
                best = top_articles[0]
                logger.info(
                    f"[NEWS] {ticker}: {len(top_articles)}/{len(unique_articles)} artigos "
                    f"(filtrados de {len(all_articles)} brutos) | "
                    f"Best: {best.get('relevance_score', 0):.1f} pts de {self._extract_domain(best.get('url', ''))}"
                )
                # Log resumo dos top artigos selecionados
                for i, art in enumerate(top_articles[:3], 1):
                    logger.info(
                        f"  [{i}] Score={art.get('relevance_score', 0):.1f} | "
                        f"{self._extract_domain(art.get('url', '')):20s} | "
                        f"{art.get('title', '')[:60]}..."
                    )
            else:
                logger.info(f"[NEWS] {ticker}: Nenhum artigo fresco encontrado (max_age={self.max_news_age_hours}h)")

            return top_articles

        except Exception as e:
            logger.error(f"Error fetching GNews for {ticker}: {e}")
            return []

    def _decode_google_news_url(self, google_url: str) -> str:
        """
        Decodifica URL do Google News para URL real do artigo.

        O GNews retorna URLs no formato:
        https://news.google.com/rss/articles/CBMi[protobuf_base64]...

        A URL real está codificada em Protocol Buffers + base64.
        """
        if 'news.google.com' not in google_url:
            return google_url

        try:
            from googlenewsdecoder import new_decoderv1
            decoded = new_decoderv1(google_url)
            if decoded and decoded.get('decoded_url'):
                return decoded['decoded_url']
        except ImportError:
            logger.debug("googlenewsdecoder not installed, using original URL")
        except Exception as e:
            logger.debug(f"Failed to decode Google News URL: {e}")

        return google_url

    async def _scrape_article_content(self, url: str, max_chars: int = 2000) -> str:
        """
        Faz scrape do conteúdo completo de um artigo.

        Usa múltiplos métodos em ordem de preferência:
        1. cloudscraper (bypass anti-bot) + trafilatura (extração)
        2. trafilatura direto
        3. newspaper3k como fallback

        Args:
            url: URL do artigo (pode ser URL do Google News)
            max_chars: Máximo de caracteres a retornar

        Returns:
            Texto do artigo (truncado se necessário)
        """
        # Primeiro, decodificar URL do Google News se necessário
        real_url = self._decode_google_news_url(url)
        if real_url != url:
            logger.debug(f"Decoded Google URL: {url[:50]}... -> {real_url[:50]}...")

        content = ""

        # Método 1: cloudscraper + trafilatura (mais robusto)
        try:
            import cloudscraper
            import trafilatura

            scraper = cloudscraper.create_scraper(
                browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
            )
            response = scraper.get(real_url, timeout=20)

            if response.status_code == 200:
                content = trafilatura.extract(response.text) or ""
                if content:
                    logger.debug(f"Scraped {len(content)} chars via cloudscraper+trafilatura")

        except ImportError:
            logger.debug("cloudscraper/trafilatura not installed, trying alternatives")
        except Exception as e:
            logger.debug(f"cloudscraper failed: {e}")

        # Método 2: trafilatura direto (se cloudscraper falhou)
        if not content:
            try:
                import trafilatura
                downloaded = trafilatura.fetch_url(real_url)
                if downloaded:
                    content = trafilatura.extract(downloaded) or ""
                    if content:
                        logger.debug(f"Scraped {len(content)} chars via trafilatura direct")
            except ImportError:
                pass
            except Exception as e:
                logger.debug(f"trafilatura direct failed: {e}")

        # Método 3: newspaper3k como fallback
        if not content:
            try:
                from newspaper import Article, Config

                config = Config()
                config.browser_user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                config.request_timeout = 15

                article = Article(real_url, config=config)
                article.download()
                article.parse()
                content = article.text or ""

                if content:
                    logger.debug(f"Scraped {len(content)} chars via newspaper3k")

            except Exception as e:
                logger.debug(f"newspaper3k failed: {e}")

        # Truncar se muito longo
        if content and len(content) > max_chars:
            content = content[:max_chars] + "..."

        return content

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
                                # === NOVA LÓGICA DE EXTRAÇÃO DE TICKERS ===
                                text_to_scan = f"{title} {description}"
                                text_lower = text_to_scan.lower()
                                found_tickers = set()

                                # 1. PRIMEIRO: Buscar NOMES de empresas (mais confiável)
                                for company_name, ticker in COMPANY_TO_TICKER.items():
                                    if company_name in text_lower:
                                        found_tickers.add(ticker)
                                        logger.debug(f"[CATALYST] Found '{company_name}' -> {ticker}")

                                # 2. SEGUNDO: Extrair tickers com padrões específicos
                                ticker_patterns = [
                                    r'\(([A-Z]{2,5})\)',  # (AAPL)
                                    r'([A-Z]{2,5})(?:\s+stock|\s+shares)',  # AAPL stock
                                    r'\$([A-Z]{2,5})\b',  # $AAPL
                                    r'([A-Z]{3,5}[0-9])\.SA\b',  # PETR4.SA
                                    r'\b([A-Z]{3,5}[0-9])\b',  # PETR4, VALE3
                                ]
                                for pattern in ticker_patterns:
                                    matches = re.findall(pattern, text_to_scan)
                                    for m in matches:
                                        # Validar contra lista de tickers conhecidos
                                        if m in VALID_TICKERS:
                                            found_tickers.add(m)
                                        elif f"{m}.SA" in VALID_TICKERS:
                                            found_tickers.add(f"{m}.SA")

                                # 3. TERCEIRO: Buscar tickers conhecidos diretamente no texto
                                for valid_ticker in VALID_TICKERS:
                                    # Buscar ticker exato (com word boundary)
                                    base_ticker = valid_ticker.replace(".SA", "")
                                    if re.search(rf'\b{re.escape(base_ticker)}\b', text_to_scan):
                                        found_tickers.add(valid_ticker)

                                tickers = list(found_tickers)

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
