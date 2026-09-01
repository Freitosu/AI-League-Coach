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

Isso vai:
1. Resolver seu Riot ID para PUUID
2. Buscar as N partidas mais recentes
3. Baixar o **match** (dados agregados) e a **timeline** (posição,
   gold/xp/cs por minuto, eventos de kill/objetivo/ward) de cada uma
4. Salvar tudo em `data/lol_macro.sqlite3`, em cache — partidas já
   baixadas não são baixadas de novo

## Estrutura

```
config.py         # configuração (API key, região, rate limits)
rate_limiter.py    # respeita os limites da Riot API automaticamente
riot_client.py     # chamadas HTTP: account, match ids, match, timeline
storage.py         # cache local em SQLite
main.py            # script de exemplo (coleta ponta a ponta)
heuristics.py      # heurísticas de macro: CS, wards, roams, objetivos, etc.
analyze.py         # roda as heurísticas sobre uma partida do cache
test_heuristics.py # teste sintético das heurísticas
```

## Parte 2 — Heurísticas (implementada)

`heuristics.py` lê o (match, timeline) salvos e gera eventos estruturados:
CS/min vs benchmark, gold/xp diff vs oponente de lane, presença em
objetivo, torres por fase, wards colocadas/destruídas, mortes isoladas,
kill participation, roams e objetivos tomados em desvantagem.

Rodar sobre uma partida já baixada:
```bash
python analyze.py <match_id> <puuid> --output relatorio.json
```

Rodar o teste sintético (não depende da API):
```bash
python test_heuristics.py
```

**Heurísticas ainda não implementadas** (da lista completa discutida):
freeze/push de wave, CS perdido em recall, resposta a gank, gold parado
(unspent gold) — todas dependem de sinais que a Timeline API não expõe
diretamente (wave state, eventos de recall) e exigiriam aproximações
mais elaboradas por posição/tempo. Posso completá-las se forem
prioridade, ou seguimos para a Parte 3 (comentário via LLM local) com
o que já está pronto.

## Próximos passos

- **Parte 3 — Geração de comentário via LLM local**: usar Ollama
  (`OLLAMA_HOST`/`OLLAMA_MODEL` já em `config.py`) para transformar os
  eventos estruturados em comentário de coach, sem custo de API.
- **Sincronização com vídeo**: input manual (ou detecção simples) do
  timestamp de início da partida no vídeo para converter
  minuto_de_jogo → timestamp_do_vídeo.
