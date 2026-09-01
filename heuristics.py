"""
Parte 2 — Heurísticas de macro.

Lê o (match, timeline) já salvos pela Parte 1 e produz uma lista de
"eventos de macro" estruturados, prontos para virar comentário de coach
na Parte 3 (LLM local). Cada heurística retorna uma lista de dicts no
formato:

    {"tipo": str, "minuto": float, "detalhe": str, "severidade": "info"|"atencao"|"critico"}

Notas de honestidade sobre os dados:
- A Riot Timeline API não expõe "wave state" nem "recall" como eventos
  diretos. Onde isso é necessário (heurísticas de freeze/push e de CS
  perdido em recall), o cálculo é uma APROXIMAÇÃO via posição e
  compras de item, e está marcado como tal no docstring da função.
- Os benchmarks de CS/min e de spawn de objetivo são valores
  aproximados e podem precisar de ajuste por patch/elo.
"""

from dataclasses import dataclass, field
from typing import Optional


# --- Constantes de referência (ajustáveis por patch/elo) ---

CS_PER_MIN_BENCHMARK = {5: 4.0, 10: 6.5, 15: 7.0, 20: 7.2}  # CS acumulado esperado / minuto

DRAGON_FIRST_SPAWN_S = 5 * 60
DRAGON_RESPAWN_S = 5 * 60
HERALD_SPAWN_S = 8 * 60
BARON_SPAWN_S = 20 * 60

ROAM_MIN_DISTANCE = 1800       # unidades de mapa; jump considerado "saiu da lane"
TEAMFIGHT_WINDOW_S = 12        # kills dentro dessa janela contam como o mesmo teamfight
ISOLATED_DEATH_MAX_ALLY_DIST = 3000  # distância do aliado mais próximo para considerar morte "isolada"

# Posição aproximada da fonte de cada time no Summoner's Rift (usada como proxy de "está na base").
# Coordenadas aproximadas — não há campo direto de "em base" na Timeline API.
BASE_COORDS = {100: {"x": 1500, "y": 1500}, 200: {"x": 13500, "y": 13500}}
NEAR_BASE_RADIUS = 2200
UNSPENT_GOLD_THRESHOLD = 1500   # gold parado considerado relevante


@dataclass
class MacroEvent:
    tipo: str
    minuto: float
    detalhe: str
    severidade: str = "info"

    def to_dict(self):
        return {"tipo": self.tipo, "minuto": round(self.minuto, 1), "detalhe": self.detalhe, "severidade": self.severidade}


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
    target_ms = minute * 60000
    return min(frames, key=lambda f: abs(f["timestamp"] - target_ms), default=None)


def team_participant_ids(match: dict, team_id: int) -> list:
    return [p["participantId"] for p in match["info"]["participants"] if p["teamId"] == team_id]


# --- Heurísticas ---

def h_cs_por_minuto(match, timeline, participant) -> list:
    """1. CS acumulado nos checkpoints (5/10/15/20min) vs benchmark."""
    out = []
    pid = participant["participantId"]
    frames = get_frames(timeline)
    for minute, expected in CS_PER_MIN_BENCHMARK.items():
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
            f"Vantagem de gold de {peak_gold_diff:.0f} sobre o oponente de lane no pico.", "info",
        ))
    elif peak_gold_diff <= -1000:
        out.append(MacroEvent(
            "desvantagem_gold_lane", peak_minute,
            f"Desvantagem de gold de {abs(peak_gold_diff):.0f} em relação ao oponente de lane no pico.", "atencao",
        ))
    return [e.to_dict() for e in out]


def h_presenca_em_objetivo(match, timeline, participant) -> list:
    """5. Presença do jogador perto de dragão/arauto/barão no momento em que foi abatido."""
    out = []
    pid = participant["participantId"]
    team_id = participant["teamId"]
    frames = get_frames(timeline)
    for event in all_events(timeline):
        if event.get("type") != "ELITE_MONSTER_KILL":
            continue
        minute = event["timestamp"] / 60000.0
        monster = event.get("monsterType", "OBJETIVO")
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
            ))
    return [e.to_dict() for e in out]


def h_torres_por_fase(match, timeline) -> list:
    """8. Torres tomadas/perdidas, agrupadas por fase do jogo."""
    out = []
    for event in all_events(timeline):
        if event.get("type") != "BUILDING_KILL":
            continue
        minute = event["timestamp"] / 60000.0
        fase = "early" if minute < 15 else "mid" if minute < 25 else "late"
        out.append(MacroEvent(
            "torre_destruida", minute,
            f"Torre ({event.get('laneType', '?')}, {event.get('towerType', '?')}) destruída na fase {fase}.",
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
            ))
        out.append(MacroEvent("resumo_visao", last_minute, f"Total: {placed} wards colocadas, {killed} destruídas.", "info"))
    return [e.to_dict() for e in out]


def h_mortes_isoladas(match, timeline, participant) -> list:
    """19. Mortes do jogador sem aliados próximos (fora de grupo)."""
    out = []
    pid = participant["participantId"]
    team_id = participant["teamId"]
    ally_ids = [p["participantId"] for p in match["info"]["participants"] if p["teamId"] == team_id and p["participantId"] != pid]
    frames = get_frames(timeline)
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
        if nearest_ally_dist is not None and nearest_ally_dist > ISOLATED_DEATH_MAX_ALLY_DIST:
            out.append(MacroEvent(
                "morte_isolada", minute,
                f"Morte sem aliados por perto (mais próximo a ~{nearest_ally_dist:.0f} unidades).",
                "atencao",
            ))
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
        severidade = "atencao" if pct < 40 else "info"
        out.append(MacroEvent(
            "kill_participation", 0,
            f"Participação em {player_participations}/{team_kills} kills do time ({pct:.0f}%).",
            severidade,
        ))
    return [e.to_dict() for e in out]


def h_roams(match, timeline, participant) -> list:
    """
    13. Roams: saltos de posição para longe da região de lane, avaliados
    pelo resultado (kill/assist do jogador em até 45s depois).
    Heurística por posição — aproximada, sem acesso a "wave state" real.
    """
    out = []
    pid = participant["participantId"]
    role = participant.get("teamPosition", "")
    if role in ("JUNGLE", ""):
        return out  # roaming é comportamento esperado do jungler; heurística não se aplica bem
    frames = get_frames(timeline)
    kill_events = [e for e in all_events(timeline) if e.get("type") == "CHAMPION_KILL"]

    prev_pos = None
    for frame in frames:
        pf = pframe(frame, pid)
        if pf is None or "position" not in pf:
            continue
        pos = pf["position"]
        minute = frame_minute(frame)
        if prev_pos is not None and distance(pos, prev_pos) > ROAM_MIN_DISTANCE and minute < 25:
            window_start = frame["timestamp"]
            window_end = window_start + 45000
            resultado = any(
                window_start <= e["timestamp"] <= window_end
                and (e.get("killerId") == pid or pid in e.get("assistingParticipantIds", []))
                for e in kill_events
            )
            out.append(MacroEvent(
                "roam" if resultado else "roam_sem_resultado", minute,
                "Saiu da lane e resultou em kill/assist." if resultado else "Saiu da lane sem kill/assist em seguida (possível tempo perdido).",
                "info" if resultado else "atencao",
            ))
        prev_pos = pos
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
        monster = event.get("monsterType")
        if monster not in ("BARON_NASHOR", "DRAGON") or event.get("monsterSubType") != "ELDER_DRAGON" and monster != "BARON_NASHOR":
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
                f"{monster} tomado com o time {abs(diff):.0f} de gold atrás do adversário — jogada de alto risco.",
                "atencao",
            ))
    return [e.to_dict() for e in out]


def h_freeze_push_wave_management(match, timeline, participant, opponent) -> list:
    """
    3. Freeze/push mal executado — APROXIMAÇÃO. A Timeline API não expõe o
    estado da wave (quantos minions, quem está empurrando), então isso é
    inferido comparando a taxa de CS do jogador vs a do oponente de lane
    entre checkpoints: se a taxa do jogador cai muito abaixo da do
    oponente por uma janela inteira, é um sinal (não uma certeza) de
    freeze mal jogado ou wave perdida.
    """
    out = []
    if opponent is None:
        return out
    pid, oid = participant["participantId"], opponent["participantId"]
    frames = get_frames(timeline)
    checkpoints = sorted(CS_PER_MIN_BENCHMARK.keys())
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
            ))
    return [e.to_dict() for e in out]


def h_cs_perdido_em_recall(match, timeline, participant) -> list:
    """
    4. CS perdido em recalls — APROXIMAÇÃO. Não existe evento de "recall"
    na Timeline API, então uma visita à base é inferida por proximidade
    da posição do jogador à fonte do próprio time. Se, no frame seguinte
    a uma visita detectada, o CS não avançou nada, é sinal de possível
    wave perdida por causa do recall (não conta lane empurrada pelo
    inimigo, nem se o back era necessário).
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
                    ))
        was_at_base = at_base_now
    return [e.to_dict() for e in out]


def h_resposta_a_gank(match, timeline, participant) -> list:
    """
    15. Resposta a gank do jungler inimigo — APROXIMAÇÃO. Detecta mortes
    do jogador causadas por um participante com papel JUNGLE do time
    adversário antes dos 20min, e verifica se havia ward do próprio
    jogador colocada nos ~2min anteriores perto do local da morte — se
    não havia, é sinal de visão insuficiente para reagir ao gank.
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
        ))
    return [e.to_dict() for e in out]


def h_gold_parado(match, timeline, participant) -> list:
    """18. Gold parado (não gasto) em checkpoints de tempo — usa currentGold direto do frame, sem aproximação de recall."""
    out = []
    pid = participant["participantId"]
    frames = get_frames(timeline)
    for minute in CS_PER_MIN_BENCHMARK.keys():
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


def run_all_heuristics(match: dict, timeline: dict, puuid: str) -> list:
    """Roda todas as heurísticas disponíveis e retorna uma lista única de eventos, ordenada por minuto."""
    participant = get_analyzed_participant(match, puuid)
    opponent = get_lane_opponent(match, participant)

    events = []
    events += h_cs_por_minuto(match, timeline, participant)
    events += h_gold_xp_diff_vs_oponente(match, timeline, participant, opponent)
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

    events.sort(key=lambda e: e["minuto"])
    return events
