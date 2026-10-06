"""Backend falso para probar el sensor sin levantar el backend real.

Imprime cada alerta recibida y responde 201. Usa el puerto 8001 por defecto para
no chocar con el backend real (8000):

    python tools/mock_backend.py            # puerto 8001
    python -m sentinelops --backend-url http://127.0.0.1:8001/api/v1/eventos
"""

import http.server
import json
import socketserver
import sys

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8001


class MockHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        # El sensor consulta /api/v1/health al arrancar.
        self._responder(200, {"estado": "ok", "mock": True})

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(content_length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._responder(422, {"error": {"codigo": "json_invalido", "mensaje": "Cuerpo no es JSON"}})
            return

        print("\n" + "=" * 50)
        print(f"🚨 [NUEVA ALERTA RECIBIDA DESDE EL SENSOR EDGE] {self.path}")
        print(f"   X-Sensor-Key: {'presente' if self.headers.get('X-Sensor-Key') else 'AUSENTE'}")
        print("=" * 50)
        print(json.dumps(data, indent=2, ensure_ascii=False))
        print("=" * 50 + "\n")
        self._responder(201, {"id": 0, "mock": True})

    def _responder(self, status, cuerpo):
        self.send_response(status)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(cuerpo).encode("utf-8"))

    def log_message(self, format, *args):
        # Silenciar los logs por defecto de http.server para limpiar la consola
        pass


with socketserver.TCPServer(("", PORT), MockHandler) as httpd:
    print(f"Mock Backend (C4) escuchando en el puerto {PORT}...")
    httpd.serve_forever()
