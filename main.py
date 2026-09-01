"""
Exemplo de uso da Parte 1 (coleta de dados): resolve o Riot ID, baixa as
partidas mais recentes com timeline completa e salva tudo localmente em
SQLite, pronto para a etapa de heurísticas (Parte 2, próximo passo).

Uso:
    export RIOT_API_KEY="RGAPI-..."
    python main.py "NomeDoJogador" "TAG" --count 5
"""

import argparse
import sys

from riot_client import RiotClient, RiotAPIError
import storage


def coletar_partidas(game_name: str, tag_line: str, count: int):
    storage.init_db()
    client = RiotClient()

    print(f"Resolvendo PUUID de {game_name}#{tag_line}...")
    puuid = client.get_puuid(game_name, tag_line)
    print(f"PUUID: {puuid}")
    storage.save_player(puuid, game_name, tag_line)

    print(f"Buscando as {count} partidas mais recentes...")
    match_ids = client.get_match_ids(puuid, count=count)
    print(f"Encontradas {len(match_ids)} partidas.")

    for i, match_id in enumerate(match_ids, 1):
        existing_match, existing_timeline = storage.load_match(match_id)
        if existing_match and existing_timeline:
            print(f"[{i}/{len(match_ids)}] {match_id} já em cache, pulando.")
            continue

        print(f"[{i}/{len(match_ids)}] Baixando {match_id}...")
        match_data = client.get_match(match_id)
        timeline_data = client.get_match_timeline(match_id)
        storage.save_match(puuid, match_id, match_data, timeline_data)

    print("\nConcluído. Partidas armazenadas localmente:")
    for m in storage.list_stored_matches(puuid):
        print(f"  {m['match_id']}  duração={m['game_duration']}s  queue={m['queue_id']}")
    print("\nPara escolher uma partida e ver o relatório de macro, rode:\n  python select_match.py")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Coleta partidas + timeline da Riot API")
    parser.add_argument("game_name", help="Nome do Riot ID (antes do #)")
    parser.add_argument("tag_line", help="Tag do Riot ID (depois do #), ex: BR1")
    parser.add_argument("--count", type=int, default=5, help="Quantas partidas recentes buscar")
    args = parser.parse_args()

    try:
        coletar_partidas(args.game_name, args.tag_line, args.count)
    except RiotAPIError as e:
        print(f"Erro na Riot API: {e}", file=sys.stderr)
        sys.exit(1)
