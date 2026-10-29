"""Manipulador HTTP comum ao servidor local e às funções do Vercel (pasta api/)."""

import hmac
import json
import mimetypes
import os
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import api

PUBLICO = Path(__file__).resolve().parents[2] / "public"


def _token_valido(recebido: str | None) -> bool:
    """Se PAINEL_TOKEN estiver definido, a API exige o mesmo valor no cabeçalho X-Painel-Token."""
    esperado = os.environ.get("PAINEL_TOKEN")
    if not esperado:
        return True
    return bool(recebido) and hmac.compare_digest(recebido, esperado)


class Manipulador(BaseHTTPRequestHandler):
    servir_arquivos = False  # o servidor local liga; no Vercel os arquivos de public/ são servidos pela plataforma

    def _json(self, status: int, corpo: dict) -> None:
        dados = json.dumps(corpo, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def do_GET(self) -> None:  # noqa: N802 (nome exigido por BaseHTTPRequestHandler)
        partes = urlsplit(self.path)
        if partes.path.startswith("/api/"):
            if not _token_valido(self.headers.get("X-Painel-Token")):
                self._json(401, {"erro": "Senha de acesso ao painel ausente ou incorreta.", "senha": True})
                return
            params = {k: v[-1] for k, v in parse_qs(partes.query).items()}
            self._json(*api.responder(partes.path, params))
            return
        if self.servir_arquivos:
            self._arquivo(partes.path)
            return
        self._json(404, {"erro": "Rota não encontrada."})

    def _arquivo(self, caminho: str) -> None:
        alvo = (PUBLICO / (caminho.lstrip("/") or "index.html")).resolve()
        if alvo.is_dir():
            alvo = alvo / "index.html"
        if not alvo.is_relative_to(PUBLICO) or not alvo.is_file():
            self._json(404, {"erro": "Arquivo não encontrado."})
            return
        dados = alvo.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(alvo.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def log_message(self, formato: str, *args) -> None:
        if os.environ.get("PAINEL_LOG"):
            super().log_message(formato, *args)
