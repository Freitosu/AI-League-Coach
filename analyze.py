"""
Roda as heurísticas de macro sobre uma partida já baixada (via main.py)
e imprime/salva o relatório estruturado. Opcionalmente gera um
comentário de coach usando um LLM local (Ollama).

Uso:
    python analyze.py <match_id> <puuid>
    python analyze.py <match_id> <puuid> --commentary

Dica: os match_ids e puuid aparecem na saída de main.py.
"""

import argparse
import json
import sys

import storage
from heuristics import run_all_heuristics


def analisar(match_id: str, puuid: str, output_path: str = None, comentario: bool = False):
    match_data, timeline_data = storage.load_match(match_id)
    if match_data is None or timeline_data is None:
        print(f"Partida {match_id} não encontrada no cache local. Rode main.py primeiro.", file=sys.stderr)
        sys.exit(1)

    events = run_all_heuristics(match_data, timeline_data, puuid)

    print(f"\n=== Relatório de macro — partida {match_id} ({len(events)} eventos) ===\n")
    for e in events:
        marcador = {"info": "  ", "atencao": "⚠ ", "critico": "‼ "}.get(e["severidade"], "  ")
        print(f"{marcador}[{e['minuto']:>5.1f}min] {e['tipo']:<28} {e['detalhe']}")

    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(events, f, ensure_ascii=False, indent=2)
        print(f"\nSalvo em {output_path}")

    if comentario:
        from commentary import gerar_comentario
        from ollama_client import OllamaError

        match_summary = storage.get_match_summary(match_id)
        print("\n=== Comentário do coach (LLM local via Ollama) ===\n")
        try:
            texto = gerar_comentario(match_summary, events)
            print(texto)
        except OllamaError as e:
            print(f"[Aviso] Não foi possível gerar o comentário: {e}", file=sys.stderr)

    return events


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Roda as heurísticas de macro sobre uma partida em cache")
    parser.add_argument("match_id")
    parser.add_argument("puuid")
    parser.add_argument("--output", "-o", help="Caminho para salvar o relatório em JSON")
    parser.add_argument("--commentary", "-c", action="store_true", help="Gera comentário de coach via LLM local (Ollama)")
    args = parser.parse_args()

    storage.init_db()
    analisar(args.match_id, args.puuid, args.output, args.commentary)
