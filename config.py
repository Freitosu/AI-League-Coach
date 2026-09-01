"""
Configuração central do projeto.

A API key da Riot NUNCA deve ficar hardcoded no código-fonte.
Defina a variável de ambiente RIOT_API_KEY antes de rodar, por exemplo:

    export RIOT_API_KEY="RGAPI-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"

Ou crie um arquivo .env na raiz do projeto (veja .env.example).
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

# --- Riot API ---
RIOT_API_KEY = os.environ.get("RIOT_API_KEY", "")

# Regional routing (para account-v1 e match-v5): "americas", "europe", "asia", "sea"
# Escolha de acordo com a região do jogador. Brasil -> "americas".
REGIONAL_ROUTING = os.environ.get("RIOT_REGIONAL_ROUTING", "americas")

# Platform routing (para endpoints por servidor, ex: summoner-v4): "br1", "na1", "euw1", etc.
PLATFORM_ROUTING = os.environ.get("RIOT_PLATFORM_ROUTING", "br1")

# --- Rate limiting (limites padrão de uma Development API Key da Riot) ---
# 20 requisições por 1 segundo, 100 requisições por 2 minutos.
RATE_LIMIT_SHORT_MAX_REQUESTS = 20
RATE_LIMIT_SHORT_WINDOW_SECONDS = 1
RATE_LIMIT_LONG_MAX_REQUESTS = 100
RATE_LIMIT_LONG_WINDOW_SECONDS = 120

# --- Armazenamento local ---
DB_PATH = os.path.join(os.path.dirname(__file__), "data", "lol_macro.sqlite3")

# --- LLM local (usado na etapa de geração de comentário, não nesta parte) ---
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")
