"""Local acceptance harness. Reads existing credentials privately; never enrolls agents.

This is a harness-initiated transport check, not evidence of autonomous host wake.
Run from the Tsunagou checkout: uv run python <this file>
"""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
import urllib.request
import uuid

ROOT = Path('D:/ALL.NET/SegaImageManageTool')
OUT = Path(__file__).parent
PROJECT = '839bdb05-c7db-474c-9517-f0e837eb5096'
TASKS = {'webui': '0a28f9e6-52c8-4d80-b805-64807da75931',
         'http': 'ab418fd1-b3a8-48a9-9ac2-f595cd833f14'}
STATE = ROOT / '.tsunagou/local'
env = {**os.environ, 'TSUNAGOU_PROJECT_ROOT': str(ROOT), 'TSUNAGOU_STATE_DIR': str(STATE)}

def now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')

def sequence():
    with sqlite3.connect(f'{(STATE / "state.sqlite3").as_uri()}?mode=ro', uri=True) as db:
        return db.execute('select max(event_seq) from events where project_id=?', (PROJECT,)).fetchone()[0]

def cli(args):
    start = now()
    timer = time.perf_counter()
    result = subprocess.run([sys.executable, '-m', 'tsunagou', *args], env=env, capture_output=True, text=True, encoding='utf-8', timeout=30)
    try:
        data = json.loads(result.stdout)
    except ValueError:
        data = {'unparseable_output': True}
    return {'args': args, 'started_at': start, 'finished_at': now(),
            'duration_ms': round((time.perf_counter()-timer)*1000, 2),
            'exit_code': result.returncode, 'response': data}

before = sequence()
queries = []
cursor = None
while True:
    args = ['project', 'history', PROJECT, '--limit', '200', '--json']
    if cursor:
        args += ['--cursor', cursor]
    page = cli(args)
    queries.append(page)
    cursor = page['response'].get('next_cursor')
    if page['exit_code'] or not cursor:
        break
for task in TASKS.values():
    queries.append(cli(['task', 'history', task, '--project-id', PROJECT, '--limit', '200', '--json']))
queries.append(cli(['project', 'diagnostics', PROJECT, '--json']))
queries.append(cli(['checkpoint', 'list', PROJECT, '--verify']))
events = [item for q in queries for item in q['response'].get('items', []) if 'event_id' in item]
if events:
    queries.append(cli(['audit', 'event', events[-1]['event_id'], '--project-id', PROJECT, '--include-evidence', '--json']))
report = {'recorded_at': now(), 'harness': 'root_acceptance_cli', 'project_id': PROJECT,
          'event_seq_before': before, 'event_seq_after': sequence(), 'queries': queries, 'secrets_included': False}
query_file = 'public-query-after-restart.json' if '--after-restart' in sys.argv else 'public-query-record.json'
(OUT / query_file).write_text(json.dumps(report, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
if '--queries-only' in sys.argv:
    print(json.dumps({'record':query_file, 'query_exit_codes':[q['exit_code'] for q in queries],
                      'event_seq_before':before, 'event_seq_after':sequence()}))
    sys.exit(0)

endpoint = json.loads((STATE/'endpoint.json').read_text(encoding='utf-8'))
base = endpoint.get('url') or endpoint.get('base_url')
if not base:
    raise RuntimeError('endpoint_url_missing')
sessions = {name: json.loads((ROOT/'.tsunagou/bridges'/name/'bridge-session.json').read_text(encoding='utf-8')) for name in ['main', 'webui', 'http']}

def rpc(name, method, params, request_id=None):
    session = sessions[name]
    request = {'jsonrpc': '2.0', 'id': request_id or str(uuid.uuid4()), 'method': method, 'params': params}
    started = now()
    timer = time.perf_counter()
    req = urllib.request.Request(base+'/api/v1/a2a', data=json.dumps(request).encode(), headers={
        'Content-Type': 'application/json', 'Authorization': 'Bearer '+session['secret_token'],
        'Tsunagou-Session-Id': session['session_id'], 'Tsunagou-Connection-Epoch': str(session['connection_epoch'])})
    with urllib.request.urlopen(req, timeout=20) as response:
        status = response.status
        data = json.load(response)
    return {'started_at': started, 'finished_at': now(), 'duration_ms': round((time.perf_counter()-timer)*1000, 2),
            'authenticated_agent_id': session['agent_id'], 'session_id': session['session_id'],
            'request': request, 'http_status': status, 'response': data}

with urllib.request.urlopen(base+'/.well-known/agent-card.json', timeout=10) as response:
    card = json.load(response)
before_a2a = sequence()
requests = []
for recipient in ['webui', 'http']:
    mid = 'acceptance-'+recipient+'-'+str(uuid.uuid4())
    params = {'message': {'messageId': mid, 'role': 'agent', 'contextId': PROJECT,
        'parts': [{'text': 'Acceptance transport probe only. Pull and acknowledge this message, then reply acceptance_probe_received to main. Do not reopen tasks or modify code.'}],
        'metadata': {'tsunagou': {'recipient_agent_id': sessions[recipient]['agent_id'], 'project_id': PROJECT,
            'kind': 'acceptance_probe', 'subject_ref': TASKS[recipient],
            'payload': {'origin': 'root_acceptance_harness', 'host_wake_claimed': False}}}}}
    request_id = 'rpc-'+mid
    first = rpc('main', 'message/send', params, request_id)
    requests.append(first)
    requests.append(rpc('main', 'message/send', params, request_id))
    requests.append(rpc('main', 'message/send', params, request_id+'-retry'))
    requests.append(rpc(recipient, 'tasks/get', {'id': 'tsunagou:task:'+TASKS[recipient]}))
# Denials are attempted as worker; completed business tasks must remain unchanged.
for method in ['tasks/cancel', 'tasks/fail', 'tasks/retry']:
    requests.append(rpc('webui', method, {'id': TASKS['http'], 'attemptId': '92aa8651-9286-4fca-93a9-dd76c95077e7', 'reason': 'acceptance_foreign_worker_denial_probe'}))
record = {'recorded_at': now(), 'harness': 'root_acceptance_using_existing_sessions',
          'qualification': 'direct HTTP JSON-RPC; not autonomous main turn or native wake evidence',
          'endpoint': base+'/api/v1/a2a', 'agent_card': card,
          'event_seq_before': before_a2a, 'event_seq_after': sequence(), 'requests': requests, 'secrets_included': False}
(OUT/'a2a-http-record.json').write_text(json.dumps(record, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
print(json.dumps({'query_count':len(queries), 'query_exit_codes':[q['exit_code'] for q in queries],
    'query_read_only':report['event_seq_before']==report['event_seq_after'],
    'a2a_event_seq_before':before_a2a, 'a2a_event_seq_after':sequence(),
    'a2a_results':[{'method':r['request']['method'], 'response':r['response']} for r in requests]}, ensure_ascii=False))
