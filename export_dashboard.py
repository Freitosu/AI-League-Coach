"""
Gera um dashboard HTML standalone (estilo BI) com todas as partidas
analisadas: ícone do campeão, resultado, timeline de eventos de macro
por severidade, e o detalhamento das heurísticas por partida.

O arquivo gerado é autocontido (dados embutidos) — basta abrir no
navegador, sem precisar de servidor. Só o ícone dos campeões e as
fontes usam internet ao abrir; se estiver offline, caem em um
fallback e o dashboard continua funcionando.

Uso:
    python export_dashboard.py                # usa o único jogador salvo
    python export_dashboard.py --puuid <puuid>
    python export_dashboard.py --output meu_dashboard.html
"""

import argparse
import json
import sys
from datetime import datetime

import requests

import storage
from heuristics import run_all_heuristics
from commentary import gerar_comentario
from ollama_client import OllamaError


DDRAGON_VERSIONS_URL = "https://ddragon.leagueoflegends.com/api/versions.json"
DDRAGON_ICON_TEMPLATE = "https://ddragon.leagueoflegends.com/cdn/{version}/img/champion/{champion}.png"
FALLBACK_DDRAGON_VERSION = "14.23.1"


def get_latest_ddragon_version() -> str:
    try:
        resp = requests.get(DDRAGON_VERSIONS_URL, timeout=10)
        resp.raise_for_status()
        versions = resp.json()
        return versions[0]
    except Exception:
        return FALLBACK_DDRAGON_VERSION


def escolher_jogador(puuid_arg: str = None) -> str:
    if puuid_arg:
        return puuid_arg
    players = storage.list_players()
    if not players:
        print("Nenhum jogador salvo. Rode main.py primeiro.", file=sys.stderr)
        sys.exit(1)
    if len(players) > 1:
        print("Vários jogadores encontrados, usando o primeiro. Use --puuid para escolher outro:")
        for p in players:
            print(f"  {p['game_name']}#{p['tag_line']} -> {p['puuid']}")
    return players[0]["puuid"]


def montar_dados(puuid: str, ddragon_version: str, gerar_comentarios: bool = False) -> dict:
    players = {p["puuid"]: p for p in storage.list_players()}
    player_info = players.get(puuid, {"game_name": "Jogador", "tag_line": ""})

    matches_summary = storage.list_stored_matches(puuid)
    matches_out = []
    for m in matches_summary:
        match_data, timeline_data = storage.load_match(m["match_id"])
        if match_data is None or timeline_data is None:
            continue
        try:
            events = run_all_heuristics(match_data, timeline_data, puuid)
        except Exception as e:
            print(f"[Aviso] Falha ao rodar heurísticas em {m['match_id']}: {e}", file=sys.stderr)
            events = []

        counts = {"critico": 0, "atencao": 0, "info": 0}
        for e in events:
            counts[e.get("severidade", "info")] = counts.get(e.get("severidade", "info"), 0) + 1

        champion = m["champion_name"] or "Desconhecido"

        coach_commentary = storage.get_commentary(m["match_id"])
        if coach_commentary is None and gerar_comentarios:
            print(f"  Gerando comentário do coach para {champion} ({m['match_id']})...")
            try:
                coach_commentary = gerar_comentario(
                    {"champion_name": champion, "win": m["win"], "game_duration": m["game_duration"]},
                    events,
                )
                storage.save_commentary(m["match_id"], coach_commentary)
            except OllamaError as e:
                print(f"  [Aviso] Não foi possível gerar comentário via Ollama: {e}", file=sys.stderr)
                coach_commentary = None

        matches_out.append({
            "match_id": m["match_id"],
            "champion_name": champion,
            "champion_icon_url": DDRAGON_ICON_TEMPLATE.format(version=ddragon_version, champion=champion),
            "win": m["win"],
            "game_creation_ms": m["game_creation"],
            "game_duration_s": m["game_duration"],
            "events": events,
            "counts": counts,
            "coach_commentary": coach_commentary,
        })

    return {
        "generated_at": datetime.now().isoformat(),
        "player": player_info,
        "ddragon_version": ddragon_version,
        "matches": matches_out,
    }


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>LoL Macro AI — Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Oswald:wght@500;600;700&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  :root{
    --bg:#0b1220; --panel:#121a2c; --panel-2:#0e1526; --border:#232c42;
    --text:#e9e6da; --text-dim:#8b93a8;
    --gold:#c8a24c; --teal:#18c3b2; --red:#e5525f;
    --win:#49bf8a; --loss:#e5525f;
  }
  *{box-sizing:border-box;}
  body{margin:0;background:var(--bg);color:var(--text);font-family:'Inter',system-ui,sans-serif;font-size:14px;}
  h1,h2,h3{margin:0;}
  .app{display:grid;grid-template-columns:320px 1fr;height:100vh;}

  .sidebar{background:var(--panel-2);border-right:1px solid var(--border);display:flex;flex-direction:column;overflow:hidden;}
  .sidebar-header{padding:22px 20px 14px;}
  .sidebar-header h1{font-family:'Oswald',sans-serif;font-weight:600;font-size:19px;letter-spacing:.01em;color:var(--gold);}
  .player-tag{font-size:12.5px;color:var(--text-dim);margin-top:3px;}
  .filter-input{margin:0 16px 12px;padding:8px 10px;width:calc(100% - 32px);background:var(--panel);border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:13px;font-family:inherit;}
  .filter-input::placeholder{color:var(--text-dim);}
  .match-list{overflow-y:auto;flex:1;padding:0 8px 16px;}
  .match-row{display:flex;align-items:center;gap:10px;padding:9px 10px;border-radius:6px;cursor:pointer;border:1px solid transparent;}
  .match-row:hover{background:var(--panel);}
  .match-row.active{background:var(--panel);border-color:var(--gold);}
  .match-row img{width:36px;height:36px;border-radius:6px;border:1px solid var(--border);object-fit:cover;background:var(--panel);flex-shrink:0;}
  .match-row .info{flex:1;min-width:0;}
  .match-row .champ-name{font-size:13.5px;font-weight:600;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
  .match-row .meta{font-size:11.5px;color:var(--text-dim);}
  .pill{font-size:11px;font-weight:600;padding:2px 7px;border-radius:4px;flex-shrink:0;}
  .pill.win{background:rgba(73,191,138,.15);color:var(--win);}
  .pill.loss{background:rgba(229,82,95,.15);color:var(--loss);}
  .empty-list{padding:20px;color:var(--text-dim);font-size:13px;}

  .main{overflow-y:auto;padding:26px 30px;}
  .kpi-row{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:22px;}
  .kpi-card{background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:16px 18px;}
  .kpi-card .value{font-family:'Oswald',sans-serif;font-size:27px;font-weight:600;color:var(--text);}
  .kpi-card .label{font-size:12.5px;color:var(--text-dim);margin-top:4px;}

  .match-detail{background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:28px;min-height:400px;}
  .empty-state{color:var(--text-dim);text-align:center;padding:90px 0;font-size:14px;}

  .detail-header{display:flex;align-items:center;gap:16px;margin-bottom:28px;}
  .detail-header img{width:64px;height:64px;border-radius:10px;border:1px solid var(--border);flex-shrink:0;}
  .detail-header h2{font-family:'Oswald',sans-serif;font-size:24px;font-weight:600;display:flex;align-items:center;gap:10px;}
  .detail-header .sub{color:var(--text-dim);font-size:13px;margin-top:4px;}
  .chip-row{margin-top:8px;}
  .chip{background:var(--panel-2);border:1px solid var(--border);border-radius:5px;padding:3px 9px;font-size:12px;color:var(--text-dim);margin-right:8px;display:inline-block;}

  .commentary-box{background:var(--panel-2);border:1px solid var(--border);border-left:3px solid var(--gold);border-radius:8px;padding:18px 20px;margin-bottom:28px;}
  .commentary-box h3{font-size:12.5px;color:var(--text-dim);margin-bottom:10px;font-weight:600;}
  .commentary-text{font-size:13.5px;line-height:1.65;color:var(--text);white-space:pre-wrap;}
  .commentary-text.muted{color:var(--text-dim);font-style:italic;}
  .commentary-text.muted code{background:var(--panel);padding:1px 5px;border-radius:3px;color:var(--teal);font-style:normal;}

  .timeline-wrap{margin-bottom:28px;}
  .timeline-label{font-size:12px;color:var(--text-dim);margin-bottom:8px;}
  .timeline{position:relative;height:56px;background:var(--panel-2);border-radius:6px;border:1px solid var(--border);}
  .timeline .dot{position:absolute;top:50%;width:11px;height:11px;border-radius:50%;transform:translate(-50%,-50%);border:2px solid var(--panel-2);cursor:pointer;transition:transform .15s ease;}
  .timeline .dot:hover{transform:translate(-50%,-50%) scale(1.5);}
  @media (prefers-reduced-motion: reduce){ .timeline .dot{transition:none;} }

  .panels-row{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:28px;}
  .panel-box{background:var(--panel-2);border:1px solid var(--border);border-radius:8px;padding:16px 18px;}
  .panel-box h3{font-size:12.5px;color:var(--text-dim);margin-bottom:12px;font-weight:600;}
  .stacked-bar{display:flex;height:14px;border-radius:4px;overflow:hidden;margin-bottom:10px;background:var(--panel);}
  .legend{display:flex;gap:14px;flex-wrap:wrap;font-size:12px;color:var(--text-dim);}
  .dot-sm{width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:5px;}

  .phase-bars{display:flex;flex-direction:column;gap:10px;}
  .phase-bar-row{display:flex;align-items:center;gap:10px;}
  .phase-bar-row .label{width:60px;font-size:12px;color:var(--text-dim);flex-shrink:0;}
  .phase-bar-row .bar-bg{flex:1;height:10px;background:var(--panel);border-radius:4px;overflow:hidden;}
  .phase-bar-row .bar-fill{height:100%;background:var(--gold);}
  .phase-bar-row .count{width:22px;text-align:right;font-size:12px;color:var(--text-dim);flex-shrink:0;}

  .event-groups h3{font-family:'Oswald',sans-serif;font-size:15px;font-weight:600;color:var(--text);margin:22px 0 10px;}
  .event-row{display:flex;gap:12px;padding:9px 0;border-bottom:1px solid var(--border);}
  .event-row .sev-bar{width:3px;border-radius:2px;align-self:stretch;flex-shrink:0;}
  .event-row .minute{width:50px;font-size:12px;color:var(--text-dim);flex-shrink:0;}
  .event-row .content .tipo{font-size:13px;font-weight:600;color:var(--text);text-transform:capitalize;}
  .event-row .content .detalhe{font-size:12.5px;color:var(--text-dim);margin-top:2px;line-height:1.45;}

  @media (max-width: 820px){
    .app{grid-template-columns:1fr;grid-template-rows:auto 1fr;}
    .sidebar{border-right:none;border-bottom:1px solid var(--border);max-height:40vh;}
    .kpi-row{grid-template-columns:repeat(2,1fr);}
    .panels-row{grid-template-columns:1fr;}
  }

  .sidebar-footer{padding:12px 16px;border-top:1px solid var(--border);font-size:11px;color:var(--text-dim);line-height:1.6;}
  .sidebar-footer code{background:var(--panel);padding:1px 5px;border-radius:3px;color:var(--teal);}
</style>
</head>
<body>
<div class="app">
  <aside class="sidebar">
    <div class="sidebar-header">
      <h1>LoL Macro AI</h1>
      <p class="player-tag" id="playerTag"></p>
    </div>
    <input type="text" id="filterInput" class="filter-input" placeholder="Filtrar por campeão">
    <div class="match-list" id="matchList"></div>
    <div class="sidebar-footer">
      Atualizado em <span id="generatedAt"></span><br>
      Partidas somem do cache após 2 dias.<br>
      Para ver partidas novas: <code>python refresh.py</code>
    </div>
  </aside>
  <main class="main">
    <section class="kpi-row" id="kpiRow"></section>
    <section class="match-detail" id="matchDetail">
      <div class="empty-state">Selecione uma partida na lista ao lado.</div>
    </section>
  </main>
</div>

<script>
const DATA = __DASHBOARD_DATA__;

const FALLBACK_ICON = 'data:image/svg+xml,' + encodeURIComponent(
  '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><rect width="64" height="64" rx="10" fill="#232c42"/><text x="32" y="40" font-size="26" text-anchor="middle" fill="#8b93a8" font-family="sans-serif">?</text></svg>'
);

const SEV_COLOR = { critico: '#e5525f', atencao: '#c8a24c', info: '#18c3b2' };
const SEV_LABEL = { critico: 'Crítico', atencao: 'Atenção', info: 'Info' };

let currentMatchId = null;

function formatDate(ms){
  if(!ms) return 'data desconhecida';
  const d = new Date(ms);
  return d.toLocaleDateString('pt-BR') + ' ' + d.toLocaleTimeString('pt-BR', {hour:'2-digit', minute:'2-digit'});
}

function formatDuration(s){
  if(!s) return '?';
  const m = Math.floor(s/60), sec = s % 60;
  return m + 'min' + String(sec).padStart(2,'0') + 's';
}

function phaseOf(minuto){
  if(minuto < 15) return 'early';
  if(minuto < 25) return 'mid';
  return 'late';
}

function renderSidebar(filterText){
  filterText = filterText || '';
  const list = document.getElementById('matchList');
  list.innerHTML = '';
  const filtered = DATA.matches.filter(function(m){
    return (m.champion_name || '').toLowerCase().indexOf(filterText.toLowerCase()) !== -1;
  });
  if(filtered.length === 0){
    list.innerHTML = '<div class="empty-list">Nenhuma partida encontrada.</div>';
    return;
  }
  filtered.forEach(function(m){
    const row = document.createElement('div');
    row.className = 'match-row' + (m.match_id === currentMatchId ? ' active' : '');
    row.onclick = function(){ selectMatch(m.match_id); };
    row.innerHTML =
      '<img src="' + m.champion_icon_url + '" onerror="this.onerror=null;this.src=FALLBACK_ICON;" alt="' + m.champion_name + '">' +
      '<div class="info">' +
        '<div class="champ-name">' + m.champion_name + '</div>' +
        '<div class="meta">' + formatDate(m.game_creation_ms) + '</div>' +
      '</div>' +
      '<span class="pill ' + (m.win ? 'win' : 'loss') + '">' + (m.win ? 'V' : 'D') + '</span>';
    list.appendChild(row);
  });
}

function renderKPIs(){
  const total = DATA.matches.length;
  const wins = DATA.matches.filter(function(m){ return m.win; }).length;
  const winRate = total ? Math.round((wins/total)*100) : 0;
  const totalCritical = DATA.matches.reduce(function(acc,m){ return acc + (m.counts.critico || 0); }, 0);
  const champCounts = {};
  DATA.matches.forEach(function(m){ champCounts[m.champion_name] = (champCounts[m.champion_name] || 0) + 1; });
  let topChamp = null;
  Object.keys(champCounts).forEach(function(c){
    if(!topChamp || champCounts[c] > champCounts[topChamp]) topChamp = c;
  });

  const kpis = [
    { value: total, label: 'Partidas analisadas' },
    { value: winRate + '%', label: 'Win rate' },
    { value: totalCritical, label: 'Alertas críticos (total)' },
    { value: topChamp || '—', label: 'Campeão mais jogado' },
  ];
  document.getElementById('kpiRow').innerHTML = kpis.map(function(k){
    return '<div class="kpi-card"><div class="value">' + k.value + '</div><div class="label">' + k.label + '</div></div>';
  }).join('');
}

function selectMatch(matchId){
  currentMatchId = matchId;
  renderSidebar(document.getElementById('filterInput').value);
  const m = DATA.matches.find(function(x){ return x.match_id === matchId; });
  if(!m) return;
  renderDetail(m);
}

function renderDetail(m){
  const el = document.getElementById('matchDetail');
  const durationMin = Math.round((m.game_duration_s || 0) / 60);
  const total = m.events.length;

  const dots = m.events.map(function(e){
    const pct = durationMin ? Math.min(100, (e.minuto / durationMin) * 100) : 0;
    const color = SEV_COLOR[e.severidade] || '#888';
    const title = '[' + e.minuto + 'min] ' + e.tipo + ': ' + e.detalhe;
    return '<div class="dot" style="left:' + pct + '%;background:' + color + ';" title="' + title.replace(/"/g,'&quot;') + '"></div>';
  }).join('');

  const sevOrder = ['critico','atencao','info'];
  const sevTotal = total || 1;
  const stackedBar = sevOrder.map(function(s){
    const count = m.counts[s] || 0;
    const pct = (count / sevTotal) * 100;
    return pct > 0 ? '<div style="width:' + pct + '%;background:' + SEV_COLOR[s] + ';"></div>' : '';
  }).join('');
  const legend = sevOrder.map(function(s){
    return '<span><span class="dot-sm" style="background:' + SEV_COLOR[s] + ';"></span>' + SEV_LABEL[s] + ': ' + (m.counts[s] || 0) + '</span>';
  }).join('');

  const phases = { early: 0, mid: 0, late: 0 };
  m.events.forEach(function(e){ phases[phaseOf(e.minuto)]++; });
  const maxPhase = Math.max(1, phases.early, phases.mid, phases.late);
  const phaseLabels = { early: '0-15min', mid: '15-25min', late: '25min+' };
  const phaseBars = ['early','mid','late'].map(function(k){
    const v = phases[k];
    return '<div class="phase-bar-row"><div class="label">' + phaseLabels[k] + '</div>' +
      '<div class="bar-bg"><div class="bar-fill" style="width:' + ((v/maxPhase)*100) + '%;"></div></div>' +
      '<div class="count">' + v + '</div></div>';
  }).join('');

  const grouped = { early: [], mid: [], late: [] };
  m.events.forEach(function(e){ grouped[phaseOf(e.minuto)].push(e); });
  const phaseTitles = { early: 'Early game (0-15min)', mid: 'Mid game (15-25min)', late: 'Late game (25min+)' };
  const eventGroupsHtml = ['early','mid','late'].map(function(k){
    const evs = grouped[k];
    if(evs.length === 0) return '';
    const rows = evs.map(function(e){
      return '<div class="event-row">' +
        '<div class="sev-bar" style="background:' + SEV_COLOR[e.severidade] + ';"></div>' +
        '<div class="minute">' + e.minuto + 'min</div>' +
        '<div class="content"><div class="tipo">' + e.tipo.split('_').join(' ') + '</div>' +
        '<div class="detalhe">' + e.detalhe + '</div></div></div>';
    }).join('');
    return '<div class="event-groups"><h3>' + phaseTitles[k] + '</h3>' + rows + '</div>';
  }).join('');

  el.innerHTML =
    '<div class="detail-header">' +
      '<img src="' + m.champion_icon_url + '" onerror="this.onerror=null;this.src=FALLBACK_ICON;" alt="' + m.champion_name + '">' +
      '<div>' +
        '<h2>' + m.champion_name + '<span class="pill ' + (m.win ? 'win' : 'loss') + '">' + (m.win ? 'Vitória' : 'Derrota') + '</span></h2>' +
        '<div class="sub">' + formatDate(m.game_creation_ms) + '</div>' +
        '<div class="chip-row">' +
          '<span class="chip">' + formatDuration(m.game_duration_s) + ' de partida</span>' +
          '<span class="chip">' + total + ' eventos detectados</span>' +
        '</div>' +
      '</div>' +
    '</div>' +
    '<div class="commentary-box">' +
      '<h3>Comentário do coach</h3>' +
      (m.coach_commentary
        ? '<div class="commentary-text">' + m.coach_commentary + '</div>'
        : '<div class="commentary-text muted">Ainda não gerado para esta partida. Rode <code>python export_dashboard.py --commentary</code> (usa o Ollama local).</div>') +
    '</div>' +
    '<div class="timeline-wrap">' +
      '<div class="timeline-label">Linha do tempo de macro (posição = minuto da partida)</div>' +
      '<div class="timeline">' + dots + '</div>' +
    '</div>' +
    '<div class="panels-row">' +
      '<div class="panel-box"><h3>Severidade dos eventos</h3>' +
        '<div class="stacked-bar">' + stackedBar + '</div>' +
        '<div class="legend">' + legend + '</div></div>' +
      '<div class="panel-box"><h3>Eventos por fase do jogo</h3>' +
        '<div class="phase-bars">' + phaseBars + '</div></div>' +
    '</div>' +
    (eventGroupsHtml || '<div class="empty-state">Nenhum evento de macro detectado nesta partida.</div>');
}

document.getElementById('playerTag').textContent = DATA.player.game_name + '#' + DATA.player.tag_line;
document.getElementById('generatedAt').textContent = new Date(DATA.generated_at).toLocaleString('pt-BR');
document.getElementById('filterInput').addEventListener('input', function(e){ renderSidebar(e.target.value); });

renderKPIs();
renderSidebar('');
if(DATA.matches.length > 0) selectMatch(DATA.matches[0].match_id);
</script>
</body>
</html>
"""


def gerar_html(dados: dict) -> str:
    data_json = json.dumps(dados, ensure_ascii=False)
    return HTML_TEMPLATE.replace("__DASHBOARD_DATA__", data_json)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gera um dashboard HTML das partidas analisadas")
    parser.add_argument("--puuid", help="PUUID do jogador (opcional se só houver um salvo)")
    parser.add_argument("--output", "-o", default="dashboard.html", help="Arquivo HTML de saída")
    parser.add_argument("--commentary", "-c", action="store_true", help="Gera (e cacheia) comentário de coach via Ollama para cada partida")
    args = parser.parse_args()

    storage.init_db()
    puuid = escolher_jogador(args.puuid)
    print("Buscando versão atual do Data Dragon (ícones dos campeões)...")
    version = get_latest_ddragon_version()
    print(f"Versão: {version}")

    print("Rodando heurísticas em todas as partidas do cache...")
    dados = montar_dados(puuid, version, gerar_comentarios=args.commentary)
    print(f"{len(dados['matches'])} partidas processadas.")

    html = gerar_html(dados)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\nDashboard gerado em: {args.output}\nAbra esse arquivo no navegador.")
