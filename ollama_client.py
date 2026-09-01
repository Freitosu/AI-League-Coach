"""
Cliente mínimo para o Ollama rodando localmente (sem custo de API,
sem depender de internet além do download inicial do modelo).

Pré-requisitos:
  1. Instalar o Ollama: https://ollama.com
  2. Baixar um modelo, ex: `ollama pull llama3.1:8b`
  3. Deixar o Ollama rodando (ele fica em segundo plano após instalado,
     ou rode `ollama serve` manualmente)
"""

import requests

import config


class OllamaError(Exception):
    pass


def chat(messages: list, model: str = None, host: str = None, temperature: float = 0.4, timeout: int = 180) -> str:
    """
    messages: lista de dicts {"role": "system"|"user"|"assistant", "content": str}
    Retorna o texto de resposta do modelo.
    """
    model = model or config.OLLAMA_MODEL
    host = host or config.OLLAMA_HOST
    url = f"{host}/api/chat"
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": temperature},
    }
    try:
        response = requests.post(url, json=payload, timeout=timeout)
    except requests.exceptions.ConnectionError as e:
        raise OllamaError(
            f"Não foi possível conectar ao Ollama em {host}. Ele está rodando? "
            f"Abra o app Ollama (ou rode 'ollama serve') e confirme que o modelo "
            f"'{model}' foi baixado com 'ollama pull {model}'."
        ) from e

    if response.status_code == 404:
        raise OllamaError(
            f"Modelo '{model}' não encontrado no Ollama. Baixe com: ollama pull {model}"
        )
    if response.status_code != 200:
        raise OllamaError(f"Ollama retornou erro {response.status_code}: {response.text}")

    data = response.json()
    try:
        return data["message"]["content"]
    except (KeyError, TypeError):
        raise OllamaError(f"Resposta inesperada do Ollama: {data}")
