# IARA Debug CLI - Guia de Uso

Sistema de inspeção de JSONs do pipeline IARA sem precisar inicializar o sistema completo.

## Como Usar

```bash
# Ver ajuda
python debug_cli.py /help

# Ver candidatos do Buzz Factory (Phase 0)
python debug_cli.py /buzz

# Ver dados técnicos de um ticker
python debug_cli.py /technical AAPL

# Ver estado do portfolio
python debug_cli.py /portfolio

# Ver configurações
python debug_cli.py /config

# Ver banco de dados
python debug_cli.py /database
```

## Comandos Disponíveis

### Phase 0 - Buzz Factory
- `/buzz` - Gera lista de oportunidades do dia

### Phase 1 - Screener
- `/technical TICKER` - Ver dados de mercado de um ativo

### Estado do Sistema
- `/portfolio` - Ver posições abertas e capital
- `/config` - Ver configurações carregadas
- `/database` - Ver histórico de decisões e trades

## Onde os JSONs são Salvos

Todos os comandos salvam JSONs em:
```
data/debug_outputs/
```

Formato dos arquivos:
```
buzz_factory_20260105_143022.json
technical_AAPL_20260105_143045.json
portfolio_state_20260105_143112.json
```

## Exemplo de Fluxo

```bash
# 1. Ver candidatos gerados
python debug_cli.py /buzz

# 2. Analisar um ticker específico
python debug_cli.py /technical AAPL

# 3. Ver estado do portfolio
python debug_cli.py /portfolio
```

## Notas

- **Não requer API keys** para a maioria dos comandos
- Funciona mesmo sem configuração completa
- JSONs são salvos automaticamente para inspeção posterior
- Output é exibido no console E salvo em arquivo
