from heuristics import run_all_heuristics, is_remake


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


print("=== Teste 1: remake ===")
match = {"info": {"gameDuration": 195, "participants": base_participants(remake=True)}}
timeline = {"info": {"frames": make_frames([0, 1, 3], [500, 600, 900], [500, 600, 900], [0, 2, 4], [0, 2, 4])}}
events = run_all_heuristics(match, timeline, "puuid-1")
assert is_remake(match, "puuid-1") is True
assert len(events) == 1 and events[0]["tipo"] == "partida_remake", events
print("OK:", events[0]["detalhe"])

print("\n=== Teste 2: partida curta (~3min, não remake) não deve gerar CS bugado de checkpoint 5/10/15/20 ===")
match = {"info": {"gameDuration": 190, "participants": base_participants(win_a=False)}}
timeline = {"info": {"frames": make_frames([0, 1, 2, 3], [500, 600, 700, 800], [500, 700, 900, 1100],
                                            [0, 1, 2, 3], [0, 3, 6, 9])}}
events = run_all_heuristics(match, timeline, "puuid-1")
cs_bench_events = [e for e in events if e["tipo"] == "cs_abaixo_benchmark"]
assert len(cs_bench_events) == 0, f"Não deveria haver evento de CS benchmark numa partida de 3min: {cs_bench_events}"
print(f"OK: nenhum evento de cs_abaixo_benchmark bugado ({len(events)} eventos no total, nenhum de CS/checkpoint)")

print("\n=== Teste 3: rendição com derrota (desvantagem de gold) ===")
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

print("\n=== Teste 4: rendição com vitória (inimigo desistiu) — deve ser evento positivo ===")
match = {"info": {"gameDuration": 20 * 60, "participants": base_participants(win_a=True, surrender=True)}}
events = run_all_heuristics(match, timeline, "puuid-1")
rendicao_events = [e for e in events if e["tipo"] == "rendicao"]
assert len(rendicao_events) == 1
assert rendicao_events[0]["severidade"] == "positivo"
print("OK:", rendicao_events[0]["detalhe"])

print("\n=== Teste 5: boa troca de dano (evento positivo) ===")
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

print("\n=== Teste 6: presença positiva em objetivo ===")
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

print("\n✅ Todos os testes de heurísticas novas passaram.")
