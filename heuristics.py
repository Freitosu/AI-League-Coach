"""
Parte 2 — Heurísticas de macro.

Lê o (match, timeline) já salvos pela Parte 1 e produz uma lista de
"eventos de macro" estruturados, prontos para virar comentário de coach
na Parte 3 (LLM local). Cada heurística retorna uma lista de dicts no
formato:

    {"tipo": str, "minuto": float, "detalhe": str, "severidade": "positivo"|"info"|"atencao"|"critico",
     "confianca": "alta"|"media"|"baixa"}

Notas de honestidade sobre os dados:
- A Riot Timeline API não expõe "wave state" nem "recall" como eventos
  diretos. Onde isso é necessário (heurísticas de freeze/push e de CS
  perdido em recall), o cálculo é uma APROXIMAÇÃO via posição e
  compras de item, e está marcado como tal no docstring da função.
- Os benchmarks de CS/min e de spawn de objetivo são valores
  aproximados e podem precisar de ajuste por patch/elo.
- Checkpoints de tempo (5/10/15/20min) só são avaliados se a partida
  durou o suficiente para chegar lá — evita comparar dado de partida
  curta (ou remake) com um benchmark de um minuto que nunca aconteceu.
- Partidas encerradas como "remake" (abandono/AFK nos primeiros
  minutos, campo gameEndedInEarlySurrender da Riot) não têm heurísticas
  de macro rodadas — não há dado relevante pra analisar.
- "Motivo provável de rendição" é uma inferência qualitativa a partir
  do estado do jogo pouco antes do fim (gold, torres), não uma causa
  confirmada — a Riot não expõe o motivo real da votação de FF.
"""

from dataclasses import dataclass
from typing import Optional


# --- Constantes de referência (ajustáveis por patch/elo) ---

CS_PER_MIN_BENCHMARK = {5: 4.0, 10: 6.5, 15: 7.0, 20: 7.2}  # CS acumulado esperado / minuto

DRAGON_FIRST_SPAWN_S = 5 * 60
DRAGON_RESPAWN_S = 5 * 60
HERALD_SPAWN_S = 8 * 60
BARON_SPAWN_S = 20 * 60

ROAM_MIN_DISTANCE = 1800       # unidades de mapa; distância da "home position" considerada "fora da lane"
ROAM_HOME_WINDOW = (2.0, 8.0)  # minutos usados para calcular a posição mediana de laning ("home")
ROAM_MIN_DURATION_S = 60       # janelas mais curtas que isso são ruído (ward run, reposicionamento), não roam
ROAM_EVIDENCE_BUFFER_S = 30    # margem após o fim da janela para procurar evidência de resultado
ROAM_OBJECTIVE_DIST = 4000     # distância máxima até um objetivo do próprio time para contar como evidência
TEAMFIGHT_WINDOW_S = 12        # kills dentro dessa janela contam como o mesmo teamfight
ISOLATED_DEATH_MAX_ALLY_DIST = 3000  # distância do aliado mais próximo para considerar morte "isolada"
ENEMY_NEARBY_RADIUS = 2000     # distância para contar um adversário como "próximo" no momento da morte
DEATH_VISION_WINDOW_S = 120    # janela antes da morte em que uma ward própria conta como "visão recente"
DEATH_VISION_RADIUS = 2500     # distância da ward até o local da morte para contar como visão do local

# Mapeia o papel do participante para o laneType usado nos eventos de torre/plate da Riot.
ROLE_TO_LANE = {"TOP": "TOP_LANE", "MIDDLE": "MID_LANE", "BOTTOM": "BOT_LANE", "UTILITY": "BOT_LANE"}

# Posição aproximada da fonte de cada time no Summoner's Rift (usada como proxy de "está na base").
BASE_COORDS = {100: {"x": 1500, "y": 1500}, 200: {"x": 13500, "y": 13500}}
NEAR_BASE_RADIUS = 2200
UNSPENT_GOLD_THRESHOLD = 1500   # gold parado considerado relevante

GOOD_TRADE_MIN_DAMAGE = 800        # dano mínimo pra considerar a janela relevante
GOOD_TRADE_RATIO = 1.5             # dano causado deve ser >= 1.5x o dano recebido
SURRENDER_GOLD_THRESHOLD = 3000    # desvantagem de gold considerada "motivo provável" de FF
SURRENDER_TOWER_DIFF = 3           # diferença de torres perdidas/tomadas considerada "motivo provável"

# Nomes de monstros em PT-BR — a Riot retorna o monsterType cru (ex: "HORDE", "RIFTHERALD"),
# que não deve vazar pro comentário do coach sem tradução.
MONSTER_NAME_PT = {
    "DRAGON": "Dragão",
    "RIFTHERALD": "Arauto do Rift",
    "BARON_NASHOR": "Barão Nashor",
    "HORDE": "Enxame de Void Grubs",
    "ATAKHAN": "Atakhan",
}


def monster_name_pt(monster_type: str) -> str:
    """Traduz o monsterType cru da Riot para um nome legível em PT-BR."""
    return MONSTER_NAME_PT.get(monster_type, (monster_type or "objetivo").replace("_", " ").title())


@dataclass
class MacroEvent:
    tipo: str
    minuto: float
    detalhe: str
    severidade: str = "info"
    # "alta" = fato observado direto na timeline (ex: torre destruída, gold real).
    # "media" = inferência razoável a partir de dados reais, mas não certeza (ex: posição, distância, janela de tempo).
    # "baixa" = heurística aproximada que o próprio sistema já marca como incerta (os "possivel_*").
    confianca: str = "alta"

    def to_dict(self):
        return {
            "tipo": self.tipo,
            "minuto": round(self.minuto, 1),
            "detalhe": self.detalhe,
            "severidade": self.severidade,
            "confianca": self.confianca,
        }


# --- Helpers de acesso aos dados ---

def get_analyzed_participant(match: dict, puuid: str) -> dict:
    """Retorna o dict do participante analisado dentro de match['info']['participants']."""
    for p in match["info"]["participants"]:
        if p.get("puuid") == puuid:
            return p
    raise ValueError("PUUID não encontrado entre os participantes desta partida.")


def get_lane_opponent(match: dict, participant: dict) -> Optional[dict]:
    """Participante do time adversário na mesma posição de lane, se identificável."""
    role = participant.get("teamPosition") or participant.get("individualPosition")
    if not role or role == "Invalid":
        return None
    for p in match["info"]["participants"]:
        if p["teamId"] != participant["teamId"] and (p.get("teamPosition") or p.get("individualPosition")) == role:
            return p
    return None


def get_frames(timeline: dict) -> list:
    return timeline["info"]["frames"]


def frame_minute(frame: dict) -> float:
    return frame["timestamp"] / 60000.0


def pframe(frame: dict, participant_id: int) -> Optional[dict]:
    return frame.get("participantFrames", {}).get(str(participant_id))


def all_events(timeline: dict) -> list:
    """Achata os eventos de todos os frames em uma única lista ordenada por timestamp."""
    events = []
    for frame in get_frames(timeline):
        events.extend(frame.get("events", []))
    events.sort(key=lambda e: e.get("timestamp", 0))
    return events


def distance(pos_a: dict, pos_b: dict) -> float:
    return ((pos_a["x"] - pos_b["x"]) ** 2 + (pos_a["y"] - pos_b["y"]) ** 2) ** 0.5


def frame_at_minute(frames: list, minute: float) -> Optional[dict]:
    """Frame mais próximo de um minuto de jogo (frames vêm a cada ~1min)."""
    if not frames:
        return None
    return min(frames, key=lambda f: abs(f["timestamp"] - minute * 60000))


def team_participant_ids(match: dict, team_id: int) -> list:
    return [p["participantId"] for p in match["info"]["participants"] if p["teamId"] == team_id]


def reachable_checkpoints(checkpoints, game_duration_s: int) -> list:
    """Filtra checkpoints de minuto (ex: 5/10/15/20) para os que a partida
    realmente alcançou — evita comparar CS de uma partida curta contra o
    benchmark de um minuto que nunca aconteceu (bug: 'CS aos 5min' usando
    o frame mais próximo disponível, que podia ser o de 1min numa partida curta)."""
    return [c for c in checkpoints if c * 60 <= (game_duration_s or 0)]


# --- Fim de jogo: remake e rendição ---

def is_remake(match: dict, puuid: str) -> bool:
    """True se a partida terminou como remake (abandono/AFK nos primeiros minutos)."""
    try:
        participant = get_analyzed_participant(match, puuid)
    except ValueError:
        return False
    return bool(participant.get("gameEndedInEarlySurrender"))


def h_rendicao(match: dict, timeline: dict, participant: dict, opponent) -> list:
    """
    Detecta se a partida terminou por rendição (surrender) e tenta indicar
    um motivo provável com base no estado do jogo pouco antes do fim —
    diferença de gold do time e saldo de torres. É uma inferência
    qualitativa, não uma causa confirmada (a Riot não expõe o motivo real
    da votação de FF).
    """
    out = []
    if not participant.get("gameEndedInSurrender"):
        return out

    team_id = participant["teamId"]
    team_ids = team_participant_ids(match, team_id)
    enemy_ids = [p["participantId"] for p in match["info"]["participants"] if p["teamId"] != team_id]
    frames = get_frames(timeline)
    if not frames:
        return out

    last_frame = frames[-1]
    minute = frame_minute(last_frame)
    team_gold = sum(pframe(last_frame, i).get("totalGold", 0) for i in team_ids if pframe(last_frame, i))
    enemy_gold = sum(pframe(last_frame, i).get("totalGold", 0) for i in enemy_ids if pframe(last_frame, i))
    gold_diff = team_gold - enemy_gold

    towers_lost = sum(1 for e in all_events(timeline) if e.get("type") == "BUILDING_KILL" and e.get("teamId") == team_id)
    towers_taken = sum(1 for e in all_events(timeline) if e.get("type") == "BUILDING_KILL" and e.get("teamId") != team_id)

    won = bool(participant.get("win"))

    if won:
        detalhe = f"Partida encerrada por rendição do time adversário, aos {minute:.0f}min — sua equipe estava à frente."
        out.append(MacroEvent("rendicao", minute, detalhe, "positivo", confianca="media"))
        return [e.to_dict() for e in out]

    if gold_diff <= -SURRENDER_GOLD_THRESHOLD:
        motivo = f"grande desvantagem de gold ({abs(gold_diff):.0f} atrás do time adversário) no momento da rendição"
    elif towers_lost - towers_taken >= SURRENDER_TOWER_DIFF:
        motivo = f"perda consistente de torres ({towers_lost} perdidas contra {towers_taken} tomadas)"
    else:
        motivo = "desvantagem acumulada ao longo da partida, sem um fator único dominante nos dados disponíveis"

    detalhe = f"Partida encerrada por rendição do seu time, aos {minute:.0f}min. Motivo provável: {motivo}."
    out.append(MacroEvent("rendicao", minute, detalhe, "atencao", confianca="media"))
    return [e.to_dict() for e in out]


# --- Heurísticas ---

def h_cs_por_minuto(match, timeline, participant) -> list:
    """1. CS acumulado nos checkpoints (5/10/15/20min) vs benchmark — só nos checkpoints que a partida alcançou.
    Não roda para JUNGLE: CS_PER_MIN_BENCHMARK é calibrado para farm de lane (creep score de laner) e não
    reflete a curva de clear de floresta — aplicar o mesmo valor a um jungler gerava falso positivo
    sistemático (jungler sempre aparecendo "abaixo do benchmark" de laner)."""
    out = []
    pid = participant["participantId"]
    role = participant.get("teamPosition", "")
    if role == "JUNGLE":
        return out
    duration_s = match["info"].get("gameDuration", 0)
    frames = get_frames(timeline)
    for minute in reachable_checkpoints(sorted(CS_PER_MIN_BENCHMARK.keys()), duration_s):
        expected = CS_PER_MIN_BENCHMARK[minute]
        frame = frame_at_minute(frames, minute)
        if frame is None:
            continue
        pf = pframe(frame, pid)
        if pf is None:
            continue
        cs = pf.get("minionsKilled", 0) + pf.get("jungleMinionsKilled", 0)
        expected_cs = expected * minute
        diff = cs - expected_cs
        if diff <= -expected_cs * 0.25:
            out.append(MacroEvent(
                "cs_abaixo_benchmark", minute,
                f"CS aos {minute}min: {cs} (esperado ~{expected_cs:.0f}). Farm significativamente abaixo do benchmark.",
                "atencao" if diff > -expected_cs * 0.4 else "critico",
                confianca="media",
            ))
    return [e.to_dict() for e in out]


def h_gold_xp_diff_vs_oponente(match, timeline, participant, opponent) -> list:
    """16/17. Curva de gold diff e xp diff vs oponente direto de lane."""
    out = []
    if opponent is None:
        return out
    pid, oid = participant["participantId"], opponent["participantId"]
    frames = get_frames(timeline)
    peak_gold_diff = 0
    peak_minute = 0
    for frame in frames:
        pf, of = pframe(frame, pid), pframe(frame, oid)
        if pf is None or of is None:
            continue
        gold_diff = pf.get("totalGold", 0) - of.get("totalGold", 0)
        if abs(gold_diff) > abs(peak_gold_diff):
            peak_gold_diff = gold_diff
            peak_minute = frame_minute(frame)
    if peak_gold_diff >= 1000:
        out.append(MacroEvent(
            "vantagem_gold_lane", peak_minute,
            f"Vantagem de gold de {peak_gold_diff:.0f} sobre o oponente de lane no pico.", "positivo",
        ))
    elif peak_gold_diff <= -1000:
        out.append(MacroEvent(
            "desvantagem_gold_lane", peak_minute,
            f"Desvantagem de gold de {abs(peak_gold_diff):.0f} em relação ao oponente de lane no pico.", "atencao",
        ))
    return [e.to_dict() for e in out]


def h_lane_snapshot(match, timeline, participant, opponent) -> list:
    """Curva de lane por checkpoint (5/10/15/20min, conforme alcançáveis pela duração real):
    diferença de gold, CS e XP vs o oponente direto, mais o saldo de turret plates na lane.
    Complementa h_gold_xp_diff_vs_oponente (que só guarda o PICO) com uma progressão completa —
    permite ao coach dizer 'estava ganhando a lane aos 10min, mas...' em vez de só o resultado
    final. Tudo aqui é dado direto da timeline (gold/CS/XP/plates), sem aproximação de posição."""
    out = []
    if opponent is None:
        return out
    role = participant.get("teamPosition", "")
    lane = ROLE_TO_LANE.get(role)
    pid, oid = participant["participantId"], opponent["participantId"]
    team_id = participant["teamId"]
    duration_s = match["info"].get("gameDuration", 0)
    frames = get_frames(timeline)
    plate_events = [e for e in all_events(timeline) if e.get("type") == "TURRET_PLATE_DESTROYED"]

    for minute in reachable_checkpoints(sorted(CS_PER_MIN_BENCHMARK.keys()), duration_s):
        frame = frame_at_minute(frames, minute)
        if frame is None:
            continue
        pf, of = pframe(frame, pid), pframe(frame, oid)
        if pf is None or of is None:
            continue

        gold_diff = pf.get("totalGold", 0) - of.get("totalGold", 0)
        cs_diff = (pf.get("minionsKilled", 0) + pf.get("jungleMinionsKilled", 0)) - \
                  (of.get("minionsKilled", 0) + of.get("jungleMinionsKilled", 0))
        xp_diff = pf.get("xp", 0) - of.get("xp", 0)

        plates_tomadas = plates_perdidas = 0
        if lane is not None:
            for e in plate_events:
                if e["timestamp"] > frame["timestamp"] or e.get("laneType") != lane:
                    continue
                if e.get("teamId") == team_id:
                    plates_perdidas += 1
                else:
                    plates_tomadas += 1

        if gold_diff >= 300:
            severidade = "positivo"
        elif gold_diff <= -300:
            severidade = "atencao"
        else:
            severidade = "info"

        plates_txt = f" Plates na lane: {plates_tomadas} tomada(s), {plates_perdidas} perdida(s)." if lane else ""
        detalhe = (
            f"Aos {minute}min vs oponente de lane: ouro {gold_diff:+.0f} "
            f"(você {pf.get('totalGold', 0):.0f} vs {of.get('totalGold', 0):.0f}), "
            f"CS {cs_diff:+d}, XP {xp_diff:+.0f}.{plates_txt}"
        )
        out.append(MacroEvent("lane_snapshot", minute, detalhe, severidade, confianca="alta"))
    return [e.to_dict() for e in out]


def h_presenca_em_objetivo(match, timeline, participant) -> list:
    """5. Presença do jogador perto de dragão/arauto/barão no momento em que foi abatido.
    Positivo quando presente e o próprio time tomou; atenção quando ausente."""
    out = []
    pid = participant["participantId"]
    team_id = participant["teamId"]
    frames = get_frames(timeline)
    for event in all_events(timeline):
        if event.get("type") != "ELITE_MONSTER_KILL":
            continue
        minute = event["timestamp"] / 60000.0
        monster = monster_name_pt(event.get("monsterType"))
        killer_team = event.get("killerTeamId")
        frame = frame_at_minute(frames, minute)
        pf = pframe(frame, pid) if frame else None
        if pf is None or "position" not in pf:
            continue
        dist = distance(pf["position"], event.get("position", pf["position"]))
        was_teammate_kill = killer_team == team_id
        if dist > 4000:
            out.append(MacroEvent(
                "ausente_em_objetivo", minute,
                f"{monster} abatido {'pelo seu time' if was_teammate_kill else 'pelo time adversário'} "
                f"enquanto você estava longe (~{dist:.0f} unidades) do local.",
                "info" if was_teammate_kill else "atencao",
                confianca="media",
            ))
        elif was_teammate_kill:
            out.append(MacroEvent(
                "presente_em_objetivo", minute,
                f"Presente na tomada de {monster} pelo seu time.",
                "positivo",
                confianca="media",
            ))
    return [e.to_dict() for e in out]


def h_torres_por_fase(match, timeline) -> list:
    """8. Torres e inibidores destruídos, agrupados por fase do jogo. Checa buildingType
    antes de towerType: inibidores não têm towerType, então sem essa checagem apareciam
    rotulados como 'Torre (LANE, ?)' em vez de Inibidor."""
    out = []
    for event in all_events(timeline):
        if event.get("type") != "BUILDING_KILL":
            continue
        minute = event["timestamp"] / 60000.0
        fase = "early" if minute < 15 else "mid" if minute < 25 else "late"
        lane = event.get("laneType", "?")
        if event.get("buildingType") == "INHIBITOR_BUILDING":
            out.append(MacroEvent(
                "inibidor_destruido", minute,
                f"Inibidor ({lane}) destruído na fase {fase}.",
                "info",
            ))
        else:
            out.append(MacroEvent(
                "torre_destruida", minute,
                f"Torre ({lane}, {event.get('towerType', '?')}) destruída na fase {fase}.",
                "info",
            ))
    return [e.to_dict() for e in out]


def h_wards(match, timeline, participant) -> list:
    """10/11. Wards colocadas e destruídas pelo jogador."""
    out = []
    pid = participant["participantId"]
    placed, killed = 0, 0
    last_minute = 0
    for event in all_events(timeline):
        minute = event["timestamp"] / 60000.0
        last_minute = max(last_minute, minute)
        if event.get("type") == "WARD_PLACED" and event.get("creatorId") == pid:
            placed += 1
        elif event.get("type") == "WARD_KILL" and event.get("killerId") == pid:
            killed += 1
    if last_minute > 0:
        rate = placed / last_minute
        role = participant.get("teamPosition", "")
        expected_rate = 1.0 if role == "UTILITY" else 0.5
        if rate < expected_rate * 0.6:
            out.append(MacroEvent(
                "visao_abaixo_esperado", last_minute,
                f"{placed} wards colocadas em {last_minute:.0f}min (~{rate:.2f}/min). Abaixo do esperado para {role or 'seu papel'}.",
                "atencao",
                confianca="media",
            ))
        out.append(MacroEvent("resumo_visao", last_minute, f"Total: {placed} wards colocadas, {killed} destruídas.", "info"))
    return [e.to_dict() for e in out]


def h_mortes_isoladas(match, timeline, participant) -> list:
    """19. Mortes do jogador sem aliados próximos (fora de grupo). Enriquecido com contexto
    de risco no momento da morte — quantos adversários estavam por perto, se havia visão
    própria recente do local, e se o jogador estava fora da posição habitual de lane — para
    o coach poder distinguir 'avançou sem informação' de outros padrões, em vez de só contar
    mortes."""
    out = []
    pid = participant["participantId"]
    team_id = participant["teamId"]
    ally_ids = [p["participantId"] for p in match["info"]["participants"] if p["teamId"] == team_id and p["participantId"] != pid]
    enemy_ids = [p["participantId"] for p in match["info"]["participants"] if p["teamId"] != team_id]
    frames = get_frames(timeline)
    home = _home_position(frames, pid)
    own_wards = [e for e in all_events(timeline) if e.get("type") == "WARD_PLACED" and e.get("creatorId") == pid]

    for event in all_events(timeline):
        if event.get("type") != "CHAMPION_KILL" or event.get("victimId") != pid:
            continue
        minute = event["timestamp"] / 60000.0
        frame = frame_at_minute(frames, minute)
        if frame is None:
            continue
        death_pos = event.get("position")
        if death_pos is None:
            continue
        nearest_ally_dist = min(
            (distance(death_pos, pframe(frame, aid)["position"])
             for aid in ally_ids if pframe(frame, aid) and "position" in pframe(frame, aid)),
            default=None,
        )
        if nearest_ally_dist is None or nearest_ally_dist <= ISOLATED_DEATH_MAX_ALLY_DIST:
            continue

        inimigos_proximos = sum(
            1 for eid in enemy_ids
            if pframe(frame, eid) and "position" in pframe(frame, eid)
            and distance(death_pos, pframe(frame, eid)["position"]) <= ENEMY_NEARBY_RADIUS
        )
        tinha_visao = any(
            (event["timestamp"] - DEATH_VISION_WINDOW_S * 1000) <= w["timestamp"] <= event["timestamp"]
            and "position" in w and distance(w["position"], death_pos) < DEATH_VISION_RADIUS
            for w in own_wards
        )
        fora_de_casa = home is not None and distance(death_pos, home) > ROAM_MIN_DISTANCE

        detalhe = (
            f"Morte isolada (aliado mais próximo a ~{nearest_ally_dist:.0f}u), "
            f"{inimigos_proximos} adversário(s) próximo(s) no momento (~{ENEMY_NEARBY_RADIUS}u), "
            f"{'com' if tinha_visao else 'sem'} visão própria recente no local"
            f"{', fora da posição habitual de lane' if fora_de_casa else ''}."
        )
        out.append(MacroEvent("morte_isolada", minute, detalhe, "atencao", confianca="media"))
    return [e.to_dict() for e in out]


def h_kill_participation(match, timeline, participant) -> list:
    """20. Participação em kills do time (%)."""
    out = []
    pid = participant["participantId"]
    team_id = participant["teamId"]
    team_kills = 0
    player_participations = 0
    for event in all_events(timeline):
        if event.get("type") != "CHAMPION_KILL":
            continue
        killer_team = event.get("killerTeamId")
        if killer_team != team_id:
            continue
        team_kills += 1
        involved = {event.get("killerId")} | set(event.get("assistingParticipantIds", []))
        if pid in involved:
            player_participations += 1
    if team_kills > 0:
        pct = 100 * player_participations / team_kills
        severidade = "atencao" if pct < 40 else ("positivo" if pct >= 65 else "info")
        out.append(MacroEvent(
            "kill_participation", 0,
            f"Participação em {player_participations}/{team_kills} kills do time ({pct:.0f}%).",
            severidade,
        ))
    return [e.to_dict() for e in out]


def _home_position(frames: list, pid: int) -> Optional[dict]:
    """Posição 'de casa' do jogador na fase de laning (mediana entre ROAM_HOME_WINDOW),
    usada como referência dinâmica em vez de coordenadas fixas de lane por patch/lado do mapa."""
    start, end = ROAM_HOME_WINDOW
    xs, ys = [], []
    for frame in frames:
        minute = frame_minute(frame)
        if minute < start or minute > end:
            continue
        pf = pframe(frame, pid)
        if pf is None or "position" not in pf:
            continue
        xs.append(pf["position"]["x"])
        ys.append(pf["position"]["y"])
    if not xs:
        return None
    xs.sort()
    ys.sort()
    mid = len(xs) // 2
    return {"x": xs[mid], "y": ys[mid]}


def h_roams(match, timeline, participant) -> list:
    """
    13. Roams: candidatos identificados por permanência contínua fora da
    'home position' de laning (mediana de posição entre 2-8min), agrupados
    em uma única janela por saída (em vez de um evento por frame que apenas
    saltou de posição).

    Isso é uma APROXIMAÇÃO por posição — não captura intenção diretamente
    (ver distinção entre roam de verdade e falso positivo por recall,
    perseguição, fuga ou reposicionamento). Para reduzir falsos positivos,
    a janela:
      - exclui trechos que tocam a própria base (recall, não roam);
      - descarta janelas curtas (< ROAM_MIN_DURATION_S), tratadas como ruído;
      - busca evidência de intenção/resultado no período (kill/assist do
        jogador, ou presença perto de objetivo abatido pelo próprio time
        logo em seguida) para atribuir confiança alta/media/baixa, em vez
        de tratar 'saiu da lane' como fato consumado.
    """
    out = []
    pid = participant["participantId"]
    team_id = participant["teamId"]
    role = participant.get("teamPosition", "")
    if role in ("JUNGLE", ""):
        return out  # roaming é comportamento esperado do jungler; heurística não se aplica bem

    frames = get_frames(timeline)
    home = _home_position(frames, pid)
    if home is None:
        return out
    base = BASE_COORDS.get(team_id)

    kill_events = [e for e in all_events(timeline) if e.get("type") == "CHAMPION_KILL"]
    objective_events = [e for e in all_events(timeline) if e.get("type") in ("ELITE_MONSTER_KILL", "BUILDING_KILL")]

    # 1. Marca frames "fora de casa" e agrupa em janelas contíguas.
    janelas = []
    janela_atual = None
    for frame in frames:
        pf = pframe(frame, pid)
        if pf is None or "position" not in pf:
            continue
        pos = pf["position"]
        minute = frame_minute(frame)
        if minute >= 25:
            continue
        fora_de_casa = distance(pos, home) > ROAM_MIN_DISTANCE
        tocando_base = base is not None and distance(pos, base) < NEAR_BASE_RADIUS
        if fora_de_casa and not tocando_base:
            if janela_atual is None:
                janela_atual = {"inicio_ts": frame["timestamp"], "fim_ts": frame["timestamp"]}
            else:
                janela_atual["fim_ts"] = frame["timestamp"]
        else:
            if janela_atual is not None:
                janelas.append(janela_atual)
                janela_atual = None
    if janela_atual is not None:
        janelas.append(janela_atual)

    # 2. Filtra por duração mínima e busca evidência dentro de cada janela (+ buffer).
    for j in janelas:
        duracao_s = (j["fim_ts"] - j["inicio_ts"]) / 1000.0
        if duracao_s < ROAM_MIN_DURATION_S:
            continue
        minuto_inicio = j["inicio_ts"] / 60000.0
        minuto_fim = j["fim_ts"] / 60000.0
        busca_fim = j["fim_ts"] + ROAM_EVIDENCE_BUFFER_S * 1000

        teve_kill_assist = any(
            j["inicio_ts"] <= e["timestamp"] <= busca_fim
            and (e.get("killerId") == pid or pid in e.get("assistingParticipantIds", []))
            for e in kill_events
        )
        perto_de_objetivo_proprio = False
        if not teve_kill_assist:
            frame_fim = frame_at_minute(frames, minuto_fim)
            pf_fim = pframe(frame_fim, pid) if frame_fim else None
            if pf_fim and "position" in pf_fim:
                perto_de_objetivo_proprio = any(
                    j["inicio_ts"] <= e["timestamp"] <= busca_fim
                    and e.get("killerTeamId") == team_id
                    and distance(pf_fim["position"], e.get("position", pf_fim["position"])) < ROAM_OBJECTIVE_DIST
                    for e in objective_events
                )

        if teve_kill_assist:
            tipo, severidade, confianca = "roam", "positivo", "alta"
            detalhe = f"Saiu da lane ({minuto_inicio:.1f}-{minuto_fim:.1f}min, ~{duracao_s:.0f}s) e resultou em kill/assist."
        elif perto_de_objetivo_proprio:
            tipo, severidade, confianca = "roam", "positivo", "media"
            detalhe = (f"Saiu da lane ({minuto_inicio:.1f}-{minuto_fim:.1f}min, ~{duracao_s:.0f}s) "
                       "e esteve perto de um objetivo abatido pelo time logo em seguida — possível suporte a jogada.")
        else:
            tipo, severidade, confianca = "roam_sem_resultado", "atencao", "baixa"
            detalhe = (f"Saiu da lane ({minuto_inicio:.1f}-{minuto_fim:.1f}min, ~{duracao_s:.0f}s) sem evidência "
                       "de kill/assist ou objetivo em seguida — candidato a roam sem resultado (aproximado, vale conferir o replay).")

        out.append(MacroEvent(tipo, minuto_inicio, detalhe, severidade, confianca=confianca))
    return [e.to_dict() for e in out]


def h_objetivo_em_desvantagem(match, timeline, participant) -> list:
    """22. Tentativas de Baron/Elder Dragon enquanto o time está em desvantagem de gold."""
    out = []
    team_id = participant["teamId"]
    team_ids = team_participant_ids(match, team_id)
    enemy_ids = [p["participantId"] for p in match["info"]["participants"] if p["teamId"] != team_id]
    frames = get_frames(timeline)
    for event in all_events(timeline):
        if event.get("type") != "ELITE_MONSTER_KILL":
            continue
        monster_raw = event.get("monsterType")
        if monster_raw not in ("BARON_NASHOR", "DRAGON") or event.get("monsterSubType") != "ELDER_DRAGON" and monster_raw != "BARON_NASHOR":
            continue
        if event.get("killerTeamId") != team_id:
            continue
        minute = event["timestamp"] / 60000.0
        frame = frame_at_minute(frames, minute)
        if frame is None:
            continue
        team_gold = sum(pframe(frame, i).get("totalGold", 0) for i in team_ids if pframe(frame, i))
        enemy_gold = sum(pframe(frame, i).get("totalGold", 0) for i in enemy_ids if pframe(frame, i))
        diff = team_gold - enemy_gold
        if diff < -2000:
            out.append(MacroEvent(
                "objetivo_alto_risco", minute,
                f"{monster_name_pt(monster_raw)} tomado com o time {abs(diff):.0f} de gold atrás do adversário — jogada de alto risco.",
                "atencao",
                confianca="media",
            ))
    return [e.to_dict() for e in out]


def h_freeze_push_wave_management(match, timeline, participant, opponent) -> list:
    """
    3. Freeze/push mal executado — APROXIMAÇÃO. Compara a taxa de CS do
    jogador vs a do oponente de lane entre checkpoints alcançáveis pela
    duração real da partida: se a taxa do jogador cai muito abaixo da do
    oponente por uma janela inteira, é um sinal (não uma certeza) de
    freeze mal jogado ou wave perdida.
    """
    out = []
    if opponent is None:
        return out
    pid, oid = participant["participantId"], opponent["participantId"]
    duration_s = match["info"].get("gameDuration", 0)
    frames = get_frames(timeline)
    checkpoints = reachable_checkpoints(sorted(CS_PER_MIN_BENCHMARK.keys()), duration_s)
    for a, b in zip(checkpoints, checkpoints[1:]):
        fa, fb = frame_at_minute(frames, a), frame_at_minute(frames, b)
        if fa is None or fb is None:
            continue
        pa, pb = pframe(fa, pid), pframe(fb, pid)
        oa, ob = pframe(fa, oid), pframe(fb, oid)
        if None in (pa, pb, oa, ob):
            continue
        player_rate = (pb.get("minionsKilled", 0) + pb.get("jungleMinionsKilled", 0)) - \
                      (pa.get("minionsKilled", 0) + pa.get("jungleMinionsKilled", 0))
        opp_rate = (ob.get("minionsKilled", 0) + ob.get("jungleMinionsKilled", 0)) - \
                   (oa.get("minionsKilled", 0) + oa.get("jungleMinionsKilled", 0))
        if opp_rate > 0 and player_rate <= opp_rate * 0.5 and (opp_rate - player_rate) >= 8:
            out.append(MacroEvent(
                "possivel_wave_mal_gerida", b,
                f"Entre {a}-{b}min, CS ganho foi de {player_rate} contra {opp_rate} do oponente de lane "
                f"(diferença grande). Pode indicar freeze mal jogado ou wave perdida — sinal aproximado, vale conferir o replay.",
                "atencao",
                confianca="baixa",
            ))
    return [e.to_dict() for e in out]


def h_cs_perdido_em_recall(match, timeline, participant) -> list:
    """
    4. CS perdido em recalls — APROXIMAÇÃO. Não existe evento de "recall"
    na Timeline API, então uma visita à base é inferida por proximidade
    da posição do jogador à fonte do próprio time. Se, no frame seguinte
    a uma visita detectada, o CS não avançou nada, é sinal de possível
    wave perdida por causa do recall.
    """
    out = []
    pid = participant["participantId"]
    team_id = participant["teamId"]
    base = BASE_COORDS.get(team_id)
    if base is None:
        return out
    frames = get_frames(timeline)
    was_at_base = False
    for i, frame in enumerate(frames):
        pf = pframe(frame, pid)
        if pf is None or "position" not in pf:
            continue
        minute = frame_minute(frame)
        at_base_now = distance(pf["position"], base) < NEAR_BASE_RADIUS
        if at_base_now and not was_at_base and minute > 3 and i + 1 < len(frames):
            next_pf = pframe(frames[i + 1], pid)
            if next_pf is not None:
                cs_now = pf.get("minionsKilled", 0) + pf.get("jungleMinionsKilled", 0)
                cs_next = next_pf.get("minionsKilled", 0) + next_pf.get("jungleMinionsKilled", 0)
                if cs_next <= cs_now:
                    out.append(MacroEvent(
                        "possivel_cs_perdido_recall", minute,
                        "Visita à base detectada sem ganho de CS no minuto seguinte — possível wave perdida no recall (aproximado).",
                        "info",
                        confianca="baixa",
                    ))
        was_at_base = at_base_now
    return [e.to_dict() for e in out]


def h_resposta_a_gank(match, timeline, participant) -> list:
    """
    15. Resposta a gank do jungler inimigo — APROXIMAÇÃO. Detecta mortes
    do jogador causadas por um participante com papel JUNGLE do time
    adversário antes dos 20min, e verifica se havia ward do próprio
    jogador colocada nos ~2min anteriores perto do local da morte.
    """
    out = []
    pid = participant["participantId"]
    enemy_jungler = next(
        (p for p in match["info"]["participants"]
         if p["teamId"] != participant["teamId"] and p.get("teamPosition") == "JUNGLE"),
        None,
    )
    if enemy_jungler is None:
        return out
    enemy_jungler_id = enemy_jungler["participantId"]
    events = all_events(timeline)
    own_wards = [e for e in events if e.get("type") == "WARD_PLACED" and e.get("creatorId") == pid]

    for event in events:
        if event.get("type") != "CHAMPION_KILL" or event.get("victimId") != pid:
            continue
        if event.get("killerId") != enemy_jungler_id:
            continue
        minute = event["timestamp"] / 60000.0
        if minute > 20:
            continue
        death_pos = event.get("position")
        had_recent_vision = False
        if death_pos is not None:
            window_start = event["timestamp"] - 120000
            for w in own_wards:
                if window_start <= w["timestamp"] <= event["timestamp"] and "position" in w:
                    if distance(w["position"], death_pos) < 2500:
                        had_recent_vision = True
                        break
        out.append(MacroEvent(
            "morte_por_gank" if had_recent_vision else "gank_sem_visao_previa", minute,
            ("Morto pelo jungler inimigo mesmo com visão próxima recente — avaliar reposicionamento."
             if had_recent_vision else
             "Morto pelo jungler inimigo sem ward própria recente perto do local — visão insuficiente para reagir."),
            "info" if had_recent_vision else "atencao",
            confianca="media",
        ))
    return [e.to_dict() for e in out]


def h_gold_parado(match, timeline, participant) -> list:
    """18. Gold parado (não gasto) nos checkpoints alcançáveis pela duração real da partida."""
    out = []
    pid = participant["participantId"]
    duration_s = match["info"].get("gameDuration", 0)
    frames = get_frames(timeline)
    for minute in reachable_checkpoints(sorted(CS_PER_MIN_BENCHMARK.keys()), duration_s):
        frame = frame_at_minute(frames, minute)
        if frame is None:
            continue
        pf = pframe(frame, pid)
        if pf is None:
            continue
        unspent = pf.get("currentGold", 0)
        if unspent >= UNSPENT_GOLD_THRESHOLD:
            out.append(MacroEvent(
                "gold_parado", minute,
                f"{unspent:.0f} de gold não gasto aos {minute}min — considerar voltar à base para comprar antes.",
                "atencao",
            ))
    return [e.to_dict() for e in out]


def h_boas_trocas_de_dano(match, timeline, participant, opponent) -> list:
    """
    Ponto positivo: janelas da fase de laning em que o jogador causou bem
    mais dano a campeões do que recebeu, sinal de troca de dano favorável.
    Usa damageStats.totalDamageDoneToChampions / totalDamageTaken, que já
    vêm nos participantFrames da Timeline API.
    """
    out = []
    if opponent is None:
        return out
    pid = participant["participantId"]
    duration_s = match["info"].get("gameDuration", 0)
    frames = get_frames(timeline)
    checkpoints = reachable_checkpoints([5, 10, 15], duration_s)
    for a, b in zip(checkpoints, checkpoints[1:]):
        fa, fb = frame_at_minute(frames, a), frame_at_minute(frames, b)
        if fa is None or fb is None:
            continue
        pa, pb = pframe(fa, pid), pframe(fb, pid)
        if pa is None or pb is None:
            continue
        dmg_done = pb.get("damageStats", {}).get("totalDamageDoneToChampions", 0) - \
                   pa.get("damageStats", {}).get("totalDamageDoneToChampions", 0)
        dmg_taken = pb.get("damageStats", {}).get("totalDamageTaken", 0) - \
                    pa.get("damageStats", {}).get("totalDamageTaken", 0)
        if dmg_done >= GOOD_TRADE_MIN_DAMAGE and dmg_done >= dmg_taken * GOOD_TRADE_RATIO:
            out.append(MacroEvent(
                "boa_troca_de_dano", b,
                f"Entre {a}-{b}min, causou {dmg_done:.0f} de dano a campeões contra {dmg_taken:.0f} recebido — troca de dano favorável.",
                "positivo",
            ))
    return [e.to_dict() for e in out]


def run_all_heuristics(match: dict, timeline: dict, puuid: str) -> list:
    """Roda todas as heurísticas disponíveis e retorna uma lista única de eventos, ordenada por minuto.
    Partidas com remake retornam só o evento de remake — sem dado relevante pra analisar."""
    participant = get_analyzed_participant(match, puuid)

    if bool(participant.get("gameEndedInEarlySurrender")):
        return [MacroEvent(
            "partida_remake", 0,
            "Partida encerrada como remake (abandono/AFK nos primeiros minutos) — sem dados de macro relevantes para analisar.",
            "info",
        ).to_dict()]

    opponent = get_lane_opponent(match, participant)

    events = []
    events += h_rendicao(match, timeline, participant, opponent)
    events += h_cs_por_minuto(match, timeline, participant)
    events += h_gold_xp_diff_vs_oponente(match, timeline, participant, opponent)
    events += h_lane_snapshot(match, timeline, participant, opponent)
    events += h_presenca_em_objetivo(match, timeline, participant)
    events += h_torres_por_fase(match, timeline)
    events += h_wards(match, timeline, participant)
    events += h_mortes_isoladas(match, timeline, participant)
    events += h_kill_participation(match, timeline, participant)
    events += h_roams(match, timeline, participant)
    events += h_objetivo_em_desvantagem(match, timeline, participant)
    events += h_freeze_push_wave_management(match, timeline, participant, opponent)
    events += h_cs_perdido_em_recall(match, timeline, participant)
    events += h_resposta_a_gank(match, timeline, participant)
    events += h_gold_parado(match, timeline, participant)
    events += h_boas_trocas_de_dano(match, timeline, participant, opponent)

    events.sort(key=lambda e: e["minuto"])
    return events
