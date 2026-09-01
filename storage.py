"""
Armazenamento local (SQLite) para partidas e timelines já baixadas da Riot API.

Guardamos o JSON bruto de match e timeline (mais simples e robusto a mudanças
de schema da Riot) junto com algumas colunas indexáveis para consulta rápida.
As heurísticas leem os JSONs daqui em vez de bater na API de novo a cada análise.
"""

import json
import os
import sqlite3

import config


SCHEMA = """
CREATE TABLE IF NOT EXISTS matches (
    match_id TEXT PRIMARY KEY,
    puuid_analisado TEXT NOT NULL,
    game_creation INTEGER,
    game_duration INTEGER,
    queue_id INTEGER,
    champion_name TEXT,
    win INTEGER,
    raw_match_json TEXT NOT NULL,
    raw_timeline_json TEXT,
    fetched_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_matches_puuid ON matches(puuid_analisado);

CREATE TABLE IF NOT EXISTS players (
    puuid TEXT PRIMARY KEY,
    game_name TEXT NOT NULL,
    tag_line TEXT NOT NULL
);
"""


def get_connection() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _migrate(conn: sqlite3.Connection):
    """Adiciona colunas novas a bancos criados por versões anteriores do schema."""
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(matches)").fetchall()}
    if "champion_name" not in existing_cols:
        conn.execute("ALTER TABLE matches ADD COLUMN champion_name TEXT")
    if "win" not in existing_cols:
        conn.execute("ALTER TABLE matches ADD COLUMN win INTEGER")
    conn.commit()


def _backfill_summary_columns(conn: sqlite3.Connection):
    """Preenche champion_name/win para partidas baixadas antes dessas colunas existirem."""
    rows = conn.execute(
        "SELECT match_id, puuid_analisado, raw_match_json FROM matches WHERE champion_name IS NULL"
    ).fetchall()
    for match_id, puuid, raw_json in rows:
        try:
            match_data = json.loads(raw_json)
            champion_name, win = _extract_summary(match_data, puuid)
        except Exception:
            continue
        conn.execute(
            "UPDATE matches SET champion_name = ?, win = ? WHERE match_id = ?",
            (champion_name, int(win) if win is not None else None, match_id),
        )
    conn.commit()


def _backfill_players(conn: sqlite3.Connection):
    """Preenche a tabela players para puuids que já têm partida em cache mas nunca
    passaram por save_player (ex: main.py rodado antes dessa funcionalidade existir).
    Usa riotIdGameName/riotIdTagline, que a Match-V5 API já inclui por participante."""
    known_puuids = {r[0] for r in conn.execute("SELECT puuid FROM players").fetchall()}
    rows = conn.execute("SELECT DISTINCT puuid_analisado, raw_match_json FROM matches").fetchall()
    for puuid, raw_json in rows:
        if puuid in known_puuids:
            continue
        try:
            match_data = json.loads(raw_json)
        except Exception:
            continue
        for p in match_data.get("info", {}).get("participants", []):
            if p.get("puuid") == puuid:
                game_name = p.get("riotIdGameName")
                tag_line = p.get("riotIdTagline")
                if game_name and tag_line:
                    conn.execute(
                        """
                        INSERT INTO players (puuid, game_name, tag_line) VALUES (?, ?, ?)
                        ON CONFLICT(puuid) DO NOTHING
                        """,
                        (puuid, game_name, tag_line),
                    )
                    known_puuids.add(puuid)
                break
    conn.commit()


def _extract_summary(match_data: dict, puuid: str):
    """Extrai (champion_name, win) do JSON de match para o puuid analisado."""
    for p in match_data.get("info", {}).get("participants", []):
        if p.get("puuid") == puuid:
            return p.get("championName"), p.get("win")
    return None, None


def init_db():
    conn = get_connection()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
        _migrate(conn)
        _backfill_summary_columns(conn)
        _backfill_players(conn)
    finally:
        conn.close()


def save_player(puuid: str, game_name: str, tag_line: str):
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO players (puuid, game_name, tag_line) VALUES (?, ?, ?)
            ON CONFLICT(puuid) DO UPDATE SET game_name=excluded.game_name, tag_line=excluded.tag_line
            """,
            (puuid, game_name, tag_line),
        )
        conn.commit()
    finally:
        conn.close()


def list_players():
    conn = get_connection()
    try:
        rows = conn.execute("SELECT puuid, game_name, tag_line FROM players").fetchall()
        return [{"puuid": r[0], "game_name": r[1], "tag_line": r[2]} for r in rows]
    finally:
        conn.close()


def save_match(puuid: str, match_id: str, match_data: dict, timeline_data: dict = None):
    """Salva (ou atualiza) o match e sua timeline no banco local."""
    info = match_data.get("info", {})
    champion_name, win = _extract_summary(match_data, puuid)
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO matches (match_id, puuid_analisado, game_creation, game_duration,
                                  queue_id, champion_name, win, raw_match_json, raw_timeline_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(match_id) DO UPDATE SET
                champion_name=excluded.champion_name,
                win=excluded.win,
                raw_match_json=excluded.raw_match_json,
                raw_timeline_json=COALESCE(excluded.raw_timeline_json, matches.raw_timeline_json)
            """,
            (
                match_id,
                puuid,
                info.get("gameCreation"),
                info.get("gameDuration"),
                info.get("queueId"),
                champion_name,
                int(win) if win is not None else None,
                json.dumps(match_data),
                json.dumps(timeline_data) if timeline_data is not None else None,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def load_match(match_id: str):
    """Retorna (match_data, timeline_data) já parseados, ou (None, None) se não existir."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT raw_match_json, raw_timeline_json FROM matches WHERE match_id = ?",
            (match_id,),
        ).fetchone()
        if row is None:
            return None, None
        match_json, timeline_json = row
        match_data = json.loads(match_json) if match_json else None
        timeline_data = json.loads(timeline_json) if timeline_json else None
        return match_data, timeline_data
    finally:
        conn.close()


def get_match_summary(match_id: str):
    """Retorna champion_name/win/game_duration etc. de uma partida em cache, sem carregar o JSON inteiro."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT match_id, game_creation, game_duration, queue_id, champion_name, win FROM matches WHERE match_id = ?",
            (match_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "match_id": row[0],
            "game_creation": row[1],
            "game_duration": row[2],
            "queue_id": row[3],
            "champion_name": row[4],
            "win": bool(row[5]) if row[5] is not None else None,
        }
    finally:
        conn.close()


def list_stored_matches(puuid: str):
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT match_id, game_creation, game_duration, queue_id, champion_name, win
            FROM matches WHERE puuid_analisado = ? ORDER BY game_creation DESC
            """,
            (puuid,),
        ).fetchall()
        return [
            {
                "match_id": r[0],
                "game_creation": r[1],
                "game_duration": r[2],
                "queue_id": r[3],
                "champion_name": r[4],
                "win": bool(r[5]) if r[5] is not None else None,
            }
            for r in rows
        ]
    finally:
        conn.close()
