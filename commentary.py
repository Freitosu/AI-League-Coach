"""
Parte 3 — Geração de comentário de coach a partir dos eventos de macro,
usando um LLM local via Ollama (sem custo de tokens de API).
"""

from collections import defaultdict

from ollama_client import chat


SYSTEM_PROMPT = """Você é um coach experiente de League of Legends, especializado em macro gameplay \
(controle de mapa, objetivos, visão, wave management, rotações). Você recebe uma lista de eventos \
estruturados extraídos automaticamente do replay de uma partida de um jogador específico, e escreve \
um comentário de análise pós-jogo em português do Brasil.

Regras:
- Foque em PADRÕES, não liste cada evento individualmente.
- Organize por fase do jogo: early (0-15min), mid (15-25min), late (25min+).
- Para cada fase, aponte 1-3 pontos principais (erros e acertos), citando o minuto quando relevante.
- Termine com 2-3 recomendações concretas e acionáveis para a próxima partida.
- Tom direto e construtivo, como um coach de verdade — não genérico, não robótico.
- Não invente informação que não esteja nos eventos fornecidos.
- Máximo de ~400 palavras.
"""


def _summarize_events_for_prompt(events: list, max_raw: int = 40) -> str:
    """Passa os eventos crus se forem poucos; agrupa por tipo se forem muitos,
    para não estourar o contexto de um modelo local menor."""
    if len(events) <= max_raw:
        return "\n".join(f"- [{e['minuto']}min] ({e['severidade']}) {e['tipo']}: {e['detalhe']}" for e in events)

    grupos = defaultdict(list)
    for e in events:
        grupos[e["tipo"]].append(e)

    linhas = []
    for tipo, evs in grupos.items():
        minutos = ", ".join(str(e["minuto"]) for e in evs[:5])
        sufixo = "..." if len(evs) > 5 else ""
        linhas.append(f"- {tipo} ({len(evs)}x, severidade {evs[0]['severidade']}): minutos {minutos}{sufixo}")
        linhas.append(f"  exemplo: {evs[0]['detalhe']}")
    return "\n".join(linhas)


def gerar_comentario(match_summary: dict, events: list) -> str:
    """
    match_summary: dict com pelo menos champion_name, win, game_duration (segundos).
    events: lista de eventos estruturados (heuristics.run_all_heuristics).
    """
    resumo_eventos = _summarize_events_for_prompt(events)
    resultado = "Vitória" if match_summary.get("win") else "Derrota"
    duracao_min = (match_summary.get("game_duration") or 0) // 60

    if not events:
        return "Nenhum evento de macro relevante foi detectado nesta partida pelas heurísticas atuais."

    user_prompt = f"""Partida: {match_summary.get('champion_name', '?')}, {resultado}, {duracao_min} minutos.

Eventos de macro detectados ({len(events)} no total):
{resumo_eventos}

Escreva o comentário de coach seguindo as regras do system prompt."""

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    return chat(messages)
