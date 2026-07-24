"""
Portal NF — Servidor Azure App Service (Flask)
Arquivo usado apenas no deploy Azure; localmente use server.py
"""
from flask import Flask, request, jsonify, send_file, Response, abort
import base64

try:
    import requests as _req
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False

import os, json, threading, shutil, datetime, requests as req_lib

app     = Flask(__name__)
BASE    = os.path.dirname(os.path.abspath(__file__))
ALLOWED = {'base.json', 'users.json', 'mapeamento.json', 'cfg.json', 'os.json', 'pendencias.json'}

WRITE_TOKEN = os.environ.get('PORTAL_TOKEN', 'transmaroni-portal-2025')

# Microsoft Graph config
GRAPH_TENANT_ID     = os.environ.get('GRAPH_TENANT_ID', '')
GRAPH_CLIENT_ID     = os.environ.get('GRAPH_CLIENT_ID', '')
GRAPH_CLIENT_SECRET = os.environ.get('GRAPH_CLIENT_SECRET', '')
GRAPH_USER_EMAIL    = os.environ.get('GRAPH_USER_EMAIL', 'maroni.tech@transmaroni.com.br')

# Arquivei config
ARQUIVEI_ACCESS_ID  = os.environ.get('ARQUIVEI_ACCESS_ID', '')
ARQUIVEI_ACCESS_KEY = os.environ.get('ARQUIVEI_ACCESS_KEY', '')

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


# ── Email Agent Hub — config persistido em email-agent.json ──────
EMAIL_AGENT_FILE = os.path.join(BASE, 'email-agent.json')

_EA_DEFAULTS = {
    'email': '',
    'intervalo': 15,
    'ativo': False,
    'palavras_chave': ['nota fiscal', 'nf-e', 'nfs-e', 'boleto', 'fatura', 'danfe', 'nfe'],
    'pasta': 'Inbox',
    'ultimo_scan': None,
    'emails_encontrados': 0,
    'log': [],
}

def _ea_load():
    if os.path.exists(EMAIL_AGENT_FILE):
        try:
            with open(EMAIL_AGENT_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if not data.get('email'):
                data['email'] = GRAPH_USER_EMAIL
            return data
        except Exception:
            pass
    cfg = dict(_EA_DEFAULTS)
    cfg['email'] = GRAPH_USER_EMAIL
    return cfg

def _ea_save(data):
    with open(EMAIL_AGENT_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

@app.route('/api/email-agent/config', methods=['GET'])
def ea_config_get():
    cfg = _ea_load()
    cfg['graph_configurado'] = bool(GRAPH_TENANT_ID and GRAPH_CLIENT_ID and GRAPH_CLIENT_SECRET)
    return _cors(jsonify(cfg))

@app.route('/api/email-agent/config', methods=['POST'])
def ea_config_save():
    token = request.headers.get('X-Portal-Token', '')
    if token != WRITE_TOKEN:
        return _cors(jsonify({'error': 'token invalido'})), 403
    body = request.get_json(force=True) or {}
    current = _ea_load()
    for k in ('email', 'intervalo', 'ativo', 'palavras_chave', 'pasta'):
        if k in body:
            current[k] = body[k]
    _ea_save(current)
    return _cors(jsonify({'ok': True}))

@app.route('/api/email-agent/status', methods=['GET'])
def ea_status():
    cfg = _ea_load()
    return _cors(jsonify({
        'graph_configurado': bool(GRAPH_TENANT_ID and GRAPH_CLIENT_ID and GRAPH_CLIENT_SECRET),
        'email':             cfg.get('email'),
        'intervalo':         cfg.get('intervalo'),
        'ativo':             cfg.get('ativo'),
        'ultimo_scan':       cfg.get('ultimo_scan'),
        'emails_encontrados':cfg.get('emails_encontrados', 0),
        'log':               cfg.get('log', [])[:20],
    }))

@app.route('/api/email-agent/run', methods=['POST'])
def ea_run():
    token = request.headers.get('X-Portal-Token', '')
    if token != WRITE_TOKEN:
        return _cors(jsonify({'error': 'token invalido'})), 403
    if not GRAPH_TENANT_ID or not GRAPH_CLIENT_ID or not GRAPH_CLIENT_SECRET:
        return _cors(jsonify({'error': 'Graph API não configurada no servidor.'})), 503
    cfg = _ea_load()
    email = cfg.get('email') or GRAPH_USER_EMAIL
    palavras = cfg.get('palavras_chave', _EA_DEFAULTS['palavras_chave'])
    ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    try:
        all_emails, matched = _graph_scan(email, palavras)
        entry = {'timestamp': ts, 'email': email, 'total': len(all_emails), 'encontrados': len(matched), 'status': 'ok'}
        cfg['ultimo_scan']       = ts
        cfg['emails_encontrados'] = len(matched)
        log = cfg.get('log', [])
        log.insert(0, entry)
        cfg['log'] = log[:50]
        _ea_save(cfg)
        return _cors(jsonify({'ok': True, 'emails': matched, 'total_verificados': len(all_emails),
                              'encontrados': len(matched), 'timestamp': ts}))
    except Exception as e:
        entry = {'timestamp': ts, 'email': email, 'total': 0, 'encontrados': 0, 'status': 'error', 'erro': str(e)}
        cfg['log'] = ([entry] + cfg.get('log', []))[:50]
        _ea_save(cfg)
        return _cors(jsonify({'error': str(e)})), 500

# ── Microsoft Graph ──────────────────────────────────────────────
def _graph_token():
    if not _HAS_REQUESTS:
        raise RuntimeError('requests not installed')
    url = f'https://login.microsoftonline.com/{GRAPH_TENANT_ID}/oauth2/v2.0/token'
    r = _req.post(url, data={
        'grant_type':    'client_credentials',
        'client_id':     GRAPH_CLIENT_ID,
        'client_secret': GRAPH_CLIENT_SECRET,
        'scope':         'https://graph.microsoft.com/.default'
    }, timeout=15)
    r.raise_for_status()
    return r.json().get('access_token')

def _graph_scan(email, palavras):
    token  = _graph_token()
    hdrs   = {'Authorization': f'Bearer {token}'}
    params = {
        '$filter':  "hasAttachments eq true and isDraft eq false",
        '$top':     '100',
        '$orderby': 'receivedDateTime desc',
        '$select':  'id,subject,from,receivedDateTime,hasAttachments,bodyPreview',
    }
    r = _req.get(f'https://graph.microsoft.com/v1.0/users/{email}/messages',
                 headers=hdrs, params=params, timeout=25)
    r.raise_for_status()
    all_emails = r.json().get('value', [])
    matched = [e for e in all_emails
               if any(k in e.get('subject','').lower() for k in palavras)]
    return all_emails, matched

@app.route('/api/graph/emails', methods=['GET'])
def graph_emails():
    if not GRAPH_TENANT_ID or not GRAPH_CLIENT_ID or not GRAPH_CLIENT_SECRET:
        return _cors(jsonify({'error': 'Graph API não configurada no servidor.'})), 503
    try:
        cfg     = _ea_load()
        email   = cfg.get('email') or GRAPH_USER_EMAIL
        palavras = cfg.get('palavras_chave', _EA_DEFAULTS['palavras_chave'])
        _, matched = _graph_scan(email, palavras)
        return _cors(jsonify({'emails': matched, 'email': email}))
    except Exception as e:
        return _cors(jsonify({'error': str(e)})), 500

@app.route('/api/graph/email/<msg_id>/attachments', methods=['GET'])
def graph_attachments(msg_id):
    try:
        cfg   = _ea_load()
        email = cfg.get('email') or GRAPH_USER_EMAIL
        token = _graph_token()
        hdrs  = {'Authorization': f'Bearer {token}'}
        r = _req.get(
            f'https://graph.microsoft.com/v1.0/users/{email}/messages/{msg_id}/attachments',
            headers=hdrs, params={'$select': 'id,name,contentType,size'}, timeout=20)
        r.raise_for_status()
        atts = [a for a in r.json().get('value', [])
                if 'pdf' in a.get('contentType','').lower() or a.get('name','').lower().endswith('.pdf')]
        return _cors(jsonify({'attachments': atts}))
    except Exception as e:
        return _cors(jsonify({'error': str(e)})), 500

@app.route('/api/graph/attachment/<msg_id>/<att_id>', methods=['GET'])
def graph_attachment(msg_id, att_id):
    try:
        cfg   = _ea_load()
        email = cfg.get('email') or GRAPH_USER_EMAIL
        token = _graph_token()
        hdrs  = {'Authorization': f'Bearer {token}'}
        r = _req.get(
            f'https://graph.microsoft.com/v1.0/users/{email}/messages/{msg_id}/attachments/{att_id}',
            headers=hdrs, timeout=30)
        r.raise_for_status()
        att = r.json()
        return _cors(jsonify({
            'nome':        att.get('name', 'arquivo.pdf'),
            'contentType': att.get('contentType', 'application/pdf'),
            'b64':         att.get('contentBytes', ''),
        }))
    except Exception as e:
        return _cors(jsonify({'error': str(e)})), 500

# ── Arquivei ──────────────────────────────────────────────
@app.route('/api/arquivei/pdf/<chave>', methods=['GET'])
def arquivei_pdf(chave):
    if not ARQUIVEI_ACCESS_ID or not ARQUIVEI_ACCESS_KEY:
        return jsonify({'error': 'Arquivei não configurada. Defina ARQUIVEI_ACCESS_ID e ARQUIVEI_ACCESS_KEY nas variáveis de ambiente.'}), 503
    if not _HAS_REQUESTS:
        return jsonify({'error': 'Dependência "requests" não instalada no servidor.'}), 503
    try:
        r = _req.get('https://app.arquivei.com.br/api/v1/nfe/pdf',
                     params={'access_id': ARQUIVEI_ACCESS_ID, 'chave': chave},
                     auth=(ARQUIVEI_ACCESS_ID, ARQUIVEI_ACCESS_KEY),
                     timeout=30)
        if r.status_code == 200:
            return jsonify({'b64': base64.b64encode(r.content).decode(), 'nome': f'NF_{chave[:10]}.pdf'})
        return jsonify({'error': f'Arquivei status {r.status_code}: {r.text[:200]}'}), r.status_code
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/arquivei/boleto/<chave>', methods=['GET'])
def arquivei_boleto(chave):
    if not ARQUIVEI_ACCESS_ID or not ARQUIVEI_ACCESS_KEY:
        return jsonify({'error': 'Arquivei não configurada.'}), 503
    if not _HAS_REQUESTS:
        return jsonify({'error': '"requests" não instalada.'}), 503
    try:
        # Arquivei boleto endpoint (via NF chave / duplicata)
        r = _req.get('https://app.arquivei.com.br/api/v1/nfe/boleto',
                     params={'access_id': ARQUIVEI_ACCESS_ID, 'chave': chave},
                     auth=(ARQUIVEI_ACCESS_ID, ARQUIVEI_ACCESS_KEY),
                     timeout=30)
        if r.status_code == 200:
            return jsonify({'b64': base64.b64encode(r.content).decode(), 'nome': f'Boleto_{chave[:10]}.pdf'})
        return jsonify({'error': f'Arquivei status {r.status_code}: {r.text[:200]}'}), r.status_code
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
