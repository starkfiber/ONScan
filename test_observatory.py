import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from observatory import Observatory, rpc, report


class ObservatoryTest(unittest.TestCase):
    def setUp(self):
        self.store = Observatory(':memory:')
        self.event = dict(id='one',source='thermal-1',metric='surface',unit='C',
                          time='2026-11-11T10:00:00+08:00',value=31.2,kind='thermal',simulation=True)

    def test_idempotence_and_conflicting_replay(self):
        self.assertTrue(self.store.ingest(self.event))
        self.assertFalse(self.store.ingest(self.event))
        with self.assertRaises(ValueError): self.store.ingest(dict(self.event,value=33))
        self.assertEqual(len(self.store.read('onscan_readings',{})),1)

    def test_alert_unit_and_source_isolation(self):
        self.store.rule('hot','thermal-1','surface','C',30)
        self.store.ingest(self.event)
        self.store.ingest(dict(self.event,id='other',source='thermal-2'))
        self.store.ingest(dict(self.event,id='fahrenheit',unit='F'))
        self.assertEqual(len(self.store.read('onscan_alerts',{})),1)

    def test_invalid_values_rejected(self):
        for changes in [dict(value=math.nan),dict(value=True),dict(time='2026-11-11'),
                        dict(source='<script>'),dict(simulation='false'),dict(kind='unknown')]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.store.ingest(dict(self.event,**changes))
        self.assertEqual(self.store.read('onscan_sources',{}),[])

    def test_limits_and_query_injection(self):
        for args in [{'limit':501},{'limit':True},{'source':"' OR 1=1"},{'sql':'DELETE'}]:
            with self.assertRaises(ValueError): self.store.read('onscan_readings',args)

    def test_normalizes_time_and_keeps_simulation(self):
        self.store.ingest(self.event)
        row=self.store.read('onscan_readings',{})[0]
        self.assertEqual(row['time'],'2026-11-11T02:00:00+00:00')
        self.assertEqual(row['simulation'],1)

    def test_mcp_read_only(self):
        listed=rpc(self.store,dict(jsonrpc='2.0',id=1,method='tools/list'))
        self.assertEqual(len(listed['result']['tools']),3)
        denied=rpc(self.store,dict(jsonrpc='2.0',id=2,method='tools/call',params={'name':'delete'}))
        self.assertTrue(denied['result']['isError'])
        self.assertIsNone(rpc(self.store,dict(jsonrpc='2.0',method='notifications/initialized')))

    def test_subprocess_handshake(self):
        with tempfile.TemporaryDirectory() as directory:
            messages=[dict(jsonrpc='2.0',id=1,method='initialize',params={}),
                      dict(jsonrpc='2.0',method='notifications/initialized'),
                      dict(jsonrpc='2.0',id=2,method='tools/call',params={'name':'onscan_sources','arguments':{}})]
            process=subprocess.run([sys.executable,str(Path(__file__).with_name('observatory.py')),
                                    '--db',str(Path(directory)/'test.sqlite'),'mcp'],
                                   input='\n'.join(map(json.dumps,messages))+'\n',text=True,capture_output=True,check=True)
            replies=[json.loads(line) for line in process.stdout.splitlines()]
            self.assertEqual([x['id'] for x in replies],[1,2])
            self.assertFalse(replies[1]['result']['isError'])

    def test_report_labels_simulation(self):
        self.store.ingest(self.event)
        with tempfile.TemporaryDirectory() as directory:
            dest=Path(directory)/'report.html';report(self.store,dest)
            self.assertIn('SIMULATION',dest.read_text())
            self.assertIn('Static snapshot',dest.read_text())


if __name__=='__main__': unittest.main()
