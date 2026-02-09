# IARA - Explicação da Estrutura do Projeto

**Última Atualização:** 2026-02-09
**Versão:** v30.1 "Profitable Swing"

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

#### 0. DUAL BRAIN Input (2026-02-07)
```
Função: O Judge agora aceita dados de DUAS fontes independentes
Localização: judge.judge() - parâmetros alpaca_data e data_coherence
             judge._build_prompt() - injeta dados no template

Brain 1 (existente): yfinance market data + GNews + Gemini Screener
Brain 2 (novo/opcional): Alpaca Markets real-time data + Benzinga News

Regras adicionais no prompt (judge.md, regras 6-9):
- Brain 1 + Brain 2 concordam -> maior confiança
- Preços divergem > 2% entre fontes -> AGUARDAR
- Ambas fontes de notícias negativas -> REDUZIDO ou REJEITAR
- Spread > 0.5% no Alpaca real-time -> REDUZIDO (liquidez baixa)

BACKWARD COMPATIBLE: Se alpaca_data/data_coherence vazios,
o Judge opera em modo single-brain (comportamento anterior).
```

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
- Suporta paper trading local (default: `paper_local`)
- Integração Alpaca Markets (`alpaca_paper` / `alpaca_live`) via `src/execution/alpaca_broker.py`
- Integração ccxt para crypto exchanges (quando configurado)

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
├── backtest_cli.py                  # CLI do backtesting engine
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
│   │   ├── app_container.py         # DI container - centraliza criacao de componentes
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
│   │   ├── broker_api.py            # Interface com broker (factory + PaperBroker)
│   │   └── alpaca_broker.py         # Alpaca Markets integration (paper + live)
│   │
│   ├── monitoring/                  # Phase 5 - Monitoramento
│   │   ├── watchdog.py              # Monitor 1 min
│   │   ├── sentinel.py              # Monitor 5 min
│   │   ├── poison_pill.py           # Scanner overnight
│   │   └── telegram_bot.py          # Alertas e controle remoto
│   │
│   └── backtesting/                 # Backtesting Engine
│       ├── __init__.py              # Exports
│       ├── engine.py                # BacktestEngine - replays history
│       ├── data_loader.py           # HistoricalDataLoader - yfinance
│       ├── metrics.py               # BacktestMetrics - Sharpe, DD, etc
│       └── report.py                # BacktestReport - ASCII output + JSON
│
├── data/                            # Dados persistentes
│   ├── iara.db                      # SQLite database
│   ├── logs/                        # Logs diários
│   ├── cache/                       # Cache temporário
│   └── rag_manuals/                 # Manuais de estratégia (RAG)
│       ├── swing_trading_rules.md   # Regras de entrada/saida swing trading
│       ├── risk_management.md       # Gestao de risco completa
│       ├── technical_patterns.md    # Padroes tecnicos RSI/ATR/SuperTrend
│       ├── macro_context.md         # VIX/SPY/macro framework
│       └── entry_exit_criteria.md   # Criterios de entrada e saida
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

## HISTORICO DE MODIFICACOES

### 2026-02-09 (Update 53)
**NOTICIAS: Google Search Grounding - Conteudo REAL de artigos**

**Problema:** GNews RSS fornece `description` que e apenas `"titulo fonte"` (HTML stripped). Web scraping falha em sites financeiros: Reuters (401), Seeking Alpha (paywall), Barron's (paywall), CNBC (retorna menu de navegacao). Resultado: Judge recebia apenas titulos repetidos como "content".

**Solucao:** Novo metodo `get_news_digest_grounded()` em `news_aggregator.py` que usa **Gemini Flash + Google Search grounding**. Em vez de scraping individual de cada artigo, faz UMA chamada ao Gemini Flash com a ferramenta `GoogleSearch()` habilitada, que busca na web em tempo real e sintetiza noticias completas com:
- Headlines reais
- Conteudo detalhado (fatos, numeros, opiniao de analistas)
- Avaliacao de impacto para trading
- Sentimento geral (BULLISH/BEARISH/NEUTRAL/MIXED)

**Arquivos modificados:**
- `src/collectors/news_aggregator.py`: Novo metodo `get_news_digest_grounded(ticker)` (~80 linhas)
  - Usa `types.Tool(google_search=types.GoogleSearch())` no Gemini Flash
  - Async via `run_in_executor` com timeout de 45s
  - Detecta ticker brasileiro (.SA) para buscar em portugues
- `src/core/orchestrator.py:838-868`: Agora usa grounding como PRIMARIO, GNews RSS como fallback
  - Se grounding retorna conteudo (>100 chars): usa direto
  - Se falhar: cai no GNews com scraping como antes

**Hierarquia de noticias para o Judge:**
1. Gemini + Google Search grounding (conteudo real, detalhado)
2. GNews RSS + scraping (fallback - titulos com tentativa de scrape)
3. "No recent news found" (se ambos falharem)

### 2026-02-09 (Update 52)
**JUDGE: Gemini 3 Pro Preview + RAG Completo + Noticias Detalhadas + Livro de Trading**

**Problema RAG:** O `_build_prompt()` truncava o RAG context para apenas 3,000 chars (`self.rag_context[:3000]`). Os 6 manuais de estrategia totalizam ~40KB, entao o Judge recebia apenas ~7% do conteudo - basicamente 1 manual cortado pela metade.

**Fix RAG** (`src/decision/judge.py:405`):
- Removida truncagem `[:3000]`, agora passa `self.rag_context` completo
- Todos os 7 manuais (~68KB, ~17K tokens) chegam ao Judge integralmente

**Troca de modelo** (`src/decision/ai_gateway.py` + `src/decision/judge.py`):
- Novo provider `AIProvider.GEMINI_PRO` no enum (ai_gateway.py:20)
- `GeminiClient.__init__` agora aceita `model` e `timeout` parametrizaveis (ai_gateway.py:91-95)
- Criado client GEMINI_PRO com `gemini-3-pro-preview` (1M input, 65K output, timeout=90s)
- Gemini 3 Pro requer thinking mode: `thinking_budget=8192` (Flash usa `thinking_budget=0`)
- Judge mudou de `AIProvider.OPENAI` (gpt-5.2) para `AIProvider.GEMINI_PRO`
- max_tokens do Judge aumentado de 1500 para 2500
- Cadeia de fallback: GEMINI_PRO -> GEMINI -> OpenAI -> Anthropic

**Noticias melhoradas** (`src/collectors/news_aggregator.py:1124-1175` + `src/core/orchestrator.py:842`):
- Orchestrator agora passa `fetch_full_content=True` e `max_results=8` ao buscar noticias para o Judge
- `format_news_for_judge()` reformatado: inclui relevance score, freshness label, sumario geral
- Formato "NEWS DOSSIER" com metadados por artigo (relevancia, freshness, fonte)

**Livro de boas praticas** (`data/rag_manuals/trading_best_practices.md` - NOVO, ~28KB):
- Parte 1: Candlestick patterns (hammer, engulfing, morning star, doji, etc.)
- Parte 2: Chart patterns (H&S, double top/bottom, triangles, flags, cup & handle, wedges)
- Parte 3: Fibonacci (retracements, extensions, regras para swing)
- Parte 4: Volume avancado (VWAP, OBV, volume profile, volume-price relationship)
- Parte 5: News trading (classificacao por impacto, timing, sentimento, earnings rules)
- Parte 6: Psicologia (10 erros comuns, checklist emocional, quando NAO operar)
- Parte 7: Market microstructure (bid-ask, market makers, institutional signals)
- Parte 8: Risk management avancado (Kelly criterion, portfolio heat, drawdown math, correlacao em estresse)
- Parte 9: Regimes de mercado (trending vs ranging, sazonalidade, OpEx effects)
- Parte 10: Setores especificos (tech, biotech, energy, financials, consumer)
- Parte 11: Pre-market workflow e priorizacao
- Parte 12: 20 regras de ouro do trading

**Testes:** 255 passed, 0 failed.

---

### 2026-02-09 (Update 51)
**REPLAY ENGINE AUDIT FIXES - VIX, Judge Context, AGUARDAR Conflict**

Auditoria completa do replay engine com 5 agentes paralelos identificou e corrigiu 4 problemas:

**Fix 1 - VIX download retry** (`src/backtesting/data_loader.py:95-117`):
- yfinance batch download falha intermitentemente para ^VIX, ^TNX, DX-Y.NYB
- Adicionado retry individual para macro tickers que falharam no batch
- Se batch falhou, tenta `yf.download("^VIX", ...)` individualmente

**Fix 2 - VIX fallback warning** (`src/backtesting/replay_engine.py:1874-1875`):
- Quando VIX usa default 20.0 (data indisponivel), agora loga warning explicito
- Removido comentario errado "not available from yfinance easily" do DXY (DXY carrega normalmente)

**Fix 3 - Judge recebe alpaca_data e data_coherence** (`src/backtesting/replay_engine.py:1244-1252`):
- Replay nao passava esses params ao Judge (live passa ambos)
- Agora passa mensagens claras: "Brain 2 not available in replay mode" e "Single data source"
- Judge nao penaliza mais por ausencia de Brain 2

**Fix 4 - Conflito AGUARDAR removido** (`src/backtesting/replay_engine.py:1206-1216`):
- Placeholder de noticias dizia "Do NOT trigger AGUARDAR" que conflitava com judge.md regra #4
- Substituido por mensagem neutra: "Treat news sentiment as NEUTRAL"

**Testes:** 255 passed, 0 failed.

---

### 2026-02-09 (Update 50)
**HISTORICAL NEWS IN REPLAY - GNews API + SQLite Cache**

Added historical news support to the Replay Engine. Previously, replay mode skipped all news and used placeholder text telling the AI to ignore the "Catalisador" criterion. Now with the `--news` flag, the replay fetches real historical news from GNews API, caches them in SQLite, and uses them in all phases (Screener, Judge, Sentinel).

First replay fetches from API (rate-limited at ~2s/call); subsequent replays use 100% SQLite cache hits (instant).

**Novo arquivo:**
- `src/backtesting/historical_news.py`: `HistoricalNewsProvider` class
  - Cache-first: SQLite -> GNews API fallback
  - `get_news_for_date(ticker, sim_date)`: main entry point
  - `prefetch_news_batch(tickers, dates)`: bulk pre-fetch
  - `_recalculate_freshness()`: freshness relative to sim_date (not datetime.now())
  - `analyze_news_impact()`: Sentinel-like AI analysis for Phase 5

**Arquivos modificados:**
- `src/core/database.py`: New tables `historical_news` + `historical_news_empty` (no-news marker). Methods: `get_historical_news()`, `save_historical_news()`, `has_historical_news()`, `mark_no_news()`
- `src/backtesting/replay_engine.py`:
  - Constructor: accepts `news_enabled` flag, initializes `HistoricalNewsProvider` + `NewsAggregator`
  - Phase 0: fetches news as catalyst indicator (`has_news_catalyst`, `news_articles` in candidate dict)
  - Phase 1: real `format_news_for_screener()` instead of placeholder (backward-compat: placeholder if no news)
  - Phase 3: real `format_news_for_judge()` instead of placeholder
  - Phase 5b: new `_phase5_news_check()` - AI analyzes news impact, CRITICAL+EXIT_NOW+conf>=0.7 closes position
  - `_phase0_historical` converted to async (needs `await` for news fetch)
  - Stats: `news_api_calls`, `news_cache_hits`, `news_exits` tracked in `ai_stats`
- `config/settings.yaml`: New `replay.news` block (enabled, prefetch, gnews_delay_seconds, max_articles, window_days, fetch_full_content, validate_gemini, sentinel_ai_analysis)
- `replay_cli.py`: New flags `--news` (enable) and `--prefetch-news` (bulk pre-fetch). Banner shows news status. AI usage section shows news stats.

**CLI usage:**
```
python replay_cli.py --start 2026-01-01 --end 2026-01-10 --tickers AAPL,MSFT --news
python replay_cli.py --start 2025-01-01 --end 2025-12-31 --news --prefetch-news
```

**SQLite schema (historical_news):**
- `ticker TEXT, sim_date TEXT, title TEXT, url TEXT, published TEXT, description TEXT, source TEXT, source_type TEXT, language TEXT, full_content TEXT, source_quality REAL, gemini_confidence REAL, gemini_validated INTEGER`
- UNIQUE constraint on (ticker, url, sim_date)
- Separate `historical_news_empty` table marks ticker+date with no results (prevents re-fetching)

---

### 2026-02-09 (Update 49)
**UNIFIED STATE - 3 interrelated state management fixes**

Consolidated 3 independent JSON files into a single unified state file with atomic writes, added mid-phase crash recovery, and guardian state persistence.

**Problem 4 - State File Consolidation:**
- Merged `data/state_snapshot.json`, `data/pipeline_state.json`, and `data/event_log.json` into single `data/iara_state.json`
- Unified file has `version: 2` schema with sections: core state, pipeline, guardian, events
- Pipeline and event data now stored in-memory (`_pipeline_data`, `_events`, `_guardian_state`) and persisted via `save_state()`
- Automatic migration from legacy files: if `iara_state.json` doesn't exist, loads from old files and next `save_state()` creates unified
- `save_state()` default path changed from `data/state_snapshot.json` to `data/iara_state.json`
- `load_state()` tries unified first, falls back to legacy for migration
- `log_event()` now appends to in-memory list (no disk I/O per event), persisted with periodic save
- `get_recent_events()` reads from in-memory list
- Tests pass explicit filepath for isolation (backward compat)

**Problem 5 - Mid-Phase Crash Recovery:**
- Added `mark_phase_start(phase)` method to StateManager - marks phase as "running" and persists immediately
- `save_pipeline_state()` now accepts `status` parameter: "running", "completed", "failed"
- `get_last_completed_phase()` now only counts phases with `status="completed"` (not "running")
- Orchestrator's `_restore_pipeline_state()` checks phase status: "running" = crashed, re-run; "completed" = restore data
- Added `mark_phase_start()` calls at start of phases 0-4 in orchestrator

**Problem 6 - Guardian State Persistence:**
- Watchdog: added `get_state_snapshot()` (serializes prices, history, alerts to JSON) and `restore_state()` (deserializes back)
- Sentinel: added `get_state_snapshot()` (serializes seen headlines) and `restore_state()` (deserializes back)
- StateManager: added `save_guardian_state(watchdog_state, sentinel_state)` and `get_guardian_state()`
- `main.py`: restores guardian state after creating watchdog/sentinel; saves in `state_saver_loop()` and `finally` block
- `iara_gui.py`: same changes - restores after creation, saves in `state_saver_loop()` and `_cleanup()`

**Arquivos modificados:**
- `src/core/state_manager.py` - Unified state file, in-memory pipeline/events/guardian, mark_phase_start, migration
- `src/core/orchestrator.py` - mark_phase_start() calls in phases 0-4, crash recovery status check
- `src/monitoring/watchdog.py` - get_state_snapshot(), restore_state()
- `src/monitoring/sentinel.py` - get_state_snapshot(), restore_state()
- `main.py` - Guardian state restore/save in state_saver_loop/finally
- `iara_gui.py` - Guardian state restore/save in state_saver_loop/_cleanup
- `tests/test_state_manager.py` - Updated to verify unified format (version, pipeline, guardian, events keys)
- `tests/test_integration_pipeline.py` - Removed references to deleted EVENT_LOG_FILE/PIPELINE_STATE_FILE attributes

**All 255 tests pass.**

---

### 2026-02-09 (Update 48)
**DI CONTAINER - AppContainer eliminates duplicated wiring**

Created `src/core/app_container.py` with `AppContainer` class that centralizes ALL component
creation previously duplicated between `main.py` and `iara_gui.py`. Uses lazy initialization
with caching (get-or-create pattern via @property). All imports are deferred inside each
property to avoid import-order issues.

**Arquivos novos:**
- `src/core/app_container.py` - DI container with 21 lazy-init properties + async `connect_broker()`

**Arquivos modificados:**
- `main.py` - Replaced ~110 lines of manual wiring (lines 73-186) with 22 lines using AppContainer
- `iara_gui.py` - Replaced ~130 lines of manual wiring (lines 209-338) with 28 lines using AppContainer

**Bug fixed:**
- `iara_gui.py` Sentinel was missing `market_data` and `technical_analyzer` params (line 313-314).
  AppContainer always provides them, fixing the inconsistency with `main.py`.

**Key design decisions:**
- Lazy imports inside each property (no module-level imports from src.*)
- Broker fallback logic (alpaca -> paper_local) centralized in `connect_broker()`
- When broker fallback triggers, `order_manager` cache is cleared so it gets recreated with new broker
- All 255 existing tests pass unchanged

---

### 2026-02-09 (Update 47)
**INTEGRATION TESTS - Cross-Component Pipeline Tests**

Added integration test file that verifies IARA components work together correctly. Uses real component classes (StateManager, PaperBroker, OrderManager, CorrelationAnalyzer, ExitRules, PositionSizer, RiskCalculator) with mocked external dependencies.

**Arquivos novos:**
- `tests/test_integration_pipeline.py` - 38 tests across 6 categories.

**Categories (38 tests total):**
- Position Lifecycle (6): open via PaperBroker, close at market, position sizing math, OCO fill cancels other leg, max positions enforcement, entry creates STOP_LIMIT
- Risk Management (9): DD triggers kill switch, daily DD blocks trades, correlation blocks correlated assets, correlation allows uncorrelated, defensive mode halves position, healthy mode 1.0x, beta rejects without volume, beta allows with volume, defensive multiplier halves sizing
- Exit Rules (9): trailing stop ratchets up, trailing stop never loosens, Friday breakeven flow, insufficient profit no breakeven, backup stop catches crash, backup stop normal, max holding forces exit, max holding within limit, flash crash detection
- State Persistence (4): save/load roundtrip, crash recovery detects downtime, pipeline state persistence, kill switch persists
- Kill Switch (4): activation clears positions + callbacks, deactivation restores RUNNING, drawdown cascade, pending close tickers consumed
- Cross-Component (6): full entry flow sizing-to-broker, correlation+risk+sizing Phase 2 flow, exit rules + order manager stop calc, PaperBroker balance consistency, position sizer 20% cap, event logging

**Total: 38 tests, all passing.**

---

### 2026-02-09 (Update 43)
**UNIT TESTS - Monitoring Modules (Watchdog + Sentinel)**

Added comprehensive unit tests for the monitoring layer (Phase 5).

**Arquivos novos:**
- `tests/test_monitoring.py` - 33 tests covering Watchdog (17) and Sentinel (16).

**Watchdog tests (17):**
- Flash crash detection (4): normal price no alert, >3% drop triggers crash, >3% spike triggers spike, isolated vs market-wide level check
- Stop loss violation (4): LONG stop violated, LONG price above stop (no alert), SHORT stop violated, auto-close via order_manager
- Take profit (2): LONG TP hit, LONG below TP (no alert)
- Panic protocol (3): DD < 4% no action, DD >= 4% closes all + kill switch, panic sends EMERGENCY alert
- Deduplication (2): duplicate stop within 5min suppressed, stop after 5min generates new alert
- Lifecycle (2): start/stop halts loop, get_status returns expected keys

**Sentinel tests (16):**
- Trailing stops (4): LONG profitable moves stop up, never loosens, skips when no market_data, SHORT moves stop down
- Friday breakeven (4): Friday after 14:00 ET moves to breakeven, before 14:00 no change, non-Friday no change, insufficient profit no change
- News alerts (4): CRITICAL+EXIT_NOW closes position, NEGATIVE calls judge, positive no alert, AI failure generates precautionary NEGATIVE
- Deduplication (1): duplicate headline skipped on second scan
- Lifecycle (3): start/stop, get_status, cleanup_old_headlines removes >24h entries

**Total: 33 tests.**

---

### 2026-02-09 (Update 42)
**UNIT TESTS - Execution Modules (OrderManager + PaperBroker)**

Added comprehensive unit tests for the execution layer (Phase 4).

**Arquivos novos:**
- `tests/test_order_manager.py` - 30 tests covering OrderManager: entry orders (4), stop loss calculation (8), OCO orders (4), take profit (4), close position (3), update stop (2), order monitoring (5). Uses MockBroker, FailingBroker, OCOBroker mock classes.
- `tests/test_broker.py` - 19 tests covering PaperBroker: connection (2), balance (2), order types (6), position tracking (5), order status (2), cancel (2). Uses make_order() helper.

**Total: 49 tests, all passing.**

**Cobertura:**
- Entry orders: create_entry_order fields, LONG/SHORT stop-limit prices (+/-0.5%), broker rejection
- Stop loss: ATR-based, earnings tight 0.5%, swing_low priority, 10% cap, dual physical+backup
- OCO: TP+SL creation, native OCO support, fallback separate orders
- Take profit: 50/50 split, odd quantity handling, correct exit sides
- Close position: market order creation, pending order cancellation, failure handling
- Update stop: cancel old + create new, no existing stop returns False
- Monitoring: add/skip logic, get_monitored_orders info, timeout values (300s market, 28800s limit)
- PaperBroker: all 4 order types, insufficient balance, invalid quantity, weighted average, short selling, partial sells

---

### 2026-02-08 (Update 35)
**BACKTESTING PARITY - Full Audit + 29 gaps corrigidos**

Auditoria completa com 5 agentes em paralelo para que os modos historicos rodem IDENTICO ao pipeline live.
Duas rodadas de correcoes: 20 gaps na primeira, +9 na segunda (auditoria de verificacao).

**Rodada 1 - Reescrita inicial (20 gaps):**

**1. `src/backtesting/engine.py` (BacktestEngine) - REESCRITA COMPLETA**
- `SimulatedPosition` expandido: `original_shares`, `backup_stop`, `trailing_stop`, `atr_at_entry`, `sector`, `tp1_hit`
- `_preload_ticker_info()`, `_get_sector()`, `_determine_tier()`
- `_update_drawdown()` - Formula live: `(initial_capital - equity) / initial_capital`
- `_check_sector_exposure()` - Max 20% por setor
- Phase 0 filters: Friday block, blacklist, market cap
- `_partial_exit_tp1()` - TP1 50%, move stop breakeven
- `_check_exits()`: backup stop, trailing stop, TP1/TP2, Friday breakeven, flash crash

**2. `src/backtesting/replay_engine.py` (ReplayEngine) - 6 fixes iniciais**
- `HistoricalEarningsChecker` class, DXY via `DX-Y.NYB`, gap_pct/100.0
- earnings_checker ao screener, sector_perf ao Judge, flash crash, daily stats

**Rodada 2 - Auditoria de verificacao (+9 fixes):**

**3. Ambos engines - Weekly DD tracking (CRITICAL FIX)**
- ANTES: Defensive multiplier usava DD TOTAL >= 5% (nunca reseta)
- DEPOIS: Usa DD SEMANAL rolling 5 dias (reseta semanalmente, igual live)
- Novos metodos: `_get_weekly_drawdown()`, `_update_capital_history()`
- `_capital_history: List[Dict]` - historico de capital com max 30 dias

**4. Ambos engines - Intraday DD panic protocol (CRITICAL FIX)**
- Watchdog live fecha TUDO quando daily DD >= 4% (antes do kill switch 6%)
- Adicionado `_intraday_panic_threshold = 0.04` em ambos engines
- Se daily DD >= 4%: close all + kill switch ativo

**5. Ambos engines - Flash crash threshold 5% -> 3% (match live Watchdog)**

**6. Ambos engines - Blacklist normalizado uppercase (match live BuzzFactory)**

**7. ReplayEngine - volatility_20d usa ATR% (CRITICAL FIX)**
- ANTES: Usava annualized vol (15-40% range)
- DEPOIS: Usa ATR/Close*100 (1-3% range, igual live TechnicalAnalyzer)
- Impacto: Judge recebia magnitude 10x errada

**8. ReplayEngine - screener_dict usa __dict__ (match live orchestrator)**

**9. ReplayEngine - Judge recebe portfolio_prices (defense-in-depth)**
- ANTES: portfolio_prices={} (bypassed Judge correlation check)
- DEPOIS: Passa precos reais do portfolio ao Judge (double-check correlation)

**10. ReplayEngine - Daily DD reset timing corrigido**
- ANTES: _daily_start_equity setado DEPOIS de exits
- DEPOIS: Setado no INICIO do dia (antes de exits), igual live

**11. ReplayEngine - filter_duplicates ja estava em Phase 0**
- Verificado: Phase 0 ja checa `held_tickers` e `pending_tickers` (linha 623-629)
- Equivalente funcional ao filter_duplicates() do live

**Gaps inerentemente impossiveis (4 - requerem dados real-time):**
- Grounding Service (sem news historico)
- News-based exits / Sentinel (sem news historico)
- Poison Pill (sem news historico)
- Brain 2 Alpaca+Benzinga (sem API historica)

---

### 2026-02-08 (Update 34)
**REPLAY MODE - Full Pipeline Historical Simulation**

Novo modo "Replay" que executa o pipeline COMPLETO de 6 fases contra dados historicos, dia a dia, com chamadas REAIS de IA (Screener via Gemini + Judge via GPT-4.1).

**Arquivos novos:**
- `src/backtesting/replay_engine.py` - Motor principal do replay. Classes: `ReplayEngine`, `ReplayPosition`, `ReplayResult`, `HistoricalEarningsChecker`. Executa Phase 0-5 completo por dia, com entrada no Open do dia seguinte, trailing stop (2x ATR), kill switch a 6% DD, e rate limiting para APIs.
- `replay_cli.py` - CLI para replay. Args: --start, --end, --capital, --tickers, --threshold, --save, --trades, --verbose. Exemplo: `python replay_cli.py --start 2025-01-01 --end 2025-12-31`.
- `src/gui/replay_dialog.py` - Dialogs GUI: `ReplayConfigDialog` (config + lancamento) e `ReplayResultDialog` (metricas, trades, AI usage, save JSON).

**Arquivos modificados:**
- `src/gui/dashboard.py` - Botao "REPLAY" adicionado na action bar (cor ACCENT_AI/purple). Handler `_on_replay()` abre ReplayConfigDialog.
- `src/gui/log_handler.py` - Rota `"src.backtesting.replay_engine": "pipeline"` adicionada ao LOGGER_ROUTING.
- `src/backtesting/__init__.py` - Exporta `ReplayEngine` e `ReplayResult`.

**Diferenca do BacktestEngine existente:**
- BacktestEngine: scoring tecnico puro (0-10), opcional AI bonus via Gemini. Rapido (~1min). Agora com paridade de risk management ao live.
- ReplayEngine: pipeline COMPLETO com Screener real + Judge real + correlacao + vault. Lento (~2-3h/ano) mas realista.

**Custos estimados:** Screener = FREE (Gemini). Judge ~$0.23/call (GPT-4.1). ~$60 para 1 ano completo.

### 2026-02-08 (Update 33)
**GUI FIXES, BROKER SELECTOR, LOGGING ENHANCEMENT**

Correcoes de runtime, melhorias visuais, seletor de broker no GUI, e logging detalhado em 16 modulos.

**1. PyInstaller PROJECT_ROOT fix** - `screener.py`, `judge.py`, `buzz_factory.py` usavam `Path(__file__).parent.parent.parent` que nao funciona em .exe. Agora usam `Path.cwd()` quando `sys.frozen=True` (iara_gui.py ja faz `os.chdir(PROJECT_ROOT)` ao iniciar).

**2. Log spam fix** - `state_manager.py` `load_pipeline_state()` logava "Restored pipeline state" a cada chamada. GUI chamava isso a cada 2s via `_sync_metrics()`. Removido o logger.info da funcao.

**3. LogPanel corner fix** - `dashboard.py` LogPanel header e textbox tinham `corner_radius=0` com `padx=1`, causando quinas quadradas visíveis dentro do frame arredondado (`corner_radius=8`). Corrigido para `corner_radius=6` e `padx=2, pady=2`.

**4. Event loop crash fix** - `iara_gui.py` `stop()` crashava com `RuntimeError: Event loop is closed` ao chamar `call_soon_threadsafe` apos cleanup. Adicionado try/except RuntimeError em todos os `call_soon_threadsafe` e check `is_running()` antes de `loop.stop()`.

**5. Orchestrator idle logging** - Pipeline parecia "travada" sem atividade visivel. Adicionado log periodico (5min) explicando por que esta idle (ex: "Phase0 done (12 candidates) | Phase1 done (3 passed) | Next: Phase 2 at 11:30").

**6. Broker mode selector** - Substituido label estatico "Broker: paper_local" por `CTkOptionMenu` dropdown no status bar. 3 opcoes: paper_local, alpaca_paper, alpaca_live. alpaca_live mostra dialogo de confirmacao (dinheiro real). Altera settings.yaml e reinicia engine automaticamente.

**7. Logging enhancement (16 modulos)** - Tags detalhadas para rotear logs para os 4 paineis da GUI:
- AI ENGINE: `[JUDGE]`, `[AI-GATEWAY]`, `[GROUNDING]` tags em judge.py, ai_gateway.py, grounding.py
- GUARDIAN: tags em watchdog.py, sentinel.py, poison_pill.py, state_manager.py, order_manager.py, position_sizer.py, broker_api.py, correlation.py, risk_math.py
- PIPELINE/MARKET: logs detalhados em orchestrator.py, buzz_factory.py, screener.py, news_aggregator.py

**8. Version bump** - Dashboard header atualizado de "v29.0" para "v30.0".

**ARQUIVOS MODIFICADOS (20+):**
- `src/decision/screener.py` - Fix 1 (PROJECT_ROOT)
- `src/decision/judge.py` - Fix 1 (PROJECT_ROOT)
- `src/collectors/buzz_factory.py` - Fix 1 (PROJECT_ROOT)
- `src/core/state_manager.py` - Fix 2 (log spam)
- `src/gui/dashboard.py` - Fixes 3, 6, 8 (corners, broker selector, version)
- `iara_gui.py` - Fix 4 (event loop)
- `src/core/orchestrator.py` - Fix 5 (idle logging)
- `src/decision/ai_gateway.py` - Fix 7 (logging)
- `src/decision/grounding.py` - Fix 7 (logging)
- `src/monitoring/watchdog.py` - Fix 7 (logging)
- `src/monitoring/sentinel.py` - Fix 7 (logging)
- `src/monitoring/poison_pill.py` - Fix 7 (logging)
- `src/execution/order_manager.py` - Fix 7 (logging)
- `src/execution/position_sizer.py` - Fix 7 (logging)
- `src/execution/broker_api.py` - Fix 7 (logging)
- `src/analysis/correlation.py` - Fix 7 (logging)
- `src/analysis/risk_math.py` - Fix 7 (logging)

---

### 2026-02-08 (Update 32)
**ALL REMAINING TODOs IMPLEMENTED - v30.0 "Full Pipeline"**

9 TODOs implemented across 17 files. Zero remaining TODOs in the codebase.

**Group A: Gemini SDK Migration (4 changes)**
1. **ai_gateway.py** - GeminiClient migrated from `google.generativeai` to `google.genai` (new SDK). Uses `genai.Client(api_key=...)` + `types.GenerateContentConfig()` pattern.
2. **grounding.py** - `_gemini_verify()` migrated to same `google.genai` SDK pattern.
3. **news_aggregator.py** - `_call_gemini()` now wraps sync call in `run_in_executor()` (was blocking event loop).
4. **requirements.txt** - Added `google-genai>=1.0.0`.

**Group B: Code TODOs (6 changes)**
5. **buzz_factory.py** - Blacklist check implemented. Loads from `config.phase0.blacklist` (list of tickers). Added to `settings.yaml`.
6. **orchestrator.py** - Position value estimation now uses real capital * risk_per_trade instead of hardcoded $10,000.
7. **telegram_bot.py** - `/close` command now calls `order_manager.close_position_at_market()` for real position closing. `main.py` updated to pass `order_manager`.
8. **sentinel.py** - `_handle_negative_news()` now fetches real market data (price, volume, change%) and technical signals (RSI, ATR, trend) when available. Added `market_data` and `technical_analyzer` params. `main.py` updated.
9. **news_scraper.py** - `get_sentiment_summary()` now uses keyword-based sentiment analysis. Positive/negative keyword sets (EN+PT). Returns score in [-1.0, +1.0].
10. **macro_data.py** - `get_economic_calendar()` now returns known FOMC dates + yfinance earnings dates for major tickers (AAPL, MSFT, NVDA, AMZN, GOOGL).

**Group C: New Features (2 changes)**
11. **backtesting/engine.py** - AI scoring support via optional `ai_gateway` param. `_score_candidate_with_ai()` calls Gemini for score adjustment [-1.5, +1.5]. In-memory cache prevents duplicate calls. `_simulate_day` and `_scan_for_entries` made async.
12. **backtest_cli.py** - Added `--ai` flag to enable AI-enhanced scoring. Initializes AIGateway with dotenv.
13. **data/rag_manuals/sector_rotation.md** - New RAG manual covering sector rotation by economic cycle, VIX-based rotation rules, defensive/cyclical sectors, SPY trend integration.

**FILES MODIFIED (17):**
- `src/decision/ai_gateway.py` - Gemini SDK migration
- `src/decision/grounding.py` - Gemini SDK migration
- `src/collectors/news_aggregator.py` - run_in_executor fix
- `requirements.txt` - google-genai added
- `src/collectors/buzz_factory.py` - blacklist check
- `config/settings.yaml` - blacklist config
- `src/core/orchestrator.py` - position value calc
- `src/monitoring/telegram_bot.py` - real close
- `src/monitoring/sentinel.py` - real market data
- `src/collectors/news_scraper.py` - sentiment analysis
- `src/collectors/macro_data.py` - economic calendar
- `main.py` - pass order_manager to telegram, market_data to sentinel
- `src/backtesting/engine.py` - AI scoring
- `backtest_cli.py` - --ai flag
- `data/rag_manuals/sector_rotation.md` - new RAG manual
- `ExplainToOwner.md` - this update

---

### 2026-02-08 (Update 31)
**LOW SEVERITY BUG FIXES - 19 fixes**

Quarta e ultima rodada de correcoes (CRITICAL->HIGH->MEDIUM->LOW). 19 bugs LOW corrigidos:

1. **SQLite timeout + WAL** - `database.py` _get_connection() sem timeout. Agora usa `timeout=30.0` + `PRAGMA journal_mode=WAL` para performance.
2. **Log directory creation** - `main.py` assumia que `data/logs/` existia. Agora cria antes do FileHandler.
3. **Config-driven capital** - `main.py` capital hardcoded 100000. Agora lido de `config.risk.starting_capital`.
4. **get_event_loop() deprecated** - 25+ ocorrencias em 13 arquivos substituidas por `get_running_loop()`. Previne DeprecationWarning e crash em Python 3.12+.
5. **Volatility NaN/zero guard** - `risk_math.py` std() podia retornar NaN/0.0. Agora verifica `pd.notna()` e `> 0`.
6. **Sharpe division by zero** - `risk_math.py` Sharpe ratio agora guarda contra annual_std == 0.
7. **Position risk division** - `risk_math.py` `calculate_position_risk()` guarda contra `entry_price == 0`.
8. **Max drawdown NaN** - `risk_math.py` `_calculate_max_drawdown()` guarda contra series vazia e NaN min.
9. **CVaR empty subset** - `risk_math.py` `_calculate_cvar()` trata returns vazio e tail vazio.
10. **Returns length check** - `risk_math.py` retorna None se `len(returns) < 20`.
11. **Watchdog stale data cleanup** - `_recent_alerts` e `_price_history` agora purgam tickers de posicoes fechadas.
12. **Friday breakeven timezone** - `sentinel.py` usava `datetime.now()` para check de Friday. Agora usa Eastern timezone.
13. **Trailing stop event loop** - `sentinel.py` usava `get_event_loop()` deprecated. Corrigido.
14. **Poison pill timezone** - `should_run_scan()` usava hora local. Agora usa Eastern timezone.
15. **Poison pill tz-aware compare** - `_last_scan` (naive) vs `now` (tz-aware) causaria TypeError. Agora converte antes de comparar.
16. **Position sizer division** - `adjust_for_volatility()` dividia por `base_size.shares` que podia ser 0. Agora pre-computa seguro.
17. **TickerResolver cache cap** - Cache crescia infinitamente. Agora limitado a 500 entries.
18. **state_saver_loop robustness** - `main.py` loop nao tratava CancelledError e podia tight-loop em erro. Agora trata ambos.
19. **News aggregator event loop** - 2 ocorrencias de `get_event_loop()` corrigidas.

**ARQUIVOS MODIFICADOS (19 arquivos):**
- `src/core/database.py` - Fix 1 (timeout + WAL)
- `main.py` - Fixes 2, 3, 18 (log dir + capital + saver loop)
- `src/execution/alpaca_broker.py` - Fix 4 (get_running_loop, 8 ocorrencias)
- `src/decision/ai_gateway.py` - Fix 4 (get_running_loop)
- `src/analysis/risk_math.py` - Fixes 5-10 (NaN/zero guards)
- `src/monitoring/watchdog.py` - Fixes 4, 11 (event loop + stale cleanup)
- `src/monitoring/sentinel.py` - Fixes 12, 13 (timezone + event loop)
- `src/monitoring/poison_pill.py` - Fixes 14, 15 (timezone + tz-aware)
- `src/execution/position_sizer.py` - Fix 16 (division guard)
- `src/collectors/news_aggregator.py` - Fixes 17, 19 (cache cap + event loop)
- `src/decision/grounding.py` - Fix 4 (get_running_loop)
- `src/decision/judge.py` - Fix 4 (get_running_loop)
- `src/collectors/alpaca_data.py` - Fix 4 (get_running_loop, 4 ocorrencias)
- `src/collectors/buzz_factory.py` - Fix 4 (get_running_loop)
- `src/backtesting/data_loader.py` - Fix 4 (get_running_loop, 2 ocorrencias)
- `src/execution/broker_api.py` - Fix 4 (get_running_loop)
- `src/core/orchestrator.py` - Fix 4 (get_running_loop, 4 ocorrencias)

---

### 2026-02-08 (Update 30)
**MEDIUM SEVERITY BUG FIXES - 12 fixes**

Terceira rodada de correcoes. 12 bugs MEDIUM corrigidos:

1. **Unrealized PnL reset** - `_check_new_day()` zerava unrealized_pnl na virada do dia. Agora preserva PnL de posicoes abertas.
2. **Phase 0 race condition** - Flag `_phase0_ran_today` nao era atomica. Agora usa double-check pattern dentro do pipeline_lock.
3. **AI Gateway timeouts** - OpenAI, Anthropic e Gemini sem timeout. Agora: 30s request + 10s connect (httpx.Timeout para OpenAI/Anthropic, asyncio.wait_for para Gemini).
4. **Watchdog market-wide timeout** - VIX/SPY fetch podia bloquear o loop de 1min. Agora tem asyncio.wait_for(15s) com TimeoutError handler.
5. **PaperBroker quantity validation** - Aceitava ordens com quantity<=0. Agora valida antes de processar.
6. **Memory leaks** - 3 fixes: grounding cache prune (>100 entries), watchdog price_history cap (100/ticker), poison_pill event_history cap (500).
7. **Judge cache invalidation** - Cache key nao incluia estado do portfolio. Agora armazena portfolio_key (tickers ordenados) no DB e invalida se mudou.
8. **Judge parse failure logging** - Quando AI retornava JSON invalido, nao logava o conteudo bruto. Agora loga raw_content[:200].
9. **NewsAggregator JSON parse** - Usava rfind("}") vulneravel. Agora usa brace/bracket counting. Rate limiter atualiza timestamp antes da chamada.
10. **Broker connect cleanup** - broker.connect() falhando nao chamava disconnect(). Agora faz cleanup antes de sys.exit(1).
11. **OCO event loop** - Usava get_event_loop() (deprecated). Agora usa get_running_loop() com fallback.
12. **Watchdog price history cap** - Historico de precos por ticker agora limitado a 100 entradas.

**ARQUIVOS MODIFICADOS:**
- `src/core/state_manager.py` - Fix 1 (unrealized PnL)
- `src/core/orchestrator.py` - Fix 2 (Phase 0 lock)
- `src/decision/ai_gateway.py` - Fix 3 (timeouts)
- `src/monitoring/watchdog.py` - Fixes 4, 12 (timeout + cap)
- `src/execution/broker_api.py` - Fix 5 (quantity validation)
- `src/decision/grounding.py` - Fix 6 (cache prune)
- `src/monitoring/poison_pill.py` - Fix 6 (event history cap)
- `src/decision/judge.py` - Fixes 7, 8 (cache key + logging)
- `src/core/database.py` - Fix 7 (portfolio_key column + query)
- `src/collectors/news_aggregator.py` - Fix 9 (JSON parse + rate limit)
- `main.py` - Fix 10 (broker cleanup)
- `src/execution/order_manager.py` - Fix 11 (get_running_loop)

---

### 2026-02-08 (Update 29)
**HIGH SEVERITY BUG FIXES - 8 fixes**

Continuacao da auditoria completa. 8 bugs HIGH corrigidos (apos 10 CRITICAL no Update 28):

1. **Watchdog sync blocking** - `_check_market_wide_crash()` chamava yfinance diretamente (sync), bloqueando o event loop. Agora usa `run_in_executor` com funcao agrupada para VIX+SPY.
2. **Correlation NaN fail-safe** - NaN retornava 0.0 (permite entrada). Agora retorna 1.0 (bloqueia). Mesmo para excecoes. Principio: "na duvida, bloqueia".
3. **Grounding word-matching** - Fallback verificava apenas 3 palavras em comum (qualquer palavra). Agora filtra stop words, exige 40%+ overlap E min 3 palavras, e multiplica confianca por 0.7.
4. **Macro data stale flag** - Quando macro fetch falha, usava VIX=20 silenciosamente. Agora marca `_stale: True` e injeta WARNING no coherence_text para o Judge.
5. **OCO task GC risk** - `asyncio.create_task` sem armazenar referencia podia ser coletado pelo GC. Agora armazena em `_background_tasks` com done_callback para cleanup.
6. **Friday blocking timezone** - Usava `datetime.now()` (timezone local). Agora usa `datetime.now(et_tz)` com Eastern timezone (America/New_York).
7. **SuperTrend KeyError** - Acessava `std_col` sem verificar se existia nas colunas. Agora verifica `std_col in supertrend.columns` com fallback "neutral".
8. **RSI/ATR NaN guard** - RSI e ATR podiam retornar NaN do pandas_ta. Agora verifica `pd.isna()` com defaults seguros (RSI=50, ATR=0).

Bonus: `get_diversification_score()` agora trata NaN na matriz de correlacao e clampa resultado em [0.0, 1.0].

**ARQUIVOS MODIFICADOS:**
- `src/monitoring/watchdog.py` - Fix 1 (run_in_executor para yfinance)
- `src/analysis/correlation.py` - Fix 2 (NaN->1.0) + Bonus (diversification NaN)
- `src/decision/grounding.py` - Fix 3 (stop words + ratio matching)
- `src/core/orchestrator.py` - Fix 4 (_stale flag + warning injection)
- `src/execution/order_manager.py` - Fix 5 (_background_tasks list)
- `src/collectors/buzz_factory.py` - Fix 6 (Eastern timezone)
- `src/analysis/technical.py` - Fixes 7-8 (SuperTrend guard + RSI/ATR NaN)

---

### 2026-02-08 (Update 28)
**CRITICAL SEVERITY BUG FIXES - 10 fixes**

Auditoria completa de 5 camadas com agentes paralelos. 122 issues encontrados (72 unicos). 10 CRITICAL corrigidos:

1. **Kill Switch ilusorio** - `activate_kill_switch()` apenas logava sem fechar posicoes. Agora remove posicoes do state e armazena em `_pending_close_positions`.
2. **Total Drawdown inexistente** - Sistema so calculava DD diario. Adicionado `get_total_drawdown()` com unrealized PnL.
3. **`.seconds` vs `.total_seconds()`** - `timedelta.seconds` retorna 0-59, nao o total. Corrigido em 2 locais no buzz_factory.
4. **Race condition no pipeline** - Fases 1-4 sem lock. Adicionado `asyncio.Lock()` no orchestrator.
5. **JSON parsing fragil** - Cada AI client tinha parser proprio com bugs. Criado `_try_parse_json()` global com 3 estrategias (regex, brace counting).
6. **Correlation apos cache** - Judge verificava correlacao DEPOIS do cache. Movido para ANTES (portfolio pode ter mudado).
7. **PaperBroker preco zero** - Ordem market sem preco caía em fallback inexistente. Agora tenta current_price, limit/stop, yfinance.
8. **Position sizer 0 shares** - `int(risk/risk_per_share)` podia dar 0. Agora `max(1, ...)`.
9. **update_stop_order IndexError** - Acessava `stop_orders[0]` sem verificar lista vazia. Agora extrai quantidade com guard.
10. **Sentinel AI failure silenciosa** - AI retornando None ignorava a noticia. Agora gera alerta precaucionario NEGATIVE.

Bonus: Escrita atomica do state_snapshot.json (tmp+rename) e flag de fase setado APOS conclusao.

**ARQUIVOS MODIFICADOS:**
- `src/core/state_manager.py` - Fixes 1, 2, Bonus (atomic write)
- `src/collectors/buzz_factory.py` - Fix 3
- `src/core/orchestrator.py` - Fix 4, Bonus (phase flag)
- `src/decision/ai_gateway.py` - Fix 5
- `src/decision/judge.py` - Fix 6
- `src/execution/broker_api.py` - Fix 7
- `src/execution/position_sizer.py` - Fix 8
- `src/execution/order_manager.py` - Fix 9
- `src/monitoring/sentinel.py` - Fix 10

---

### 2026-02-07 (Update 27)
**GUI AUDIT - 10 bugs corrigidos**

Auditoria completa de todos os arquivos da GUI. Bugs encontrados e corrigidos:

1. **Version mismatch** - dashboard.py e iara_gui.py diziam "v28.0", corrigido para "v29.0"
2. **Unused imports** - Removidos `tkinter as tk`, `Callable` (dashboard.py), `Optional` (log_handler.py)
3. **Log trimming off-by-one** - LogPanel.append() deletava 0 linhas quando line_count=801 (delete "1.0" to "1.0"). Corrigido com calculo `excess + 1`
4. **daily_pnl nao existe** no StateManager - Dashboard lia atributo inexistente, agora usa `daily_stats.realized_pnl + unrealized_pnl`
5. **total_drawdown_pct nao existe** - Substituido por `get_current_drawdown() * 100`
6. **daily_drawdown_pct nao existe** - Mesma correcao na Capital Detail dialog
7. **starting_capital nao persistido** - Adicionado `self.starting_capital` ao StateManager, salvo em `to_dict()` e restaurado em `load_state()`
8. **Restart bloqueava GUI** - `engine.restart()` tinha `sleep(2)` + `join(10)` no main thread. Agora roda em daemon thread
9. **take_profit_1 nao existe** no Position - Positions dialog usava atributo errado, corrigido para `take_profit`
10. **Sem feedback no TEST PIPELINE** - Clique silencioso quando engine parada, agora mostra "ENGINE: NOT RUNNING"
11. **Trades Today e Win Rate nunca atualizados** - Adicionado leitura de `daily_stats.trades_count` e `daily_stats.wins`

**ARQUIVOS MODIFICADOS:**
- `src/gui/dashboard.py` - Fixes 1-6, 8-11
- `src/gui/log_handler.py` - Fix 2 (unused Optional import)
- `src/core/state_manager.py` - Fix 7 (starting_capital persistence)
- `iara_gui.py` - Fix 1 (version string)

---

### 2026-02-07 (Update 26)
**GUI DASHBOARD + .EXE PACKAGING**

Interface visual completa com 4 paineis de log em tempo real + empacotamento .exe.

**ARQUIVOS CRIADOS:**

#### `src/gui/__init__.py`
- Package init

#### `src/gui/theme.py`
- Constantes visuais: cores (dark tech, glassmorphism), fontes, tamanhos
- 4 panel configs: Pipeline (blue), Market Data (green), AI Engine (purple), Guardian (orange)
- Log level colors: DEBUG (dim), INFO (white), WARNING (amber), ERROR (red), CRITICAL (bright red)

#### `src/gui/log_handler.py`
- `GUILogHandler` - Custom logging handler com queue thread-safe
- `classify_logger()` - Roteia loggers para paineis corretos:
  * Pipeline: orchestrator, buzz_factory, news_aggregator, IARA
  * Market: market_data, macro_data, alpaca_data, technical
  * AI: screener, judge, ai_gateway, grounding
  * Guardian: watchdog, sentinel, poison_pill, risk_math, correlation, broker
- `GUILogRecord` - Lightweight record para consumo pela GUI

#### `src/gui/dashboard.py`
- `IaraDashboard(ctk.CTk)` - Janela principal com layout completo:
  * Header: titulo IARA + relogio ET + status do mercado (OPEN/CLOSED/PRE-MARKET)
  * Phase Bar: indicador visual Phase 0-5 (pending/active/completed) + uptime
  * Log Grid 2x2: 4 paineis com scrolling, tags coloridas, contador de linhas, botao CLR
  * Metrics Bar: Capital, Daily P&L, Total P&L, Drawdown, Positions, VIX, Trades Today, Win Rate
  * Status Bar: Engine status + spinner, API dots (OpenAI/Gemini/Anthropic), Broker, Kill Switch
  * Action Bar: RESTART, TEST PIPELINE, POSITIONS, CAPITAL DETAIL, CLEAR LOGS, KILL SWITCH
- `LogPanel` - Widget de painel individual com header colorido + textbox scrollable
- `MetricCard` - Card de metrica com label + valor
- `StatusDot` - Indicador verde/cinza para status de APIs
- Dialogs: Positions (tabela), Capital Detail (overview completo), Kill Switch (confirmacao), Restart
- Auto-scroll inteligente (nao scroll se usuario esta lendo historico)
- Polling: logs a cada 100ms, clock a cada 1s, metrics a cada 2s

#### `iara_gui.py`
- Entry point principal da GUI
- `EngineController` - Bridge thread-safe entre GUI (main thread) e engine (daemon thread)
  * `start()` - Inicia engine em thread separada com event loop proprio
  * `stop()` - Para engine graciosamente (cancela tasks, cleanup, save state)
  * `restart()` - Stop + delay + start
  * `_engine_main()` - Inicializa TODOS componentes (identico ao main.py) em async
  * Expoe: state_manager, orchestrator, ai_gateway, macro_data para GUI ler
- Engine roda em daemon thread (morre automaticamente ao fechar GUI)

#### `build_exe.py`
- Script de build com PyInstaller
- Modo `--onedir` + `--windowed` (sem console)
- Inclui customtkinter data, hidden imports para todos modulos src/
- Output: `dist/IARA/IARA.exe` (469MB com dependencias)

**COMO USAR:**
```bash
# Modo desenvolvimento (com console):
python iara_gui.py

# Construir .exe:
python build_exe.py

# Rodar .exe (deve estar na pasta raiz do projeto):
dist\IARA\IARA.exe
```

**LAYOUT DO DASHBOARD:**
```
+--[IARA  v30.0                    12:30:45 PM ET | MARKET: OPEN]--+
+--[Phase: 0:Buzz  1:Screener  2:Vault  3:Judge  4:Exec  5:Guard]-+
+--[PIPELINE (blue)]----------+ +--[MARKET DATA (green)]----------+
|  10:30:15 [INFO] Phase 0... | |  10:30:20 [INFO] AAPL $228...  |
+-----------------------------+ +----------------------------------+
+--[AI ENGINE (purple)]-------+ +--[GUARDIAN (orange)]-------------+
|  10:31:00 [INFO] Judge...   | |  10:31:30 [INFO] Watchdog OK   |
+-----------------------------+ +----------------------------------+
+--[Capital $100K | P&L +$0 | DD 0.0% | Pos 0/5 | VIX 17.8]------+
+--[ENGINE: RUNNING | APIs: OpenAI Gemini | Broker: [paper_local v]]--+
+--[RESTART] [TEST PIPELINE] [POSITIONS] [CAPITAL] [KILL SWITCH]---+
```

**Status:** OK - Dashboard funcional, .exe construido com sucesso

---

### 2026-02-07 (Update 25)
**REAL DATA CONNECTION - Judge agora recebe dados REAIS (zero placeholders)**

O Judge (Phase 3) antes recebia dados hardcoded (RSI=50, ATR=0, VIX=20, etc).
Agora recebe dados REAIS de:

1. **TechnicalAnalyzer** (RSI, ATR, SuperTrend, Volume Ratio, Support, Resistance)
2. **MacroDataCollector** (VIX + regime, SPY price/trend/change, QQQ, DXY, 10Y Yield)
3. **CorrelationAnalyzer** (correlacao real com portfolio aberto)
4. **Sector Exposure** (exposicao real por setor)

**ARQUIVOS MODIFICADOS:**

#### `src/core/orchestrator.py`
- Constructor: novos params `technical_analyzer` e `macro_data`
- Phase 3 `_phase_3_judge()`:
  * Pre-fetch macro data UMA vez via `run_in_executor` (sync yfinance)
  * Pre-fetch portfolio prices via `run_in_executor`
  * Per-ticker: fetch historico 60d + TechnicalAnalyzer.analyze()
  * Reutiliza historico para calculo de correlacao real
  * Calcula sector exposure real
  * Todas chamadas sync (yfinance) usam `run_in_executor`
  * Fallback gracioso: se TechnicalAnalyzer/MacroData falhar, usa defaults

#### `main.py`
- Passa `technical_analyzer=technical` e `macro_data=macro_data` ao Orchestrator

#### `src/decision/judge.py`
- `_build_prompt()`: novos campos macro (vix_regime, spy_price, spy_change_pct, qqq_price, dxy_price, us10y_yield)

#### `config/prompts/judge.md`
- Secao "Analise Macro" expandida com todos campos macro reais

**ANTES (hardcoded):**
```
RSI: 50 | ATR: $0 | VIX: 20 | SPY: neutral | Correlation: 0
```

**DEPOIS (real):**
```
RSI: 68.43 | ATR: $6.00 (2.16%) | VIX: 17.76 (normal) | SPY: $690.62 (bullish, +1.92%) | Correlation: 0.153
QQQ: $609.65 | DXY: $97.68 | 10Y: 4.21%
```

**Status:** OK - Testado com dados reais AAPL/SPY/VIX

---

### 2026-02-07 (Update 24)
**BRAIN 2 - ALPACA DATA COLLECTOR (Cross-Validation Data Source)**

**CONTEXTO:**
Adicionado segundo coletor de dados independente ("Brain 2") usando Alpaca Markets API.
Brain 1 (yfinance + GNews) e Brain 2 (Alpaca) permitem cross-validacao de precos e noticias,
aumentando confiabilidade das decisoes do Judge (Phase 3).

**ARQUIVO CRIADO:**

#### `src/collectors/alpaca_data.py` (NOVO)
- Classe `AlpacaDataCollector` - coletor Brain 2 completo
- Usa `alpaca-py` SDK com TODOS os SDK calls via `run_in_executor` (sync lib em async context)
- Graceful fallback: se API keys nao configuradas, `self.available = False` e tudo retorna None/vazio
- Metodos:
  * `get_realtime_snapshot(ticker)` - Quote real-time (price, bid, ask, spread, volume)
  * `get_historical_bars(ticker, days)` - Barras OHLCV diarias (DataFrame pandas)
  * `get_news(ticker, limit)` - Noticias Benzinga via REST API (com sentiment estimado)
  * `get_market_overview(tickers)` - Snapshot batch de multiplos tickers
  * `compare_with_yfinance(ticker, yf_price)` - Cross-validacao Brain 1 vs Brain 2 (alerta se diff > 2%)
  * `format_for_judge(snapshot, news, coherence)` - Formata dados para prompt do Judge

**DETALHES TECNICOS:**
- News API usa REST direto via aiohttp (GET https://data.alpaca.markets/v1beta1/news)
- Sentiment estimation basico via keywords (positive/negative/neutral)
- Coherence check: flag warning se diferenca de preco > 2% entre fontes
- Format output claramente rotulado como "BRAIN 2 - ALPACA REAL-TIME DATA"

**VARIAVEIS DE AMBIENTE (.env):**
```
ALPACA_API_KEY=xxx     # Ja existia (usado pelo alpaca_broker.py tambem)
ALPACA_SECRET_KEY=xxx  # Ja existia
```

**Status:** OK - Brain 2 data collector funcional

---

### 2026-02-07 (Update 24)
**DUAL BRAIN ARCHITECTURE - Alpaca como segundo cerebro decisor**

A IARA agora tem DUAS linhas de pensamento independentes que convergem no Judge:

```
BRAIN 1 (yfinance + GNews + Gemini):  Dados historicos + noticias scraping
BRAIN 2 (Alpaca Real-Time + Benzinga): Cotacao real-time + noticias profissionais
                    |
                    v
        JUDGE (GPT-4.1) decide com AMBAS perspectivas
```

**ARQUIVOS CRIADOS:**
- `src/collectors/alpaca_data.py` - AlpacaDataCollector (Brain 2)

**ARQUIVOS MODIFICADOS:**
- `config/prompts/judge.md` - Novas secoes: Alpaca Data + Coerencia + 4 novas regras
- `src/decision/judge.py` - Aceita alpaca_data e data_coherence (backward compatible)
- `src/core/orchestrator.py` - Busca Brain 2 antes de chamar Judge (Phase 3)
- `main.py` - Inicializa AlpacaDataCollector quando broker=alpaca

**BACKWARD COMPATIBLE:** Em modo paper_local, Brain 2 e desativado. Judge funciona como antes.

### 2026-02-07 (Update 23)
**FULL PIPELINE PERSISTENCE + CRASH RECOVERY + EVENT LOG**

A IARA agora sobrevive a quedas de energia/internet com contexto completo.

**ARQUIVOS MODIFICADOS:**
```
src/core/state_manager.py  - Pipeline state + Event log
src/core/orchestrator.py   - Smart resume + Phase save + Event logging
```

**NOVOS ARQUIVOS DE DADOS (auto-criados):**
```
data/pipeline_state.json   - Estado do pipeline do dia (candidatos, resultados por fase)
data/event_log.json        - Log de auditoria (startup, shutdown, crash, trades, erros)
```

**O QUE PERSISTE AGORA:**
1. Capital e posicoes (ja existia) -> `data/state_snapshot.json`
2. Candidatos da Phase 0 (NOVO) -> `data/pipeline_state.json`
3. Resultados do Screener Phase 1 (NOVO)
4. Validacoes do Vault Phase 2 (NOVO)
5. Decisoes do Judge Phase 3 (NOVO)
6. Status de execucao Phase 4 (NOVO)
7. Timestamp de ultima gravacao (NOVO) - detecta downtime
8. Log de eventos completo (NOVO) -> `data/event_log.json`

**SMART RESUME (orchestrator):**
- Ao reiniciar, detecta ultima fase completada HOJE
- Pula fases ja completadas (ex: se Phase 0 e 1 ja rodaram, retoma da Phase 2)
- Restaura candidatos/resultados da memoria persistente
- Log de downtime: "System was DOWN for X minutes"

**EVENT LOG (auditoria):**
Tipos de evento: STARTUP, SHUTDOWN, CRASH_RECOVERY, PHASE_COMPLETE, PHASE_ERROR,
TRADE_EXECUTED, TRADE_ERROR, KILL_SWITCH, PIPELINE_RESTORED

### 2026-02-07 (Update 22)
**API UPDATES + COMPREHENSIVE PHASE TESTING (235/237 tests passed)**

**API CHANGES:**
- OpenAI: `gpt-4` -> `gpt-4.1` em `src/decision/ai_gateway.py` (confirmed working)
- Gemini: Tentativa de upgrade para `gemini-2.5-flash` REVERTIDA - modelo "thinking" incompativel com SDK `google.generativeai` (deprecated). Manteve `gemini-2.0-flash` (estavel).
- Anthropic: `claude-sonnet-4-5-20250929` mantido (bom custo/qualidade para fallback)

**BUG FIX:**
- `config/prompts/screener.md`: Corrigido curly braces nao-escapados que causavam KeyError no `.format()` do Python

**TESTES POR FASE (6 agentes em paralelo):**
- Phase 0 (Buzz Factory): 26/26 PASS - yfinance, GNews, volume spikes, gaps, tiers
- Phase 1 (Screener): 4/5 PASS - Gemini 2.0-flash OK, gpt-4.1 OK, fallback chain OK (1 skip: placeholder Anthropic key)
- Phase 2 (Vault): 36/36 PASS - RSI, ATR, SuperTrend, correlacao, NaN handling, diversification
- Phase 3 (Judge): 33/34 PASS - gpt-4.1 OK, trade decisions, cache, R/R validation (1 skip: no fallback keys)
- Phase 4 (Execution): 62/62 PASS - PaperBroker orders, PositionSizer, OrderManager, stop updates
- Phase 5 (Guardian): 76/76 PASS - StateManager, Watchdog, PoisonPill, Kill Switch, state persistence

**NOTA FUTURA:** Migracao de `google.generativeai` para `google.genai` (novo SDK) permitira uso de Gemini 2.5+ com thinking models.

**SCRIPTS DE TESTE CRIADOS:**
```
test_phase0_live.py  - Testa Buzz Factory com dados reais
test_phase1_live.py  - Testa Screener com Gemini API real
test_phase2_live.py  - Testa math layer com dados reais
test_phase3_live.py  - Testa Judge com OpenAI API real
test_phase4_live.py  - Testa PaperBroker e order flow
test_phase5_live.py  - Testa Guardian e state management
```

### 2026-02-07 (Update 19)
**BACKTESTING ENGINE - Replay historico com pipeline real**

**FUNCIONALIDADE:**
Motor de backtesting que replays dados historicos atraves do pipeline real do IARA (TechnicalAnalyzer, RiskCalculator, CorrelationAnalyzer, PositionSizer) sem chamadas de IA.

**ARQUIVOS CRIADOS:**
```
src/backtesting/__init__.py      - Exports do modulo
src/backtesting/engine.py        - BacktestEngine: simulacao dia-a-dia
src/backtesting/data_loader.py   - HistoricalDataLoader: yfinance async
src/backtesting/metrics.py       - BacktestMetrics: Sharpe, Sortino, DD, etc
src/backtesting/report.py        - BacktestReport: ASCII + JSON output
backtest_cli.py                  - CLI com argparse
```

**COMPONENTES:**

#### 1. HistoricalDataLoader (`data_loader.py`)
- `load_ohlcv(tickers, start, end)` - Download batch via yfinance
- `load_spy_benchmark(start, end)` - SPY para benchmark
- Todas as chamadas via `run_in_executor` (non-blocking)
- Flatten de MultiIndex columns (yfinance >= 0.2.40)

#### 2. BacktestEngine (`engine.py`) - Reescrito Update 35
- Usa componentes REAIS: TechnicalAnalyzer, RiskCalculator, CorrelationAnalyzer, PositionSizer
- Scoring tecnico puro (sem IA): RSI, trend, volume, SuperTrend, EMA
- Simulacao dia-a-dia com paridade ao pipeline LIVE:
  * Check exits: stop, TP1 parcial (50%), TP2, backup stop (-10%), trailing stop (2*ATR)
  * Friday breakeven (+0.1% para posicoes lucrativas)
  * Flash crash approximation (slippage via OHLCV)
  * Defensive multiplier (0.5x em DD alto)
  * Sector exposure check (max 20% por setor)
  * Phase 0 filters (Friday block, blacklist, market cap)
  * Drawdown formula identica ao live (initial_capital-based)
  * Daily DD tracking + reset
  * Daily win/loss/trade stats
  * Pre-load de ticker info (sector, market_cap)
- Kill Switch ativo se DD >= 6%
- Threshold de entrada configuravel (default 7.0)

#### 3. BacktestMetrics (`metrics.py`)
- Total/Annualized return
- Sharpe ratio (annualized)
- Sortino ratio (downside deviation)
- Max drawdown % e duracao em dias
- Win rate, profit factor
- Avg win/loss, best/worst trade
- Avg holding period
- Alpha vs SPY benchmark

#### 4. BacktestReport (`report.py`)
- `print_summary()` - Relatorio ASCII formatado
- `print_trade_log()` - Tabela de trades recentes
- `save_to_json()` - Export completo

#### 5. CLI (`backtest_cli.py`)
```bash
python backtest_cli.py --start 2025-01-01 --end 2025-12-31
python backtest_cli.py --start 2025-06-01 --end 2025-12-31 --capital 50000
python backtest_cli.py --start 2025-01-01 --end 2025-12-31 --tickers AAPL,MSFT,TSLA
python backtest_cli.py --start 2025-01-01 --end 2025-12-31 --save results.json
python backtest_cli.py --start 2025-01-01 --end 2025-12-31 --threshold 6.5 -v
```

**TESTE DE VALIDACAO (5 tickers, 2025 completo):**
```
90 trades | +13.27% return | Sharpe 1.08 | Max DD 4.64%
Win rate 55.6% | Profit factor 1.66 | Completed in 8.7s
```

**Status:** OK - Backtesting engine funcional e testado

---

### 2026-02-08 (Update 23)
**LOGGING AUDIT - All 4 GUI Panels Enhanced**

**CONTEXTO:**
Audit completo de logging em TODOS os modulos fonte do IARA para garantir que os 4 paineis da GUI (PIPELINE, MARKET DATA, AI ENGINE, GUARDIAN) exibam atividade detalhada e util. Adicionados/melhorados logs INFO e DEBUG em pontos-chave de decisao sem alterar nenhuma logica de negocio.

**REGRAS APLICADAS:**
- Todos os logs usam formato `[TAG]` para facil identificacao
- INFO para decisoes-chave, DEBUG para dados detalhados
- Mensagens concisas (max ~200 chars, GUI trims at 300)
- Nenhuma logica de negocio alterada

**ARQUIVOS MODIFICADOS (AI ENGINE panel):**

#### `src/decision/judge.py`
- `[JUDGE]` tags em TODOS os logs
- Correlation check: log inicio + resultado
- Grounding: log verificacao + confianca
- Dossier construction: brain mode, screener score, RSI, VIX
- AI call: provider, timing, token count
- Final verdict: decisao, score, R/R, entry/SL/TP
- Business rule overrides: score < threshold, R/R < 2.0, stop wrong side
- Post-validation: pass/fail com detalhes

#### `src/decision/ai_gateway.py`
- `[AI-GATEWAY]` tags em todos os logs
- Provider initialization: mostra modelos + contagem total
- Fallback chain: mostra ordem de tentativa
- Per-call: provider, elapsed ms, tokens, JSON parse status
- Fallback: warning com motivo e tempo
- All-providers-failed: error critico
- Per-client errors: tipo de excecao + mensagem truncada

#### `src/decision/grounding.py`
- `[GROUNDING]` tags
- Cache hit/miss com resultado
- Search query + result count
- AI vs word-matching method selection
- Final result: VERIFIED/UNVERIFIED + confianca + sources

**ARQUIVOS MODIFICADOS (GUARDIAN panel):**

#### `src/monitoring/watchdog.py`
- `[WATCHDOG]` start com config (interval, thresholds)
- Cycle count + positions monitored (every 5 cycles)
- Per-position: price, PnL%, SL/TP distances
- Panic protocol: DD value + "CLOSING ALL"

#### `src/monitoring/sentinel.py`
- `[SENTINEL]` cycle logging com posicao count
- News scan results per ticker
- Alert handling: impact, action, confidence
- Trailing stop updates: old -> new price
- Friday breakeven: per-position moves
- Judge exit calls: ticker + news headline

#### `src/monitoring/poison_pill.py`
- `[POISON]` start + scan progress
- Ticker list being scanned
- Article count per ticker
- Keyword match details
- Event summary: type, headline, impact
- Clean scan confirmation

#### `src/core/state_manager.py`
- `[STATE]` position add: full details (qty, price, SL, TP, count)
- Position remove: confirmation + remaining count
- DD check: daily + total values (debug)
- DD limits: blocking reason
- Kill switch: deactivation log
- State save: capital + position count

#### `src/execution/order_manager.py`
- `[ORDER]` all order lifecycle events
- Entry: ticker, side, qty, type, price
- OCO: TP/SL prices, direction
- Submit: success with broker_id / reject with reason
- Stop calculation: method (ATR/swing/earnings) + values
- Dual stop: physical + backup prices
- Multi-TP: quantities + prices
- Market close: ticker, direction, reason
- OCO fill: which leg triggered

#### `src/execution/position_sizer.py`
- `[SIZER]` calculation breakdown
- Invalid risk/share errors
- Cap warnings (20% max)
- Final result: shares, value, risk
- Validation: pass/fail + exposure details
- Volatility adjustment: factor + share change

#### `src/execution/broker_api.py`
- `[BROKER]` creation, connect, disconnect
- Paper broker: balance tracking

#### `src/analysis/correlation.py`
- `[CORRELATION]` per-pair check results (OK/HIGH)
- Enforce limit: PASSED/HARD VETO
- NaN handling: fail-safe block

#### `src/analysis/risk_math.py`
- `[RISK]` metrics summary: Beta, Vol, Sharpe, MaxDD, VaR
- Insufficient data warnings
- Beta adjustment reasoning
- Position risk calculations

**Status:** OK - Todos os 4 paineis GUI agora mostram atividade detalhada

---

### 2026-02-07 (Update 18)
**ALPACA BROKER INTEGRATION - Paper + Live Trading**

**CONTEXTO:**
Adicionada integracao completa com Alpaca Markets para permitir trading real (nao apenas paper local).

**ARQUIVOS CRIADOS:**

#### `src/execution/alpaca_broker.py` (NOVO)
- Classe `AlpacaBroker(BaseBrokerAPI)` - implementacao completa
- Usa `alpaca-py` SDK com TODOS os SDK calls via `run_in_executor` (sync lib em async context)
- Suporta modos: `paper=True` (paper trading) e `paper=False` (live trading)
- Implementa TODOS os metodos abstratos de `BaseBrokerAPI`:
  * `connect()` - Conecta e valida conta
  * `get_balance()` - Equity, buying power, margin
  * `get_positions()` - Posicoes abertas com P/L
  * `place_order()` - MARKET, LIMIT, STOP, STOP_LIMIT
  * `cancel_order()` - Cancela por ID (tolerante a ordens ja preenchidas)
  * `get_order_status()` - Status, filled qty, avg price
  * `disconnect()` - Cleanup
- Metodos adicionais:
  * `get_account_info()` - Detalhes da conta (equity, day trades, blocked status)
  * `place_bracket_order()` - Bracket nativo Alpaca (entry + TP + SL em uma ordem)
  * `place_oco_order()` - OCO nativo Alpaca (compativel com OrderManager.submit_oco)
  * `cancel_all_orders()` - Cancela tudo (Kill Switch)
  * `close_all_positions()` - Fecha tudo (Kill Switch)
  * `_sync_positions()` - Sincroniza posicoes existentes no startup

**ARQUIVOS MODIFICADOS:**

#### `src/execution/broker_api.py`
- Factory `BrokerAPI.create()` agora suporta:
  * `"paper"` / `"paper_local"` -> PaperBroker (existente)
  * `"alpaca_paper"` -> AlpacaBroker(paper=True)
  * `"alpaca_live"` -> AlpacaBroker(paper=False)
  * `"ccxt"` -> CCXTBroker (existente)

#### `config/settings.yaml`
- Nova secao `broker:` com `provider: "paper_local"`
- Opcoes: `paper_local`, `alpaca_paper`, `alpaca_live`

#### `main.py`
- Broker agora e config-driven: `config["broker"]["provider"]`
- Verifica sucesso da conexao e faz sys.exit(1) se falhar
- Log mostra provider em vez de hardcoded "Paper Trading"

#### `requirements.txt`
- Adicionado `alpaca-py>=0.30.0`

**VARIAVEIS DE AMBIENTE (.env):**
```
ALPACA_API_KEY=xxx
ALPACA_SECRET_KEY=xxx
```

**Status:** OK - Integracao Alpaca completa (paper + live)

---

### 2026-02-07 (Update 17)
**AUDIT COMPLETO + 17 FIXES CRITICOS - "Battle Hardened"**

**CONTEXTO:**
Audit completo do sistema IARA usando 4 agentes em paralelo. Identificados e corrigidos 17 bugs criticos que impediam o sistema de funcionar em producao. Muitos metodos eram stubs/TODO que agora estao implementados.

**BUGS CRITICOS CORRIGIDOS:**

#### Fix 1: Orchestrator timing impossivel (`src/core/orchestrator.py`)
**ANTES (Bug):** `hour == 8 and minute == 0` com sleep de 5 minutos = Phase 0 quase NUNCA executava
**DEPOIS (Fix):** Window-based scheduling com tracking diario:
```python
# Phase 0: 08:00-09:25 ET (janela de 1h25)
in_phase0_window = (hour == 8) or (hour == 9 and minute <= 25)
if in_phase0_window and self._phase0_ran_today != today:

# Phases 1-4: 10:30-15:30 ET (janela de 5h)
in_trading_window = (hour == 10 and minute >= 30) or (11 <= hour <= 15)
if in_trading_window and self._phases_1to4_ran_today != today:
```
- Adicionado `_phase0_ran_today` e `_phases_1to4_ran_today` para evitar re-execucao
- Adicionado skip de weekends
- Adicionado check de kill_switch no inicio do ciclo
- Reduzido sleep de 300s para 60s
- Erro no ciclo agora faz `await asyncio.sleep(30)` em vez de `raise` (crash)
- Adicionado `run_full_pipeline(force=False)` para testes

#### Fix 2: Orchestrator sem timezone (`src/core/orchestrator.py`)
**ANTES (Bug):** `datetime.now()` usava horario LOCAL (ex: Brazil -3h)
**DEPOIS (Fix):** Timezone do config (Eastern Time):
```python
from zoneinfo import ZoneInfo
self._tz = ZoneInfo(config.get("schedule", {}).get("timezone", "US/Eastern"))
def _now(self): return datetime.now(self._tz)
```
- `is_market_open()` agora usa timezone e skip weekends
- Localizacao: linhas 10, 52-54, 74-90

#### Fix 3: GeminiClient bloqueava event loop (`src/decision/ai_gateway.py`)
**ANTES (Bug):** `model.generate_content()` era SINCRONO dentro de `async def`
**DEPOIS (Fix):** `run_in_executor` para nao bloquear:
```python
loop = asyncio.get_event_loop()
response = await loop.run_in_executor(
    None, lambda: model.generate_content(full_prompt, generation_config=...)
)
```
- Modelo atualizado de `"gemini-pro"` para `"gemini-2.0-flash"`
- Localizacao: linhas 56-85

#### Fix 4: Anthropic Client adicionado (`src/decision/ai_gateway.py`)
**ANTES:** Fallback chain: OpenAI -> Gemini (sem Anthropic)
**DEPOIS:** Fallback chain completa: OpenAI -> Anthropic -> Gemini
```python
class AnthropicClient(BaseAIClient):
    def __init__(self, api_key, model="claude-sonnet-4-5-20250929"):
    async def complete(self, prompt, system_prompt="", temperature=0.7, max_tokens=2000):
        from anthropic import AsyncAnthropic
        client = AsyncAnthropic(api_key=self.api_key)
        ...
```
- Localizacao: linhas 184-230 (classe), 288 (inicializacao)

#### Fix 5: Kill Switch era no-op (`src/core/state_manager.py`)
**ANTES (Bug):** Kill switch so setava flag, NAO fechava posicoes
**DEPOIS (Fix):** Rastreia posicoes a fechar + callback system:
```python
self._pending_close_tickers = [p.ticker for p in self.positions]
if self._kill_switch_callback:
    await self._kill_switch_callback(self._pending_close_tickers)
```
- Adicionado `register_kill_switch_callback(callback)`
- Adicionado `get_pending_close_tickers()`
- Localizacao: metodo `activate_kill_switch()`

#### Fix 6: State persistence (crash recovery) (`src/core/state_manager.py`)
**ANTES:** Crash = perda total de tracking de posicoes
**DEPOIS:** Persistencia JSON com load/save:
```python
def save_state(filepath="data/state_snapshot.json") -> bool:
def load_state(filepath="data/state_snapshot.json") -> bool:
```
- Serializa/deserializa posicoes com datetime handling
- Chamado em main.py: load on startup, save on shutdown, periodic save every 5 min
- Localizacao: linhas 370-430

#### Fix 7: PaperBroker ignorava STOP_LIMIT (`src/execution/broker_api.py`)
**ANTES (Bug):** PaperBroker so simulava market orders (o sistema usa STOP_LIMIT como padrao!)
**DEPOIS (Fix):** Reescrita completa de `place_order()`:
- Suporta: market, limit, stop, stop_limit
- Verifica balance antes de comprar
- Calcula preco medio ponderado em acumulacao
- Suporta short sell
- Logging detalhado por tipo de ordem
- Localizacao: `PaperBroker.place_order()` (reescrito completamente)

#### Fix 8: OCO handler incompleto (`src/execution/order_manager.py`)
**ANTES (Bug):** Quando um lado do OCO executava, o outro NAO era cancelado
**DEPOIS (Fix):** Cancelamento real via broker:
```python
async def _handle_oco_fill(self, filled_order):
    # Cancela o outro lado via broker
    await self._async_cancel_broker_order(other_order)
```
- Adicionado `_async_cancel_broker_order(order)` helper
- Localizacao: metodo `_handle_oco_fill()`

#### Fix 9: close_position_at_market (NOVO) (`src/execution/order_manager.py`)
**Metodo completamente novo** para fechar posicoes imediatamente:
```python
async def close_position_at_market(self, ticker, direction, quantity, reason=""):
    side = OrderSide.SELL if direction == "LONG" else OrderSide.BUY
    # Cria market order + cancela TODOS os pending orders do ticker
```
- Usado pelo Watchdog (panic), Sentinel (critical news), Kill Switch
- Localizacao: linha 590+

#### Fix 10: update_stop_order (NOVO) (`src/execution/order_manager.py`)
**Metodo completamente novo** para atualizar stop loss:
```python
async def update_stop_order(self, ticker, new_stop_price, direction) -> bool:
    # Cancela stop antigo, cria novo (respeita backup stops)
```
- Usado pelo Sentinel (trailing stops, Friday breakeven)
- Localizacao: apos close_position_at_market

#### Fix 11: _cancel_all_ticker_orders (NOVO) (`src/execution/order_manager.py`)
**Helper novo** para cancelar todos os pending orders de um ticker:
```python
async def _cancel_all_ticker_orders(self, ticker, exclude_id=""):
```
- Localizacao: apos update_stop_order

#### Fix 12: Watchdog panic protocol funcional (`src/monitoring/watchdog.py`)
**ANTES (Bug):** Panic protocol so logava, NAO fechava posicoes
**DEPOIS (Fix):** Fecha posicoes via order_manager:
```python
def __init__(self, config, market_data, state_manager, order_manager=None):
    self.order_manager = order_manager

async def _check_intraday_dd_panic(self):
    if self.order_manager:
        await self.order_manager.close_position_at_market(
            position.ticker, position.direction, position.quantity,
            reason=f"PANIC: DD {current_dd:.2%}")
```
- Envia alerta via handlers apos panic
- Localizacao: `__init__()` e `_check_intraday_dd_panic()`

#### Fix 13: Sentinel trailing stops + Friday breakeven (`src/monitoring/sentinel.py`)
**ANTES (Bug):** Trailing stops e Friday breakeven eram TODO stubs
**DEPOIS (Fix):** Implementacoes reais:
- `start()` agora chama `update_trailing_stops()` e `check_friday_breakeven()` cada ciclo
- Trailing stops usam `order_manager.update_stop_order()`
- Friday breakeven usa `order_manager.update_stop_order()`
- `call_judge_for_exit()`: news CRITICAL agora chama `close_position_at_market()`
- Constructor recebe `judge=None, order_manager=None`

#### Fix 14: DataFrame mutation em TechnicalAnalyzer (`src/analysis/technical.py`)
**ANTES (Bug):** `df["RSI"] = ...` mutava DataFrame do caller
**DEPOIS (Fix):** `df = df.copy()` no inicio de `analyze()`
- Adicionados null checks para RSI e ATR series com fallback values
- Localizacao: linha 70

#### Fix 15: Correlation NaN handling (`src/analysis/correlation.py`)
**ANTES (Bug):** Correlation podia retornar NaN, causando comportamento indefinido
**DEPOIS (Fix):**
```python
corr = aligned.iloc[:, 0].corr(aligned.iloc[:, 1])
if pd.isna(corr):
    return 0.0
return float(corr)
```
- Try/except wrapper adicionado
- Return explicito float
- Localizacao: metodo `calculate_correlation()`

#### Fix 16: Judge sem validacao R/R e stop/entry (`src/decision/judge.py`)
**ANTES (Bug):** IA podia aprovar trades com R/R < 2.0 ou stop no lado errado
**DEPOIS (Fix):** Validacoes em `_parse_decision()`:
- R/R < 2.0 + APROVAR = REJEITAR automatico
- LONG com stop >= entry = REJEITAR
- SHORT com stop <= entry = REJEITAR
- `alerts` type safety (garante list)
- Localizacao: metodo `_parse_decision()` linhas 260-310

#### Fix 17: main.py integracoes + loops (`main.py`)
**Mudancas:**
- Watchdog recebe `order_manager=order_manager` (para panic protocol)
- Sentinel recebe `judge=judge, order_manager=order_manager` (para trailing/exit)
- State persistence: `load_state()` on startup, `save_state()` on shutdown
- Novo: `poison_pill_loop()` - roda a cada 30min, checa `should_run_scan()`
- Novo: `state_saver_loop()` - salva estado a cada 5min (crash recovery)
- Ambos loops adicionados ao `asyncio.gather()` de tasks

#### Fix 18: Phase 2 optimization (`src/core/orchestrator.py`)
- Pre-fetches SPY data UMA VEZ (nao por ticker)
- Pre-fetches portfolio prices UMA VEZ
- Usa `run_in_executor` para yfinance calls (non-blocking)
- Localizacao: metodo `_phase_2_vault()`

**RESUMO DE IMPACTO:**
```
ANTES: 12+ bugs criticos, stubs/TODO em metodos essenciais
DEPOIS: Sistema funcional end-to-end para paper trading

Arquivos modificados: 10
  - src/core/orchestrator.py (timing, timezone, optimization)
  - src/core/state_manager.py (kill switch, persistence)
  - src/decision/ai_gateway.py (Gemini async, Anthropic client)
  - src/decision/judge.py (R/R validation, stop validation)
  - src/analysis/technical.py (DataFrame copy, null checks)
  - src/analysis/correlation.py (NaN handling)
  - src/execution/broker_api.py (PaperBroker rewrite)
  - src/execution/order_manager.py (3 new methods + OCO fix)
  - src/monitoring/watchdog.py (panic protocol)
  - src/monitoring/sentinel.py (trailing stops, Friday breakeven, exit)
  - main.py (integrations, loops, persistence)

Metodos novos: 6
  - close_position_at_market()
  - update_stop_order()
  - _cancel_all_ticker_orders()
  - _async_cancel_broker_order()
  - save_state() / load_state()

Stubs removidos: 5
  - OCO fill handler
  - Watchdog panic close
  - Sentinel trailing stops
  - Sentinel Friday breakeven
  - Sentinel judge exit
```

**Status:** OK - Sistema "Battle Hardened" para paper trading

---

### 2026-01-07 (Update 16)
**TickerRegistry - Centralizacao de Tickers e Mapeamentos**

**PROBLEMA RESOLVIDO:**
Duplicacao de dados de tickers em multiplos arquivos:
- `news_aggregator.py` tinha COMPANY_TO_TICKER, VALID_TICKERS, TICKER_COUNTRY_MAP
- `buzz_factory.py` tinha _get_scan_universe() com lista propria
- `TickerResolver` tinha mapeamento estatico proprio (_get_static_name)

**SOLUCAO IMPLEMENTADA:**

1. **TickerRegistry Centralizado:**
   Criado `src/utils/ticker_registry.py` como fonte unica de verdade:
   ```python
   from src.utils.ticker_registry import TickerRegistry

   # Verificar se ticker e valido
   if TickerRegistry.is_valid("AAPL"): ...

   # Obter informacoes
   info = TickerRegistry.get_info("PBR")
   # -> {"name": "Petrobras", "country": "BR", "sector": "energy"}

   # Resolver empresa para ticker
   ticker = TickerRegistry.resolve_company("apple")  # -> "AAPL"
   ```

2. **Universo Expandido:**
   - **136 tickers** (antes: ~50)
   - **US:** 85 tickers (Big Tech, Finance, Healthcare, Consumer, Energy, Industrial, Semis, Software)
   - **BR:** 51 tickers (ADRs + B3)
   - **121 mapeamentos empresa->ticker** (antes: ~35)

3. **Arquivos Atualizados:**
   ```
   src/utils/ticker_registry.py (NOVO)
     + TickerInfo dataclass
     + TickerRegistry class com:
       - _REGISTRY: Dict[str, TickerInfo] - 136 tickers
       - _COMPANY_TO_TICKER: Dict[str, str] - 121 mapeamentos
       - get_universe(), get_us_tickers(), get_br_tickers()
       - get_info(), get_name(), get_country()
       - resolve_company(), is_valid()
       - yfinance fallback com cache

   src/collectors/news_aggregator.py
     ~ COMPANY_TO_TICKER = TickerRegistry.get_company_mapping()
     ~ VALID_TICKERS = TickerRegistry.get_valid_tickers_set()
     ~ TickerResolver agora usa TickerRegistry.get_info()
     ~ _get_country_bonus() usa _get_ticker_country() (nao mais TICKER_COUNTRY_MAP)

   src/collectors/buzz_factory.py
     ~ _get_scan_universe() = TickerRegistry.get_universe()
   ```

4. **Estrategia Hibrida:**
   - Dados estaticos para ~136 tickers principais (rapido, confiavel)
   - yfinance como fallback para tickers nao mapeados (lento, dinamico)
   - Cache de resultados dinamicos

**BENEFICIOS:**
- Unica fonte de verdade para todo o sistema
- Facil adicionar/remover tickers
- Universo muito maior sem duplicacao de codigo
- Menos bugs por inconsistencia entre arquivos

**Status:** OK - Unificacao completa do sistema de tickers

---

### 2026-01-07 (Update 15)
**Catalyst News - Google Search API + Validacao Gemini**

**PROBLEMA RESOLVIDO:**
1. O metodo `find_catalyst_news()` usava apenas GNews (agora usa GNews + Google Search)
2. Falsos positivos como "Wegovy" -> WEGE3.SA, "Axsome" -> PRIO3.SA (agora valida com Gemini)

**SOLUCAO IMPLEMENTADA:**

1. **Google Search em Paralelo com GNews:**
   ```python
   find_catalyst_news(use_google_search=True)  # novo parametro
   ```
   Agora busca em paralelo:
   - 4 topicos GNews (BUSINESS + TECHNOLOGY em EN + PT-BR)
   - 7 queries Google Search (catalisadores de alto impacto)

2. **Queries de Catalisadores para Google:**
   ```python
   google_search_queries = [
       "stock earnings report today",
       "FDA approval drug stock",
       "merger acquisition announcement stock",
       "stock upgrade downgrade analyst",
       "IPO stock market today",
       "acoes bovespa alta queda hoje",      # PT-BR
       "resultados trimestre empresa bolsa",  # PT-BR
   ]
   ```

3. **Validacao Gemini para Filtrar Falsos Positivos:**
   Apos extrair tickers, valida com GeminiNewsValidator:
   ```
   "Wegovy obesity pill" + WEGE3.SA -> Gemini: "Wegovy is Novo Nordisk, not WEG" -> FILTRADO
   "Axsome FDA approval" + PRIO3.SA -> Gemini: "Axsome is not PetroRio" -> FILTRADO
   ```

4. **Deduplicacao por URL + Restricao Temporal:**
   - Resultados de GNews e Google mesclados sem duplicatas
   - Google Search usa `date_restrict="d1"` (ultimas 24h)

**FLUXO ATUALIZADO:**
```
find_catalyst_news() ->
  PARALELO:
    GNews EN-BUSINESS (15 artigos)
    GNews EN-TECHNOLOGY (15 artigos)
    GNews PT-BUSINESS (15 artigos)
    GNews PT-TECHNOLOGY (15 artigos)
    Google "earnings report" (10 artigos)
    Google "FDA approval" (10 artigos)
    ... (mais queries)
  -> Dedup por URL
  -> Filtro por keywords
  -> Extracao de tickers (regex + COMPANY_TO_TICKER)
  -> VALIDACAO GEMINI (filtra falsos positivos)
  -> NewsArticle[] (apenas validados)
```

**ARQUIVOS MODIFICADOS:**
```
news_aggregator.py:1286-1577
  ~ find_catalyst_news() - novo parametro use_google_search=True
  + google_search_queries[] - 7 queries de catalisadores
  + Integracao com GoogleSearchNews.search()
  + Deduplicacao por URL (seen_urls set)
  + Validacao Gemini em batch apos extracao de tickers
  + Log com contagem separada (GNews vs Google vs filtrados)
```

**OUTPUT ESPERADO:**
```
[CATALYST] Buscando 4 GNews + 7 Google em paralelo...
[CATALYST] Extraidos: 25 candidatos (14 Google) de 126 artigos
[CATALYST] Validando 25 candidatos com Gemini...
[CATALYST] Validacao Gemini: 18 aprovados, 7 filtrados
```

**Status:** OK - Descoberta usa GNews + Google + Validacao Gemini

---

### 2026-01-07 (Update 14)
**News System - Validacao Gemini + Google Search API**

**PROBLEMA RESOLVIDO:**
Noticias irrelevantes contaminando os resultados. Exemplos:
- PBR (Petrobras) retornava "Professional Bull Riders"
- MSTR retornava noticias genericas de crypto
- Fontes limitadas apenas ao GNews

**SOLUCAO IMPLEMENTADA:**

1. **TickerResolver** - Resolve ticker para nome da empresa:
   ```python
   TickerResolver.get_search_query("PBR")  # -> "Petrobras stock"
   TickerResolver.get_search_query("MSTR") # -> "MicroStrategy bitcoin company stock"
   ```
   Usa mapeamento estatico + yfinance dinamico.

2. **GeminiNewsValidator** - Valida relevancia com IA:
   ```python
   is_relevant, confidence = await GeminiNewsValidator.validate_relevance(
       ticker="PBR",
       company_name="Petrobras",
       news_title="Professional Bull Riders announces tour..."
   )
   # -> is_relevant=False, confidence=0.95 (FILTRADO!)
   ```

3. **GoogleSearchNews** - Fonte adicional de noticias:
   ```python
   articles = await GoogleSearchNews.search(
       query="Petrobras stock",
       num_results=10,
       date_restrict="d3"  # ultimos 3 dias
   )
   ```
   Usa Google Custom Search API (100 queries/dia gratis).

**FLUXO ATUALIZADO:**
```
get_gnews() ->
  1. TickerResolver: obter nome da empresa
  2. GNews EN: buscar por nome da empresa
  3. GNews PT: buscar em portugues (se BR)
  4. Google Search: buscar via API
  5. Dedup: remover URLs duplicadas
  6. Freshness: filtrar > 48h
  7. Gemini: validar relevancia de cada artigo
  8. Score: calcular pontuacao final
  9. Return: top N artigos validados
```

**RESULTADOS DO TESTE:**
```
[PBR] Gemini filtered 7/27 irrelevant articles
      Incluindo: "Australiano vence 3a etapa da PBR" (Bull Riders)
      Resultado: Apenas noticias sobre Petrobras

[MSTR] Gemini filtered 5/22 irrelevant articles
       Resultado: Apenas noticias sobre MicroStrategy

[AAPL] Mix de fontes: GNews(1) + Google(4)
       Score mais alto: 4.7 pts (bloomberg.com)
```

**ARQUIVOS MODIFICADOS:**
```
news_aggregator.py:191-341 (NOVAS CLASSES)
  + GeminiNewsValidator - validacao de relevancia com Gemini AI
  + GoogleSearchNews - busca via Google Custom Search API

news_aggregator.py:344-420 (ATUALIZADO)
  ~ TickerResolver - mapeamento estatico expandido + yfinance

news_aggregator.py:660-877 (ATUALIZADO)
  ~ get_gnews() - parametros validate_with_gemini e use_google_search
  + Integracao com GoogleSearchNews
  + Validacao Gemini apos freshness filter
  + Log com indicador de fonte (N=GNews, G=Google)
```

**CONFIGURACAO NECESSARIA (.env):**
```
GEMINI_API_KEY=xxx        # Ja existia
GOOGLE_SEARCH_API_KEY=xxx # Para Custom Search API
GOOGLE_CSE_ID=xxx         # ID do Search Engine
```

**Status:** OK - Noticias validadas com 95%+ de precisao

---

### 2026-01-07 (Update 13)
**Phase 0 - Paralelismo VERDADEIRO das 4 Fases**

**PROBLEMA RESOLVIDO:**
As 4 fases do Phase 0 (WATCHLIST, VOLUME, GAPS, NEWS) estavam rodando SEQUENCIALMENTE.
Cada await esperava a fase anterior terminar antes de comecar a proxima.

**ANTES (Sequencial):**
```python
watchlist_candidates = await self._scan_watchlist_parallel()  # Espera terminar
volume_candidates = await self._scan_volume_spikes_parallel()  # So depois comeca
gap_candidates = await self._scan_gaps_parallel()              # So depois comeca
news_candidates = await self._scan_news_catalysts()            # So depois comeca
# Tempo total = soma de todas as fases (~1697s)
```

**DEPOIS (Paralelo):**
```python
all_results = await asyncio.gather(
    run_watchlist(),
    run_volume(),
    run_gaps(),
    run_news(),
    return_exceptions=True
)
# Tempo total = fase mais lenta (~542s)
```

**RESULTADOS DO TESTE:**
```
[02:56:31] Todas as 4 fases iniciam simultaneamente

Fase       | Tempo   | Candidatos
-----------|---------|------------
WATCHLIST  | 281.5s  | 9
NEWS       | 358.0s  | 13
VOLUME     | 514.7s  | 1
GAPS       | 542.4s  | 13
TOTAL      | 542.5s  | 36

Ganho: 3.1x mais rapido (1697s -> 542s)
```

**ARQUIVOS MODIFICADOS:**
```
buzz_factory.py:501-592
  ~ generate_daily_buzz() agora usa asyncio.gather() para as 4 fases
  + Wrapper functions para cada fase (run_watchlist, run_volume, run_gaps, run_news)
  + Tratamento de excecoes por fase
```

**Status:** OK - Fases rodam em paralelo verdadeiro

---

### 2026-01-07 (Update 12)
**Sistema de Logs Coloridos para Execucao Paralela**

**FUNCIONALIDADE:**
Logs coloridos por fase para visualizar execucao paralela do Phase 0 em terminal unico.

**CORES POR FASE:**
```
WATCHLIST = Cyan claro     (\033[96m)
VOLUME    = Amarelo        (\033[93m)
GAPS      = Magenta        (\033[95m)
NEWS      = Verde          (\033[92m)
SYSTEM    = Branco         (\033[97m)
```

**CLASSES ADICIONADAS:**

#### PhaseColors (buzz_factory.py:32-51)
Constantes ANSI para cores. Compativel com Windows cmd.exe e PowerShell.

#### ColoredPhaseLogger (buzz_factory.py:54-167)
- `log(phase, message)` - Log com cor da fase
- `success(phase, message)` - Log de sucesso (verde)
- `ticker_found(phase, ticker, detail)` - Candidato encontrado
- `phase_start()` / `phase_complete()` - Inicio/fim de fase

**OUTPUT ESPERADO:**
```
[14:32:01] [WATCHLIST ] Iniciando scan (9 items em paralelo)...
[14:32:02] [WATCHLIST ] AAPL: $2.8T | tier1 large cap
[14:32:02] [VOLUME    ] NVDA: 2.3x spike | $125.4M volume
[14:32:03] [GAPS      ] TSLA: Gap +5.2% | $245.30
```

**ARQUIVOS MODIFICADOS:**
```
buzz_factory.py:
  + class PhaseColors
  + class ColoredPhaseLogger
  ~ class ParallelProgressTracker (usa logger colorido)
  ~ Metodos de scan paralelo (logs de candidatos encontrados)

debug_cli.py:
  + Habilita ANSI no Windows
```

**Status:** OK - Logs coloridos funcionando

---

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

### Pendencias (TODO no codigo)

1. **[RESOLVIDO] Fluxo de Noticias** (`src/collectors/buzz_factory.py`)
   - **Status:** CORRIGIDO em Update 8 (2026-01-06)

2. **[RESOLVIDO] Orchestrator timing e sequenciamento** (`src/core/orchestrator.py`)
   - **Status:** CORRIGIDO em Update 17 (2026-02-07)
   - Window-based scheduling + timezone + daily tracking

3. **[RESOLVIDO] Order Manager stubs** (`src/execution/order_manager.py`)
   - **Status:** CORRIGIDO em Update 17 (2026-02-07)
   - close_position_at_market, update_stop_order, OCO handler implementados

4. **[RESOLVIDO] Monitoring stubs** (`src/monitoring/`)
   - **Status:** CORRIGIDO em Update 17 (2026-02-07)
   - Trailing stops, Friday breakeven, panic protocol implementados

5. **[RESOLVIDO] RAG Context** (`data/rag_manuals/`)
   - **Status:** CORRIGIDO em Update 20 (2026-02-07)
   - 5 manuals criados: swing_trading_rules, risk_management, technical_patterns, macro_context, entry_exit_criteria
   - Judge carrega automaticamente via _load_rag_context()

6. **[RESOLVIDO] Grounding Service** (`src/decision/grounding.py`)
   - **Status:** CORRIGIDO em Update 20 (2026-02-07)
   - .seconds bug fixed to .total_seconds()
   - AI verification via Gemini (run_in_executor) com fallback para word-matching

7. **[RESOLVIDO] Phase 4 hardcoded tier** (`src/core/orchestrator.py`)
   - **Status:** CORRIGIDO em Update 21 (2026-02-07)
   - Tier agora calculado dinamicamente via market_data.market_cap

8. **[RESOLVIDO] Watchdog stop execution** (`src/monitoring/watchdog.py`)
   - **Status:** CORRIGIDO em Update 21 (2026-02-07)
   - stop_violated agora auto-closes via order_manager.close_position_at_market()
   - Alert deduplication implementado (5 min cooldown)

9. **[RESOLVIDO] Poison Pill pre-market gaps** (`src/monitoring/poison_pill.py`)
   - **Status:** CORRIGIDO em Update 21 (2026-02-07)
   - check_pre_market_gaps() implementado com yfinance pre-market price
   - .seconds bug fixed to .total_seconds()

### Proximas Melhorias Planejadas

1. ~~Preencher RAG manuals com estrategias de trading~~ (RESOLVIDO - Update 20)
2. ~~Implementar Grounding com AI (Gemini) em vez de word-matching~~ (RESOLVIDO - Update 20)
3. ~~Watchdog auto-close em stop_violated~~ (RESOLVIDO - Update 21)
4. ~~Backtesting engine~~ (RESOLVIDO - Update 19)
5. Web dashboard (opcional)
6. ~~Integracao broker real~~ (RESOLVIDO - Update 18, Alpaca Markets)
7. ~~Poison pill pre-market gap detection~~ (RESOLVIDO - Update 21)
8. ~~Migrar google.generativeai -> google.genai~~ (RESOLVIDO - Update 32)
9. ~~Backtesting com AI scoring~~ (RESOLVIDO - Update 32, --ai flag)
10. ~~Sector rotation strategy em RAG~~ (RESOLVIDO - Update 32)
11. ~~Backtesting parity com live pipeline~~ (RESOLVIDO - Update 35, 20 gaps corrigidos)

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

### 2026-02-09 (Update 46)
**REFACTOR - Backtesting engines now use shared ExitRules class**

Refatorados `src/backtesting/replay_engine.py` e `src/backtesting/engine.py` para usar a classe compartilhada `ExitRules` de `src/core/exit_rules.py` em vez de logica inline de saida duplicada. Isso completa a unificacao: live (Sentinel/Watchdog) e backtesting (ReplayEngine/BacktestEngine) agora usam exatamente a mesma logica de exit decisions.

**Refatoracao: `src/backtesting/replay_engine.py` (`_phase5_check_exits()`)**
- Trailing stop: `peak_price - 2*ATR` inline -> `ExitRules.calculate_trailing_stop()`
- Friday breakeven: `entry_price * 1.005 / 1.002` inline -> `ExitRules.calculate_friday_breakeven()`
- Flash crash: `(open-low)/open >= 0.03` inline -> `ExitRules.is_flash_crash()`
- Max holding: `np.busday_count() >= 7` inline -> `ExitRules.should_close_max_holding()`
- Backup stop: `low <= backup_stop` inline -> `ExitRules.is_backup_stop_violated()`
- Removido `import numpy as np` (nao mais usado diretamente)

**Refatoracao: `src/backtesting/engine.py` (`_check_exits()`)**
- Trailing stop: `close - 2*ATR` inline -> `ExitRules.calculate_trailing_stop()`
- Friday breakeven: `entry_price * 1.005 / 1.002` inline -> `ExitRules.calculate_friday_breakeven()`
- Flash crash: `(open-low)/open >= 0.03` inline -> `ExitRules.is_flash_crash()`
- Backup stop LONG: `low <= backup_stop` inline -> `ExitRules.is_backup_stop_violated(low, entry, "LONG")`
- Backup stop SHORT: `high >= backup_stop` inline -> `ExitRules.is_backup_stop_violated(high, entry, "SHORT")`
- Removido `import numpy as np` (nao mais usado diretamente)

**Logica preservada intacta:** _close_position(), PnL calculations, logging, peak price tracking, ordem dos checks de saida, TP1/TP2 partial exit logic.

**Arquivos modificados (2):**
1. `src/backtesting/replay_engine.py` - Exit logic delegada para ExitRules, numpy removido
2. `src/backtesting/engine.py` - Exit logic delegada para ExitRules, numpy removido

---

### 2026-02-09 (Update 45)
**REFACTOR - Shared ExitRules class to eliminate duplicated exit logic**

Criada classe `ExitRules` em `src/core/exit_rules.py` com metodos estaticos para todas as decisoes de saida. Sentinel e Watchdog refatorados para usar essa classe em vez de logica inline duplicada. Isso cria um unico ponto de verdade para trailing stops, Friday breakeven, flash crash detection, backup stop, max holding period e calculo de stop loss inicial.

**Novo arquivo: `src/core/exit_rules.py`**
- Classe `ExitRules` com 6 metodos estaticos:
  - `calculate_trailing_stop()`: Trailing stop baseado em peak price e ATR (so aperta, nunca afrouxa)
  - `calculate_friday_breakeven()`: Breakeven de sexta-feira com min_profit_pct (0.5%) e buffer (0.2%)
  - `is_flash_crash()`: Detecta flash crash a partir de historico de precos
  - `is_backup_stop_violated()`: Verifica stop catastrofico (perda maxima 10%)
  - `should_close_max_holding()`: Verifica periodo maximo de holding (7 dias uteis)
  - `calculate_stop_loss()`: Calculo inicial de stop loss baseado em ATR

**Refatoracao: `src/monitoring/sentinel.py`**
- `update_trailing_stops()`: Removido `import yfinance as yf` direto (usava yfinance em vez do market_data injetado). Agora usa `self.market_data.get_historical()` via `run_in_executor`. Adicionado peak price tracking via `position._peak_price`. Calculo delegado para `ExitRules.calculate_trailing_stop()`.
- `check_friday_breakeven()`: Removida logica inline com buffer de 0.1%. Agora usa `ExitRules.calculate_friday_breakeven()` com buffer de 0.2% e exigencia de 0.5% de lucro minimo para ativar.

**Refatoracao: `src/monitoring/watchdog.py`**
- `_check_position()`: Deteccao de flash crash inline substituida por `ExitRules.is_flash_crash()`. Corrigida referencia a variavel `oldest_price` que nao existia mais apos refatoracao (substituida por leitura do price_history).

**Arquivos modificados (3):**
1. `src/core/exit_rules.py` - NOVO: Classe compartilhada de regras de saida
2. `src/monitoring/sentinel.py` - Trailing stops e Friday breakeven delegados para ExitRules
3. `src/monitoring/watchdog.py` - Flash crash detection delegado para ExitRules

---

### 2026-02-09 (Update 44)
**FEATURE - Order Monitoring System (polling for fills, cancels, rejects)**

Orders were previously fire-and-forget: submitted once and assumed filled. This is dangerous for live trading where orders can be partially filled, rejected, stuck, or expire. Added a complete order polling/monitoring system to `OrderManager`.

**New in `src/execution/order_manager.py`:**
- `_monitored_orders: Dict[str, Dict]` - tracks orders being polled (key=order.id, value={order, submitted_at, last_check, timeout_seconds})
- `_monitoring_active: bool` - controls the background loop
- `_add_to_monitoring(order, timeout_seconds)` - auto-called from `submit_order()`. Market orders get 300s timeout (5min), limit/stop/stop_limit get 28800s (8h/trading day)
- `start_order_monitoring()` - background async loop polling every 10s. Handles: filled (logs + updates + triggers OCO), partial (logs + keeps monitoring), cancelled/rejected/expired (logs + updates + removes), timeout (warns + removes). Never crashes - all exceptions caught.
- `stop_order_monitoring()` - graceful shutdown
- `_poll_monitored_orders()` - single poll cycle, queries `broker.get_order_status()` for each tracked order
- `get_monitored_orders() -> List[Dict]` - returns snapshot of all monitored orders with elapsed time, time remaining, etc (for GUI/debug)
- Removed redundant `import asyncio` inside `_handle_oco_fill` (now at module level)

**Changes in `main.py`:**
- Added `order_manager.start_order_monitoring()` as asyncio task alongside watchdog/sentinel
- Added `order_manager.stop_order_monitoring()` in cleanup/finally block

**Behavior by broker type:**
- PaperBroker: fills instantly, monitoring finds "filled" on first poll and removes. No-op but safe.
- AlpacaBroker: real polling matters. Limit orders may take hours to fill. Partial fills tracked.
- CCXTBroker: same as Alpaca, real status polling.

---

### 2026-02-09 (Update 43)
**MAJOR OVERHAUL - 13 fixes across 6 files for profitability + correctness**

Analise profunda dos logs de replay revelou que IARA fazia apenas 3 trades em 15 dias, todos saindo com +0.10% PnL. Causa raiz: cadeia de 4 bugs criticos + screener conservador + trailing stop quebrado. Todas as correcoes aplicam tanto ao modo replay quanto ao live.

**Bug 1: OpenAI gpt-5.2 rejeita parametro `max_tokens` - CORRIGIDO**
- Causa: gpt-5.2 requer `max_completion_tokens` em vez de `max_tokens`. Resultado: Judge SEMPRE fazia fallback para Gemini (modelo inferior).
- Fix: `max_tokens=max_tokens` -> `max_completion_tokens=max_tokens`
- Arquivo: `src/decision/ai_gateway.py` (metodo `_call_openai`)

**Bug 2: Correlation timezone mismatch retornava 1.0 (false block) - CORRIGIDO**
- Causa: `pd.concat()` de series tz-naive (OHLCV historico) com tz-aware (yfinance live) lanca excecao. Fail-safe retornava 1.0, bloqueando TODOS os trades como "altamente correlacionados".
- Fix: Normalizar timezone (strip tz info) ANTES de calcular pct_change/concat.
- Arquivo: `src/analysis/correlation.py` (metodo `calculate_correlation`)

**Bug 3: Friday breakeven look-ahead bias - CORRIGIDO**
- Causa: Usava `close` (informacao futura no intraday) para definir breakeven stop, depois verificava se `low` atingiu. Em backtest daily, isso e impossivel (close so e conhecido no fim do dia).
- Fix: Usar `open` (conhecido no inicio do dia), exigir +0.5% acima de entry para ativar, e buffer de +0.2% (era +0.1%).
- Arquivos: `src/backtesting/replay_engine.py`, `src/backtesting/engine.py`

**Bug 4: Judge buscava dados LIVE via yfinance durante replay - CORRIGIDO**
- Causa: `judge.py` fazia `yf.Ticker(ticker).history(period="60d")` para correlation check, buscando dados ATUAIS mesmo em modo replay. Isso causava tz-mismatch e valores de correlacao incorretos.
- Fix: Verificar `portfolio_prices` primeiro (dados pre-carregados), so buscar yfinance se nao encontrado. Filtrar self-correlation.
- Arquivo: `src/decision/judge.py` (metodo de correlation check)

**Melhoria 1: Screener prompt reescrito para swing trade - APLICADO**
- Problema: Prompt antigo instruia "Seja objetivo e conservador", penalizava falta de noticias, e tinha escala rigida 5x 0-2pts.
- Fix: Reescrita completa com foco em swing trade (3-5 dias), escala balanceada (Volume 0-2, Tendencia 0-2.5, Momentum 0-2.5, Risco/Retorno 0-3), instrucao explicita "Use a escala COMPLETA de 0 a 10", e "nao penalize se noticias nao disponiveis".
- Arquivo: `config/prompts/screener.md`

**Melhoria 2: Rate limiting configuravel no replay - APLICADO**
- Fix: `_screener_delay = 1.0s` (era 4s), `_judge_delay = 1.0s` (era 2s). Replay roda 3x mais rapido.
- Arquivo: `src/backtesting/replay_engine.py`

**Melhoria 3: Peak price tracking para trailing stop - APLICADO**
- Problema: Trailing stop usava preco de abertura do dia, nao o pico desde entrada. Resultado: stop nunca ratchetava para cima.
- Fix: Campo `peak_price` em ReplayPosition, atualizado com max(peak, close) a cada dia. Trailing stop = peak - 2.0x ATR.
- Arquivo: `src/backtesting/replay_engine.py`

**Melhoria 4: Filtro de tendencia no Phase 0 - APLICADO**
- Fix: Skip acoes em downtrend forte (close < SMA20 AND close < SMA50) EXCETO se volume spike ou gap.
- Arquivo: `src/backtesting/replay_engine.py`

**Melhoria 5: Precos do candidato incluidos em portfolio_prices - APLICADO**
- Fix: Judge recebe precos do proprio candidato em portfolio_prices para correlation check sem buscar yfinance live.
- Arquivo: `src/backtesting/replay_engine.py`

**Melhoria 6: Slippage de entrada (0.1%) - APLICADO**
- Fix: Preco de entrada = open * 1.001 (realismo de execucao).
- Arquivo: `src/backtesting/replay_engine.py`

**Melhoria 7: Max holding period de 7 dias - APLICADO**
- Fix: Fechar posicoes apos 7 dias uteis (disciplina de swing trade, evita capital preso).
- Arquivo: `src/backtesting/replay_engine.py`

**Melhoria 8: Cap de TP levels - APLICADO**
- Fix: TP1 max 4x ATR, TP2 max 7x ATR acima de entry (evita TPs irreais que nunca sao atingidos).
- Arquivo: `src/backtesting/replay_engine.py`

**Arquivos modificados (6):**
1. `src/decision/ai_gateway.py` - max_completion_tokens fix
2. `src/analysis/correlation.py` - timezone normalization
3. `config/prompts/screener.md` - reescrita completa do prompt
4. `src/backtesting/replay_engine.py` - 8 melhorias (rate limiting, Friday breakeven, trailing stop, trend filter, portfolio prices, slippage, max holding, TP cap)
5. `src/decision/judge.py` - replay correlation check
6. `src/backtesting/engine.py` - Friday breakeven fix

---

### 2026-02-09 (Update 42)
**CRITICAL FIX - Replay mode: 4 bugs causing zero trades in 10 days**

Investigacao profunda com 4 agentes em paralelo revelou 4 bugs que combinados impediam qualquer trade no modo replay.

**Bug 1: Screener scores sistematicamente baixos (2-6/10) - CORRIGIDO**
- Causa: O prompt do screener tem 5 criterios de 0-2 pts cada (total 10). O criterio "Catalisador" (news) SEMPRE recebia 0 no replay (sem noticias historicas). Max possivel = 8/10, com threshold = 7, praticamente impossivel passar.
- Fix: `news_summary` agora instrui a IA a ignorar o criterio "Catalisador" e reescalar os 4 criterios restantes para 0-10 (cada um 0-2.5 pts).
- Arquivo: `src/backtesting/replay_engine.py` linhas 845-855

**Bug 2: Sector veto bloqueava primeira posicao em portfolio vazio - CORRIGIDO**
- Causa: `position_value_estimate = risk_amount / stop_distance`. Para acoes de baixa volatilidade (ATR < 2%), estimativa = 25%+ do capital. Primeiro trade em portfolio vazio ja excedia 20% de sector.
- Exemplo real: PETR4.SA (ATR 1.6%): $1000/0.04 = $25K = 25% > 20% = VETADO.
- Fix: `position_value_estimate = min(estimate, capital * 0.20)` - cap de 20% alinhado com o que Phase 4 PositionSizer realmente aplica.
- Arquivos: `src/backtesting/replay_engine.py`, `src/backtesting/engine.py`, `src/core/orchestrator.py`

**Bug 3: Earnings checker com janela dupla (abs) - CORRIGIDO**
- Causa: `abs((ed - sim_date).days)` bloqueava +/-5 dias (10 dias total). Live usa apenas 0-5 dias (futuro).
- Fix: `delta = (ed - sim_date).days; if 0 <= delta <= 5` - agora match com live.
- Arquivo: `src/backtesting/replay_engine.py` linhas 58-72

**Bug 4: Judge recebia "no news available" e podia recusar - CORRIGIDO**
- Causa: Judge rules dizem "AGUARDAR se faltam dados criticos". Sem news, podia recusar trades validos.
- Fix: `news_details` agora instrui o Judge a tratar news como NEUTRAL e avaliar apenas dados tecnicos/macro.
- Arquivo: `src/backtesting/replay_engine.py` linha 1063-1068

---

### 2026-02-08 (Update 41)
**CRITICAL BUG FIX - Gemini 2.5 Flash thinking tokens consuming entire output budget**

Apos upgrade para `gemini-2.5-flash` (Update 38), TODOS os screener calls falhavam: API retornava `success=True` mas `parsed_json=None` (log: "0 tokens, plain text"). Causa raiz: Gemini 2.5 Flash e um "thinking model" que usa ate 8192 tokens de raciocinio interno. Esses tokens contam contra o `max_output_tokens`. Com screener usando `max_tokens=500`, o modelo gastava todo o budget pensando e retornava conteudo vazio/truncado sem JSON.

**Correcao**: Desabilitar thinking com `thinking_budget=0` em todas as chamadas Gemini que requerem output estruturado (JSON). Tambem adicionado fallback robusto para extracao de texto e token counting real.

**Arquivos modificados (3):**
- `src/decision/ai_gateway.py` - GeminiClient: `ThinkingConfig(thinking_budget=0)` no GenerateContentConfig. Fallback manual para extrair texto de `response.candidates[0].content.parts` (skip thought parts). Token counting via `response.usage_metadata.total_token_count`.
- `src/decision/grounding.py` - `_gemini_verify()`: `ThinkingConfig(thinking_budget=0)` + `response.text or ""` guard.
- `src/collectors/news_aggregator.py` - `GeminiNewsValidator._call_gemini()`: `ThinkingConfig(thinking_budget=0)`.

---

### 2026-02-08 (Update 36)
**CRITICAL BUG FIX - Sector Exposure sempre bloqueava 100% dos trades**

Bug encontrado ao rodar o Replay Mode: a formula de estimativa de posicao `risk_amount / 0.02` criava uma posicao estimada de $50,000 (50% de $100K), que SEMPRE excedia o limite de 20% de setor. Nenhum trade podia entrar em qualquer modo (live, replay, backtest).

**Problema**: `position_value_estimate = risk_amount / 0.02` assumia stop distance fixo de 2%, gerando posicao de 50% do portfolio. O sector exposure check vetava TUDO.

**Correcao**: Usar ATR real do ativo para estimar stop distance (2.5x ATR, como o Phase 4 faz), gerando posicoes realistas:
- AAPL (ATR 2.7%): posicao $15K = 15% sector -> OK
- NVDA (ATR 5.1%): posicao $7.8K = 7.8% sector -> OK
- PETR4 (ATR 1.6%): posicao $25K = 25% sector -> bloqueado (correto - risco real)

**Arquivos modificados:**
- `src/backtesting/replay_engine.py` (line ~893): ATR-based position estimate
- `src/backtesting/engine.py` (line ~756): mesma correcao
- `src/core/orchestrator.py` (line ~569): mesma correcao para modo live
- Replay engine: progress logging a cada 5 dias (era 20)
- Engines agora leem `phase2.sector_exposure_max` do config (antes `risk.max_sector_exposure` que nao existia)

---

### 2026-02-08 (Update 37)
**GUI Integration - Replay Mode mostra metricas em tempo real no Dashboard**

O Replay Mode rodava em thread separada sem comunicar progresso ao dashboard. O usuario nao via nada durante a simulacao (equity, positions, drawdown, win rate - tudo zerado).

**Solucao**: Sistema de `ReplayState` thread-safe que conecta o ReplayEngine ao Dashboard:

1. **`ReplayState`** (nova classe em `src/gui/replay_dialog.py`):
   - Container thread-safe com `threading.Lock`
   - Metodo `update()` chamado pelo ReplayEngine a cada dia simulado
   - Metodo `snapshot()` chamado pelo Dashboard a cada 2s para leitura segura

2. **Replay Progress Bar** (nova barra no Dashboard):
   - Aparece automaticamente quando replay inicia, desaparece quando termina
   - Mostra: badge REPLAY, data simulada, barra de progresso, % completo
   - Quick stats: equity (com return %), trades, AI calls (Screener/Judge)
   - Botao STOP para cancelar replay em andamento

3. **Metric Cards Override**: Durante replay, os cards do dashboard mostram dados do replay:
   - CAPITAL -> equity atual da simulacao
   - DAILY P&L -> TOTAL P&L (label muda)
   - TOTAL P&L -> RETURN % (label muda)
   - DRAWDOWN -> drawdown total da simulacao
   - POSITIONS -> contagem + tickers ativos
   - TRADES TODAY -> TRADES total
   - WIN RATE -> percentual com W/L count
   - VIX -> SIM DAY (dia atual da simulacao)

4. **Engine Status**: Muda para "REPLAY: Day X/Y (X%)" durante simulacao e
   "REPLAY DONE: +X.X% | Sharpe X.XX | MaxDD X.X%" quando finaliza

5. **ReplayEngine progress_callback**: Agora envia dict rico com 18+ campos
   (antes enviava 3 args posicionais). Inclui equity, positions, trades, wins/losses,
   drawdown, AI stats, kill switch, etc.

**Arquivos modificados:**
- `src/gui/dashboard.py`: _replay_state/_replay_engine attrs, _create_replay_bar(), _show/_hide_replay_bar(), _on_stop_replay(), _sync_replay_metrics(), label restore em _sync_metrics()
- `src/gui/replay_dialog.py`: ReplayState class, progress_callback wiring, dashboard ref, state cleanup on close
- `src/backtesting/replay_engine.py`: Rich dict progress_callback (18+ fields), completion callback with final metrics

---

### 2026-02-08 (Update 38)
**AI Model Upgrade - Todos os modelos atualizados para versoes 2026**

Modelos antigos estavam deprecated ou sendo aposentados. Atualizado para as versoes mais recentes:

| Provider | Antes | Depois | Motivo |
|----------|-------|--------|--------|
| Gemini | `gemini-2.0-flash` | `gemini-2.5-flash` | **DEPRECATED** - desliga 31/Mar/2026 |
| OpenAI | `gpt-4.1` | `gpt-5.2` | Modelo mais capaz, gpt-4.1 sendo aposentado |
| Anthropic | `claude-sonnet-4-5-20250929` | `claude-sonnet-4-5` (alias) | Simplificado para alias (resolve automaticamente) |

**Arquivos modificados:**
- `src/decision/ai_gateway.py`: GeminiClient, OpenAIClient, AnthropicClient defaults + log messages
- `src/decision/grounding.py`: Gemini model ref
- `src/collectors/news_aggregator.py`: Gemini model ref
- `src/backtesting/replay_engine.py`: Docstrings + rate limit comment
- `src/gui/replay_dialog.py`: AI info labels
- `replay_cli.py`: CLI output labels
- `test_phase1_live.py`: Model lists atualizadas (Gemini, OpenAI, Anthropic)
- `test_phase3_live.py`: Fallback alternatives list

**Nota**: `gpt-4.1` mantido apenas como fallback alternativo nos testes (caso gpt-5.2 falhe).

---

### 2026-02-08 (Update 39)
**Replay Mode - Engine live para durante replay (Opcao A)**

Antes: Engine live e Replay rodavam em paralelo, competindo por rate limits do Gemini free tier.
Agora: Fluxo exclusivo - engine live para antes do replay e reinicia depois.

**Fluxo novo:**
```
[Clica REPLAY] -> [Config Dialog] -> [START]
    |
    v
engine.stop()            <-- Para Orchestrator, Watchdog, Sentinel, PoisonPill
    |
    v
ReplayEngine.run()       <-- Replay roda sozinho (sem competicao de rate limits)
    |
    v
[Results Dialog]         <-- Metricas do replay ficam visiveis no dashboard
    |
    v
[Fecha Results] -> engine.start()  <-- Engine live reinicia automaticamente
```

**Casos de falha**: Se replay falha (exception, no tickers, no AI providers), engine reinicia automaticamente via `_restart_engine()`.

**Arquivos modificados:**
- `src/gui/replay_dialog.py`: `_on_start()` para engine antes de lancar thread, `_stop_engine_then_replay()` novo metodo, `_restart_engine()` helper, `ReplayResultDialog._on_close()` reinicia engine, early returns tambem reiniciam engine

---

### 2026-02-08 (Update 40)
**GUI - Engine nao inicia automaticamente, botao START/STOP**

Antes: Engine iniciava automaticamente ao abrir o GUI. Agora o usuario escolhe o modo (broker) e clica START quando estiver pronto.

**Fluxo novo:**
```
[Abre GUI] -> Engine PARADO, status "ENGINE: STOPPED"
    |
    |--- Escolhe modo no dropdown (paper_local / alpaca_paper / alpaca_live)
    |    Config salva em settings.yaml, status mostra "MODE: ALPACA_PAPER (click START)"
    |
    |--- Clica [START ENGINE] (botao verde)
    |    Engine inicia, botao vira [STOP ENGINE] (botao vermelho)
    |
    |--- Clica [STOP ENGINE]
    |    Engine para, botao volta a [START ENGINE]
```

**Mudancas:**
- `iara_gui.py`: Removido `engine.start()` automatico (linha 445)
- `src/gui/dashboard.py`:
  - Status inicial "ENGINE: STOPPED" (antes "ENGINE: STARTING")
  - Botao RESTART substituido por toggle START ENGINE / STOP ENGINE
  - `_on_engine_toggle()`: Inicia ou para engine baseado no estado atual
  - `_update_engine_btn()`: Sincroniza visual do botao com estado real (chamado a cada 2s)
  - `_apply_broker_mode()`: Se engine parado, so salva config (antes tentava restart)
  - `_update_metrics()`: Quando engine parado, mostra estado idle

---

### Update 44 - Correcao de 3 Bugs do Replay (2026-02-09)

**Encontrados via analise de logs de replay real. Todos afetam fidelidade do backtest/replay.**

#### Bug 1 (CRITICO): Sector VETO falso positivo por floating-point
- **Problema**: `position_sizer` limita posicao a 20% do capital, mas sector check compara `sector_pct > 0.20`. Floating-point faz `20.000001% > 20%` = True, vetando TODAS entradas mesmo com 0 posicoes no setor.
- **Arquivos**: `src/backtesting/replay_engine.py` (linha 412), `src/backtesting/engine.py` (linha 287)
- **Fix**: Adicionado tolerancia `+ 1e-9` na comparacao: `sector_pct > self.max_sector_exposure + 1e-9`

#### Bug 2 (MEDIO): Screener bias sempre NEUTRO
- **Problema**: Prompt do Screener (`config/prompts/screener.md`) define chave `"vies"` (sem acento), mas `screener.py` buscava `"viés"` (com acento). Key lookup falhava, sempre retornava default "NEUTRO".
- **Arquivo**: `src/decision/screener.py` (linha 156)
- **Fix**: Tenta ambas as chaves: `result_data.get("vies", result_data.get("viés", "NEUTRO"))`

#### Bug 3 (ALTO): Judge cache reutiliza decisoes entre dias no replay
- **Problema**: `database.py` usa `datetime.now()` para validar cache (< 2h). No replay, todos os dias simulados ocorrem em minutos reais, entao cache do Dia 1 e "fresco" no Dia 15. Judge reutiliza decisoes obsoletas.
- **Arquivos**: `src/core/database.py` (novo metodo `clear_decision_cache()`), `src/backtesting/replay_engine.py` (chamada no inicio de cada dia)
- **Fix**: Adicionado `Database.clear_decision_cache()` que limpa TODA a tabela. ReplayEngine chama no inicio de cada dia simulado.

**Resultado**: 255/255 testes passando.

---

### 2026-02-09 (Update 47)
**FEATURE - Judge Audit View + Fullscreen + GUI Navigation**

Sistema de auditoria em tempo real dos prompts enviados ao Judge (GPT-5.2). Permite ver exatamente o que a IA recebeu, de onde veio a chamada, e qual foi o resultado. GUI agora abre em fullscreen com botao de minimizar.

**Novo arquivo: `src/gui/judge_audit.py`**
- `JudgeAuditStore`: Persistencia em `data/judge_audit.jsonl` (JSON Lines, append-only). Max 500 entradas em memoria. Metodos: `add()`, `clear()`, `_load()`.
- `JudgeAuditPanel` (CTkFrame): Toolbar com titulo roxo, contador de entradas, botao CLEAR ALL. Scrollable frame com entradas (mais recente no topo). Cada entrada: header (timestamp | ticker | origin | badge colorido) + prompt expandivel. Badges: verde=APROVAR, vermelho=REJEITAR, amarelo=AGUARDAR. Max 200 widgets renderizados.
- `_AuditEntryWidget`: Widget individual com header, justificativa compacta, e area de prompt expandivel/colapsavel.

**Modificado: `src/decision/judge.py`**
- Adicionado `_judge_audit_callback` (module-level) e `set_judge_audit_callback(cb)` para registrar callback de auditoria.
- Adicionado `_emit_audit(entry)` helper com try/except silencioso (nunca quebra o pipeline).
- Audit emitido em TODOS os caminhos de decisao:
  - Correlation veto (origin="Phase 3 - Correlation Veto")
  - Cache hit (origin="Phase 3 - Cache Hit")
  - Grounding veto (origin="Phase 3 - Grounding Veto")
  - AI failure (origin="Phase 3 - AI Failure")
  - Decisao normal (origin="Phase 3 - Judge Decision", inclui prompt completo)
  - Exception (origin="Phase 3 - Exception")

**Modificado: `src/gui/dashboard.py`**
- `__init__()`: Aceita `audit_queue` opcional. Cria `JudgeAuditStore` e `JudgeAuditPanel`. Wrap de todo conteudo (phase_bar ate action_bar) em `_dashboard_frame`. Header fica fora (sempre visivel).
- Fullscreen: `self.after(100, lambda: self.state("zoomed"))` no fim do init.
- Minimize: Botao "_" no header (right_frame) com `self.iconify()`.
- Navegacao: Botao "JUDGE AUDIT" roxo no header, alterna para audit view. Texto muda para "DASHBOARD" quando em audit view.
- `_toggle_view()`: Pack/unpack entre `_dashboard_frame` e `_audit_panel`.
- `_poll_audit()`: A cada 500ms, le da audit_queue e adiciona ao store/panel.

**Modificado: `src/gui/theme.py`**
- `FONT_AUDIT_PROMPT = ("Consolas", 11)`
- `FONT_AUDIT_HEADER = ("Segoe UI Semibold", 11)`
- `COLOR_AUDIT_APPROVE = "#3fb950"`, `COLOR_AUDIT_REJECT = "#f85149"`, `COLOR_AUDIT_WAIT = "#d29922"`

**Modificado: `iara_gui.py`**
- Cria `audit_queue = queue.Queue(maxsize=500)`.
- Importa `set_judge_audit_callback` de `src.decision.judge`.
- Callback faz `audit_queue.put_nowait(entry)` (thread-safe, drop se cheio).
- Passa `audit_queue` ao `IaraDashboard`.

**Thread safety:**
- Judge roda na thread do engine/replay -> callback coloca na Queue (thread-safe)
- GUI main thread poll a cada 500ms -> le da queue e atualiza UI
- Escrita no arquivo JSONL acontece na main thread via _poll_audit

**Arquivos modificados (5):**
1. `src/decision/judge.py` - Callback de auditoria module-level + emissao em todos os paths
2. `src/gui/judge_audit.py` - NOVO: JudgeAuditStore + JudgeAuditPanel
3. `src/gui/dashboard.py` - Fullscreen, minimize, navegacao dashboard/audit, poll audit
4. `src/gui/theme.py` - Constantes de fonte/cor para audit
5. `iara_gui.py` - Wiring: audit_queue + callback + passagem ao dashboard

---

**FIM DO DOCUMENTO**

*Este documento deve ser atualizado sempre que houver mudanças significativas na arquitetura, lógicas ou responsabilidades dos arquivos.*
