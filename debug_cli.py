#!/usr/bin/env python3
"""
IARA DEBUG CLI - Sistema de Inspeção de JSONs

Execute: python debug_cli.py

Comandos disponíveis:
- /help                    -> Mostrar ajuda
- /buzz                    -> Ver output do Buzz Factory
- /news [TICKER]           -> Ver notícias raw
- /gnews [TICKER]          -> Ver notícias do GNews API
- /gnews-treated [TICKER]  -> Ver notícias após tratamento de IA
- /technical [TICKER]      -> Ver análise técnica
- /screener [TICKER]       -> Ver resultado do screener
- /risk [TICKER]           -> Ver análise de risco
- /correlation             -> Ver matriz de correlação
- /judge [TICKER]          -> Ver decisão do Judge
- /grounding [TICKER]      -> Ver Google Grounding
- /execution [TICKER]      -> Ver cálculos de execução
- /portfolio               -> Ver estado do portfolio
- /config                  -> Ver configurações
- exit ou quit             -> Sair
"""

import sys
import asyncio
import logging
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.debug.debug_commands import DebugCommands
from main import initialize_components

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


async def main():
    """Inicia o CLI de debug."""
    print("\n" + "="*80)
    print("  IARA DEBUG CLI - Sistema de Inspeção de JSONs")
    print("="*80)
    print("\nDigite /help para ver comandos disponíveis")
    print("Digite 'exit' ou 'quit' para sair\n")

    # Inicializar componentes
    print("🔧 Inicializando componentes do sistema...\n")

    try:
        orchestrator, config = await initialize_components()
        debug_cmd = DebugCommands(orchestrator)

        print("✅ Sistema inicializado com sucesso!\n")
        print(f"📁 Outputs salvos em: {debug_cmd.output_dir}\n")

    except Exception as e:
        print(f"❌ Erro ao inicializar sistema: {e}\n")
        return

    # Loop interativo
    while True:
        try:
            # Prompt
            command = input("IARA> ").strip()

            if not command:
                continue

            # Exit commands
            if command.lower() in ["exit", "quit", "q"]:
                print("\n👋 Até logo!\n")
                break

            # Executar comando
            await debug_cmd.run_command(command)

        except KeyboardInterrupt:
            print("\n\n👋 Interrompido pelo usuário. Até logo!\n")
            break

        except Exception as e:
            logger.error(f"Error in CLI loop: {e}")
            print(f"\n❌ Erro: {e}\n")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n👋 Saindo...\n")
        sys.exit(0)
