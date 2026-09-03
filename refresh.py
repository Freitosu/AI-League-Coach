"""
Atualiza o cache local (busca as partidas mais recentes na Riot API,
pulando as que já estão em cache) e regenera o dashboard.html
automaticamente. É o "botão de refresh" do projeto — como o dashboard
é um HTML estático, ele não pode chamar a Riot API sozinho (exigiria
expor sua API key no navegador), então esse script faz o papel de
atualizar os dados e já deixa o dashboard pronto pra reabrir.

Uso:
    python refresh.py                  # 10 partidas mais recentes
    python refresh.py --count 20
    python refresh.py --commentary     # também gera comentário via Ollama nas novas
    python refresh.py --puuid <puuid>  # se houver mais de um jogador salvo
"""

import argparse
import sys

import storage
from riot_client import RiotClient, RiotAPIError
from export_dashboard import get_latest_ddragon_version, montar_dados, gerar_html


def escolher_jogador(puuid_arg: str = None) -> str:
    if puuid_arg:
        return puuid_arg
    players = storage.list_players()
    if not players:
        print("Nenhum jogador salvo. Rode main.py primeiro.", file=sys.stderr)
        sys.exit(1)
    if len(players) > 1:
        print("Vários jogadores salvos, usando o primeiro. Use --puuid para escolher outro:")
        for p in players:
            print(f"  {p['game_name']}#{p['tag_line']} -> {p['puuid']}")
    return players[0]["puuid"]


def atualizar_partidas(puuid: str, count: int) -> int:
    client = RiotClient()
    print(f"Buscando as {count} partidas mais recentes na Riot API...")
    match_ids = client.get_match_ids(puuid, count=count)

    novas = 0
    for i, match_id in enumerate(match_ids, 1):
        existing_match, existing_timeline = storage.load_match(match_id)
        if existing_match and existing_timeline:
            continue
        print(f"  [{i}/{len(match_ids)}] Partida nova: baixando {match_id}...")
        match_data = client.get_match(match_id)
        timeline_data = client.get_match_timeline(match_id)
        storage.save_match(puuid, match_id, match_data, timeline_data)
        novas += 1

    if novas == 0:
        print("Nenhuma partida nova encontrada (já estavam todas em cache).")
    else:
        print(f"{novas} partida(s) nova(s) baixada(s).")
    return novas


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Atualiza o cache de partidas e regenera o dashboard")
    parser.add_argument("--puuid", help="PUUID do jogador (opcional se só houver um salvo)")
    parser.add_argument("--count", type=int, default=10, help="Quantas partidas recentes verificar na Riot API")
    parser.add_argument("--output", "-o", default="dashboard.html", help="Arquivo HTML de saída")
    parser.add_argument("--commentary", "-c", action="store_true", help="Gera comentário via Ollama para partidas novas")
    args = parser.parse_args()

    storage.init_db()  # também expira partidas com mais de 2 dias no cache
    puuid = escolher_jogador(args.puuid)

    try:
        atualizar_partidas(puuid, args.count)
    except RiotAPIError as e:
        print(f"Erro na Riot API: {e}", file=sys.stderr)
        sys.exit(1)

    print("\nRegenerando dashboard...")
    version = get_latest_ddragon_version()
    dados = montar_dados(puuid, version, gerar_comentarios=args.commentary)
    html = gerar_html(dados)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Dashboard atualizado: {args.output}\nReabra (ou dê F5) o arquivo no navegador.")
