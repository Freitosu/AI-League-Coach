"""
Teste rápido das heurísticas com um timeline sintético minimalista,
sem depender da Riot API. Não é uma suíte de testes completa — serve
para validar que o parsing e as heurísticas não quebram e produzem
resultados plausíveis.
"""

from heuristics import run_all_heuristics


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
