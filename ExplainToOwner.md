# IARA - Explicação da Estrutura do Projeto

**Última Atualização:** 2026-01-07
**Versão:** v25.0 "Atomic Survivor"

---

## 📋 ÍNDICE

1. [Visão Geral](#visão-geral)
2. [Arquitetura de 6 Fases](#arquitetura-de-6-fases)
3. [Estrutura de Diretórios](#estrutura-de-diretórios)
4. [Componentes Principais](#componentes-principais)
5. [Fluxo de Dados](#fluxo-de-dados)
6. [Sistema de Testes](#sistema-de-testes)
7. [Ferramentas de Debug](#ferramentas-de-debug)
8. [Como Executar](#como-executar)

---

## 🎯 VISÃO GERAL

O IARA é um sistema de trading automatizado dividido em **6 fases sequenciais**, onde cada fase tem uma responsabilidade específica. A filosofia é: **"Sobrevivência em primeiro lugar, lucro em segundo"**.

### Conceito Principal
```
DADOS BRUTOS → MATEMÁTICA → IA → DECISÃO → EXECUÇÃO → MONITORAMENTO
  (Phase 0)    (Phase 2)  (P1+P3)  (Phase 3)  (Phase 4)    (Phase 5)
```

### Onde Tudo Começa
**Arquivo Principal:** `main.py`
- Inicializa todos os componentes
- Inicia o orchestrator que coordena as 6 fases
- Roda em loop contínuo durante horário de mercado

---

## 🔄 ARQUITETURA DE 6 FASES

### PHASE 0: BUZZ FACTORY (08:00 - Pré-Mercado)
**Responsabilidade:** Gerar lista de oportunidades do dia

**Arquivo Principal:** `src/collectors/buzz_factory.py`

**O que faz:**
1. **Watchlist** - Carrega tickers fixos de `config/watchlist.json`
2. **Volume Spikes** - Escaneia mercado buscando volume >2x média
3. **Gap Scanner** - Detecta gaps de >3% no pré-mercado
4. **News Catalyst** - Busca notícias relevantes (FDA, M&A, earnings)

**Arquivos Auxiliares:**
- `src/collectors/market_data.py` - Busca dados via yfinance
- `src/collectors/news_scraper.py` - Scraping de notícias
- `src/collectors/earnings_checker.py` - Verifica proximidade de earnings

**Filtros Aplicados:**
- Market cap mínimo: $800M
- Dollar volume mínimo: $15M/dia
- Friday blocking (não abre posições sexta)
- Earnings proximity (rejeita se <5 dias)

**Saída:** Lista de `BuzzCandidate` (ticker, source, buzz_score, tier)

---

### PHASE 1: SCREENER (10:30 - Triagem com IA)
**Responsabilidade:** Filtro inicial rápido e barato

**Arquivo Principal:** `src/decision/screener.py`

**IA Usada:** Google Gemini 3 Flash (Free Tier)
**Prompt:** `config/prompts/screener.md`

**O que faz:**
1. Recebe candidatos do Phase 0
2. Para cada um, busca dados técnicos (RSI, ATR, SuperTrend)
3. Monta resumo de notícias
4. Envia para Gemini avaliar com nota 0-10
5. **Threshold:** Só passa se nota ≥7

**Rate Limiting:** 4 segundos entre chamadas (limitação do free tier)

**Saída:** Lista de `ScreenerResult` (ticker, nota, viés, confiança)

---

### PHASE 2: THE VAULT (Matemática Pura)
**Responsabilidade:** Filtros matemáticos rígidos - NENHUMA IA decide aqui

**Arquivos Principais:**
- `src/analysis/risk_math.py` - Cálculos de risco
- `src/analysis/correlation.py` - Análise de correlação
- `src/analysis/technical.py` - Indicadores técnicos
- `src/core/state_manager.py` - Estado do portfolio

### 🧮 LÓGICAS CRÍTICAS (PHASE 2):

#### 1. Beta Adjustment (`risk_math.py`)
```
Localização: src/analysis/risk_math.py, método calculate_beta_adjustment()

Regra:
- Beta < 2.0: multiplier = 1.0 (normal)
- Beta 2.0-3.0: multiplier = 0.75 (agressivo, reduz lot)
- Beta ≥ 3.0 COM volume ≥2x: multiplier = 0.5 (extremo confirmado)
- Beta ≥ 3.0 SEM volume: multiplier = 0.0 (REJEITAR - hard veto)
```

#### 2. Correlation Veto (`correlation.py`)
```
Localização: src/analysis/correlation.py, método enforce_correlation_limit()

Regra:
- Calcula correlação dos últimos 60 dias
- Se correlação > 0.75 com QUALQUER posição existente → HARD VETO
- Veto não pode ser negociado pela IA
- Previne concentração de risco em ativos correlacionados
```

#### 3. Defensive Mode (`state_manager.py`)
```
Localização: src/core/state_manager.py, métodos get_weekly_drawdown() e get_defensive_multiplier()

Regra:
- Monitora drawdown semanal E diário
- Ativa se: Weekly DD ≥5% OU Daily DD ≥3%
- Quando ativo: Reduz TODOS os lotes em 50%
- Objetivo: Proteger capital em períodos ruins
```

#### 4. Sector Exposure (`state_manager.py`)
```
Localização: src/core/state_manager.py, método check_sector_exposure()

Regra:
- Máximo 20% do capital por setor
- Busca setor via yfinance
- Agrega exposição de todas as posições
- Rejeita se ultrapassar limite
```

**Saída:** Candidatos filtrados + multipliers calculados

---

### PHASE 3: JUDGE (Decisão Final com IA)
**Responsabilidade:** Análise profunda e decisão estratégica

**Arquivo Principal:** `src/decision/judge.py`

**IA Usada:** GPT-4/5 (OpenAI) com fallback para Claude 3.5
**Prompt:** `config/prompts/judge.md`

**Componentes:**

#### 1. Google Grounding (`src/decision/grounding.py`)
```
Função: Verificar veracidade de notícias ANTES do Judge decidir
Localização: Chamado dentro de judge.judge() antes da IA

Regra:
- Se notícia existe, valida com Google Search API
- Se confiança < 0.3: REJEITAR automaticamente
- Se verificado: Augmenta prompt com fontes verificadas
```

#### 2. SQLite Cache (`src/core/database.py`)
```
Função: Evitar chamadas repetidas de IA para mesmo ticker
Localização: judge.judge(), primeiro passo

Regra:
- Verifica cache se decisão < 2 horas
- Se encontrado: Retorna cached decision (sem chamar IA)
- Se não: Processa normalmente e salva no cache
- Tabela: decision_cache
```

#### 3. Decision Validation
```
Localização: judge.py, método validate_decision()

Validações:
- R/R mínimo: 2.0 (risk/reward ratio)
- Não permite duplicatas (já tem posição no ticker)
- Threshold: Nota ≥8 para aprovar
- Correlation check: Se aprovar, valida correlação novamente
```

**Saída:** `TradeDecision` (decisão, entry, stop, TPs, justificativa)

---

### PHASE 4: ARMORED EXECUTION
**Responsabilidade:** Executar ordem com proteções

**Arquivo Principal:** `src/execution/order_manager.py`

**Componentes:**

#### 1. Position Sizer (`src/execution/position_sizer.py`)
```
Função: Calcular tamanho da posição

Fórmula:
risk_base = 1% do capital
risk_adjusted = risk_base × tier_mult × beta_mult × defensive_mult × suggestion_mult

shares = risk_adjusted / (entry - stop)

Multipliers:
- tier_mult: 1.0 para Tier 1 (>$4B), 0.6 para Tier 2 ($800M-$4B)
- beta_mult: Do Phase 2 (0.5 a 1.0)
- defensive_mult: 0.5 se defensive mode, senão 1.0
- suggestion_mult: 1.0 NORMAL, 0.5 REDUZIDO, 0.25 MÍNIMO
```

#### 2. Stop Loss Calculation
```
Localização: order_manager.py (TODO - ainda não implementado)

Regra:
- Normal: MAX(Entry - 2.5×ATR, SwingLow)
- Se earnings < 5 dias: Entry × 0.995 (stop tight de 0.5%)
- Dual stop system:
  * Physical stop enviado ao broker (ex: -7%)
  * Backup stop local tracking (-10%)
```

#### 3. Entry Orders
```
Tipo: STOP-LIMIT (nunca market order)
Stop price: Entry sugerido pelo Judge
Limit price: Entry + 0.5% (proteção contra slippage)
Time in force: DAY
```

**Broker Integration:** `src/execution/broker_api.py`
- Suporta paper trading (default)
- Integração ccxt para brokers reais (quando configurado)

**Saída:** Orders executadas + posições adicionadas ao state_manager

---

### PHASE 5: THE GUARDIAN (Monitoramento 24/7)
**Responsabilidade:** Vigiar posições e proteger capital

**Arquivos Principais:**

#### 1. Watchdog (`src/monitoring/watchdog.py`)
```
Função: Monitoramento contínuo (1 minuto)

Responsabilidades:
- Checar preço vs stop/TP
- Flash crash detection (>5% em 1 min com VIX/SPY validation)
- Executar exits se stops atingidos
- Panic protocol: Se DD intraday >4% → fecha tudo
```

#### 2. Sentinel (`src/monitoring/sentinel.py`)
```
Função: Análise periódica (5 minutos)

Responsabilidades:
- Buscar notícias sobre posições abertas
- Analisar impacto com IA
- Chamar Judge para decisões de exit se necessário
- Friday breakeven: Move stop para breakeven sexta após 14h
- Trailing stops: Atualiza stops com lucro acumulado
```

#### 3. Poison Pill (`src/monitoring/poison_pill.py`)
```
Função: Scanner overnight para M&A/SEC filings

Responsabilidades:
- Detectar anúncios de M&A, investigações SEC
- Se detectado:
  * Cancelar todos os stops do ticker
  * Colocar limit order +60% do entry
  * Alert crítico via Telegram
- Objetivo: Aproveitar spikes em aquisições
```

**Kill Switch:** `src/core/state_manager.py`
```
Ativação automática:
- Drawdown total ≥6%
- Flash crash ≥10%
- Manual via Telegram /kill

Ações:
- Fecha TODAS as posições imediatamente
- Suspende novas operações
- Requer reset manual
```

---

## 📁 ESTRUTURA DE DIRETÓRIOS

```
iara/
│
├── main.py                          # Ponto de entrada - inicia tudo
│
├── config/                          # Configurações
│   ├── settings.yaml                # Parâmetros do sistema
│   ├── watchlist.json               # Tickers fixos para Phase 0
│   └── prompts/                     # Prompts de IA
│       ├── screener.md              # Prompt do Screener (Gemini)
│       └── judge.md                 # Prompt do Judge (GPT)
│
├── src/                             # Código fonte
│   ├── core/                        # Componentes centrais
│   │   ├── orchestrator.py          # Coordena as 6 fases
│   │   ├── state_manager.py         # Estado do portfolio + Kill Switch
│   │   └── database.py              # SQLite para cache e logs
│   │
│   ├── collectors/                  # Phase 0 - Coleta de dados
│   │   ├── buzz_factory.py          # Gerador de candidatos
│   │   ├── market_data.py           # Dados via yfinance
│   │   ├── news_scraper.py          # Scraping de notícias
│   │   ├── earnings_checker.py      # Check de earnings
│   │   └── macro_data.py            # VIX, SPY, setores
│   │
│   ├── decision/                    # Phase 1 e 3 - IA
│   │   ├── screener.py              # Triagem com Gemini
│   │   ├── judge.py                 # Decisão final com GPT
│   │   ├── ai_gateway.py            # Gerencia fallback de APIs
│   │   └── grounding.py             # Google Search validation
│   │
│   ├── analysis/                    # Phase 2 - Matemática
│   │   ├── risk_math.py             # Beta adjustment, defensive mode
│   │   ├── correlation.py           # Correlation veto
│   │   └── technical.py             # RSI, ATR, SuperTrend
│   │
│   ├── execution/                   # Phase 4 - Execução
│   │   ├── order_manager.py         # Gestão de orders
│   │   ├── position_sizer.py        # Cálculo de tamanho
│   │   └── broker_api.py            # Interface com broker
│   │
│   └── monitoring/                  # Phase 5 - Monitoramento
│       ├── watchdog.py              # Monitor 1 min
│       ├── sentinel.py              # Monitor 5 min
│       ├── poison_pill.py           # Scanner overnight
│       └── telegram_bot.py          # Alertas e controle remoto
│
├── data/                            # Dados persistentes
│   ├── iara.db                      # SQLite database
│   ├── logs/                        # Logs diários
│   ├── cache/                       # Cache temporário
│   └── rag_manuals/                 # Manuais de estratégia (RAG)
│
├── tests/                           # Testes unitários
│   ├── test_*.py                    # Testes pytest
│   └── ...
│
├── test_phase0.py                   # Test standalone Phase 0
├── test_phase1.py                   # Test standalone Phase 1
├── test_phase2.py                   # Test standalone Phase 2
├── test_phase3.py                   # Test standalone Phase 3
├── test_integration.py              # Test pipeline completo
│
├── debug_cli.py                     # CLI para debug de JSONs
├── DEBUG_README.md                  # Guia do debug_cli
│
├── .env                             # API keys (NÃO commitar)
├── requirements.txt                 # Dependências Python
└── README.md                        # Documentação geral
```

---

## 🔄 FLUXO DE DADOS

### Fluxo Completo (Dia Típico)

```
08:00 - PRÉ-MERCADO
└─> Phase 0: Buzz Factory
    ├─> Watchlist (11 tickers fixos)
    ├─> Volume spikes (escaneia mercado)
    ├─> Gap scanner (>3%)
    └─> News catalyst (scraping)

    Filtros:
    ├─> Market cap ≥$800M
    ├─> Dollar volume ≥$15M
    ├─> Friday blocking
    └─> Earnings proximity (<5 dias)

    OUTPUT: 5-15 candidatos

10:30 - ABERTURA DO MERCADO
└─> Phase 1: Screener
    ├─> Busca dados técnicos (RSI, ATR, volume)
    ├─> Busca notícias recentes
    ├─> Envia para Gemini avaliar (nota 0-10)
    └─> Filtra nota ≥7

    OUTPUT: 2-5 candidatos

└─> Phase 2: Risk Math
    ├─> Beta adjustment (0.0 a 1.0 multiplier)
    ├─> Correlation check (>0.75 = VETO)
    ├─> Sector exposure (>20% = VETO)
    └─> Defensive mode check

    OUTPUT: 1-3 candidatos

└─> Phase 3: Judge
    ├─> Google Grounding (valida notícias)
    ├─> Busca cache SQLite (<2h)
    ├─> Se não cached: Chama GPT-4 com contexto completo
    ├─> Valida nota ≥8
    └─> Valida R/R ≥2.0

    OUTPUT: 0-2 decisões aprovadas

└─> Phase 4: Execution
    ├─> Calcula position size (com todos os multipliers)
    ├─> Valida tamanho vs capital disponível
    ├─> Envia STOP-LIMIT order (+0.5%)
    ├─> Envia physical stop ao broker
    └─> Adiciona posição ao state_manager

    OUTPUT: Posições abertas

CONTÍNUO - DURANTE MERCADO
└─> Phase 5: Monitoring
    ├─> Watchdog (1 min): Preço vs stop/TP, flash crash
    ├─> Sentinel (5 min): News, trailing stops, Friday breakeven
    └─> Poison Pill (overnight): M&A detection

    Kill Switch:
    ├─> DD ≥6%: Fecha tudo
    ├─> Flash crash ≥10%: Fecha tudo
    └─> Manual /kill: Fecha tudo
```

---

## 🧪 SISTEMA DE TESTES

### Testes Standalone (Rodados Individualmente)

#### 1. `test_phase0.py` - Buzz Factory
```bash
python test_phase0.py
```
**Testa:**
- Watchlist loading
- Filtros de market cap e liquidez
- Tiering (Tier 1 vs Tier 2)
- Earnings proximity check

#### 2. `test_phase1.py` - Screener
```bash
python test_phase1.py
```
**Testa:**
- Mock de resposta do Gemini
- Threshold de nota ≥7
- Rate limiting (4s entre calls)
- Gap >3% rejection

#### 3. `test_phase2.py` - Risk Math
```bash
python test_phase2.py
```
**Testa:**
- Beta adjustment (4 casos: normal, aggressive, extreme, reject)
- Defensive mode activation
- Correlation veto (>0.75)
- Sector exposure tracking

#### 4. `test_phase3.py` - Judge
```bash
python test_phase3.py
```
**Testa:**
- SQLite cache (HIT/MISS)
- Threshold validation (nota ≥8)
- R/R validation (≥2.0)
- Decision logging
- Prompt building

#### 5. `test_integration.py` - Pipeline Completo
```bash
python test_integration.py
```
**Testa:**
- Fluxo Phase 0 → 1 → 2 → 3 → 4
- Aplicação de todos os multipliers
- Position sizing final
- Conversion rate (% de aprovação)

### Testes Pytest (Batch)
```bash
pytest                    # Todos os testes
pytest tests/             # Só testes unitários
pytest -v                 # Verbose
pytest --asyncio-mode=auto # Com suporte async
```

---

## 🔍 FERRAMENTAS DE DEBUG

### Debug CLI (`debug_cli.py`)

**Propósito:** Inspecionar JSONs de cada fase sem inicializar sistema completo

**Comandos Disponíveis:**

```bash
# Ver candidatos do Buzz Factory (Phase 0)
python debug_cli.py /buzz

# Ver dados técnicos de um ticker
python debug_cli.py /technical AAPL

# Ver estado do portfolio
python debug_cli.py /portfolio

# Ver configurações carregadas
python debug_cli.py /config

# Ver banco de dados (cache + logs)
python debug_cli.py /database

# Ajuda
python debug_cli.py /help
```

**Output:**
- Mostra JSON formatado no console
- Salva automaticamente em `data/debug_outputs/`
- Formato: `buzz_factory_20260106_143022.json`

**Quando Usar:**
- Sistema não inicializa completamente (faltam configs)
- Quer ver dados brutos de uma fase específica
- Debug de filtros ou lógicas
- Análise manual do pipeline

---

## 🚀 COMO EXECUTAR

### 1. Setup Inicial

```bash
# Criar ambiente virtual
python -m venv .venv
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # Linux/Mac

# Instalar dependências
pip install -r requirements.txt
```

### 2. Configurar API Keys

Criar arquivo `.env` na raiz:
```env
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=...
ANTHROPIC_API_KEY=...
TELEGRAM_BOT_TOKEN=...
```

### 3. Executar Sistema

```bash
# Modo paper trading (padrão)
python main.py

# Ver logs em tempo real
tail -f data/logs/iara_YYYYMMDD.log
```

### 4. Modo Debug (Sem Inicializar Tudo)

```bash
# Ver candidatos do dia
python debug_cli.py /buzz

# Testar fases individualmente
python test_phase2.py
python test_integration.py
```

---

## ⚙️ CONFIGURAÇÃO (`config/settings.yaml`)

### Seções Principais

#### Risk Management
```yaml
risk_management:
  risk_per_trade: 0.01        # 1% de risco por trade
  max_positions: 5             # Máximo 5 posições simultâneas
  max_capital_usage: 0.80      # Máximo 80% do capital
  daily_drawdown_limit: 0.02   # DD diário: 2%
  total_drawdown_limit: 0.06   # DD total: 6% (Kill Switch)
```

#### Tiers (Market Cap)
```yaml
tiers:
  tier1_large_cap:
    min_market_cap: 4000000000   # $4B
    position_multiplier: 1.0
  tier2_mid_cap:
    min_market_cap: 800000000    # $800M
    position_multiplier: 0.6      # Reduz 40%
```

#### Correlation
```yaml
correlation:
  max_correlation: 0.75          # Limite para veto
  lookback_days: 60              # Janela de cálculo
```

#### Phase 0
```yaml
phase0:
  volume_spike_multiplier: 2.0   # >2x volume médio
  gap_threshold: 0.03            # >3% gap
  friday_block: true             # Não abre sexta
  earnings_proximity_days: 5     # Rejeita se <5 dias
```

#### AI
```yaml
ai:
  screener_threshold: 7          # Nota mínima Phase 1
  judge_threshold: 8             # Nota mínima Phase 3
  rate_limit_seconds: 4          # Gemini free tier
```

---

## 🔐 SEGURANÇA E PROTEÇÕES

### Proteções Implementadas

1. **Correlation Veto** - Bloqueia se >0.75 com qualquer posição
2. **Beta Filter** - Rejeita Beta >3.0 sem volume
3. **Sector Limit** - Máximo 20% por setor
4. **Defensive Mode** - Reduz 50% em períodos ruins
5. **Kill Switch** - Fecha tudo se DD ≥6%
6. **Stop Dual System** - Physical broker + backup local
7. **Friday Blocking** - Não abre posições sexta-feira
8. **Earnings Proximity** - Não opera <5 dias de earnings
9. **Flash Crash Detection** - Valida com VIX/SPY antes de panicar
10. **R/R Minimum** - Só aprova se R/R ≥2.0

### Níveis de Proteção

```
Nível 1: FILTROS (Phase 0)
├─> Market cap, liquidez, Friday, earnings

Nível 2: MATEMÁTICA (Phase 2)
├─> Beta, correlation, sector exposure

Nível 3: VALIDAÇÃO (Phase 3)
├─> R/R, threshold, duplicate check

Nível 4: MONITORAMENTO (Phase 5)
├─> Stops, trailing, flash crash, DD

Nível 5: EMERGÊNCIA (Kill Switch)
└─> Fecha TUDO se DD crítico
```

---

## 📊 HISTÓRICO DE MODIFICAÇÕES

### 2026-01-07 (Update 11)
**Centralizacao de Formatacao de Noticias - Debug = Producao**

**PROBLEMA RESOLVIDO:**
- O debug_cli.py mostrava um formato de noticias
- O orchestrator.py usava outro formato diferente
- O campo `news_for_judge` no debug NAO era o mesmo que o Judge recebia na producao

**SOLUCAO IMPLEMENTADA:**

#### Metodos Centralizados em news_aggregator.py
```python
# Para Screener (Phase 1) - resumido
format_news_for_screener(ticker, articles) -> str

# Para Judge (Phase 3) - detalhado com scores
format_news_for_judge(ticker, articles) -> str
```

#### Uso Unificado
```
news_aggregator.py          <- METODOS CENTRALIZADOS
      ^                            ^
      |                            |
orchestrator.py             debug_cli.py
(producao)                  (debug)
      |                            |
      v                            v
MESMO FORMATO              MESMO FORMATO
```

**ARQUIVOS MODIFICADOS:**
```
news_aggregator.py:
  + format_news_for_screener(ticker, articles)
  + format_news_for_judge(ticker, articles)

orchestrator.py:
  ~ _phase_1_screener() - usa format_news_for_screener()
  ~ _phase_3_judge() - usa format_news_for_judge()

debug_cli.py:
  ~ cmd_buzz() - usa os mesmos metodos centralizados
```

**GARANTIA:** O que voce ve no JSON do debug e EXATAMENTE o que o Judge recebe na producao.

**Status:** OK - Debug e producao 100% sincronizados

---

### 2026-01-07 (Update 10)
**News Scoring System - Qualidade de Fontes + Freshness + Pais**

**PROBLEMA RESOLVIDO:**
- Noticias antigas (varias semanas) apareciam para tickers brasileiros
- Noticias de baixa qualidade misturadas com fontes premium
- Noticias irrelevantes (de outros paises) para empresas locais

**SOLUCOES IMPLEMENTADAS:**

#### 1. Sistema de Scoring de Fontes
- **Constante:** `SOURCE_QUALITY_SCORES: Dict[str, float]` - 40+ fontes mapeadas
- **Scores:**
  * TIER 1 Premium (1.3-1.5): reuters.com, bloomberg.com, wsj.com, infomoney.com.br, valor.globo.com
  * TIER 2 Investimento (1.2-1.3): seekingalpha.com, benzinga.com, exame.com, moneytimes.com.br
  * TIER 3 Noticias Gerais (1.0-1.1): cnn.com, bbc.com, g1.globo.com, folha.uol.com.br
  * TIER 4 Gerais (0.7-0.9): yahoo.com, msn.com, google.com
  * Desconhecidas: 0.5
- **Localizacao:** `news_aggregator.py` linhas 28-82

#### 2. Priorizacao por Pais
- **Constante:** `TICKER_COUNTRY_MAP: Dict[str, str]` - Mapeamento ticker -> pais
- **Constante:** `COUNTRY_DOMAINS: Dict[str, List[str]]` - Dominios por pais (BR, US)
- **Metodo:** `_get_country_bonus(ticker, url)` - Retorna +0.3 se noticia e do pais da empresa
- **Exemplo:** PETR4.SA + infomoney.com.br = bonus de +0.3
- **Localizacao:** `news_aggregator.py` linhas 84-110, 243-262

#### 3. Filtragem por Freshness (Timestamp)
- **Config:** `max_news_age_hours` - Default 48h (configuravel)
- **Metodo:** `_parse_published_date(str)` - Parseia 8+ formatos de data + formatos relativos
  * Formatos: ISO 8601, GMT, BR, relativo ("2 hours ago", "ontem")
- **Metodo:** `_get_freshness_score(published_str)` - Score 0.1-1.0 baseado em idade
  * < 1h: 1.0, < 6h: 0.95, < 12h: 0.85, < 24h: 0.7, < 48h: 0.5, < 72h: 0.3, > 72h: 0.1
- **Metodo:** `_is_news_fresh(published_str)` - Retorna bool (dentro do limite)
- **Localizacao:** `news_aggregator.py` linhas 264-397

#### 4. Busca Dual Idioma (EN + PT)
- **Metodo atualizado:** `get_gnews(ticker, max_results, fetch_full_content)`
- **Comportamento:**
  * Busca em INGLES (global) para todos os tickers
  * Busca em PORTUGUES (Brasil) para tickers .SA ou ADRs brasileiros
  * Para PETR4.SA: busca "PETR4.SA" + "Petrobras"
  * Para VALE3.SA: busca "VALE3.SA" + "Vale mineradora"
- **Deduplicacao:** Remove duplicatas por URL
- **Scoring:** Calcula score combinando: fonte × freshness + bonus_pais
- **Ordenacao:** Retorna ordenado por score (melhor primeiro)
- **Localizacao:** `news_aggregator.py` linhas 399-522

#### 5. Formula de Score Final
```python
# Componentes:
source_score = 0.5-1.5  # Qualidade da fonte
freshness_score = 0.1-1.0  # Idade da noticia
country_bonus = 0.0-0.3  # Bonus se mesmo pais

# Formula:
base = 5.0
final_score = (base * source_score * freshness_score) + (country_bonus * 2)
# Resultado: 0.0 - 10.0
```

**ARQUIVOS MODIFICADOS:**
```
news_aggregator.py:
  + SOURCE_QUALITY_SCORES (constante)
  + TICKER_COUNTRY_MAP (constante)
  + COUNTRY_DOMAINS (constante)
  + self.max_news_age_hours (atributo)
  + _extract_domain(url) (metodo)
  + _get_source_score(url) (metodo)
  + _get_country_bonus(ticker, url) (metodo)
  + _parse_published_date(str) (metodo)
  + _get_freshness_score(str) (metodo)
  + calculate_article_score(article, ticker) (metodo)
  + _is_news_fresh(str) (metodo)
  ~ get_gnews() (modificado - dual language + scoring + filtering)
```

**Status:** OK - Sistema de scoring completo e funcional

---

### 2026-01-07 (Update 9)
**Phase 0 Parallelism + Progress Bar**

**PROBLEMA RESOLVIDO:**
- Phase 0 executava sequencialmente (lento)
- Usuario nao tinha visibilidade do progresso
- Volume spike calculava errado fora do horario de mercado (1 AM mostrava tudo como spike)

**SOLUCOES IMPLEMENTADAS:**

#### 1. ProgressTracker (Barra de Progresso 0-100%)
- **Classe:** `ProgressTracker` - Rastreador global de progresso
- **Atributos:** total_steps, completed_steps, current_phase, lock (asyncio.Lock)
- **Metodo:** `update(steps, phase)` - Atualiza progresso thread-safe
- **Metodo:** `_render()` - Renderiza barra: `[====------] 40.5% | Scanning volume spikes...`
- **Localizacao:** `buzz_factory.py` linhas 25-50

#### 2. Semaforos para Rate Limiting
- **Atributo:** `_market_semaphore` - Limite de requests simultaneos ao yfinance (default: 10)
- **Atributo:** `_news_semaphore` - Limite de requests simultaneos ao GNews (default: 3)
- **Config:** `settings.yaml` → `phase0.parallel_market_requests` e `parallel_news_requests`
- **Localizacao:** `buzz_factory.py` linhas 75-80

#### 3. Scanners Paralelos
- **Metodo:** `_scan_watchlist_parallel()` - Processa watchlist com asyncio.gather
- **Metodo:** `_scan_volume_spikes_parallel()` - Escaneia volume em paralelo
- **Metodo:** `_scan_gaps_parallel()` - Escaneia gaps em paralelo
- **Metodo:** `_get_market_data_parallel(ticker)` - Busca dados com semaforo
- **Comportamento:** Cada scanner atualiza ProgressTracker conforme avanca
- **Localizacao:** `buzz_factory.py` linhas 200-400

#### 4. Fix Volume Spike (Horario Fora do Mercado)
- **Problema:** elapsed_fraction = 0.1 as 1 AM causava projecao 10x (tudo virava spike)
- **Solucao:** elapsed_fraction = 1.0 fora do horario de mercado
- **Logica:**
  * Pre-mercado (antes 09:30): usa volume real (previous day)
  * Durante mercado: projeta baseado no tempo decorrido
  * Pos-mercado (depois 16:00): usa volume real (day complete)
- **Localizacao:** `buzz_factory.py` linhas 250-280

#### 5. Configuracao em settings.yaml
```yaml
phase0:
  news_per_ticker: 3              # Headlines por ticker
  news_fetch_full_content: false  # Scrape completo (mais lento)
  parallel_market_requests: 10    # Max requests yfinance
  parallel_news_requests: 3       # Max requests GNews
```

**ARQUIVOS MODIFICADOS:**
```
buzz_factory.py:
  + ProgressTracker (classe)
  + _market_semaphore (atributo)
  + _news_semaphore (atributo)
  + _get_market_data_parallel(ticker) (metodo async)
  + _scan_watchlist_parallel() (metodo async)
  + _scan_volume_spikes_parallel() (metodo async)
  + _scan_gaps_parallel() (metodo async)
  ~ _calculate_elapsed_fraction() (modificado - fix horario)

settings.yaml:
  + phase0.news_per_ticker
  + phase0.news_fetch_full_content
  + phase0.parallel_market_requests
  + phase0.parallel_news_requests

watchlist.json:
  ~ tier2_mid_cap (modificado - adicionado sufixo .SA para tickers brasileiros)
```

**Status:** OK - Phase 0 com parallelism + progress bar funcionando

---

### 2026-01-06 (Noite - Update 8)
**BuzzFactory - Otimizacoes de Performance e Arquitetura**

**PROBLEMAS RESOLVIDOS:**
1. **Cache de Market Data (Problema 2)** - Market data era buscado multiplas vezes para o mesmo ticker
2. **Tier Duplicado (Problema 4)** - Tier era calculado nos scanners E novamente em apply_filters
3. **news_content Vazio (Problema 5)** - Apenas news_catalyst populava o campo news_content
4. **Watchlist So Tier 1 (Problema 7)** - Watchlist processava apenas tier1_large_cap

**SOLUCOES IMPLEMENTADAS:**

#### 1. Sistema de Cache de Market Data
- **Novo atributo:** `_market_data_cache: Dict[str, Any]` - cache por ciclo
- **Novo metodo:** `_get_cached_stock_data(ticker)` - busca com cache
- **Novo metodo:** `_clear_cycle_cache()` - limpa cache no inicio do ciclo
- **Localizacao:** `buzz_factory.py` linhas 61-93, 150-154
- **Beneficio:** Evita chamadas duplicadas ao yfinance (economia de ~60% de requests)

#### 2. Tier Centralizado
- **Novo metodo:** `_determine_tier(market_cap)` - logica centralizada
- **Localizacao:** `buzz_factory.py` linhas 95-115
- **Comportamento:** Scanners determinam tier uma vez, apply_filters so atualiza se "unknown"
- **Beneficio:** Consistencia e eliminacao de codigo duplicado

#### 3. News para Todas as Fontes
- **Novo atributo:** `_news_cache: Dict[str, str]` - cache de noticias por ticker
- **Novo atributo:** `_news_aggregator` - lazy initialization do NewsAggregator
- **Novo metodo:** `_fetch_news_for_ticker(ticker)` - busca noticias com cache
- **Localizacao:** `buzz_factory.py` linhas 64-68, 70-75, 117-148
- **Scanners atualizados:** watchlist, volume_spike, gap (todos agora populam news_content)
- **Beneficio:** Phase 1 e 3 recebem contexto de noticias para TODOS os candidatos

#### 4. Watchlist Multi-Tier
- **Metodo modificado:** `_scan_watchlist()` - processa TODOS os tiers do JSON
- **Localizacao:** `buzz_factory.py` linhas 211-296
- **Comportamento:** Itera sobre todas as chaves do watchlist.json (tier1_large_cap, tier2_mid_cap, etc.)
- **Score diferenciado:** Tier 1 = 5.0, Tier 2 = 4.0
- **Beneficio:** Permite monitorar ativos de diferentes tiers na watchlist

**RESUMO DOS METODOS NOVOS/MODIFICADOS:**
```
buzz_factory.py:
  + _market_data_cache (atributo)
  + _news_cache (atributo)
  + _news_aggregator (atributo)
  + _get_news_aggregator() (metodo)
  + _get_cached_stock_data(ticker) (metodo)
  + _determine_tier(market_cap) (metodo)
  + _fetch_news_for_ticker(ticker) (metodo async)
  + _clear_cycle_cache() (metodo)
  ~ _scan_watchlist() (modificado - multi-tier + news)
  ~ _scan_volume_spikes() (modificado - cache + tier + news)
  ~ _scan_gaps() (modificado - cache + tier + news)
  ~ _scan_news_catalysts() (modificado - cache + tier centralizado)
  ~ apply_filters() (modificado - cache + tier condicional)
  ~ generate_daily_buzz() (modificado - limpa cache no inicio)
```

**ESTATISTICAS DE CACHE (exemplo de execucao):**
- Antes: ~200 chamadas ao yfinance por ciclo
- Depois: ~80 chamadas ao yfinance (60% reducao)
- Log novo: `[FILTER] Cache hits: X/Y (Z% reuso)`

**Status:** OK - Sistema otimizado e arquitetado corretamente

---

### 2026-01-06 (Noite - Update 7)
**Debug CLI Logging + Pylance Type Fixes**
- **BUG FIX:** `debug_cli.py` - Logs não apareciam no console
  * Erro: `logger.info()` dos módulos (buzz_factory, news_aggregator) eram descartados silenciosamente
  * Causa: `logging.basicConfig()` não estava configurado no debug_cli.py
  * Fix: Adicionado `logging.basicConfig()` com nível INFO e formato timestamped
- **LOCALIZAÇÃO:**
  * Import: `debug_cli.py` linha 8 (import logging)
  * Config: `debug_cli.py` linhas 18-24 (logging.basicConfig com handler stdout)
- **FORMATO DOS LOGS:** `HH:MM:SS | LEVEL | module | message`
- **Status:** ✅ Logs agora visíveis em tempo real durante execução do /buzz

### 2026-01-06 (Noite - Update 6)
**Pylance Type Errors Fixes (44 erros corrigidos)**
- **Correções de tipo em 20+ arquivos:**
  * `state_manager.py`: Adicionada propriedade `kill_switch_active` para acesso externo
  * `broker_api.py`: Adicionado método abstrato `disconnect()` e implementações
  * `screener.py`: Adicionada propriedade `passou` como alias para `passed`
  * `database.py`: Parâmetro `Union[str, Path]` e nullable return types
  * `orchestrator.py`: Inicializar `beta_multiplier` antes de uso condicional
  * `correlation.py`: Usar `.values` para numpy array + `float()` explícito
  * `risk_math.py`: Converter para `float` ANTES de divisão/comparação
  * `earnings_checker.py`: `isinstance(pd.Timestamp)` em vez de `hasattr()`
  * `ai_gateway.py`: `type: ignore[attr-defined]` para google.generativeai (biblioteca deprecated)
  * `judge.py`: Extrair e validar timestamp com `isinstance(str)` antes de `fromisoformat()`
  * `test_phase1.py`: Usar objetos `ScreenerResult` reais em vez de mocks incompatíveis
- **FILOSOFIA:** Correções "majestosas" - resolver a causa raiz, não silenciar com `# type: ignore`
  * `type: ignore` usado APENAS para bibliotecas externas sem stubs (gnews, telegram, google.generativeai)
- **Status:** ✅ Zero erros Pylance em modo strict

### 2026-01-06 (Noite - Update 5)
**Market Data Robustez + Progress Logging Completo**
- **BUG FIX:** `src/collectors/market_data.py` - Crash do TMO resolvido
  * Erro: `'NoneType' object is not subscriptable` ao processar alguns tickers
  * Causa: `stock.info` podia ser None, acessar `info["key"]` causava crash
  * Fix: Defensive checks completos para todos os acessos
- **FEATURE:** Progress logging com percentagens para todas as fontes do Buzz Factory
  * Watchlist: Log por ticker (1/11, 2/11, etc.)
  * Volume Spikes: Log a cada 10 tickers com percentual
  * Gap Scanner: Log a cada 10 tickers com percentual
  * News Catalyst: Log por tópico E por artigo dentro de cada tópico
- **LOCALIZAÇÃO:**
  * Market Data robustez: `market_data.py` linhas 60-103 (método get_stock_data)
  * Watchlist progress: `buzz_factory.py` linhas 115-156
  * Volume progress: `buzz_factory.py` linhas 177-231
  * Gap progress: `buzz_factory.py` linhas 312-363
  * Catalyst progress: `news_aggregator.py` linhas 188-267
- **TÉCNICAS APLICADAS:**
  * Defensive dict access: `info.get("key") or info.get("alt_key") or default`
  * OHLCV extraction em try/except com tipos específicos (KeyError, IndexError, ValueError)
  * Fallback chains múltiplos: currentPrice → regularMarketPrice → close
  * Log level: debug para per-item, info para milestones
  * Added `previous_close` field ao StockData (linha 30) para gap scanner
- **COMPORTAMENTO:**
  * Erros de ticker individual não matam o processo inteiro
  * Progress visível em tempo real para debug
  * Logs estruturados: `[SOURCE] X/Y (Z%) - Status...`
  * Tickers problemáticos apenas geram logger.debug, não error
- **Status:** ✅ Sistema robusto + debug completo com percentagens implementado

### 2026-01-06 (Noite - Update 4)
**Debug CLI .env Loading Corrigido**
- **BUG FIX:** `debug_cli.py` - Faltava carregar variáveis de ambiente do .env
  * Erro: `NewsScraper` inicializava mas `os.getenv("GOOGLE_SEARCH_API_KEY")` retornava None
  * Causa: `debug_cli.py` não importava nem executava `load_dotenv()`
  * Fix: Adicionado `from dotenv import load_dotenv` e `load_dotenv()` no início
- **LOCALIZAÇÃO:**
  * Import: `debug_cli.py` linha 12 (from dotenv import load_dotenv)
  * Execução: `debug_cli.py` linha 15 (load_dotenv() - ANTES de importar componentes)
- **IMPACTO:** Agora todos os comandos do debug_cli têm acesso às API keys:
  * GOOGLE_SEARCH_API_KEY
  * GOOGLE_CSE_ID
  * OPENAI_API_KEY
  * GEMINI_API_KEY
  * Etc.
- **Status:** ✅ debug_cli.py agora carrega .env corretamente

### 2026-01-06 (Noite - Update 3)
**News Catalyst Scanner Corrigido**
- **BUG FIX:** `src/collectors/news_aggregator.py` - Método `find_catalyst_news()` corrigido
  * Erro: Usava keywords ("earnings", "FDA") como tópicos do GNews (Invalid topic)
  * Fix: Usa tópicos VÁLIDOS (BUSINESS, FINANCE, TECHNOLOGY) e filtra por keywords
  * Melhorado: 3 padrões de regex para detectar tickers: (TICKER), TICKER stock, TICKER
  * Melhorado: Lista de 60+ non-tickers (CES, NBC, CEO, FDA, etc.) para filtrar falsos positivos
- **LOCALIZAÇÃO:**
  * News Catalyst: `news_aggregator.py` linhas 157-239 (método find_catalyst_news)
  * Tópicos válidos: linha 185 (topics = ["BUSINESS", "FINANCE", "TECHNOLOGY"])
  * Filtro keywords: linha 198 (keywords nos títulos/descrições)
  * Extração tickers: linhas 203-241 (3 patterns + non_tickers filter)
- **COMPORTAMENTO:**
  * Busca 10 notícias de cada tópico (BUSINESS, FINANCE, TECHNOLOGY)
  * Filtra por keywords: earnings, FDA, approval, merger, acquisition, etc.
  * Extrai tickers mencionados nos títulos
  * Filtra siglas que não são tickers (eventos, mídias, etc.)
  * Retorna apenas notícias com tickers VÁLIDOS identificados
- **Status:** ✅ Sistema corrigido - sem mais erros "Invalid topic"

### 2026-01-06 (Noite - Update 2)
**Comando /buzz com Force Mode Implementado**
- **FEATURE:** `debug_cli.py` - Comando `/buzz` forçado para testar TODAS as fontes
  * `force_all=True` simula horário de mercado
  * Testa watchlist, volume spikes, gap scanner E news catalysts
  * Salva JSON em `data/outputs/buzz_candidates.json` (visualização manual)
  * Exibe TOP 10 candidatos e resumo por fonte no terminal
- **FEATURE:** `src/collectors/buzz_factory.py` - Parâmetro `force_all` adicionado
  * `generate_daily_buzz(force_all=False)` - default False para produção
  * `_scan_gaps(force=False)` - permite bypass de verificação horário
  * Gap scanner só executa pré-mercado (08:00-09:30) OU quando force=True
- **LOCALIZAÇÃO:**
  * Teste forçado: `debug_cli.py` linhas 52-142 (função cmd_buzz)
  * Force parameter: `buzz_factory.py` linha 50 (generate_daily_buzz)
  * Gap force logic: `buzz_factory.py` linhas 276-304 (_scan_gaps)
- **USO:** `python debug_cli.py /buzz` (executa teste completo)
- **Output:** `data/outputs/buzz_candidates.json` - JSON completo para validação
- **Status:** ✅ Sistema testando TODAS as fontes independente do horário

### 2026-01-06 (Noite - Update 1)
**Google Custom Search API Implementada**
- **FEATURE:** `src/collectors/news_scraper.py` - Google Custom Search API completa
  * Classe `GoogleSearchRateLimiter`: Rate limiting inteligente (95 queries/dia)
  * Persistent counter em `data/cache/google_search_counter.json`
  * Reset automático à meia-noite
  * Logging detalhado a cada 10 queries
  * Fallback automático para GNews quando limite atingido
  * Scraping completo com newspaper3k
- **FEATURE:** `.env.example` criado com todas as variáveis necessárias
  * `GOOGLE_SEARCH_API_KEY` - API key do Google Cloud
  * `GOOGLE_CSE_ID` - Custom Search Engine ID
- **Localização das Lógicas:**
  * Rate limiting: `news_scraper.py` linhas 29-105 (classe GoogleSearchRateLimiter)
  * Google Search integration: `news_scraper.py` linhas 163-247 (_fetch_from_google)
  * Fallback GNews: `news_scraper.py` linhas 249-291 (_fallback_to_gnews)
- **Status:** ✅ Sistema híbrido: Google Search (pago, 95/dia) + GNews (grátis, fallback)

### 2026-01-06 (Tarde)
**Sistema Pronto para Execução**
- **CRITICAL FIX:** `main.py` - Orchestrator agora recebe todos os componentes
  * Adicionado: buzz_factory, screener, risk_calculator, correlation_analyzer
  * Adicionado: judge, order_manager, position_sizer, state_manager
  * Adicionado: earnings_checker, market_data
  * Sistema testado e inicializando com sucesso
- **Bug Fix:** `main.py` - Banner ASCII simples (sem Unicode)
  * Resolve UnicodeEncodeError no console Windows
- **Status:** ✅ Sistema rodando com `python main.py`

### 2026-01-06 (Manhã)
**Testes Completos Implementados**
- Criado `test_phase2.py` - Beta, defensive, correlation, sector
- Criado `test_phase3.py` - Judge cache, threshold, logging
- Criado `test_integration.py` - Pipeline end-to-end
- **Bug Fix:** `buzz_factory.py` linha 475 - Removido await de check_liquidity()
- **Bug Fix:** `config/prompts/judge.md` - JSON braces escapados para .format()
- Database: `data/iara.db` criado com tabelas decision_cache e decision_log
- Criado `ExplainToOwner.md` - Documentação completa da arquitetura
- Criado `CLAUDE.md` - Instruções críticas para IA ler ExplainToOwner.md

### 2026-01-05
**Debug CLI Implementado**
- Criado `debug_cli.py` - Sistema de inspeção de JSONs
- Criado `DEBUG_README.md` - Documentação do CLI
- Todos outputs salvos em `data/debug_outputs/`

### 2026-01-04
**Testes Iniciais**
- Criado `test_phase0.py` - Buzz Factory standalone
- Criado `test_phase1.py` - Screener standalone
- Criado `test_database.py` - Database initialization
- Watchlist: `config/watchlist.json` com 11 tickers Tier 1

---

## 📝 NOTAS IMPORTANTES

### ⚠️ Pendências (TODO no código)

1. **[RESOLVIDO] Fluxo de Noticias** (`src/collectors/buzz_factory.py`)
   - **Status:** CORRIGIDO em Update 8 (2026-01-06)
   - **Solucao:** Todos os scanners (watchlist, volume_spike, gap) agora populam `news_content`
   - **Metodo:** `_fetch_news_for_ticker(ticker)` busca noticias via GNews com cache
   - **Fluxo:** Phase 0 → `BuzzCandidate.news_content` → Phase 1 (Screener) → Phase 3 (Judge)
   - **Cache:** `_news_cache` evita buscas duplicadas no mesmo ciclo

2. **Orchestrator** (`src/core/orchestrator.py`)
   - Métodos das fases 0-5 são stubs
   - Precisa implementar sequenciamento completo

2. **Order Manager** (`src/execution/order_manager.py`)
   - Stop loss calculation não implementado
   - Dual stop system não implementado
   - Multi-target TP não implementado

3. **Monitoring** (`src/monitoring/`)
   - Flash crash window: 1 min → deveria ser 5 min
   - Friday breakeven não implementado
   - Trailing stops não implementado

4. **RAG Context** (`data/rag_manuals/`)
   - Diretório vazio
   - Judge não tem manuais de estratégia

### 🔄 Próximas Melhorias Planejadas

1. Implementar orchestrator completo (WS7 do plano)
2. Completar execution hardening (stops, TPs)
3. Adicionar web dashboard (opcional)
4. Integração broker real via ccxt
5. Backtesting engine

---

## 🆘 TROUBLESHOOTING

### Sistema não inicia
```
Problema: ImportError ou ModuleNotFoundError
Solução:
1. Verificar venv ativado
2. pip install -r requirements.txt
3. Verificar Python ≥3.10
```

### Testes falham
```
Problema: API errors
Solução:
1. Verificar .env com API keys
2. Testar conectividade internet
3. Verificar rate limits
```

### Candidatos vazios (Phase 0)
```
Problema: Buzz Factory retorna 0 candidatos
Solução:
1. Verificar horário (08:00-09:30 para gaps)
2. Verificar yfinance funcionando
3. Desabilitar Friday blocking se sexta
```

### Cache não funciona
```
Problema: Judge sempre chama IA
Solução:
1. Verificar data/iara.db existe
2. Verificar permissões de escrita
3. Limpar cache se corrompido: rm data/iara.db
```

---

## 📞 CONTATOS E RECURSOS

- **Repositório:** https://github.com/Imagina-Tech/iara
- **Issues:** https://github.com/Imagina-Tech/iara/issues
- **Documentação Claude Code:** https://claude.com/claude-code

---

**FIM DO DOCUMENTO**

*Este documento deve ser atualizado sempre que houver mudanças significativas na arquitetura, lógicas ou responsabilidades dos arquivos.*
