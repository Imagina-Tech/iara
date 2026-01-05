# IARA 🧜‍♀️ - Institutional Automated Risk Analysis (v25.0)

> **Sistema Autônomo de Trading Quantitativo "Market Survivor".**
> *Focado em Swing Trade (3-5 dias), Proteção de Capital Extrema e Arquitetura Híbrida de Custo Otimizado.*

![Status](https://img.shields.io/badge/Status-Production%20Ready-green) ![Version](https://img.shields.io/badge/Version-v25.0%20Atomic-blue) ![Python](https://img.shields.io/badge/Python-3.10%2B-yellow)

A **IARA** não é apenas um robô de trade; é um sistema de tesouraria completo. Diferente de bots comuns que focam apenas em "Sinais de Entrada", a IARA foi arquitetada com foco em **Sobrevivência**, implementando travas contra Flash Crashes, Correlação Cruzada de Portfólio, Detecção de OPA/M&A (Poison Pill) e execução tierizada para Small Caps.

---

## 🧠 Arquitetura "Atomic Survivor"

O sistema opera em um fluxo sequencial de 6 fases, combinando **Matemática Pura (Python Local)** para dados e risco, com **Inteligência Artificial (Nuvem)** para estratégia e triagem.

### 1. 🏭 Fase 0: Fábrica de Universo (08:00)
Geração inteligente da lista de ativos do dia.
*   **Buzz Factory:** Combina dados quantitativos (`yfinance` Top Gainers/Volume) com dados qualitativos (Scraper de Manchetes + NLP).
*   **Tiering Dinâmico:** Classifica ativos em **Tier 1** (Blue Chips > $4B) e **Tier 2** (Small Caps > $800M).
*   **Filtros de Qualidade:** Rejeita liquidez < $15M/dia e Market Cap < $800M.

### 2. 🔍 Fase 1: Triagem Híbrida (10:30)
Análise profunda com custo otimizado.
*   **Coleta:** Técnica (`pandas_ta`), Fundamentalista e Notícias (`newspaper3k`).
*   **IA de Triagem:** Utiliza **Google Gemini 3 Flash (Free Tier)** com *Rate Limiting* (Sleep 4s) para filtrar ruído e dar notas de relevância (0-10).
*   **Filtros Técnicos:** Bloqueio de Gaps > 3% e Earnings em 5 dias.

### 3. 🛡️ Fase 2: O Cofre de Risco (Matemática)
Nenhuma IA toma decisão sem passar pela matemática.
*   **Correlação Cruzada:** Bloqueia entrada se a correlação com o portfólio atual for > 0.75.
*   **Beta Inteligente:** Permite Beta > 3.0 apenas se o volume for alto, ajustando o lote.
*   **Drawdown Gradual:** Reduz lote em 50% se DD > 5%. **Kill Switch** se DD > 8%.

### 4. ⚖️ Fase 3: O Tribunal (Hierarquia de IA)
Decisão estratégica baseada em Dossiês.
*   **Grounding:** Pesquisa Google (Free) para validar rumores antes de julgar.
*   **Juiz Principal:** **GPT-5.2** (OpenAI) com acesso a RAG (Manuais de Estratégia).
*   **Fallback System:** Se OpenAI cair -> Tenta GPT-4o-mini -> Tenta Claude 3.5 -> Último caso Gemini.

### 5. ⚙️ Fase 4: Execução Blindada
Protocolo de ordens para evitar *slippage* e erros.
*   **Entrada:** Apenas **STOP-LIMIT** (+0.5% do gatilho). Nunca a mercado.
*   **Position Sizing:** Risco fixo de 1-2% ajustado por ATR e Tier (Redutor para Small Caps).
*   **Proteção Física:** Envio de Stop Loss Físico para a corretora + Backup Stop (Market) em -10%.

### 6. 👮 Fase 5: O Guardião 24/7
Monitoramento contínuo e protocolos de emergência.
*   **Anti-Cascata:** Monitora Drawdown Intraday. Se cair 4%, zera tudo (Panic Protocol).
*   **Poison Pill (M&A):** Scanner noturno busca termos de OPA/Fusão. Se achar, cancela stops e busca alvo de +60%.
*   **Kill Switch Remoto:** Integração com **Telegram** para zeragem imediata via comando.

---

## 🛠️ Tech Stack

*   **Core:** Python 3.10+
*   **Dados:** `yfinance`, `requests`, `newspaper3k`
*   **Matemática:** `pandas`, `pandas_ta` (Indicadores), `numpy`
*   **AI Gateways:** `openai` (GPT-5.2), `google-generativeai` (Gemini Flash), `anthropic`
*   **Infra:** `sqlite3` (Logs/Cache), `python-telegram-bot`
*   **Hardware:** Integração Serial Opcional (Raspberry Pi Pico para LEDs de Status).
