#!/usr/bin/env python3
"""
Portal NF - Servidor de Rede Interna
Uso: python server.py
     python server.py 9090   (porta customizada)
"""
from http.server import HTTPServer, BaseHTTPRequestHandler
import os, sys, socket, datetime, json, threading, shutil, urllib.request

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
ALLOWED     = {'/base.json', '/users.json', '/mapeamento.json', '/cfg.json'}
BACKUP_DIR  = os.path.join(BASE_DIR, 'backups')
AUDIT_FILE  = os.path.join(BASE_DIR, 'audit.log')
WRITE_TOKEN = os.environ.get('PORTAL_TOKEN', 'transmaroni-portal-2025')
_write_lock = threading.Lock()

os.makedirs(BACKUP_DIR, exist_ok=True)


# ── Utilitários ─────────────────────────────────────────────────

def _fazer_backup(fpath):
    """Salva cópia de base.json antes de sobrescrever; apaga backups > 7 dias."""
    if not os.path.exists(fpath):
        return
    ts   = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    dest = os.path.join(BACKUP_DIR, f'base_{ts}.json')
    shutil.copy2(fpath, dest)
    limite = datetime.datetime.now() - datetime.timedelta(days=7)
    for f in os.listdir(BACKUP_DIR):
        fp = os.path.join(BACKUP_DIR, f)
        if os.path.isfile(fp) and datetime.datetime.fromtimestamp(os.path.getmtime(fp)) < limite:
            os.remove(fp)


def _audit(arquivo, detalhes, ip):
    """Registra linha no audit.log."""
    ts  = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    linha = f'{ts} | POST | {arquivo} | {detalhes} | IP: {ip}\n'
    with open(AUDIT_FILE, 'a', encoding='utf-8') as f:
        f.write(linha)


class Handler(BaseHTTPRequestHandler):

    # ── CORS ─────────────────────────────────────────────────────
    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-Portal-Token')

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    # ── GET ──────────────────────────────────────────────────────
    def do_GET(self):
        path = self.path.split('?')[0]
        if path == '/':
            self._serve_file('index.html', 'text/html; charset=utf-8')
        elif path in ALLOWED:
            self._serve_file(path.lstrip('/'), 'application/json; charset=utf-8')
        elif path == '/audit.log':
            token = self.headers.get('X-Portal-Token', '')
            if token != WRITE_TOKEN:
                self.send_response(403); self.end_headers(); return
            self._serve_file('audit.log', 'text/plain; charset=utf-8')
        else:
            self.send_response(404)
            self.end_headers()

    # ── POST ─────────────────────────────────────────────────────
    def do_POST(self):
        path = self.path.split('?')[0]

        # Proxy webhook (não exige token — o frontend já tem o URL completo)
        if path == '/proxy-webhook':
            self._proxy_webhook()
            return

        if path not in ALLOWED:
            self.send_response(403); self.end_headers(); return

        # Verificação de token
        token = self.headers.get('X-Portal-Token', '')
        if token != WRITE_TOKEN:
            self.send_response(403)
            self._cors()
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"error":"token invalido"}')
            return

        length = int(self.headers.get('Content-Length', 0))
        body   = self.rfile.read(length)

        # Validação de JSON
        try:
            data = json.loads(body)
            for chk in ('base.json', 'users.json', 'mapeamento.json'):
                if path == f'/{chk}' and not isinstance(data, list):
                    raise ValueError(f'{chk} deve ser uma lista')
        except (json.JSONDecodeError, ValueError) as e:
            self.send_response(400)
            self._cors()
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'error': str(e)}).encode())
            return

        fpath   = os.path.join(BASE_DIR, path.lstrip('/'))
        ip      = self.client_address[0]

        with _write_lock:
            # Backup automático apenas para base.json
            if path == '/base.json':
                _fazer_backup(fpath)

            tmp = fpath + '.tmp'
            try:
                with open(tmp, 'wb') as f:
                    f.write(body)
                os.replace(tmp, fpath)
            except Exception as e:
                if os.path.exists(tmp):
                    os.remove(tmp)
                self.send_response(500)
                self._cors()
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode())
                return

        # Auditoria
        nome = path.lstrip('/')
        if isinstance(data, list):
            det = f'{len(data)} registros'
        else:
            det = 'objeto'
        _audit(nome, det, ip)

        self.send_response(200)
        self._cors()
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    # ── Proxy Webhook ─────────────────────────────────────────────
    def _proxy_webhook(self):
        try:
            length = int(self.headers.get('Content-Length', 0))
            body   = self.rfile.read(length)
            payload = json.loads(body)
            url     = payload.get('_url', '')
            data    = json.dumps(payload.get('_data', {})).encode()
            req = urllib.request.Request(url, data=data,
                  headers={'Content-Type': 'application/json'}, method='POST')
            urllib.request.urlopen(req, timeout=10)
            self.send_response(200)
            self._cors()
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
        except Exception as e:
            self.send_response(502)
            self._cors()
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'error': str(e)}).encode())

    # ── Servir arquivo ────────────────────────────────────────────
    def _serve_file(self, filename, ctype):
        fpath = os.path.join(BASE_DIR, filename)
        if not os.path.exists(fpath):
            if 'json' in ctype:
                self.send_response(200)
                self._cors()
                self.send_header('Content-Type', ctype)
                self.end_headers()
                self.wfile.write(b'null')
                return
            self.send_response(404)
            self.end_headers()
            return
        with open(fpath, 'rb') as f:
            data = f.read()
        self.send_response(200)
        self._cors()
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        hora   = datetime.datetime.now().strftime('%H:%M:%S')
        metodo = args[0].split()[0] if args[0].split() else '-'
        rota   = args[0].split()[1] if len(args[0].split()) > 1 else '-'
        status = args[1]
        if rota not in ('/favicon.ico',):
            print(f'  {hora}  {status}  {metodo:6} {rota}')


def get_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return 'localhost'


PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
IP   = get_ip()

print()
print('  ╔══════════════════════════════════════════╗')
print('  ║       Portal NF — Rede Interna           ║')
print('  ╠══════════════════════════════════════════╣')
print(f'  ║  Local :  http://localhost:{PORT}           ║')
print(f'  ║  Rede  :  http://{IP}:{PORT}      ║')
print('  ║                                          ║')
print('  ║  Compartilhe o endereço "Rede" com       ║')
print('  ║  os colegas. Para parar: Ctrl+C          ║')
print('  ╚══════════════════════════════════════════╝')
print()

HTTPServer(('0.0.0.0', PORT), Handler).serve_forever()
