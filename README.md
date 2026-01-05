# IARA 🧜‍♀️ (Inteligência Artificial de Risco e Análise)

> **Sistema Autônomo de Swing Trade "Institutional Grade" com Arquitetura Híbrida.**

A **IARA** é um sistema de trading quantitativo desenvolvido para operar Swing Trade (3-5 dias) com rigor de Hedge Fund. Diferente de bots tradicionais, ela prioriza a **Proteção de Capital** sobre o lucro rápido, utilizando uma arquitetura híbrida que une o processamento de dados local (GPU) com a inteligência de decisão na nuvem (LLMs).

---

## 🧠 Arquitetura Híbrida
O sistema opera em dois ambientes para maximizar eficiência e reduzir custos:

1.  **Local (RTX 2060 / Llama 3):** Responsável pelo trabalho pesado e repetitivo.
    *   Scraping de notícias e triagem inicial.
    *   Cálculo de indicadores técnicos (ATR, ADX, AVWAP).
    *   Monitoramento de preço 24/7 e Watchdog.
2.  **Nuvem (OpenAI GPT-4o):** O "Cérebro" estratégico.
    *   Atua como o **Juiz** no "Tribunal Iara".
    *   Realiza análise de sentimento complexa e correlação macro.
    *   Decide a entrada baseada em Dossiês filtrados.

## ✨ Funcionalidades Principais

*   **🛡️ Gestão de Risco Institucional:**
    *   **Kill Switch:** Bloqueio total se Drawdown > 8%.
    *   **Position Sizing:** Cálculo de lotes baseado em Volatilidade (ATR) e Risco Fixo (1-2%).
    *   **Filtros de Segurança:** Bloqueio de Gaps > 3%, proteção de Sexta-feira e travas de horário.
*   **⚖️ O Tribunal:** Sistema de decisão onde agentes (Touro vs Urso) debatem antes do veredito final do Juiz.
*   **📡 Integração Hardware:** Telemetria física via **Raspberry Pi Pico** (LEDs de Status e Alerta).
*   **⚙️ Execução Profissional:** Ordens OCO (One-Cancels-Other) com Stop-Limit, Stop Loss Técnico e Alvos Dinâmicos.

## 🛠️ Tech Stack

*   **Linguagem:** Python 3.10+
*   **Análise de Dados:** `yfinance`, `pandas_ta`, `numpy`
*   **IA & NLP:** `openai` (API), `torch` (Local), `transformers`
*   **Conexão:** `ccxt` (Corretoras/Crypto), `requests`
*   **Hardware:** `pyserial` (Comunicação com Raspberry Pi)
