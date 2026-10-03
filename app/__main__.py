"""Ponto de entrada:  python -m app"""

import logging
import re

import uvicorn

from .config import settings


class _RedactOAuthQuery(logging.Filter):
    """Não deixa o código de autorização do Google aparecer no log de acesso."""

    _pattern = re.compile(r"(/auth/callback)\?[^\s\"]*")

    def filter(self, record: logging.LogRecord) -> bool:
        if record.args:
            record.args = tuple(
                self._pattern.sub(r"\1?[omitido]", a) if isinstance(a, str) else a for a in record.args
            )
        return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("uvicorn.access").addFilter(_RedactOAuthQuery())
    uvicorn.run("app.main:app", host=settings.app_host, port=settings.app_port, log_config=None)
