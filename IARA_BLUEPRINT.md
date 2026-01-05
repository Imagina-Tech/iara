# IARA TRADER - Blueprint v25.0

## Visão Geral

**IARA** (Intelligent Automated Risk-Aware Trader) é um sistema de trading automatizado que utiliza múltiplas camadas de inteligência artificial para identificar, analisar e executar operações no mercado de ações.

---

## Arquitetura do Sistema

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              IARA TRADER v25.0                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐       │
│  │   FASE 0        │     │   FASE 1        │     │   FASE 2        │       │
│  │   Buzz Factory  │────▶│   Screener      │────▶│   Quant         │       │
│  │                 │     │   (Gemini)      │     │   Analysis      │       │
│  │   • Watchlist   │     │                 │     │                 │       │
│  │   • Volume Scan │     │   Nota 0-10     │     │   • RSI/ATR     │       │
│  │   • Gap Scan    │     │   Threshold: 7  │     │   • Beta/Vol    │       │
│  │   • News Scan   │     │                 │     │   • Correlação  │       │
│  └─────────────────┘     └─────────────────┘     └─────────────────┘       │
│           │                      │                       │                 │
│           ▼                      ▼                       ▼                 │
│  ┌─────────────────────────────────────────────────────────────────┐       │
│  │                         FASE 3                                   │       │
│  │                     JUIZ FINAL (GPT + RAG)                      │       │
│  │                                                                  │       │
│  │   • Análise completa de todos os dados                          │       │
│  │   • Consulta manuais de estratégia via RAG                      │       │
│  │   • Decisão: APROVAR / REJEITAR / AGUARDAR                      │       │
│  │   • Define: Entry, Stop Loss, Take Profit, Tamanho              │       │
│  │   • Threshold: Nota >= 8                                        │       │
│  └─────────────────────────────────────────────────────────────────┘       │
│                                    │                                        │
│                                    ▼                                        │
│  ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐       │
│  │   FASE 4        │     │   FASE 5        │     │   KILL SWITCH   │       │
│  │   Execution     │────▶│   Monitoring    │────▶│                 │       │
│  │                 │     │                 │     │   • Telegram    │       │
│  │   • Position    │     │   • Watchdog    │     │   • Drawdown    │       │
│  │     Sizing      │     │   • Sentinel    │     │   • Flash Crash │       │
│  │   • OCO Orders  │     │   • Poison Pill │     │                 │       │
│  │   • Broker API  │     │                 │     │                 │       │
│  └─────────────────┘     └─────────────────┘     └─────────────────┘       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Fases do Pipeline

### FASE 0: Buzz Factory
**Objetivo:** Gerar lista de oportunidades do dia

**Fontes:**
- Watchlist fixa (Tier 1)
- Scan de volume (>2x média)
- Scan de gaps (>3%)
- Scan de notícias (catalisadores)

**Output:** Lista de tickers candidatos

---

### FASE 1: Screener (Gemini Free)
**Objetivo:** Triagem inicial usando IA de baixo custo

**Input:** Candidatos da Fase 0 + dados básicos

**Critérios (Nota 0-10):**
1. Volume (0-2 pts)
2. Tendência (0-2 pts)
3. Momentum (0-2 pts)
4. Catalisador (0-2 pts)
5. Risco/Retorno (0-2 pts)

**Threshold:** Nota >= 7 passa para Fase 2

---

### FASE 2: Análise Quantitativa
**Objetivo:** Matemática pura, sem IA

**Métricas:**
- **Technical:** RSI, ATR, SuperTrend, Suporte/Resistência
- **Risk:** Beta, Volatilidade 20/60d, VaR, Max Drawdown
- **Correlation:** Matriz com posições abertas

**Regra Crítica:** Correlação > 0.7 = VETO automático

---

### FASE 3: Juiz Final (GPT + RAG)
**Objetivo:** Decisão final com modelo premium

**Input Completo:**
- Nota do Screener
- Dados de mercado
- Análise técnica
- Dados macro (VIX, SPY)
- Correlação do portfólio
- Notícias detalhadas
- Contexto RAG (manuais)

**Output:**
```json
{
  "decisao": "APROVAR",
  "nota_final": 8.5,
  "direcao": "LONG",
  "entry_price": 150.00,
  "stop_loss": 145.00,
  "take_profit_1": 160.00,
  "take_profit_2": 165.00,
  "tamanho_sugerido": "NORMAL"
}
```

**Threshold:** Nota >= 8 para APROVAR

---

### FASE 4: Execução
**Objetivo:** Sizing e envio de ordens

**Position Sizing:**
- Base: 1% de risco por trade
- Ajuste por Tier: Large Cap 1x, Mid 0.7x, Small 0.5x
- Ajuste por Sugestão: Normal 1x, Reduzido 0.5x, Mínimo 0.25x
- Ajuste por VIX: >25 = 0.75x, >30 = 0.5x

**Ordens:**
- OCO: Take Profit + Stop Loss
- Backup: Stop-Limit em caso de gap

---

### FASE 5: Monitoramento 24/7
**Objetivo:** Proteger posições abertas

**Componentes:**
1. **Watchdog** (1 min loop)
   - Preço atual vs Stop/TP
   - Flash Crash (>5% em 1 min)
   - Gap detection

2. **Sentinel** (5 min loop)
   - Notícias de posições abertas
   - Análise de impacto com IA

3. **Poison Pill** (Noturno)
   - M&A / OPA
   - SEC investigations
   - Gaps overnight

---

## Gestão de Risco

### Limites Globais
| Parâmetro | Valor |
|-----------|-------|
| Drawdown Diário Máx | 2% |
| Drawdown Total Máx | 6% |
| Risco por Trade | 1% |
| Max Posições | 5 |
| Max Correlação | 0.7 |
| Max Exposição | 80% |

### Kill Switch
**Ativação Automática:**
- Drawdown total >= 6%
- Flash crash >= 10%
- Comando Telegram /kill

**Ação:**
- Fecha todas as posições
- Suspende novas operações
- Envia alerta crítico

---

## Hierarquia de IA

```
┌─────────────────────────────────────────────┐
│         HIERARQUIA DE PROVEDORES            │
├─────────────────────────────────────────────┤
│  1. Screener (FASE 1)                       │
│     └── Gemini Free (custo zero)            │
│                                              │
│  2. Juiz (FASE 3)                           │
│     └── GPT-4/5 (alta qualidade)            │
│     └── Fallback: Claude                    │
│                                              │
│  3. Sentinel (FASE 5)                       │
│     └── GPT-4 Turbo (rápido)                │
│                                              │
│  4. Grounding                               │
│     └── Google Search API                   │
└─────────────────────────────────────────────┘
```

---

## Fluxo de Decisão

```
Candidato
    │
    ▼
┌─────────────────┐
│ Screener (Gemini)│
│   Nota >= 7?    │
└────────┬────────┘
         │ SIM
         ▼
┌─────────────────┐
│ Análise Quant   │
│ Correlação < 0.7│
└────────┬────────┘
         │ SIM
         ▼
┌─────────────────┐
│ Juiz (GPT)      │
│   Nota >= 8?    │
│   R/R >= 2:1?   │
│   VIX < 30?     │
└────────┬────────┘
         │ SIM
         ▼
┌─────────────────┐
│ Position Sizing │
│ + Order OCO     │
└────────┬────────┘
         │
         ▼
    EXECUÇÃO
```

---

## Tecnologias

| Categoria | Tecnologia |
|-----------|------------|
| Linguagem | Python 3.11+ |
| Dados de Mercado | yfinance |
| Análise Técnica | pandas-ta |
| IA - Screener | Google Gemini |
| IA - Juiz | OpenAI GPT-4/5 |
| IA - Backup | Anthropic Claude |
| Broker | ccxt / Paper Trading |
| Alertas | Telegram Bot |
| Banco de Dados | SQLite |
| Cache | Local (JSON) |

---

## Próximos Passos

1. [ ] Implementar integração completa com yfinance
2. [ ] Configurar APIs de IA
3. [ ] Testar em paper trading
4. [ ] Calibrar thresholds de decisão
5. [ ] Adicionar backtesting
6. [ ] Implementar RAG com manuais
7. [ ] Dashboard web (opcional)

---

## Avisos Legais

**ATENÇÃO:** Este sistema é para fins educacionais e de pesquisa. Trading envolve riscos significativos de perda financeira. Sempre faça sua própria análise e nunca invista mais do que pode perder.

---

*IARA TRADER v25.0 - Intelligent Automated Risk-Aware Trader*
