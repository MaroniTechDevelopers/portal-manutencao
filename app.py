"""
Portal NF — Servidor Azure App Service (Flask)
Arquivo usado apenas no deploy Azure; localmente use server.py
"""
from flask import Flask, request, jsonify, send_file, Response, abort
import os, json, threading, shutil, datetime, requests as req_lib

app     = Flask(__name__)
BASE    = os.path.dirname(os.path.abspath(__file__))
ALLOWED = {'base.json', 'users.json', 'mapeamento.json', 'cfg.json', 'os.json', 'pendencias.json'}

WRITE_TOKEN = os.environ.get('PORTAL_TOKEN', 'transmaroni-portal-2025')
_write_lock = threading.Lock()
BACKUP_DIR  = os.path.join(BASE, 'backups')
AUDIT_FILE  = os.path.join(BASE, 'audit.log')

os.makedirs(BACKUP_DIR, exist_ok=True)


# ── Utilitários ─────────────────────────────────────────────────

def _fazer_backup(fpath):
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
    ts    = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    linha = f'{ts} | POST | {arquivo} | {detalhes} | IP: {ip}\n'
    with open(AUDIT_FILE, 'a', encoding='utf-8') as f:
        f.write(linha)


def _cors(resp):
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    resp.headers['Access-Control-Allow-Headers'] = 'Content-Type, X-Portal-Token'
    return resp


# ── Rotas ────────────────────────────────────────────────────────

@app.route('/')
def index():
    return send_file(os.path.join(BASE, 'index.html'))


@app.route('/<path:name>', methods=['OPTIONS'])
def options(name):
    return _cors(Response(''))


@app.route('/<path:name>', methods=['GET'])
def get_data(name):
    if name == 'audit.log':
        token = request.headers.get('X-Portal-Token', '')
        if token != WRITE_TOKEN:
            abort(403)
        fpath = os.path.join(BASE, 'audit.log')
        if not os.path.exists(fpath):
            return Response('', mimetype='text/plain')
        return send_file(fpath, mimetype='text/plain')
    if name not in ALLOWED:
        abort(404)
    path = os.path.join(BASE, name)
    if not os.path.exists(path):
        return Response('null', mimetype='application/json')
    return send_file(path, mimetype='application/json')


@app.route('/<path:name>', methods=['POST'])
def post_data(name):
    # Proxy webhook
    if name == 'proxy-webhook':
        try:
            payload  = request.get_json(force=True)
            url      = payload.get('_url', '')
            data     = payload.get('_data', {})
            r = req_lib.post(url, json=data, timeout=10)
            resp = jsonify({'ok': True, 'status': r.status_code})
            return _cors(resp)
        except Exception as e:
            resp = jsonify({'error': str(e)})
            resp.status_code = 502
            return _cors(resp)

    if name not in ALLOWED:
        abort(403)

    token = request.headers.get('X-Portal-Token', '')
    if token != WRITE_TOKEN:
        resp = jsonify({'error': 'token invalido'})
        resp.status_code = 403
        return _cors(resp)

    body = request.data

    try:
        data = json.loads(body)
        if name in ('base.json', 'users.json', 'mapeamento.json') and not isinstance(data, list):
            raise ValueError(f'{name} deve ser uma lista')
    except (json.JSONDecodeError, ValueError) as e:
        resp = jsonify({'error': str(e)})
        resp.status_code = 400
        return _cors(resp)

    path = os.path.join(BASE, name)
    ip   = request.remote_addr

    with _write_lock:
        if name == 'base.json':
            _fazer_backup(path)
        tmp = path + '.tmp'
        try:
            with open(tmp, 'wb') as f:
                f.write(body)
            os.replace(tmp, path)
        except Exception as e:
            if os.path.exists(tmp):
                os.remove(tmp)
            resp = jsonify({'error': str(e)})
            resp.status_code = 500
            return _cors(resp)

    det = f'{len(data)} registros' if isinstance(data, list) else 'objeto'
    _audit(name, det, ip)

    return _cors(jsonify({'ok': True}))


@app.route('/api/status', methods=['GET'])
def api_status():
    try:
        from connectors.arquivei import ArquiveiConnector
        from connectors.rodopar  import RodoparConnector
        arq_ok = ArquiveiConnector().is_configurado()
        rod_ok = RodoparConnector().is_configurado()
    except Exception:
        arq_ok = rod_ok = False
    resp = jsonify({
        'arquivei': {'configurado': arq_ok, 'ultimo_sync': None},
        'rodopar':  {'configurado': rod_ok, 'ultimo_sync': None},
        'versao':   '1.0.0',
    })
    return _cors(resp)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
