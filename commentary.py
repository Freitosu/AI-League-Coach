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
- A duração real da partida vem informada no início do prompt do usuário. Organize por fase do jogo \
(early: 0-15min, mid: 15-25min, late: 25min+), mas escreva sobre uma fase SOMENTE se a partida realmente \
alcançou aquele tempo de jogo. Nunca escreva sobre uma fase que a partida não chegou a ter — isso é um erro grave.
- Cada evento vem com um nível de confiança entre parênteses. Trate cada nível de forma diferente:
  - confiança ALTA = fato observado diretamente na timeline (ex: torre destruída, gold real). Apresente como fato.
  - confiança MEDIA = interpretação razoável a partir de dados reais, mas não é certeza (ex: posição, distância, \
janela de tempo). Apresente como "provável", "sinal de", "parece indicar" — nunca como certeza absoluta.
  - confiança BAIXA = heurística aproximada que o próprio sistema já marca como incerta. Apresente como hipótese \
a conferir no replay, nunca como fato ("possivelmente", "vale checar se").
- O texto de cada evento (depois de "confiança: ...") já é a frase pronta em português — baseie-se SOMENTE nele. \
Não existe mais nenhum identificador técnico para você repetir; se não houver frase pronta, não invente uma.
- Para cada fase existente, aponte 1-3 pontos principais (erros e acertos), citando o minuto quando relevante.
- Termine com 2-3 recomendações concretas e acionáveis para a próxima partida.
- Tom direto e construtivo, como um coach de verdade — não genérico, não robótico.
- Não invente informação que não esteja nos eventos fornecidos.
- Máximo de ~400 palavras.
"""

SEVERIDADE_LABEL = {
    "critico": "crítico",
    "atencao": "atenção",
    "positivo": "positivo",
    "info": "informativo",
}

CONFIANCA_LABEL = {
    "alta": "alta",
    "media": "média",
    "baixa": "baixa",
}


def _rotulo_severidade(e: dict) -> str:
    return SEVERIDADE_LABEL.get(e.get("severidade"), e.get("severidade", "informativo"))


def _rotulo_confianca(e: dict) -> str:
    return CONFIANCA_LABEL.get(e.get("confianca", "alta"), "alta")


def _formatar_linha_evento(e: dict) -> str:
    """Uma linha por evento. Propositalmente NÃO inclui o campo 'tipo' cru (ex:
    'vantagem_gold_lane') — só o 'detalhe' já escrito em português, para o LLM não
    misturar o identificador técnico com a frase legível (isso já causou saídas do
    tipo 'gold lane' aparecendo cru no texto final)."""
    return f"- [{e['minuto']}min] (severidade: {_rotulo_severidade(e)}, confiança: {_rotulo_confianca(e)}) {e['detalhe']}"


def _summarize_events_for_prompt(events: list, max_raw: int = 40) -> str:
    """Passa os eventos crus se forem poucos; agrupa por tipo se forem muitos,
    para não estourar o contexto de um modelo local menor."""
    if len(events) <= max_raw:
        return "\n".join(_formatar_linha_evento(e) for e in events)

    grupos = defaultdict(list)
    for e in events:
        grupos[e["tipo"]].append(e)

    linhas = []
    for tipo, evs in grupos.items():
        rotulo = tipo.replace("_", " ")
        minutos = ", ".join(str(e["minuto"]) for e in evs[:5])
        sufixo = "..." if len(evs) > 5 else ""
        linhas.append(
            f"- {rotulo} ({len(evs)}x, severidade {_rotulo_severidade(evs[0])}, "
            f"confiança {_rotulo_confianca(evs[0])}): minutos {minutos}{sufixo}"
        )
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

    user_prompt = f"""Partida: {match_summary.get('champion_name', '?')}, {resultado}, duração real de {duracao_min} minutos.

IMPORTANTE: esta partida durou {duracao_min} minutos no total. Não escreva sobre nenhuma fase do jogo \
(early/mid/late) que a partida não tenha alcançado — por exemplo, se a partida durou menos de 25 minutos, \
não existe "late game" para comentar.

Eventos de macro detectados ({len(events)} no total):
{resumo_eventos}

Escreva o comentário de coach seguindo as regras do system prompt."""

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    return chat(messages)
