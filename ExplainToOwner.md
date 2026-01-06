# IARA - Explicação da Estrutura do Projeto

**Última Atualização:** 2026-01-06
**Versão:** v25.0 "Atomic Survivor"

---

## ⚠️ INSTRUÇÃO CRÍTICA PARA IA

**SEMPRE LEIA ESTE ARQUIVO ANTES DE COMEÇAR A PROGRAMAR**

Este documento é o mapa completo do projeto. Antes de modificar qualquer código:
1. Leia este arquivo para entender onde está a lógica atual
2. Verifique qual arquivo é responsável pela funcionalidade
3. Após fazer mudanças, ATUALIZE este documento com as modificações
4. Adicione entrada no "Histórico de Modificações"

**Regra de Ouro:** Se você moveu, modificou ou criou algo → Documente aqui IMEDIATAMENTE

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

### 2026-01-06
**Testes Completos Implementados**
- Criado `test_phase2.py` - Beta, defensive, correlation, sector
- Criado `test_phase3.py` - Judge cache, threshold, logging
- Criado `test_integration.py` - Pipeline end-to-end
- **Bug Fix:** `buzz_factory.py` linha 475 - Removido await de check_liquidity()
- **Bug Fix:** `config/prompts/judge.md` - JSON braces escapados para .format()
- Database: `data/iara.db` criado com tabelas decision_cache e decision_log

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

1. **Orchestrator** (`src/core/orchestrator.py`)
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
