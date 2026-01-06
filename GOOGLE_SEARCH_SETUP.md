# Como Configurar Google Custom Search API

## Passo 1: Criar API Key

1. Acesse: https://console.cloud.google.com/
2. Selecione seu projeto (ou crie um novo)
3. No menu lateral: **APIs e serviços** → **Credenciais**
4. Clique em **+ CRIAR CREDENCIAIS**
5. Escolha **Chave de API** (NÃO escolha OAuth ou Service Account)
6. Copie a API Key gerada
7. (Opcional) Clique em "RESTRINGIR CHAVE" e limite apenas para "Custom Search API"

## Passo 2: Habilitar Custom Search API

1. No menu lateral: **APIs e serviços** → **Biblioteca**
2. Busque por "Custom Search API"
3. Clique em **ATIVAR**

## Passo 3: Criar Custom Search Engine (CSE)

1. Acesse: https://programmablesearchengine.google.com/
2. Clique em **Add** (ou "Adicionar")
3. Configure:
   - **Nome do mecanismo**: IARA News Search
   - **O que pesquisar**: Escolha uma das opções:

     **Opção A - Sites Específicos (Recomendado):**
     ```
     *.reuters.com
     *.bloomberg.com
     *.cnbc.com
     *.marketwatch.com
     *.wsj.com
     *.ft.com
     *.seekingalpha.com
     *.barrons.com
     ```

     **Opção B - Web Inteira:**
     - Deixe em branco ou selecione "Pesquisar toda a web"
     - Depois vá em Configurações → "Pesquisar toda a web" = ON

   - **Idioma**: English

4. Clique em **Criar**
5. Na página seguinte, copie o **ID do mecanismo de pesquisa** (cx)
   - Exemplo: `012345678901234567890:abcdefghijk`

## Passo 4: Configurar .env

1. Abra o arquivo `.env` (ou crie copiando `.env.example`)
2. Adicione as duas variáveis:

```env
# Google Custom Search API
GOOGLE_SEARCH_API_KEY=AIzaSyA... (sua API key do Passo 1)
GOOGLE_CSE_ID=012345678901234567890:abc... (seu CSE ID do Passo 3)
```

3. Salve o arquivo

## Passo 5: Instalar Dependência (se necessário)

```bash
pip install google-api-python-client
```

(Já está em `requirements.txt`, mas se precisar instalar manualmente)

## Passo 6: Testar

```bash
python main.py
```

Você deve ver no log de inicialização:
```
[OK] Google Search API configurada: 95/95 queries disponíveis hoje
```

## Limites e Custos

### Free Tier:
- **100 queries/dia** GRÁTIS
- IARA usa limite de **95/dia** (margem de segurança de 5)
- Reset automático à meia-noite (UTC)

### Após Free Tier:
- **$5 por 1000 queries adicionais**
- Você pode configurar alertas de billing no Google Cloud Console

## Fallback Automático

Se o limite for atingido, IARA automaticamente usa **GNews (grátis)** como fallback:

```
[WARNING] Google Search API: Limite diario atingido (95/95). Usando fallback GNews...
[FALLBACK] Usando GNews API para AAPL...
```

O sistema continua funcionando normalmente!

## Logs de Monitoramento

### Durante Execução:
```
[OK] Google Search API configurada: 95/95 queries disponiveis hoje
[SEARCH] Google Search API: Buscando noticias para AAPL...
[NEWS] Google Search API: 10 resultados encontrados para AAPL
[OK] Google Search API: 9 artigos processados para AAPL
```

### A cada 10 queries:
```
[STATS] Google Search API: 10/95 queries usadas hoje (restam 85)
[STATS] Google Search API: 20/95 queries usadas hoje (restam 75)
...
```

### Quando atingir limite:
```
[WARNING] Google Search API: Limite diario atingido (95/95). Usando fallback GNews...
```

### Novo dia (reset automático):
```
[RESET] Google Search API: Novo dia detectado. Reset contador: 95 -> 0
[OK] Google Search API: 95/95 queries disponiveis hoje
```

## Contador Persistente

O contador é salvo em: `data/cache/google_search_counter.json`

Formato:
```json
{
  "count": 45,
  "date": "2026-01-06"
}
```

Se você quiser resetar manualmente, delete este arquivo.

## Troubleshooting

### Erro: "API key not valid"
- Verifique se copiou a API key completa
- Verifique se habilitou "Custom Search API" no Google Cloud Console
- Aguarde alguns minutos (pode levar até 5min para propagar)

### Erro: "Invalid CSE ID"
- Verifique se copiou o ID completo (inclui o `:` no meio)
- Formato correto: `012345678901234567890:abcdefghijk`

### Sistema sempre usa GNews (não usa Google Search)
- Verifique se as variáveis estão no `.env` (não `.env.example`)
- Verifique se não há espaços ou aspas nas variáveis
- Reinicie o sistema após editar `.env`

### Limite atingido muito rápido
- Verifique o contador: `cat data/cache/google_search_counter.json`
- Se necessário, delete o arquivo para resetar
- Sistema limita a 95/dia automaticamente

## Sem Google Search? Sem Problemas!

Se você **NÃO** configurar Google Search API:
- Sistema usa **GNews gratuito** automaticamente
- Funcionalidade completa mantida
- Log mostra: `[WARNING] Google Search API nao configurada. Usando fallback GNews.`

IARA funciona 100% mesmo sem Google Search!
