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
import json
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

# === MAPEAMENTO DE TICKERS - USA TICKER REGISTRY CENTRALIZADO ===
# Importar do registro centralizado (fonte unica de verdade)
from src.utils.ticker_registry import TickerRegistry

def _get_ticker_country(ticker: str) -> str:
    """Obtem pais do ticker via TickerRegistry."""
    return TickerRegistry.get_country(ticker)

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
# Usa TickerRegistry centralizado (fonte unica de verdade)
COMPANY_TO_TICKER = TickerRegistry.get_company_mapping()

# === LISTA DE TICKERS VÁLIDOS PARA VALIDAÇÃO ===
# Usa TickerRegistry centralizado (fonte unica de verdade)
VALID_TICKERS = TickerRegistry.get_valid_tickers_set()


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


# === TICKER RESOLVER - Obtem nome da empresa dinamicamente ===
class GeminiNewsValidator:
    """
    Valida se noticias sao relevantes usando Gemini.
    Suporta dois modos:
    1. Single ticker: valida se artigos sao sobre um ticker especifico
    2. Multi ticker: valida quais dos tickers propostos em cada artigo sao validos

    Rate Limiting:
    - Paid tier: 2000 RPM
    - Delay de 1s entre chamadas
    - Retry com backoff em caso de 429
    """

    MIN_DELAY = 1.0  # Segundos entre chamadas
    BATCH_SIZE = 15  # Artigos por batch no validate_all

    # Estado global
    _semaphore: Optional[asyncio.Semaphore] = None
    _last_call_time: float = 0

    @classmethod
    def _get_semaphore(cls) -> asyncio.Semaphore:
        """Retorna semaphore singleton (max 1 chamada por vez)."""
        if cls._semaphore is None:
            cls._semaphore = asyncio.Semaphore(1)
        return cls._semaphore

    @classmethod
    def _parse_json_response(cls, text: str) -> List[Dict]:
        """Parseia resposta JSON do Gemini, removendo markdown se necessario.
        Uses brace-counting for robust extraction."""
        text = text.strip()

        # Strategy 1: Remove markdown code block wrapper
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()

        # Strategy 2: Try direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Strategy 3: Brace/bracket counting for [ ... ] or { ... }
        for open_char, close_char in [("[", "]"), ("{", "}")]:
            start = text.find(open_char)
            if start >= 0:
                depth = 0
                for i in range(start, len(text)):
                    if text[i] == open_char:
                        depth += 1
                    elif text[i] == close_char:
                        depth -= 1
                    if depth == 0:
                        result = json.loads(text[start:i + 1])
                        if isinstance(result, dict):
                            return [result]
                        return result

        raise json.JSONDecodeError("No valid JSON found", text, 0)

    @classmethod
    async def _call_gemini(cls, prompt: str, max_output_tokens: int = 3000) -> Optional[str]:
        """
        Faz uma chamada ao Gemini com rate limiting e retry.
        Retorna o texto da resposta ou None em caso de erro.
        """
        import os
        import time

        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            logger.debug("[GeminiValidator] No API key")
            return None

        async with cls._get_semaphore():
            # Garantir delay minimo entre chamadas (recalculate inside semaphore)
            now = time.time()
            elapsed = now - cls._last_call_time
            if elapsed < cls.MIN_DELAY:
                await asyncio.sleep(cls.MIN_DELAY - elapsed)
            # Update timestamp BEFORE call (prevents concurrent requests during slow calls)
            cls._last_call_time = time.time()

            # Retry com backoff exponencial
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    from google import genai
                    from google.genai import types

                    client = genai.Client(api_key=api_key)

                    # Disable thinking for structured JSON output (gemini-2.5+ thinking
                    # tokens count against max_output_tokens budget)
                    gen_config = types.GenerateContentConfig(
                        temperature=0.1,
                        max_output_tokens=max_output_tokens,
                        thinking_config=types.ThinkingConfig(thinking_budget=0)
                    )

                    # Run sync Gemini call in executor to not block the event loop
                    loop = asyncio.get_running_loop()
                    response = await loop.run_in_executor(
                        None,
                        lambda: client.models.generate_content(
                            model="gemini-2.5-flash",
                            contents=prompt,
                            config=gen_config
                        )
                    )

                    cls._last_call_time = time.time()

                    if not response.text:
                        raise ValueError("Empty response from Gemini")

                    return response.text

                except Exception as e:
                    error_str = str(e).lower()
                    if "429" in str(e) or "resource exhausted" in error_str or "quota" in error_str:
                        backoff = (2 ** attempt) * 5
                        logger.warning(f"[GeminiValidator] Rate limited, waiting {backoff}s (attempt {attempt + 1}/{max_retries})")
                        await asyncio.sleep(backoff)
                        continue

                    logger.warning(f"[GeminiValidator] Error: {type(e).__name__}: {e}")
                    return None

            logger.warning(f"[GeminiValidator] All retries failed")
            return None

    @classmethod
    async def validate_single_ticker(
        cls,
        ticker: str,
        company_name: str,
        articles: List[Dict[str, Any]]
    ) -> List[Tuple[bool, float, str]]:
        """
        Valida se artigos sao sobre UM ticker especifico.
        Usado pelo get_gnews() quando busca noticias de um ticker.

        Args:
            ticker: Ticker do ativo (ex: PBR, AAPL)
            company_name: Nome da empresa (ex: Petrobras, Apple)
            articles: Lista de dicts com 'title' e 'description'

        Returns:
            Lista de tuples (is_relevant, confidence, reason)
        """
        if not articles:
            return []

        # Construir prompt
        articles_text = ""
        for i, art in enumerate(articles):
            title = art.get("title", "")[:150]
            desc = art.get("description", "")[:100]
            articles_text += f'\n[{i}] Title: "{title}"'
            if desc:
                articles_text += f'\n    Desc: "{desc}"'

        prompt = f"""You are a financial news filter. Analyze if these articles are about {company_name} (stock ticker: {ticker}).

ARTICLES:{articles_text}

Return a JSON array with one object per article:
[{{"id": 0, "relevant": true/false, "confidence": 0.0-1.0, "reason": "brief"}}, ...]

FILTERING RULES (BE STRICT):
- relevant=true: Article specifically mentions or is about {company_name} the company
- relevant=false: Article is about something else that happens to share the ticker symbol
- relevant=false: "PBR" as Professional Bull Riders (rodeo) is NOT Petrobras
- relevant=false: Generic market/sector news without specific {company_name} mention
- relevant=false: News about other companies (Exxon, Shell, etc.) even if same sector

Return EXACTLY {len(articles)} objects. JSON array only, no other text."""

        response_text = await cls._call_gemini(prompt)
        if not response_text:
            return [(True, 0.5, "api_error") for _ in articles]

        try:
            results = cls._parse_json_response(response_text)
            if not isinstance(results, list):
                return [(True, 0.5, "parse_error") for _ in articles]

            output = []
            for i, art in enumerate(articles):
                result = next((r for r in results if r.get("id") == i), None)
                if result is None and i < len(results):
                    result = results[i]

                if result:
                    is_relevant = result.get("relevant", True)
                    confidence = result.get("confidence", 0.5)
                    reason = result.get("reason", "")

                    if not is_relevant:
                        logger.info(f"[GeminiValidator] FILTERED: '{art.get('title', '')[:40]}...' - {reason}")

                    output.append((is_relevant, confidence, reason))
                else:
                    output.append((True, 0.5, "no_result"))

            return output

        except json.JSONDecodeError as e:
            logger.warning(f"[GeminiValidator] JSON parse error: {e}")
            return [(True, 0.5, "json_error") for _ in articles]

    @classmethod
    async def validate_multi_ticker(
        cls,
        articles: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Valida artigos com MULTIPLOS tickers propostos em UMA unica chamada.
        Usado pelo find_catalyst_news() para validar catalysts.

        Args:
            articles: Lista de dicts com 'title', 'description'/'summary', 'tickers'

        Returns:
            Lista de dicts com 'valid_tickers', 'confidence', 'reason' adicionados
        """
        if not articles:
            return []

        # Construir prompt com contexto de empresas
        articles_text = ""
        ticker_names: Dict[str, str] = {}

        for i, art in enumerate(articles):
            title = art.get("title", "")[:120]
            desc = (art.get("description") or art.get("summary") or "")[:80]
            tickers = art.get("tickers", [])

            # Obter nomes das empresas
            ticker_context = []
            for t in tickers:
                if t not in ticker_names:
                    info = TickerResolver.get_company_info(t)
                    ticker_names[t] = info.get("name", "") or t
                ticker_context.append(f"{t}={ticker_names[t]}")

            articles_text += f'\n[{i}] Title: "{title}"'
            if desc:
                articles_text += f'\n    Desc: "{desc}"'
            articles_text += f'\n    Proposed: {", ".join(tickers)}'
            articles_text += f'\n    Companies: {", ".join(ticker_context)}'

        prompt = f"""You are a financial news filter. For each article, analyze which of the PROPOSED tickers are actually relevant.

ARTICLES:{articles_text}

Return a JSON array with one object per article:
[{{"id": 0, "valid_tickers": ["AAPL"], "confidence": 0.95, "reason": "brief"}}, ...]

FILTERING RULES (BE STRICT):
- valid_tickers: Only include tickers where the article SPECIFICALLY mentions that company
- confidence: 0.0-1.0 how confident you are
- "PBR" as Professional Bull Riders (rodeo) is NOT Petrobras - exclude PBR
- "Wegovy" (obesity drug by Novo Nordisk) is NOT WEG motors - exclude WEGE3.SA
- "Axsome Therapeutics" is NOT PetroRio oil - exclude PRIO3.SA
- Generic market/sector news without specific company mention = empty valid_tickers
- News about other companies in same sector = empty valid_tickers
- Empty valid_tickers means article should be filtered out

Return EXACTLY {len(articles)} objects. JSON array only, no other text."""

        response_text = await cls._call_gemini(prompt)
        if not response_text:
            # Em caso de erro, retorna todos os artigos sem modificar
            return articles

        try:
            results = cls._parse_json_response(response_text)
            if not isinstance(results, list):
                return articles

            validated = []
            for i, art in enumerate(articles):
                result = next((r for r in results if r.get("id") == i), None)
                if result is None and i < len(results):
                    result = results[i]

                if result:
                    valid_tickers = result.get("valid_tickers", [])
                    confidence = result.get("confidence", 0.5)
                    reason = result.get("reason", "")

                    if valid_tickers:
                        art["valid_tickers"] = valid_tickers
                        art["confidence"] = confidence
                        validated.append(art)
                    else:
                        logger.info(f"[GeminiValidator] FILTERED: '{art.get('title', '')[:40]}...' - {reason}")
                else:
                    validated.append(art)

            return validated

        except json.JSONDecodeError as e:
            logger.warning(f"[GeminiValidator] JSON parse error: {e}")
            return articles

    # Alias para compatibilidade
    @classmethod
    async def validate_batch(cls, ticker: str, company_name: str, articles: List[Dict[str, Any]]) -> List[Tuple[bool, float, str]]:
        """Alias para validate_single_ticker (compatibilidade)."""
        return await cls.validate_single_ticker(ticker, company_name, articles)

    @classmethod
    async def validate_all(
        cls,
        ticker: str,
        company_name: str,
        articles: List[Dict[str, Any]]
    ) -> List[Tuple[bool, float, str]]:
        """
        Valida TODOS os artigos, dividindo em batches automaticamente.

        Args:
            ticker: Ticker do ativo
            company_name: Nome da empresa
            articles: Lista de artigos

        Returns:
            Lista de tuples (is_relevant, confidence, reason)
        """
        if not articles:
            return []

        all_results = []
        total_batches = (len(articles) + cls.BATCH_SIZE - 1) // cls.BATCH_SIZE

        for batch_num in range(total_batches):
            start_idx = batch_num * cls.BATCH_SIZE
            end_idx = min(start_idx + cls.BATCH_SIZE, len(articles))
            batch = articles[start_idx:end_idx]

            logger.debug(f"[GeminiValidator] Processing batch {batch_num + 1}/{total_batches} ({len(batch)} articles)")

            batch_results = await cls.validate_batch(ticker, company_name, batch)
            all_results.extend(batch_results)

        return all_results


class GoogleSearchNews:
    """
    Busca noticias usando Google Custom Search API.
    Mais diversidade de fontes que GNews.
    """

    @staticmethod
    async def search(
        query: str,
        num_results: int = 10,
        date_restrict: str = "d3"  # Ultimos 3 dias
    ) -> List[Dict[str, Any]]:
        """
        Busca noticias no Google Custom Search.

        Args:
            query: Query de busca
            num_results: Numero de resultados (max 10 por request)
            date_restrict: Restricao de data (d1=1dia, d3=3dias, w1=1semana)

        Returns:
            Lista de artigos com title, url, snippet, source
        """
        import os
        import aiohttp

        api_key = os.getenv("GOOGLE_SEARCH_API_KEY")
        cse_id = os.getenv("GOOGLE_CSE_ID")

        if not api_key or not cse_id:
            logger.debug("[GoogleSearch] Missing API key or CSE ID")
            return []

        try:
            # Adicionar filtro de noticias
            search_query = f"{query} news stock market"

            url = "https://www.googleapis.com/customsearch/v1"
            params = {
                "key": api_key,
                "cx": cse_id,
                "q": search_query,
                "num": min(num_results, 10),
                "dateRestrict": date_restrict,
                "sort": "date",  # Mais recentes primeiro
            }

            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, params=params) as response:
                    if response.status != 200:
                        logger.debug(f"[GoogleSearch] HTTP {response.status}")
                        return []

                    data = await response.json()

            articles = []
            items = data.get("items", [])

            for item in items:
                articles.append({
                    "title": item.get("title", ""),
                    "url": item.get("link", ""),
                    "description": item.get("snippet", ""),
                    "source": item.get("displayLink", "Google"),
                    "published": "",  # Google Search nao retorna data exata
                    "language": "en"
                })

            logger.debug(f"[GoogleSearch] Found {len(articles)} results for '{query}'")
            return articles

        except asyncio.TimeoutError:
            logger.warning(f"[GoogleSearch] Timeout for query: {query[:30]}...")
            return []
        except Exception as e:
            logger.error(f"[GoogleSearch] Error ({type(e).__name__}): {e}")
            return []


class TickerResolver:
    """
    Resolve ticker para nome da empresa.
    Usa TickerRegistry como fonte primaria + yfinance como fallback.
    """
    _cache: Dict[str, Dict[str, str]] = {}  # {ticker: {name, sector, industry}}

    @classmethod
    def get_company_info(cls, ticker: str) -> Dict[str, str]:
        """
        Obtem informacoes da empresa pelo ticker.

        Estrategia:
        1. Verificar cache local
        2. Buscar no TickerRegistry (rapido, estatico)
        3. Buscar no yfinance (lento, fallback)

        Returns:
            Dict com 'name', 'sector', 'industry' (strings vazias se nao encontrar)
        """
        ticker_upper = ticker.upper()

        # 1. Verificar cache local
        if ticker_upper in cls._cache:
            return cls._cache[ticker_upper]

        # Resultado default
        result = {"name": "", "sector": "", "industry": ""}

        # 2. Tentar TickerRegistry (rapido, fonte unica de verdade)
        registry_info = TickerRegistry.get_info(ticker_upper)
        if registry_info:
            result["name"] = registry_info.get("name", "")
            result["sector"] = registry_info.get("sector", "")
            # TickerRegistry nao tem industry, deixar vazio
            cls._cache[ticker_upper] = result
            return result

        # 3. Tentar yfinance (fallback lento)
        try:
            import yfinance as yf
            stock = yf.Ticker(ticker_upper)
            info = stock.info

            if info:
                result["name"] = info.get("longName") or info.get("shortName") or ""
                result["sector"] = info.get("sector") or ""
                result["industry"] = info.get("industry") or ""

                # Se nome vazio, tentar extrair do simbolo
                if not result["name"] and "symbol" in info:
                    result["name"] = info["symbol"]

        except Exception as e:
            logger.debug(f"[TickerResolver] yfinance failed for {ticker}: {e}")

        # Cap cache at 500 entries to prevent unbounded growth
        if len(cls._cache) > 500:
            # Remove oldest half
            keys = list(cls._cache.keys())
            for k in keys[:250]:
                del cls._cache[k]

        cls._cache[ticker_upper] = result
        return result

    @classmethod
    def get_search_query(cls, ticker: str) -> str:
        """
        Retorna query de busca otimizada para o ticker.
        Usa nome da empresa se disponivel, senao ticker + contexto.
        """
        info = cls.get_company_info(ticker)
        name = info.get("name", "")

        if name:
            # Se tem nome, usar nome + stock
            return f"{name} stock"
        else:
            # Fallback: ticker + stock market (evita ambiguidade)
            return f"{ticker} stock market"


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
        # Determinar pais do ticker via TickerRegistry
        ticker_country = _get_ticker_country(ticker)

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

    async def get_gnews(
        self,
        ticker: str,
        max_results: int = 5,
        fetch_full_content: bool = False,
        validate_with_gemini: bool = True,
        use_google_search: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Busca noticias com multiplas fontes e validacao AI.

        Fontes:
        1. GNews API (ingles + portugues)
        2. Google Custom Search API (se habilitado)

        Filtros:
        - TickerResolver para nome correto da empresa
        - Validacao Gemini para relevancia (evita PBR -> Bull Riders)
        - Freshness filter (>48h descartado)
        - Score baseado em: fonte, freshness, pais

        Args:
            ticker: Ticker do ativo
            max_results: Numero maximo de resultados
            fetch_full_content: Se True, faz scrape completo do artigo
            validate_with_gemini: Se True, valida relevancia com Gemini AI
            use_google_search: Se True, tambem busca via Google Search API

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
            loop = asyncio.get_running_loop()

            # OBTER NOME DA EMPRESA via TickerResolver (evita PBR -> Professional Bull Riders)
            search_query = TickerResolver.get_search_query(ticker)
            company_info = TickerResolver.get_company_info(ticker)
            company_name = company_info.get("name", "") or ticker

            logger.debug(f"[NEWS] {ticker} -> search query: '{search_query}' (company: {company_name})")

            # Funcoes sincronas para rodar em thread pool
            def fetch_gnews_en(search_term: str):
                """Busca GNews em ingles (bloqueante)."""
                try:
                    google_news = GNews(language='en', country='US', max_results=fetch_count)
                    return google_news.get_news(search_term) or []
                except Exception:
                    return []

            def fetch_gnews_pt(search_term: str):
                """Busca GNews em portugues (bloqueante)."""
                try:
                    google_news = GNews(language='pt', country='BR', max_results=fetch_count)
                    return google_news.get_news(search_term) or []
                except Exception:
                    return []

            # === BUSCA PARALELA DE TODAS AS FONTES ===
            # Criar tasks para executar em paralelo
            tasks = []
            task_labels = []  # Para identificar resultados

            # Task 1: GNews EN
            tasks.append(loop.run_in_executor(None, fetch_gnews_en, search_query))
            task_labels.append(("gnews_en", None))

            # Task 2+: GNews PT (se brasileiro) - uma task por termo
            if is_brazilian:
                search_terms = [company_name] if company_name else []
                search_terms.append(ticker)
                for term in search_terms:
                    tasks.append(loop.run_in_executor(None, fetch_gnews_pt, term))
                    task_labels.append(("gnews_pt", term))

            # Task N: Google Custom Search
            if use_google_search:
                tasks.append(GoogleSearchNews.search(
                    query=search_query,
                    num_results=fetch_count,
                    date_restrict="d3"
                ))
                task_labels.append(("google_search", None))

            # Executar todas as fontes em paralelo
            logger.debug(f"[NEWS] {ticker}: Fetching {len(tasks)} sources in parallel...")
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Processar resultados
            for (source_type, term), result in zip(task_labels, results):
                if isinstance(result, Exception):
                    logger.debug(f"[NEWS] {ticker}: {source_type} failed: {result}")
                    continue

                # Cast result to list (after exception check)
                items: List[Dict[str, Any]] = result if isinstance(result, list) else []

                if source_type == "gnews_en":
                    for item in items:
                        all_articles.append({
                            "title": item.get("title", ""),
                            "url": item.get("url", ""),
                            "published": item.get("published date", ""),
                            "description": item.get("description", ""),
                            "source": item.get("publisher", {}).get("title", "GNews"),
                            "source_type": "gnews",
                            "language": "en"
                        })

                elif source_type == "gnews_pt":
                    for item in items:
                        all_articles.append({
                            "title": item.get("title", ""),
                            "url": item.get("url", ""),
                            "published": item.get("published date", ""),
                            "description": item.get("description", ""),
                            "source": item.get("publisher", {}).get("title", "GNews-BR"),
                            "source_type": "gnews",
                            "language": "pt"
                        })

                elif source_type == "google_search":
                    for art in items:
                        art["source_type"] = "google_search"
                        all_articles.append(art)
                    logger.debug(f"[NEWS] Google Search added {len(items)} articles for {ticker}")

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

            # === VALIDACAO GEMINI EM BATCH (filtra noticias irrelevantes) ===
            validated_articles = fresh_articles
            if validate_with_gemini and company_name and fresh_articles:
                # Usar batch validation (15 artigos por chamada)
                logger.debug(f"[NEWS] {ticker}: Validating {len(fresh_articles)} articles with Gemini (batch mode)...")

                validation_results = await GeminiNewsValidator.validate_all(
                    ticker=ticker,
                    company_name=company_name,
                    articles=fresh_articles
                )

                # Aplicar resultados
                validated_articles = []
                filtered_count = 0

                for art, (is_relevant, confidence, reason) in zip(fresh_articles, validation_results):
                    if is_relevant:
                        art["gemini_confidence"] = round(confidence, 2)
                        validated_articles.append(art)
                    else:
                        filtered_count += 1

                if filtered_count > 0:
                    logger.info(f"[NEWS] {ticker}: Gemini filtered {filtered_count}/{len(fresh_articles)} irrelevant articles")

            # Calcular score para cada artigo
            scored_articles = []
            for art in validated_articles:
                score = self.calculate_article_score(art, ticker)

                # Bonus para artigos validados com alta confianca
                gemini_bonus = art.get("gemini_confidence", 0.5) * 0.5
                score += gemini_bonus

                art["relevance_score"] = round(score, 2)
                art["source_quality"] = round(self._get_source_score(art.get("url", "")), 2)
                art["freshness_score"] = round(self._get_freshness_score(art.get("published", "")), 2)
                scored_articles.append(art)

            # Ordenar por score (maior primeiro)
            scored_articles.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)

            # Pegar top results
            top_articles = scored_articles[:max_results]

            # Buscar conteudo completo se solicitado (em paralelo)
            if fetch_full_content:
                import asyncio as _aio

                async def _scrape_one(art):
                    if art.get("url"):
                        try:
                            text = await self._scrape_article_content(art["url"], max_chars=10000)
                            art["full_content"] = text if text else ""
                        except Exception as e:
                            logger.warning(f"[NEWS] Scrape failed for {art.get('source', '?')}: {e}")
                            art["full_content"] = ""
                    else:
                        art["full_content"] = ""

                await _aio.gather(*[_scrape_one(a) for a in top_articles])

            # Log detalhado do resultado final
            if top_articles:
                best = top_articles[0]
                # Contar fontes
                gnews_count = sum(1 for a in top_articles if a.get("source_type") == "gnews")
                google_count = sum(1 for a in top_articles if a.get("source_type") == "google_search")

                logger.info(
                    f"[NEWS] {ticker}: {len(top_articles)}/{len(unique_articles)} artigos "
                    f"(GNews:{gnews_count} Google:{google_count}) | "
                    f"Best: {best.get('relevance_score', 0):.1f} pts de {self._extract_domain(best.get('url', ''))}"
                )
                # Log resumo dos top artigos selecionados
                for i, art in enumerate(top_articles[:3], 1):
                    src_icon = "G" if art.get("source_type") == "google_search" else "N"
                    logger.info(
                        f"  [{i}][{src_icon}] Score={art.get('relevance_score', 0):.1f} | "
                        f"{self._extract_domain(art.get('url', '')):20s} | "
                        f"{art.get('title', '')[:55]}..."
                    )
            else:
                logger.info(f"[NEWS] {ticker}: Nenhum artigo fresco encontrado (max_age={self.max_news_age_hours}h)")

            return top_articles

        except Exception as e:
            logger.error(f"Error fetching GNews for {ticker}: {e}")
            return []

    def format_news_for_screener(self, ticker: str, articles: List[Dict[str, Any]]) -> str:
        """
        Formata noticias para o SCREENER (Phase 1).
        Formato resumido: apenas titulos com score.

        ESTE METODO E USADO TANTO NO CODIGO DE PRODUCAO QUANTO NO DEBUG.

        Args:
            ticker: Ticker do ativo
            articles: Lista de artigos do get_gnews()

        Returns:
            String formatada para incluir no prompt do Screener
        """
        if not articles:
            return f"No recent news found for {ticker}"

        lines = [f"Recent news for {ticker} (scored by relevance):"]
        for art in articles[:3]:
            score = art.get('relevance_score', 0)
            title = art.get('title', 'No title')
            lines.append(f"- [{score:.1f}] {title}")

        return "\n".join(lines)

    def format_news_for_judge(self, ticker: str, articles: List[Dict[str, Any]]) -> str:
        """
        Formata noticias para o JUDGE (Phase 3).
        Formato detalhado: titulo, conteudo completo, fonte, timestamp,
        relevancia, freshness e indicadores de sentimento.
        Ordenado por relevancia (mais relevante primeiro).

        Args:
            ticker: Ticker do ativo
            articles: Lista de artigos do get_gnews()

        Returns:
            String formatada para incluir no prompt do Judge
        """
        if not articles:
            return f"No recent news found for {ticker}. Treat news sentiment as NEUTRAL."

        # Ordenar por relevancia (mais relevante primeiro)
        sorted_articles = sorted(
            articles[:8],
            key=lambda x: x.get('relevance_score', 0),
            reverse=True
        )

        # Resumo geral
        avg_score = sum(a.get('relevance_score', 0) for a in sorted_articles) / len(sorted_articles)
        high_relevance = sum(1 for a in sorted_articles if a.get('relevance_score', 0) >= 7)

        lines = [f"=== NEWS DOSSIER FOR {ticker} ({len(sorted_articles)} articles) ==="]
        lines.append(f"Average relevance: {avg_score:.1f}/10 | High-relevance articles: {high_relevance}")
        lines.append("")

        for i, art in enumerate(sorted_articles, 1):
            title = art.get('title', 'No title')
            source = art.get('source', 'Unknown')
            published = art.get('published', 'Unknown')
            relevance = art.get('relevance_score', 0)
            freshness = art.get('freshness_score', 0)

            # Freshness label
            if freshness >= 0.9:
                fresh_label = "BREAKING"
            elif freshness >= 0.7:
                fresh_label = "Recent"
            elif freshness >= 0.4:
                fresh_label = "Today"
            else:
                fresh_label = "Older"

            full_content = art.get('full_content', '')
            description = art.get('description', '')

            lines.append(f"[{i}] {title}")
            lines.append(f"    Source: {source} | Published: {published}")
            lines.append(f"    Relevance: {relevance:.1f}/10 | Freshness: {fresh_label}")
            if full_content:
                lines.append(f"    Full Article:")
                lines.append(f"    {full_content}")
            elif description:
                lines.append(f"    Summary: {description}")
            else:
                lines.append(f"    (headline only, no article body available)")
            lines.append("")

        lines.append("--- END NEWS DOSSIER ---")
        lines.append("Use the above news to assess catalysts, sentiment, and event risk.")

        return "\n".join(lines)

    async def get_news_digest_grounded(self, ticker: str) -> str:
        """
        Busca noticias COMPLETAS usando Gemini Flash + Google Search grounding.

        Em vez de scraping (que falha em sites financeiros com paywall/anti-bot),
        usa o Gemini com acesso ao Google Search para buscar e sintetizar
        noticias em tempo real com conteudo completo.

        Args:
            ticker: Ticker do ativo (ex: AMZN, PETR4.SA)

        Returns:
            String formatada com noticias detalhadas para o Judge, ou "" se falhar
        """
        import os
        gemini_key = os.getenv("GEMINI_API_KEY")
        if not gemini_key:
            logger.warning("[NEWS-GROUNDED] GEMINI_API_KEY not set")
            return ""

        try:
            from google import genai
            from google.genai import types

            # Determine context based on ticker origin
            is_brazilian = ticker.endswith(".SA")
            lang = "Portuguese (Brazil)" if is_brazilian else "English"
            market = "Brazilian stock market (B3)" if is_brazilian else "US stock market"

            prompt = (
                f"Search for the LATEST financial news about {ticker} stock.\n"
                f"Focus on news from the last 24 hours about this specific company.\n\n"
                f"For each piece of news you find, provide:\n"
                f"1. The headline\n"
                f"2. The source (publication name)\n"
                f"3. A DETAILED summary of the article content (at least 2-3 sentences "
                f"with specific facts, numbers, analyst opinions, earnings data)\n"
                f"4. Why this news matters for trading (potential market impact)\n\n"
                f"Format your response EXACTLY like this:\n\n"
                f"=== NEWS DIGEST FOR {ticker} ===\n\n"
                f"[1] HEADLINE: <title>\n"
                f"    SOURCE: <publication>\n"
                f"    CONTENT: <detailed 2-3 sentence summary with specific facts and numbers>\n"
                f"    IMPACT: <brief trading impact assessment>\n\n"
                f"[2] HEADLINE: <title>\n"
                f"    SOURCE: <publication>\n"
                f"    CONTENT: <detailed summary>\n"
                f"    IMPACT: <brief impact>\n\n"
                f"(continue for all relevant articles found, up to 8)\n\n"
                f"--- OVERALL SENTIMENT ---\n"
                f"Direction: <BULLISH / BEARISH / NEUTRAL / MIXED>\n"
                f"Key catalysts: <list main catalysts>\n"
                f"Risk events: <list risk events if any>\n\n"
                f"IMPORTANT:\n"
                f"- Include SPECIFIC numbers, percentages, analyst price targets when available\n"
                f"- Focus on {market} context\n"
                f"- Write in {lang}\n"
                f"- If no recent news is found, state that clearly"
            )

            client = genai.Client(api_key=gemini_key)

            loop = asyncio.get_running_loop()

            def _sync_call() -> str:
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        tools=[types.Tool(google_search=types.GoogleSearch())],
                        temperature=0.3,
                        max_output_tokens=4000,
                    )
                )
                return response.text or ""

            result = await asyncio.wait_for(
                loop.run_in_executor(None, _sync_call),
                timeout=45.0
            )

            if result and len(result) > 100:
                logger.info(f"[NEWS-GROUNDED] {ticker}: Got {len(result)} chars of grounded news digest")
                return result
            else:
                logger.warning(f"[NEWS-GROUNDED] {ticker}: Empty or too short response ({len(result) if result else 0} chars)")
                return ""

        except Exception as e:
            logger.error(f"[NEWS-GROUNDED] {ticker}: Failed - {type(e).__name__}: {str(e)[:150]}")
            return ""

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

    async def _scrape_article_content(self, url: str, max_chars: int = 10000) -> str:
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
        domain = real_url.split('/')[2] if len(real_url.split('/')) > 2 else "unknown"

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
                    logger.info(f"[NEWS-SCRAPE] {domain}: {len(content)} chars (cloudscraper+trafilatura)")

        except ImportError:
            logger.warning("[NEWS-SCRAPE] cloudscraper/trafilatura not installed")
        except Exception as e:
            logger.debug(f"[NEWS-SCRAPE] {domain}: cloudscraper failed: {type(e).__name__}")

        # Método 2: trafilatura direto (se cloudscraper falhou)
        if not content:
            try:
                import trafilatura
                downloaded = trafilatura.fetch_url(real_url)
                if downloaded:
                    content = trafilatura.extract(downloaded) or ""
                    if content:
                        logger.info(f"[NEWS-SCRAPE] {domain}: {len(content)} chars (trafilatura)")
            except ImportError:
                pass
            except Exception as e:
                logger.debug(f"[NEWS-SCRAPE] {domain}: trafilatura failed: {type(e).__name__}")

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
                    logger.info(f"[NEWS-SCRAPE] {domain}: {len(content)} chars (newspaper3k)")

            except Exception as e:
                logger.debug(f"[NEWS-SCRAPE] {domain}: newspaper3k failed: {type(e).__name__}")

        if not content:
            logger.warning(f"[NEWS-SCRAPE] {domain}: ALL methods failed - headline only")

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
        keywords: Optional[List[str]] = None,
        use_google_search: bool = True
    ) -> List[NewsArticle]:
        """
        Busca notícias com catalisadores específicos.

        Fontes:
        1. GNews API (tópicos BUSINESS/TECHNOLOGY em EN + PT-BR)
        2. Google Custom Search API (queries de catalisadores)

        Args:
            keywords: Lista de keywords para filtrar nos títulos (earnings, FDA, merger, etc.)
            use_google_search: Se True, também busca via Google Custom Search API

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
        seen_urls: set = set()  # Deduplicação

        try:
            from gnews import GNews  # type: ignore
            import re

            loop = asyncio.get_running_loop()

            # Configurações de busca por idioma
            search_configs = [
                {"language": "en", "country": "US", "topics": ["BUSINESS", "TECHNOLOGY"], "lang": "EN"},
                {"language": "pt", "country": "BR", "topics": ["BUSINESS", "TECHNOLOGY"], "lang": "PT-BR"},
            ]

            # Queries para Google Search (catalisadores de alto impacto)
            google_search_queries = [
                "stock earnings report today",
                "FDA approval drug stock",
                "merger acquisition announcement stock",
                "stock upgrade downgrade analyst",
                "IPO stock market today",
                "acoes bovespa alta queda hoje",  # PT-BR
                "resultados trimestre empresa bolsa",  # PT-BR
            ]

            # Funcao bloqueante para rodar em thread pool
            def fetch_topic_sync(language: str, country: str, topic: str):
                """Busca um topico de forma sincrona (roda em thread pool)."""
                try:
                    gnews = GNews(language=language, country=country, max_results=15)
                    news = gnews.get_news_by_topic(topic)
                    return news[:15] if news else []  # Top 15
                except Exception:
                    return []

            # === CRIAR TASKS PARA TODAS AS FONTES EM PARALELO ===
            tasks = []
            task_labels = []  # (source_type, detail)

            # 1. GNews por tópicos
            for config in search_configs:
                for topic in config["topics"]:
                    tasks.append(loop.run_in_executor(
                        None,
                        fetch_topic_sync,
                        config["language"],
                        config["country"],
                        topic
                    ))
                    task_labels.append(("gnews", f"{config['lang']}-{topic}"))

            # 2. Google Custom Search API (se habilitado)
            if use_google_search:
                for query in google_search_queries:
                    tasks.append(GoogleSearchNews.search(
                        query=query,
                        num_results=10,
                        date_restrict="d1"  # Últimas 24h para catalisadores
                    ))
                    task_labels.append(("google", query[:20]))

            # Executar todas as buscas em paralelo
            gnews_count = sum(1 for t in task_labels if t[0] == "gnews")
            google_count = sum(1 for t in task_labels if t[0] == "google")
            print(f"\r[CATALYST] Buscando {gnews_count} GNews + {google_count} Google em paralelo...    ", end="", flush=True)

            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Processar resultados
            total_scanned = 0
            total_found = 0
            google_found = 0

            # Função helper para processar artigo e extrair tickers
            def process_article(item: Dict[str, Any], source_label: str) -> Optional[NewsArticle]:
                nonlocal total_scanned, total_found, google_found

                title = item.get("title", "")
                description = item.get("description", "") or item.get("snippet", "")
                url = item.get("url", "") or item.get("link", "")

                # Deduplicar por URL
                if url in seen_urls:
                    return None
                seen_urls.add(url)

                total_scanned += 1
                full_text = f"{title} {description}".lower()

                # Filtrar por keywords nos títulos/descrições
                has_catalyst = any(keyword.lower() in full_text for keyword in keywords)

                if not has_catalyst:
                    return None

                # === EXTRAÇÃO DE TICKERS ===
                text_to_scan = f"{title} {description}"
                text_lower = text_to_scan.lower()
                found_tickers: set = set()

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
                    if "google" in source_label.lower():
                        google_found += 1

                    return NewsArticle(
                        title=title,
                        url=url,
                        published_date=None,
                        source=source_label,
                        summary=description,
                        tickers_mentioned=tickers,
                        sentiment=None,
                        relevance_score=8.0
                    )

                return None

            # Processar todos os resultados
            for (source_type, detail), result in zip(task_labels, results):
                if isinstance(result, Exception):
                    logger.debug(f"Error fetching {source_type}/{detail}: {result}")
                    continue

                # Cast result to list (after exception check)
                articles: List[Dict[str, Any]] = result if isinstance(result, list) else []

                for item in articles:
                    if source_type == "gnews":
                        source_label = f"GNews-{detail}"
                    else:
                        source_label = f"Google-{detail}"

                    article = process_article(item, source_label)
                    if article:
                        catalyst_news.append(article)

            print(f"\r[CATALYST] Extraidos: {total_found} candidatos ({google_found} Google) de {total_scanned} artigos    ")
            logger.info(f"[CATALYST] Extraidos: {total_found} candidatos ({google_found} do Google) de {total_scanned} artigos")

            # === VALIDACAO GEMINI - Filtrar falsos positivos (UMA chamada) ===
            if catalyst_news:
                print(f"\r[CATALYST] Validando {len(catalyst_news)} candidatos com Gemini (1 batch)...    ", end="", flush=True)

                # Converter NewsArticle para dict para validacao
                articles_for_validation = [
                    {
                        "title": art.title,
                        "description": art.summary,
                        "tickers": art.tickers_mentioned,
                        "_original": art  # Referencia ao objeto original
                    }
                    for art in catalyst_news
                ]

                # Validar com metodo unificado
                validated_dicts = await GeminiNewsValidator.validate_multi_ticker(articles_for_validation)

                # Reconstruir lista de NewsArticle com tickers validados
                validated_news = []
                for vd in validated_dicts:
                    original = vd.get("_original")
                    if original:
                        # Atualizar tickers com os validados
                        original.tickers_mentioned = vd.get("valid_tickers", original.tickers_mentioned)
                        validated_news.append(original)

                filtered_count = len(catalyst_news) - len(validated_news)
                catalyst_news = validated_news

                print(f"\r[CATALYST] Validacao Gemini: {len(catalyst_news)} aprovados, {filtered_count} filtrados    ")
                logger.info(f"[CATALYST] Validacao Gemini: {len(catalyst_news)} aprovados, {filtered_count} filtrados")

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
