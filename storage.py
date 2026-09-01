"""
Armazenamento local (SQLite) para partidas e timelines já baixadas da Riot API.

Guardamos o JSON bruto de match e timeline (mais simples e robusto a mudanças
de schema da Riot) junto com algumas colunas indexáveis para consulta rápida.
As heurísticas (etapa seguinte) leem os JSONs daqui em vez de bater na API
de novo a cada análise.
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
    raw_match_json TEXT NOT NULL,
    raw_timeline_json TEXT,
    fetched_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_matches_puuid ON matches(puuid_analisado);
"""


def get_connection() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_connection()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def save_match(puuid: str, match_id: str, match_data: dict, timeline_data: dict = None):
    """Salva (ou atualiza) o match e sua timeline no banco local."""
    info = match_data.get("info", {})
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO matches (match_id, puuid_analisado, game_creation, game_duration,
                                  queue_id, raw_match_json, raw_timeline_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(match_id) DO UPDATE SET
                raw_match_json=excluded.raw_match_json,
                raw_timeline_json=COALESCE(excluded.raw_timeline_json, matches.raw_timeline_json)
            """,
            (
                match_id,
                puuid,
                info.get("gameCreation"),
                info.get("gameDuration"),
                info.get("queueId"),
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
            "SELECT match_id, game_creation, game_duration, queue_id FROM matches WHERE puuid_analisado = ? ORDER BY game_creation DESC",
            (puuid,),
        ).fetchall()
        return [
            {"match_id": r[0], "game_creation": r[1], "game_duration": r[2], "queue_id": r[3]}
            for r in rows
        ]
    finally:
        conn.close()
