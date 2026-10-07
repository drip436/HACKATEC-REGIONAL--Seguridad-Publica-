import http.server
import socketserver
import json
import sys

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8000

class MockHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        data = json.loads(post_data.decode('utf-8'))
        
        print("\n" + "="*50)
        print("🚨 [NUEVA ALERTA RECIBIDA DESDE EL SENSOR EDGE]")
        print("="*50)
        print(json.dumps(data, indent=2))
        print("="*50 + "\n")
        
        self.send_response(201)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(b'{"status": "ok", "message": "Alerta registrada"}')

    def log_message(self, format, *args):
        # Silenciar los logs por defecto de http.server para limpiar la consola
        pass

with socketserver.TCPServer(("", PORT), MockHandler) as httpd:
    print(f"Mock Backend (C4) escuchando en el puerto {PORT}...")
    httpd.serve_forever()