# LoL Macro AI — Parte 1: Coleta de dados (Riot API)

Pipeline local (sem custo de API de IA) para analisar macro gameplay de
partidas de League of Legends, usando dados oficiais da Riot em vez de
visão computacional sobre o vídeo.

## Setup

1. Crie uma API key em https://developer.riotgames.com/ (key de
   desenvolvimento expira em 24h — ok para testar; depois é possível
   solicitar uma personal/production key para uso contínuo).

2. Instale as dependências:
   ```bash
   pip install -r requirements.txt
   ```

3. Configure a variável de ambiente com sua key:
   ```bash
   export RIOT_API_KEY="RGAPI-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
   ```
   ou crie um arquivo `.env` na raiz do projeto com o conteúdo de
   `.env.example` e ajuste os valores. O projeto já carrega esse
   arquivo automaticamente via `python-dotenv`.

4. Ajuste `RIOT_REGIONAL_ROUTING` em `config.py` se necessário. Para
   contas brasileiras, `americas` (regional, usado em Account-V1 e
   Match-V5) já é o correto por padrão.

## Uso

```bash
python main.py "SeuNome" "TAG" --count 10
```

Depois, para escolher qual partida analisar (mostra campeão, data/hora
e vitória/derrota):

```bash
python select_match.py
```

Isso vai:
1. Resolver seu Riot ID para PUUID
2. Buscar as N partidas mais recentes
3. Baixar o **match** (dados agregados) e a **timeline** (posição,
   gold/xp/cs por minuto, eventos de kill/objetivo/ward) de cada uma
4. Salvar tudo em `data/lol_macro.sqlite3`, em cache — partidas já
   baixadas não são baixadas de novo

## Estrutura

```
config.py         # configuração (API key, região, rate limits, Ollama)
rate_limiter.py    # respeita os limites da Riot API automaticamente
riot_client.py     # chamadas HTTP: account, match ids, match, timeline
storage.py         # cache local em SQLite (partidas, jogadores)
main.py            # coleta ponta a ponta (Riot API -> SQLite)
select_match.py    # escolhe interativamente qual partida analisar
heuristics.py      # heurísticas de macro: CS, wards, roams, objetivos, etc.
analyze.py         # roda as heurísticas (+ comentário opcional) sobre uma partida
ollama_client.py   # cliente mínimo para o Ollama local
commentary.py      # gera o comentário de coach a partir dos eventos
export_dashboard.py # gera o dashboard.html (com ícones, comentário, etc.)
refresh.py         # busca partidas novas na Riot API + regenera o dashboard
test_heuristics.py # teste sintético das heurísticas
```

## Parte 2 — Heurísticas (implementada)

`heuristics.py` lê o (match, timeline) salvos e gera eventos estruturados:
CS/min vs benchmark, gold/xp diff vs oponente de lane, curva de lane por
checkpoint (ouro/CS/XP/plates vs o oponente direto em 5/10/15/20min),
presença em objetivo, torres e inibidores por fase, wards
colocadas/destruídas, mortes isoladas (com contexto de risco: inimigos
próximos, visão recente, se estava fora da posição habitual de lane),
kill participation, roams e objetivos tomados em desvantagem — além de:

- **Schema de confiança** (`confianca`: `alta`/`media`/`baixa`, separado
  de `severidade`): todo evento distingue fato observado direto na
  timeline (`alta`) de inferência aproximada por posição/janela de tempo
  (`media`/`baixa`) — o `commentary.py` usa isso para instruir o LLM a
  tratar cada nível de forma diferente (fato vs "possivelmente").
- **Roams por janela contígua**: em vez de um evento por frame que
  saltou de posição, `h_roams` calcula uma "home position" dinâmica do
  jogador (mediana de posição entre 2-8min) e agrupa toda a permanência
  contínua fora dela em uma única janela — exclui trechos que tocam a
  própria base (recall ≠ roam), descarta janelas curtas (<60s, ruído), e
  classifica confiança por evidência de kill/assist ou objetivo próximo
  em seguida, em vez de tratar toda saída de lane como fato.
- **Detecção de remake**: partidas encerradas por abandono/AFK nos
  primeiros minutos (`gameEndedInEarlySurrender`) retornam só um evento
  de remake, sem heurísticas sem sentido rodando em cima de dado curto
  demais.
- **Detecção de rendição**: partidas encerradas por FF (`gameEndedInSurrender`)
  geram um evento com um **motivo provável** (desvantagem de gold ou
  saldo de torres no momento da rendição) quando o time perde, ou um
  evento positivo quando o adversário desiste com você na frente. É uma
  inferência qualitativa — a Riot não expõe o motivo real da votação.
- **Checkpoints respeitam a duração real da partida**: os benchmarks de
  5/10/15/20min só são avaliados se a partida durou o suficiente para
  chegar lá — corrige o bug em que uma partida curta comparava CS de um
  minuto que nunca aconteceu (ex: mostrar "CS abaixo aos 5min" usando o
  frame de 1min disponível).
- **Torres vs inibidores**: `h_torres_por_fase` checa `buildingType`
  antes de `towerType` — inibidores não têm `towerType`, então sem essa
  checagem apareciam rotulados como "Torre (LANE, ?)" em vez de Inibidor.
- **Eventos positivos** (severidade `"positivo"`): vantagem de gold vs
  oponente de lane, presença em objetivo que o time tomou, roam
  bem-sucedido, boa troca de dano (mais dano causado a campeões do que
  recebido numa janela de laning), alta participação em kills, e a
  rendição do inimigo enquanto você vencia.

Rodar sobre uma partida já baixada:
```bash
python analyze.py <match_id> <puuid> --output relatorio.json
```

Rodar os testes sintéticos (não dependem da API):
```bash
python test_heuristics.py   # cobre básicos + remake, rendição, timing, eventos positivos
```

Todas as 13 heurísticas da lista original estão implementadas,
incluindo as 4 aproximadas (freeze/push de wave, CS perdido em recall,
resposta a gank, gold parado) que dependem de proxies de posição em
vez de eventos diretos da API — o `detalhe` de cada evento deixa claro
quando é uma aproximação.

## Parte 3 — Comentário via LLM local (implementada)

Usa o [Ollama](https://ollama.com) rodando na sua máquina — sem custo
de tokens, sem depender de internet após o download do modelo.

1. Instale o Ollama e baixe um modelo:
   ```bash
   ollama pull llama3.1:8b
   ```
2. Deixe o Ollama rodando (abre em segundo plano após instalado, ou
   rode `ollama serve` manualmente).
3. Rode a análise com a flag `--commentary`:
   ```bash
   python select_match.py --commentary
   # ou
   python analyze.py <match_id> <puuid> --commentary
   ```

O `commentary.py` recebe os eventos estruturados (não o vídeo, nem
dados brutos) e escreve um comentário organizado por fase do jogo
(early/mid/late) com recomendações — o modelo local só precisa
"traduzir" dado estruturado em texto, não entender LoL do zero.

Se o Ollama não estiver rodando ou o modelo não estiver baixado, o
script avisa exatamente o que fazer em vez de travar.

## Dashboard visual (estilo BI)

`export_dashboard.py` gera um arquivo HTML único e autônomo com um
painel visual de todas as partidas em cache: KPIs (win rate, alertas
críticos, campeão mais jogado), lista de partidas com ícone do campeão
ao lado do nome, e por partida uma linha do tempo dos eventos de macro
coloridos por severidade, gráfico de fase do jogo, comentário do coach
e a lista detalhada.

```bash
python export_dashboard.py                # só heurísticas
python export_dashboard.py --commentary   # + comentário via Ollama (cacheado por partida)
```

Depois é só abrir o `dashboard.html` gerado no navegador (duplo
clique) — não precisa de servidor. Os ícones dos campeões vêm do Data
Dragon oficial da Riot; se estiver offline na hora de abrir, caem num
ícone genérico de fallback e o resto do dashboard continua funcionando
normalmente.

O comentário do coach (`--commentary`) fica **cacheado no banco** por
partida — só é gerado de novo se a partida sair e voltar pro cache
(após expirar e ser rebaixada). Cada chamada ao Ollama roda localmente
e pode levar alguns segundos por partida, dependendo do modelo e da
sua máquina.

## Expiração de cache e atualização de partidas

Partidas ficam em cache local por **2 dias** (contados a partir de
quando foram baixadas, não da data do jogo). Toda vez que qualquer
script roda `storage.init_db()` (o que main.py, select_match.py,
analyze.py e export_dashboard.py já fazem), partidas mais antigas que
isso são removidas automaticamente do banco — isso mantém o cache
enxuto e os dados sempre razoavelmente recentes. Ajustável via
`storage.CACHE_MAX_AGE_DAYS`.

Como o dashboard é um HTML estático (não pode chamar a Riot API
sozinho sem expor sua key no navegador), atualizar com partidas novas
é feito por um script único que busca o que tem de novo e já regenera
o dashboard:

```bash
python refresh.py                  # verifica as 10 partidas mais recentes
python refresh.py --count 20
python refresh.py --commentary     # também gera comentário nas partidas novas
```

Depois é só dar F5 (ou reabrir) o `dashboard.html` no navegador. O
próprio dashboard mostra no rodapé da barra lateral quando foi gerado
pela última vez e o comando pra atualizar.

## Próximos passos

- **Sincronização com replay**: integração com o LoL Replay API local
  (`https://127.0.0.1:2999/replay/`, requer `EnableReplayApi=1` em
  `game.cfg`) para gerar um roteiro de coaching com timestamps e
  auto-pause nos momentos de macro relevantes — narração em tempo real
  foi descartada, o plano é um roteiro assíncrono.
- **Ajuste fino de benchmarks**: os valores de CS/min e de spawn de
  objetivo em `heuristics.py` são aproximados; ajustar por elo/patch
  deixaria os alertas mais precisos.
- **Modelo ativo**: `qwen2.5:14b` (configurado via `OLLAMA_MODEL` no
  `.env`) substituiu o `llama3.1:8b` do exemplo acima por qualidade de
  comentário melhor.
