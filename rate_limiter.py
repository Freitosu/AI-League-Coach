"""
Rate limiter de janela deslizante simples.

A Riot API (Development Key) limita por padrão a:
  - 20 requisições / 1 segundo
  - 100 requisições / 2 minutos

Este limiter bloqueia (time.sleep) automaticamente até haver espaço
disponível em ambas as janelas antes de liberar uma nova requisição.
Não é thread-safe de propósito -- o client é usado de forma sequencial.
"""

import time
from collections import deque


class RateLimiter:
    def __init__(self, short_max, short_window, long_max, long_window):
        self.short_max = short_max
        self.short_window = short_window
        self.long_max = long_max
        self.long_window = long_window
        self._short_calls = deque()
        self._long_calls = deque()

    def _prune(self, calls: deque, window: float, now: float):
        while calls and now - calls[0] > window:
            calls.popleft()

    def acquire(self):
        while True:
            now = time.monotonic()
            self._prune(self._short_calls, self.short_window, now)
            self._prune(self._long_calls, self.long_window, now)

            if len(self._short_calls) < self.short_max and len(self._long_calls) < self.long_max:
                self._short_calls.append(now)
                self._long_calls.append(now)
                return

            # Calcula quanto tempo esperar até a janela mais restritiva abrir espaço
            wait_short = (
                self.short_window - (now - self._short_calls[0]) if len(self._short_calls) >= self.short_max else 0
            )
            wait_long = (
                self.long_window - (now - self._long_calls[0]) if len(self._long_calls) >= self.long_max else 0
            )
            wait = max(wait_short, wait_long, 0.05)
            time.sleep(wait)
