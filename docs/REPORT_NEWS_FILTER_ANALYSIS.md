# Relatorio: Analise do Filtro de Noticias (News Catalyst)

**Data:** 2026-01-06
**Arquivo:** `src/collectors/news_aggregator.py` - metodo `find_catalyst_news()`

---

## Resumo Executivo

O scan de `news_catalyst` esta retornando **0 candidatos** devido a multiplas camadas de filtragem muito restritivas. O problema NAO esta na infraestrutura - ela funciona. O problema esta na **logica de extracao de tickers** que exige condicoes muito especificas.

---

## Fluxo Atual do News Catalyst

```
1. Busca artigos por TOPICO (BUSINESS, FINANCE, TECHNOLOGY)
        |
        v
2. Pega top 10 artigos de cada topico (30 artigos total)
        |
        v
3. Verifica se titulo/descricao contem KEYWORDS especificas
   ["earnings", "FDA approval", "merger", "acquisition",
    "partnership", "breakthrough", "buyback", "guidance"]
        |
        v  (FILTRO 1 - muitos artigos eliminados aqui)
        |
4. Se contem keyword, tenta extrair TICKER do TITULO via regex:
   - \(([A-Z]{2,5})\)        -> (AAPL)
   - ([A-Z]{2,5})\s+stock    -> AAPL stock
   - \b([A-Z]{2,5})\b        -> qualquer palavra maiuscula
        |
        v  (FILTRO 2 - extrai muitos falsos positivos)
        |
5. Remove "non_tickers" (lista de ~80 siglas):
   CEO, SEC, FDA, USA, NFL, AI, etc...
        |
        v  (FILTRO 3 - pode remover tickers legitimos)
        |
6. Se sobrar algum ticker valido -> cria BuzzCandidate
```

---

## Problemas Identificados

### Problema 1: Keywords Muito Especificas

**Arquivo:** `news_aggregator.py:172`

```python
keywords = ["earnings", "FDA", "approval", "merger", "acquisition",
            "partnership", "breakthrough", "guidance", "buyback", "announces"]
```

**Impacto:** Uma noticia como "Apple stock surges 5% on strong iPhone sales" NAO passa porque nao contem nenhuma dessas palavras exatas.

**Sugestao:** Expandir keywords:
- "surges", "plunges", "jumps", "drops", "falls", "rises"
- "beats", "misses", "outlook", "forecast", "revenue"
- "upgrade", "downgrade", "target", "rating"
- "deal", "contract", "launches", "announces"

---

### Problema 2: Extracao de Ticker Apenas do Titulo

**Arquivo:** `news_aggregator.py:214-221`

```python
for pattern in ticker_patterns:
    potential_tickers.extend(re.findall(pattern, title))  # Apenas TITULO!
```

**Impacto:** Se a noticia menciona o ticker na descricao mas nao no titulo, nao e detectado.

**Exemplo perdido:**
- Titulo: "Tech stocks rally amid AI optimism"
- Descricao: "NVDA and AMD lead gains as investors..."
- Resultado: Nenhum ticker extraido (NVDA/AMD estao na descricao)

**Sugestao:** Buscar tambem na descricao:
```python
full_text = f"{title} {description}"
for pattern in ticker_patterns:
    potential_tickers.extend(re.findall(pattern, full_text))
```

---

### Problema 3: Lista de Exclusao Excessiva

**Arquivo:** `news_aggregator.py:224-246`

A lista `non_tickers` tem ~80 siglas, incluindo algumas que sao tickers reais:
- "IT" - e ticker real (Gartner Inc)
- Possivelmente outros

**Sugestao:** Validar se o ticker existe na bolsa antes de excluir.

---

### Problema 4: Sem Validacao de Ticker Real

O sistema extrai qualquer palavra maiuscula de 2-5 letras e assume que e ticker.

**Exemplo:** "The NEW CEO said..." -> "NEW" extraido como ticker (falso positivo)

**Sugestao:** Validar contra lista de tickers reais (S&P 500, NASDAQ 100, etc) ou usar yfinance para verificar.

---

## Solucao Proposta (3 Niveis)

### Nivel 1: Quick Fix (Sem Mudar Logica)

Expandir keywords para pegar mais noticias:
```python
keywords = [
    # Eventos corporativos
    "earnings", "revenue", "profit", "guidance", "outlook", "forecast",
    # Regulatorio
    "FDA", "approval", "SEC", "investigation",
    # M&A
    "merger", "acquisition", "deal", "buyout", "takeover",
    # Mercado
    "surges", "plunges", "jumps", "drops", "rallies", "tumbles",
    # Analistas
    "upgrade", "downgrade", "target", "rating",
    # Outros
    "partnership", "breakthrough", "buyback", "announces", "launches"
]
```

### Nivel 2: Medium Fix (Melhorar Extracao)

Buscar tickers no titulo E descricao:
```python
full_text = f"{title} {description}".upper()
for pattern in ticker_patterns:
    potential_tickers.extend(re.findall(pattern, full_text))
```

### Nivel 3: Full Fix (Validacao Real)

Validar tickers extraidos contra lista real:
```python
# Carregar lista de tickers validos (S&P 500, NASDAQ, etc)
VALID_TICKERS = load_valid_tickers()

# Validar antes de criar candidato
validated_tickers = [t for t in potential_tickers if t in VALID_TICKERS]
```

---

## Importante: O Que FUNCIONA

1. **GNews API** - Busca artigos corretamente
2. **news_content** - Campo salvo corretamente no BuzzCandidate
3. **Pipeline Phase 1/3** - Noticias sao passadas para Screener e Judge
4. **Busca por ticker especifico** - `get_gnews(ticker)` funciona perfeitamente

O problema e especificamente no **scan de catalysts** que tenta DESCOBRIR tickers a partir de noticias genericas.

---

## Recomendacao

Para a IARA funcionar com noticias AGORA:

1. Nao depender do `news_catalyst` para descobrir candidatos
2. Usar `get_gnews(ticker)` para buscar noticias dos candidatos ja identificados (watchlist, volume, gaps)
3. Isso JA esta implementado no orchestrator (Phase 1 e Phase 3)

O `news_catalyst` seria um "bonus" para descobrir candidatos que nao estao no radar, mas nao e critico para o fluxo principal.

---

## Conclusao

| Componente | Status | Observacao |
|------------|--------|------------|
| GNews API | OK | Funciona |
| news_content field | OK | Implementado |
| Phase 1 news | OK | Busca por ticker |
| Phase 3 news | OK | Busca detalhada |
| news_catalyst scan | RESTRITIVO | Keywords + Regex muito limitados |

**Acao recomendada:** Prioridade baixa para corrigir o news_catalyst. O fluxo principal de noticias ja funciona via busca direta por ticker.
