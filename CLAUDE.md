# CLAUDE.md — LoL Macro AI

Instruções de contexto para trabalhar neste projeto. Leia isto antes de
explorar a pasta.

## Arquitetura (visão geral)

Pipeline local, sem custo de API de IA:

  Riot API → SQLite (cache local) → heurísticas → comentário (Ollama, opcional) → dashboard.html

1. `main.py` / `refresh.py` baixam partidas da Riot API e salvam em `data/lol_macro.sqlite3`.
2. `heuristics.py` lê (match, timeline) do cache e produz eventos de macro estruturados.
3. `commentary.py` (opcional, via Ollama local) transforma os eventos em texto de coach.
4. `export_dashboard.py` monta tudo isso e gera `dashboard.html`, um arquivo único e autocontido.

## Função de cada módulo

| Arquivo | Função |
|---|---|
| `config.py` | Configuração central (API key, região, Ollama, caminho do DB) |
| `rate_limiter.py` | Rate limiting das chamadas à Riot API |
| `riot_client.py` | Cliente HTTP da Riot API (account, match ids, match, timeline) |
| `storage.py` | Toda a camada SQLite: schema, migração, cache, expiração de 2 dias |
| `main.py` | Coleta inicial de partidas para um jogador novo |
| `refresh.py` | Busca partidas novas + regenera o dashboard numa chamada |
| `select_match.py` | CLI interativa para escolher e analisar uma partida |
| `analyze.py` | Roda heurísticas (+ comentário opcional) numa partida específica |
| `heuristics.py` | Todas as heurísticas de macro (CS, objetivos, visão, remake, rendição, etc.) |
| `ollama_client.py` | Cliente mínimo do Ollama local |
| `commentary.py` | Monta o prompt e gera o comentário de coach via Ollama |
| `export_dashboard.py` | Monta os dados + gera o HTML do dashboard (template embutido) |
| `test_heuristics.py` | Teste sintético das heurísticas, sem depender da API real |
| `test_new_heuristics.py` | Teste sintético de remake, rendição, timing e eventos positivos |

## Nunca ler estes arquivos por inteiro

- **`data/lol_macro.sqlite3`** — binário, ~10 MB e crescendo. NUNCA usar
  `view`/`read_text_file` nele. Ver seção "Como consultar o banco" abaixo.
- **`dashboard.html`** — gerado, contém todo o histórico de partidas
  embutido como JSON inline. Se precisar inspecionar o template
  HTML/CSS/JS, leia por `view_range` (as primeiras ~300 linhas são
  template; o JSON de dados vem depois, numa única linha longa — não
  tem valor de leitura). Nunca precise ler isso pra entender o
  código-fonte Python.
- **`.env`** — contém a API key da Riot. Nunca ler o conteúdo.
- **`__pycache__/`** e **`.git/`** — nunca relevantes para entender ou
  editar o código. Se listar a pasta recursivamente, exclua ambos.

## Como consultar o banco (sem carregar o arquivo inteiro)

Nunca abra o `.sqlite3` como arquivo de texto. Para investigar dados
específicos, rode uma query pontual via Python, por exemplo:

    python -c "import storage; print(storage.get_match_summary('MATCH_ID'))"
    python -c "import storage; print(storage.list_stored_matches('PUUID'))"

Ou uma query SQL direta e filtrada quando precisar de algo que
`storage.py` não expõe:

    python -c "
    import storage
    conn = storage.get_connection()
    print(conn.execute('SELECT match_id, champion_name FROM matches WHERE win = 0 LIMIT 5').fetchall())
    conn.close()
    "

Sempre filtre por `match_id`/`puuid`/`LIMIT` — nunca faça `SELECT *` sem
filtro numa tabela que pode crescer.

## Mantendo o contexto pequeno durante o desenvolvimento

- Leia só o(s) módulo(s) que a tarefa realmente toca. Editar uma
  heurística não exige reler `export_dashboard.py`, `riot_client.py`
  etc., a menos que a tarefa explicitamente envolva esses módulos.
- Prefira `str_replace`/edições pontuais a reescrever um arquivo
  inteiro quando a mudança é pequena.
- Antes de editar, confirme rapidamente o trecho atual do arquivo
  (arquivos aqui já divergiram entre máquinas antes — sempre releia o
  trecho relevante antes de editar, mas só o trecho, não o arquivo
  inteiro se ele for grande).
- Ao investigar um bug relatado numa partida específica, peça/gere o
  `match_id` e consulte só aquela partida — nunca carregue o histórico
  inteiro do dashboard ou do banco para debugar um caso.

## Escopo das alterações

- Mudanças ficam restritas ao que foi pedido. Não "aproveitar" uma
  tarefa para refatorar, renomear ou reorganizar arquivos não
  relacionados.
- Não dividir/reorganizar módulos por preferência de estilo — só
  quando houver um motivo concreto e citável (ex: um arquivo virou
  gargalo real de contexto ou mistura responsabilidades que atrapalham
  a tarefa em questão).
- Ao terminar uma tarefa, o diff esperado toca só os arquivos
  necessários para aquela tarefa específica.
