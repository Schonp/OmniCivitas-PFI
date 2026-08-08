"""Rate limiting de ventana deslizante en memoria para los canales públicos.

Alcance del prototipo: un solo proceso. En producción el contador iría en Redis
para compartirse entre workers.
"""

import time
from collections import defaultdict, deque

from app.core.config import settings

WINDOW_SECONDS = 60

_hits: dict[str, deque[float]] = defaultdict(deque)


def check_rate_limit(key: str, limit: int | None = None) -> bool:
    """Registra un hit y devuelve False si `key` superó el límite por minuto."""
    max_hits = settings.rate_limit_per_minute if limit is None else limit
    now = time.monotonic()
    hits = _hits[key]

    while hits and now - hits[0] >= WINDOW_SECONDS:
        hits.popleft()

    if len(hits) >= max_hits:
        return False

    hits.append(now)
    return True


def reset_rate_limit() -> None:
    _hits.clear()
