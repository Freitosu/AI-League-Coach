"""
Cliente da Riot Games API para o pipeline de análise de macro.

Cobre os endpoints necessários para a Parte 1 do projeto:
  - ACCOUNT-V1: resolver Riot ID (nome#tag) -> PUUID
  - MATCH-V5: listar partidas por PUUID
  - MATCH-V5: detalhes de uma partida
  - MATCH-V5: timeline de uma partida (posições, eventos, gold/xp por minuto)

Uso básico:

    from riot_client import RiotClient

    client = RiotClient()
    puuid = client.get_puuid("NomeDoJogador", "BR1")
    match_ids = client.get_match_ids(puuid, count=5)
    match = client.get_match(match_ids[0])
    timeline = client.get_match_timeline(match_ids[0])
"""

import time
import requests

import config
from rate_limiter import RateLimiter


class RiotAPIError(Exception):
    def __init__(self, status_code, message, url):
        self.status_code = status_code
        self.message = message
        self.url = url
        super().__init__(f"Riot API error {status_code} em {url}: {message}")


class RiotClient:
    def __init__(self, api_key: str = None, regional_routing: str = None):
        self.api_key = api_key or config.RIOT_API_KEY
        if not self.api_key:
            raise ValueError(
                "RIOT_API_KEY não configurada. Defina a variável de ambiente ou passe api_key=."
            )
        self.regional_routing = regional_routing or config.REGIONAL_ROUTING
        self.session = requests.Session()
        self.session.headers.update({"X-Riot-Token": self.api_key})
        self.limiter = RateLimiter(
            config.RATE_LIMIT_SHORT_MAX_REQUESTS,
            config.RATE_LIMIT_SHORT_WINDOW_SECONDS,
            config.RATE_LIMIT_LONG_MAX_REQUESTS,
            config.RATE_LIMIT_LONG_WINDOW_SECONDS,
        )

    def _get(self, url: str, params: dict = None, max_retries: int = 3):
        """GET com rate limiting local + respeito ao header Retry-After em 429."""
        attempt = 0
        while True:
            self.limiter.acquire()
            response = self.session.get(url, params=params, timeout=15)

            if response.status_code == 200:
                return response.json()

            if response.status_code == 429:
                # Rate limit estourado no lado da Riot (pode acontecer mesmo respeitando
                # o limiter local, ex: outra aplicação usando a mesma key).
                retry_after = int(response.headers.get("Retry-After", "1"))
                time.sleep(retry_after + 0.1)
                attempt += 1
                if attempt > max_retries:
                    raise RiotAPIError(429, "Rate limit excedido repetidamente", url)
                continue

            if response.status_code in (500, 502, 503, 504) and attempt < max_retries:
                attempt += 1
                time.sleep(1.5 * attempt)
                continue

            raise RiotAPIError(response.status_code, response.text, url)

    # --- ACCOUNT-V1 ---
    def get_puuid(self, game_name: str, tag_line: str) -> str:
        """Resolve um Riot ID (ex: 'Faker', 'KR1') para o PUUID do jogador."""
        url = f"https://{self.regional_routing}.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{game_name}/{tag_line}"
        data = self._get(url)
        return data["puuid"]

    # --- MATCH-V5 ---
    def get_match_ids(self, puuid: str, count: int = 20, start: int = 0, queue: int = None) -> list:
        """Lista os IDs das partidas mais recentes de um jogador."""
        url = f"https://{self.regional_routing}.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids"
        params = {"start": start, "count": count}
        if queue is not None:
            params["queue"] = queue
        return self._get(url, params=params)

    def get_match(self, match_id: str) -> dict:
        """Detalhes agregados de uma partida (KDA, itens, dano, gold final, etc.)."""
        url = f"https://{self.regional_routing}.api.riotgames.com/lol/match/v5/matches/{match_id}"
        return self._get(url)

    def get_match_timeline(self, match_id: str) -> dict:
        """
        Timeline minuto a minuto: posição de cada jogador, gold/xp/cs por frame,
        e a lista de eventos (kills, torres, dragões, barão, wards, etc.).
        Este é o dado principal para as heurísticas de macro.
        """
        url = f"https://{self.regional_routing}.api.riotgames.com/lol/match/v5/matches/{match_id}/timeline"
        return self._get(url)
