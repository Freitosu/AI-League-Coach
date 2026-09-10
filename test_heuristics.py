"""
Teste rápido das heurísticas com um timeline sintético minimalista,
sem depender da Riot API. Não é uma suíte de testes completa — serve
para validar que o parsing e as heurísticas não quebram e produzem
resultados plausíveis.
"""

from heuristics import run_all_heuristics, is_remake


def build_fake_match():
    participants = []
    for i in range(1, 11):
        team = 100 if i <= 5 else 200
        role = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"][(i - 1) % 5]
        participants.append({
            "participantId": i,
            "puuid": f"puuid-{i}",
            "teamId": team,
            "teamPosition": role,
            "championName": "TestChamp",
        })
    return {"info": {"participants": participants, "gameDuration": 1800, "gameCreation": 0}}


def build_fake_timeline():
    frames = []
    # Frame aos 5, 10, 15, 20 minutos com CS baixo propositalmente para o participantId=1
    for minute in [0, 5, 10, 15, 20]:
        pframes = {}
        for i in range(1, 11):
            cs = 2 * minute if i == 1 else int(7 * minute)  # participante 1 com CS ruim
            pframes[str(i)] = {
                "position": {"x": 1000 + i * 10, "y": 1000},
                "totalGold": 500 + cs * 20,
                "minionsKilled": cs,
                "jungleMinionsKilled": 0,
                "xp": cs * 50,
                "level": min(1 + minute // 2, 18),
            }
        events = []
        if minute == 10:
            events.append({
                "type": "CHAMPION_KILL", "timestamp": minute * 60000,
                "killerId": 6, "victimId": 1, "victimDamageReceived": [],
                "assistingParticipantIds": [7],
                "position": {"x": 5000, "y": 5000},  # longe dos aliados
            })
        if minute == 15:
            events.append({
                "type": "ELITE_MONSTER_KILL", "timestamp": minute * 60000,
                "killerId": 2, "killerTeamId": 100, "monsterType": "DRAGON",
                "position": {"x": 9000, "y": 4000},
            })
        frames.append({"timestamp": minute * 60000, "participantFrames": pframes, "events": events})
    return {"info": {"frames": frames}}


def base_participants(win_a=True, remake=False, surrender=False):
    return [
        {"puuid": "puuid-1", "championName": "Ahri", "win": win_a, "participantId": 1, "teamId": 100,
         "teamPosition": "MIDDLE", "gameEndedInEarlySurrender": remake, "gameEndedInSurrender": surrender},
        {"puuid": "puuid-x", "championName": "Zed", "win": not win_a, "participantId": 6, "teamId": 200,
         "teamPosition": "MIDDLE", "gameEndedInEarlySurrender": remake, "gameEndedInSurrender": surrender},
    ]


def make_frames(minutes, pid_gold, opp_gold, pid_cs, opp_cs, dmg_done=None, dmg_taken=None):
    frames = []
    for i, m in enumerate(minutes):
        p_stats = {"totalGold": pid_gold[i], "minionsKilled": pid_cs[i], "jungleMinionsKilled": 0,
                   "position": {"x": 100, "y": 100}, "xp": pid_gold[i], "currentGold": 200}
        if dmg_done:
            p_stats["damageStats"] = {"totalDamageDoneToChampions": dmg_done[i], "totalDamageTaken": dmg_taken[i]}
        o_stats = {"totalGold": opp_gold[i], "minionsKilled": opp_cs[i], "jungleMinionsKilled": 0,
                   "position": {"x": 200, "y": 200}, "xp": opp_gold[i], "currentGold": 200}
        frames.append({"timestamp": m * 60000, "participantFrames": {"1": p_stats, "6": o_stats}, "events": []})
    return frames


if __name__ == "__main__":
    match = build_fake_match()
    timeline = build_fake_timeline()
    events = run_all_heuristics(match, timeline, puuid="puuid-1")

    assert len(events) > 0, "Nenhum evento gerado — algo está errado."
    tipos = {e["tipo"] for e in events}
    assert "cs_abaixo_benchmark" in tipos, "Deveria ter detectado CS abaixo do benchmark para puuid-1."
    assert "morte_isolada" in tipos, "Deveria ter detectado a morte isolada em 10min."

    print(f"{len(events)} eventos gerados. Tipos encontrados: {sorted(tipos)}")
    for e in events:
        print(f"  [{e['minuto']:>5.1f}min] {e['tipo']:<28} {e['detalhe']}")
    print("\nOK: testes básicos passaram.")

    print("\n=== Teste 2: remake ===")
    match = {"info": {"gameDuration": 195, "participants": base_participants(remake=True)}}
    timeline = {"info": {"frames": make_frames([0, 1, 3], [500, 600, 900], [500, 600, 900], [0, 2, 4], [0, 2, 4])}}
    events = run_all_heuristics(match, timeline, "puuid-1")
    assert is_remake(match, "puuid-1") is True
    assert len(events) == 1 and events[0]["tipo"] == "partida_remake", events
    print("OK:", events[0]["detalhe"])

    print("\n=== Teste 3: partida curta (~3min, não remake) não deve gerar CS bugado de checkpoint 5/10/15/20 ===")
    match = {"info": {"gameDuration": 190, "participants": base_participants(win_a=False)}}
    timeline = {"info": {"frames": make_frames([0, 1, 2, 3], [500, 600, 700, 800], [500, 700, 900, 1100],
                                                [0, 1, 2, 3], [0, 3, 6, 9])}}
    events = run_all_heuristics(match, timeline, "puuid-1")
    cs_bench_events = [e for e in events if e["tipo"] == "cs_abaixo_benchmark"]
    assert len(cs_bench_events) == 0, f"Não deveria haver evento de CS benchmark numa partida de 3min: {cs_bench_events}"
    print(f"OK: nenhum evento de cs_abaixo_benchmark bugado ({len(events)} eventos no total, nenhum de CS/checkpoint)")

    print("\n=== Teste 4: rendição com derrota (desvantagem de gold) ===")
    minutes = list(range(0, 21))
    pid_gold = [500 + m * 200 for m in minutes]
    opp_gold = [500 + m * 500 for m in minutes]  # abre uma diferença grande
    pid_cs = [m * 7 for m in minutes]
    opp_cs = [m * 7 for m in minutes]
    match = {"info": {"gameDuration": 20 * 60, "participants": base_participants(win_a=False, surrender=True)}}
    timeline = {"info": {"frames": make_frames(minutes, pid_gold, opp_gold, pid_cs, opp_cs)}}
    events = run_all_heuristics(match, timeline, "puuid-1")
    rendicao_events = [e for e in events if e["tipo"] == "rendicao"]
    assert len(rendicao_events) == 1, rendicao_events
    assert rendicao_events[0]["severidade"] == "atencao"
    assert "gold" in rendicao_events[0]["detalhe"]
    print("OK:", rendicao_events[0]["detalhe"])

    print("\n=== Teste 5: rendição com vitória (inimigo desistiu) — deve ser evento positivo ===")
    match = {"info": {"gameDuration": 20 * 60, "participants": base_participants(win_a=True, surrender=True)}}
    events = run_all_heuristics(match, timeline, "puuid-1")
    rendicao_events = [e for e in events if e["tipo"] == "rendicao"]
    assert len(rendicao_events) == 1
    assert rendicao_events[0]["severidade"] == "positivo"
    print("OK:", rendicao_events[0]["detalhe"])

    print("\n=== Teste 6: boa troca de dano (evento positivo) ===")
    minutes = [0, 5, 10, 15]
    pid_gold = [500, 1500, 3000, 4500]
    opp_gold = [500, 1400, 2800, 4200]
    pid_cs = [0, 30, 65, 100]
    opp_cs = [0, 28, 60, 95]
    dmg_done = [0, 1500, 3500, 5500]   # +1500 no primeiro trecho, +2000, +2000
    dmg_taken = [0, 500, 1200, 1900]   # bem menor que o causado
    match = {"info": {"gameDuration": 15 * 60, "participants": base_participants(win_a=True)}}
    timeline = {"info": {"frames": make_frames(minutes, pid_gold, opp_gold, pid_cs, opp_cs, dmg_done, dmg_taken)}}
    events = run_all_heuristics(match, timeline, "puuid-1")
    trade_events = [e for e in events if e["tipo"] == "boa_troca_de_dano"]
    assert len(trade_events) >= 1, events
    assert all(e["severidade"] == "positivo" for e in trade_events)
    print(f"OK: {len(trade_events)} evento(s) de boa troca de dano —", trade_events[0]["detalhe"])

    print("\n=== Teste 7: presença positiva em objetivo ===")
    match = {"info": {"gameDuration": 15 * 60, "participants": base_participants(win_a=True)}}
    frames = make_frames([0, 5, 10], [500, 1500, 3000], [500, 1400, 2800], [0, 30, 65], [0, 28, 60])
    frames[1]["events"] = [{
        "type": "ELITE_MONSTER_KILL", "timestamp": 5 * 60000, "killerTeamId": 100,
        "monsterType": "DRAGON", "position": {"x": 100, "y": 100},
    }]
    timeline = {"info": {"frames": frames}}
    events = run_all_heuristics(match, timeline, "puuid-1")
    presence_events = [e for e in events if e["tipo"] == "presente_em_objetivo"]
    assert len(presence_events) == 1, events
    assert presence_events[0]["severidade"] == "positivo"
    print("OK:", presence_events[0]["detalhe"])

    print("\n✅ Todos os testes passaram.")
