"""Lossless telemetry rotation without importing or starting live chat workers."""
import ast
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock
from concurrent.futures import ThreadPoolExecutor
import threading
from fastapi import HTTPException
from server.dashboard_cache import ReadCache

class ChatRetentionTests(unittest.TestCase):

    def test_busy_work_event_returns_immediately_without_waiting_for_room_lock(self):
        tree = ast.parse((Path(__file__).resolve().parents[2] / 'agents/chat_room.py').read_text())
        node = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'api_receive_work_event'))
        node.decorator_list = []
        lock = threading.RLock()
        receive = Mock()
        scope = dict(Dict=dict, Any=object, _ROOM_LOCK=lock, HTTPException=HTTPException, receive_work_event=receive)
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<admission>', 'exec'), scope)
        with ThreadPoolExecutor(max_workers=1) as executor:
            lock.acquire()
            future = executor.submit(scope['api_receive_work_event'], {'event': 'retained by producer'})
            try:
                with self.assertRaises(HTTPException) as error:
                    future.result(0.5)
                self.assertEqual(error.exception.status_code, 503)
                receive.assert_not_called()
            finally:
                lock.release()

    def test_expensive_read_routes_use_single_flight_caches(self):
        tree = ast.parse((Path(__file__).resolve().parents[2] / 'agents/chat_room.py').read_text())
        for name, cache_name, builder in [('get_chat_room', '_ROOM_READ_CACHE', '_build_chat_room'), ('get_crew_live_workstream_status', '_CREW_READ_CACHE', '_build_crew_live_workstream_status'), ('sync_and_broadcast_pipeline_workstream', '_WORKSTREAM_SYNC_CACHE', '_sync_pipeline_workstream')]:
            node = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name))
            node.returns = None
            node.decorator_list = []
            scope = dict(Dict=dict, Any=object, List=list, HTTPException=HTTPException)
            cache = Mock()
            cache.get.return_value = 'cached projection'
            scope.update({cache_name: cache, builder: Mock()})
            exec(compile(ast.Module(body=[node], type_ignores=[]), '<cached-route>', 'exec'), scope)
            self.assertEqual(scope[name](), 'cached projection')
            self.assertIs(cache.get.call_args.args[1], scope[builder])

    def test_one_settings_read_per_employee_per_room_snapshot(self):
        tree = ast.parse((Path(__file__).resolve().parents[2] / 'agents/chat_room.py').read_text())
        node = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_enrich_legacy_message'))
        reads = []

        def brain(who):
            reads.append(who)
            return {'model': 'current-assigned-model'}
        scope = dict(Dict=dict, Any=object, List=list, AGENT_MAP={'jarvis': {}, 'publi': {}}, _extract_mentioned_slugs=lambda text: [], _get_agent_brain_safe=brain)
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<snapshot>', 'exec'), scope)
        messages = [{'id': str(i), 'who': 'jarvis' if i % 2 else 'publi', 'text': 'saved conversation', 'taskTracker': {}} for i in range(100)]
        brains = {}
        for index, row in enumerate(messages):
            scope['_enrich_legacy_message'](row, index, messages, brains)
        self.assertEqual(sorted(reads), ['jarvis', 'publi'])
        self.assertTrue(all((row['brain']['model'] == 'current-assigned-model' for row in messages)))

    def test_old_transport_events_are_archived_but_conversations_remain(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            tree = ast.parse((Path(__file__).resolve().parents[2] / 'agents/chat_room.py').read_text())
            node = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'compact_room_telemetry'))
            scope = dict(CHATS_DIR=root, json=json, hashlib=hashlib, os=os)
            exec(compile(ast.Module(body=[node], type_ignores=[]), '<retention>', 'exec'), scope)
            messages = [{'id': str(i), 'eventType': 'crew_work_event', 'phase': 'completed'} for i in range(400)]
            user = {'id': 'human', 'who': 'user', 'text': 'Keep my conversation'}
            messages.insert(4, user)
            room = {'messages': messages, 'sid': 42}
            scope['compact_room_telemetry'](room, keep=20)
            self.assertIn(user, room['messages'])
            self.assertEqual(room['sid'], 42)
            self.assertEqual(len(room['messages']), 21)
            archived = list((root / 'work-event-history').glob('*.json'))
            history = json.loads(archived[0].read_text())['messages']
            self.assertEqual(len(history), 380)
            self.assertEqual({r['id'] for r in history + room['messages']}, {r['id'] for r in messages})
            scope['compact_room_telemetry'](room, keep=20)
            self.assertEqual(len(list((root / 'work-event-history').glob('*.json'))), 1)
            room = {'messages': messages}
            with patch.object(Path, 'write_bytes', side_effect=OSError('Disk full')):
                with self.assertRaises(OSError):
                    scope['compact_room_telemetry'](room, keep=10)
            self.assertEqual(room['messages'], messages)
            quiet=[{'id':'patch-completed','who':'patch','eventType':'crew_work_event','phase':'completed','ts':1},
                   {'id':'patch-latest','who':'patch','eventType':'crew_work_event','phase':'progress','ts':2}]
            busy=[{'id':'publi-'+str(i),'who':'publi','eventType':'crew_work_event','phase':'completed','ts':i+3} for i in range(1000)]
            room={'messages':quiet+busy}
            scope['compact_room_telemetry'](room,keep=20)
            self.assertEqual(len(room['messages']),22)
            self.assertTrue({'patch-completed','patch-latest'}.issubset({row['id'] for row in room['messages']}))
            scope['compact_room_telemetry'](room,keep=20)
            self.assertEqual(len(room['messages']),22)

if __name__ == '__main__':
    unittest.main()
