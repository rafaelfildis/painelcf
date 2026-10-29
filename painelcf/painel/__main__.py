"""Servidor local do painel: python -m painelcf.painel [porta]."""

import sys
import webbrowser
from http.server import ThreadingHTTPServer

from .http import Manipulador


class ManipuladorLocal(Manipulador):
    servir_arquivos = True


porta = next((int(a) for a in sys.argv[1:] if a.isdigit()), 8000)
servidor = ThreadingHTTPServer(("127.0.0.1", porta), ManipuladorLocal)
print(f"Painel em http://127.0.0.1:{porta}  (Ctrl+C para encerrar)")
if "--sem-navegador" not in sys.argv:
    webbrowser.open(f"http://127.0.0.1:{porta}")
try:
    servidor.serve_forever()
except KeyboardInterrupt:
    pass
