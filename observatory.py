"""ONScan Observatory: local sensor ledger and read-only MCP, Python 3.9+."""
import argparse
from datetime import datetime, timezone
import html
import json
import math
from pathlib import Path
import re
import sqlite3
import sys

ID = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")


class Observatory:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS readings (
          id TEXT PRIMARY KEY, source TEXT NOT NULL, metric TEXT NOT NULL,
          unit TEXT NOT NULL, time TEXT NOT NULL, value REAL NOT NULL,
          kind TEXT NOT NULL, simulation INTEGER NOT NULL);
        CREATE INDEX IF NOT EXISTS reading_series ON readings(source,metric,time);
        CREATE TABLE IF NOT EXISTS rules (
          id TEXT PRIMARY KEY, source TEXT NOT NULL, metric TEXT NOT NULL,
          unit TEXT NOT NULL, above REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS alerts (
          reading_id TEXT NOT NULL, rule_id TEXT NOT NULL,
          UNIQUE(reading_id,rule_id));
        ''')

    def ingest(self, event):
        if not isinstance(event, dict):
            raise ValueError('Reading must be an object')
        for key in ('id', 'source', 'metric', 'unit'):
            if not isinstance(event.get(key), str) or not ID.fullmatch(event[key]):
                raise ValueError('Invalid ' + key)
        value = event.get('value')
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError('value must be finite')
        time = datetime.fromisoformat(str(event.get('time', '')).replace('Z', '+00:00'))
        if time.tzinfo is None:
            raise ValueError('time requires a timezone')
        kind = event.get('kind', 'sensor')
        if kind not in ('sensor', 'thermal', 'camera-derived'):
            raise ValueError('Unknown kind')
        simulation = event.get('simulation', False)
        if not isinstance(simulation, bool):
            raise ValueError('simulation must be boolean')
        row = (event['id'], event['source'], event['metric'], event['unit'],
               time.astimezone(timezone.utc).isoformat(), value, kind, int(simulation))
        with self.db:
            old = self.db.execute('SELECT * FROM readings WHERE id=?', (row[0],)).fetchone()
            if old:
                if tuple(old) != row:
                    raise ValueError('ID already belongs to a different reading')
                return False
            self.db.execute('INSERT INTO readings VALUES (?,?,?,?,?,?,?,?)', row)
            self.db.execute('''INSERT INTO alerts SELECT ?,id FROM rules
              WHERE source=? AND metric=? AND unit=? AND ?>above''',
                            (row[0], row[1], row[2], row[3], value))
        return True

    def rule(self, id, source, metric, unit, above):
        if any(not ID.fullmatch(x) for x in (id, source, metric, unit)):
            raise ValueError('Invalid rule identifier')
        if not math.isfinite(above):
            raise ValueError('Invalid threshold')
        with self.db:
            self.db.execute('INSERT INTO rules VALUES (?,?,?,?,?)', (id, source, metric, unit, above))

    def read(self, name, args):
        if not isinstance(args, dict) or set(args) - {'source', 'limit'}:
            raise ValueError('Use only source and limit')
        limit = args.get('limit', 100)
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError('limit must be 1..500')
        source = args.get('source')
        if source is not None and (not isinstance(source, str) or not ID.fullmatch(source)):
            raise ValueError('Invalid source')
        if name == 'onscan_sources':
            sql = 'SELECT source,metric,unit,kind,simulation,COUNT(*) AS samples,MAX(time) AS latest FROM readings'
            suffix = ' GROUP BY source,metric,unit,kind,simulation ORDER BY latest DESC LIMIT ?'
        elif name == 'onscan_readings':
            sql = 'SELECT * FROM readings'
            suffix = ' ORDER BY time DESC,id LIMIT ?'
        elif name == 'onscan_alerts':
            sql = 'SELECT readings.*,alerts.rule_id FROM readings JOIN alerts ON readings.id=alerts.reading_id'
            suffix = ' ORDER BY time DESC,id LIMIT ?'
        else:
            raise ValueError('Unknown tool')
        params = []
        if source is not None:
            sql += ' WHERE source=?'
            params.append(source)
        return [dict(r) for r in self.db.execute(sql + suffix, (*params, limit))]


def rpc(store, request):
    if not isinstance(request, dict) or request.get('jsonrpc') != '2.0' or not isinstance(request.get('method'), str):
        return {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32600, 'message': 'Invalid request'}}
    if 'id' not in request:
        return None
    response = {'jsonrpc': '2.0', 'id': request['id']}
    method = request['method']
    if method == 'initialize':
        result = {'protocolVersion': '2025-11-25', 'capabilities': {'tools': {}},
                  'serverInfo': {'name': 'onscan-observatory', 'version': '0.1.0'}}
    elif method == 'ping':
        result = {}
    elif method == 'tools/list':
        result = {'tools': [{'name': name, 'description': description,
                  'inputSchema': {'type': 'object', 'properties': {'source': {'type': 'string'},
                    'limit': {'type': 'integer', 'minimum': 1, 'maximum': 500}}, 'additionalProperties': False},
                  'annotations': {'readOnlyHint': True, 'destructiveHint': False, 'openWorldHint': False}}
                  for name, description in [('onscan_sources', 'List local sources and metrics'),
                    ('onscan_readings', 'Read recent observations; simulation is explicit'),
                    ('onscan_alerts', 'Read threshold alerts; not medical or safety diagnoses')]]}
    elif method == 'tools/call':
        try:
            params = request.get('params', {})
            if not isinstance(params, dict):
                raise ValueError('Invalid parameters')
            data = store.read(params.get('name'), params.get('arguments', {}))
            result = {'content': [{'type': 'text', 'text': json.dumps(data)}], 'isError': False}
        except (ValueError, TypeError) as e:
            result = {'content': [{'type': 'text', 'text': str(e)}], 'isError': True}
    else:
        response['error'] = {'code': -32601, 'message': 'Method not found'}
        return response
    response['result'] = result
    return response


def report(store, destination):
    rows = store.read('onscan_readings', {'limit': 500})
    groups = {}
    for row in reversed(rows):
        groups.setdefault((row['source'], row['metric'], row['unit'], row['simulation']), []).append(row)
    cards = []
    for (source, metric, unit, simulation), points in groups.items():
        values = [p['value'] for p in points]
        lo, hi = min(values), max(values)
        coords = ' '.join(f'{i * 600 / max(len(points)-1,1):.1f},{140-(v-lo)*120/max(hi-lo,0.001):.1f}' for i,v in enumerate(values))
        esc = html.escape
        cards.append(f'<article><small>{"SIMULATION" if simulation else "RECORDED"} · {esc(source)}</small><h2>{esc(metric)}</h2><strong>{values[-1]:g} <small>{esc(unit)}</small></strong><svg viewBox="0 0 600 170" role="img" aria-label="{esc(metric)} sample trend"><polyline points="{coords}" fill="none" stroke="#78ecc3" stroke-width="3"/></svg><p>{len(points)} samples · min {lo:g} / max {hi:g}</p><small>Latest {esc(points[-1]["time"])}</small></article>')
    alerts = store.read('onscan_alerts', {'limit': 500})
    document = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ONScan Observatory</title><style>body{margin:0;background:#0d181e;color:#eef6f4;font:16px/1.6 system-ui}main{max-width:1180px;margin:auto;padding:56px 24px}h1{font-size:clamp(36px,6vw,72px);line-height:1.08;letter-spacing:-.05em;max-width:750px}p,small{color:#b7cbc7}section{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,310px),1fr));gap:20px}article{padding:28px;border:1px solid #35454d;border-radius:20px;background:#14252d;min-width:0;overflow-wrap:anywhere}h2{font-size:24px}strong{font-size:38px}svg{width:100%;margin-top:24px}footer{margin-top:32px}</style><main><p>ONSCAN / OBSERVATORY</p><h1>See your signals.<br>Understand the change.</h1><p>Local sensor history, threshold alerts and read-only agent access.</p>'''
    document += f'<p>{len(rows)} recent readings · {len(alerts)} recent threshold alerts</p><section>' + ''.join(cards) + '</section><footer>Static snapshot · Trends are ordered samples, not evenly timed intervals. Threshold alerts require human review. No inference service or hardware control is enabled.</footer></main></html>'
    Path(destination).write_text(document, encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', default='onscan.sqlite')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('mcp')
    load = commands.add_parser('ingest'); load.add_argument('jsonl')
    rule = commands.add_parser('rule')
    for field in ('id', 'source', 'metric', 'unit'): rule.add_argument(field)
    rule.add_argument('above', type=float)
    render = commands.add_parser('report'); render.add_argument('html')
    args = parser.parse_args(); store = Observatory(args.db)
    if args.command == 'ingest':
        with open(args.jsonl, encoding='utf-8') as source:
            for line in source:
                if len(line) > 65536: raise ValueError('Reading exceeds 64KB')
                if line.strip(): store.ingest(json.loads(line))
    elif args.command == 'rule': store.rule(args.id,args.source,args.metric,args.unit,args.above)
    elif args.command == 'report': report(store,args.html)
    else:
        for line in sys.stdin:
            try:
                if len(line) > 65536: raise ValueError('Request too large')
                response = rpc(store,json.loads(line))
            except (ValueError,TypeError):
                response = {'jsonrpc':'2.0','id':None,'error':{'code':-32700,'message':'Parse error'}}
            if response is not None: print(json.dumps(response),flush=True)


if __name__ == '__main__': main()
