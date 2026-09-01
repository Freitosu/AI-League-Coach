"""
Lista as partidas já baixadas e deixa você escolher qual quer analisar,
mostrando o campeão jogado, o horário da partida e se foi vitória ou
derrota. Depois de escolher, roda as heurísticas de macro sobre ela.

Uso:
    python select_match.py
    python select_match.py --puuid <puuid>       # pula a seleção de jogador
    python select_match.py --output relatorio.json
    python select_match.py --commentary          # também gera comentário via LLM local
"""

import argparse
import sys
from datetime import datetime

import storage
from analyze import analisar


def escolher_jogador():
    players = storage.list_players()
    if not players:
        print("Nenhum jogador salvo ainda. Rode main.py primeiro para baixar partidas.", file=sys.stderr)
        sys.exit(1)
    if len(players) == 1:
        return players[0]["puuid"]

    print("Vários jogadores encontrados no cache local:\n")
    for i, p in enumerate(players, 1):
        print(f"  [{i}] {p['game_name']}#{p['tag_line']}")
    escolha = input("\nEscolha o jogador (número): ").strip()
    try:
        idx = int(escolha) - 1
        return players[idx]["puuid"]
    except (ValueError, IndexError):
        print("Escolha inválida.", file=sys.stderr)
        sys.exit(1)


def formatar_data(game_creation_ms: int) -> str:
    if not game_creation_ms:
        return "data desconhecida"
    dt = datetime.fromtimestamp(game_creation_ms / 1000)
    return dt.strftime("%d/%m/%Y %H:%M")


def formatar_duracao(segundos: int) -> str:
    if not segundos:
        return "?"
    minutos, seg = divmod(segundos, 60)
    return f"{minutos}min{seg:02d}s"


def escolher_partida(puuid: str):
    matches = storage.list_stored_matches(puuid)
    if not matches:
        print("Nenhuma partida em cache para esse jogador. Rode main.py primeiro.", file=sys.stderr)
        sys.exit(1)

    print(f"\nPartidas disponíveis:\n")
    print(f"{'#':<4}{'Data/Hora':<18}{'Campeão':<16}{'Duração':<12}{'Resultado':<10}")
    print("-" * 60)
    for i, m in enumerate(matches, 1):
        resultado = "✅ Vitória" if m["win"] is True else "❌ Derrota" if m["win"] is False else "? "
        champion = m["champion_name"] or "?"
        print(
            f"{i:<4}{formatar_data(m['game_creation']):<18}{champion:<16}"
            f"{formatar_duracao(m['game_duration']):<12}{resultado:<10}"
        )

    escolha = input("\nEscolha a partida para analisar (número): ").strip()
    try:
        idx = int(escolha) - 1
        return matches[idx]["match_id"]
    except (ValueError, IndexError):
        print("Escolha inválida.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Escolhe interativamente uma partida em cache e roda as heurísticas")
    parser.add_argument("--puuid", help="Pula a seleção de jogador e usa esse PUUID diretamente")
    parser.add_argument("--output", "-o", help="Caminho para salvar o relatório em JSON")
    parser.add_argument("--commentary", "-c", action="store_true", help="Gera comentário de coach via LLM local (Ollama)")
    args = parser.parse_args()

    storage.init_db()
    puuid = args.puuid or escolher_jogador()
    match_id = escolher_partida(puuid)
    analisar(match_id, puuid, args.output, args.commentary)
