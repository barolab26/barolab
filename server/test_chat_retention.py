"""Lossless telemetry rotation without importing or starting live chat workers."""
import ast
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


class ChatRetentionTests(unittest.TestCase):
    def test_old_transport_events_are_archived_but_conversations_remain(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            tree=ast.parse((Path(__file__).parent/'chat_room.py').read_text())
            node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='compact_room_telemetry')
            scope=dict(CHATS_DIR=root,json=json,hashlib=hashlib,os=os)
            exec(compile(ast.Module(body=[node],type_ignores=[]),'<retention>','exec'),scope)
            messages=[{'id':str(i),'eventType':'crew_work_event','phase':'completed'} for i in range(400)]
            user={'id':'human','who':'user','text':'Keep my conversation'}
            messages.insert(4,user)
            room={'messages':messages,'sid':42}
            scope['compact_room_telemetry'](room,keep=20)
            self.assertIn(user,room['messages']);self.assertEqual(room['sid'],42)
            self.assertEqual(len(room['messages']),21)
            archived=list((root/'work-event-history').glob('*.json'))
            history=json.loads(archived[0].read_text())['messages']
            self.assertEqual(len(history),380)
            self.assertEqual({r['id'] for r in history+room['messages']},{r['id'] for r in messages})
            scope['compact_room_telemetry'](room,keep=20)
            self.assertEqual(len(list((root/'work-event-history').glob('*.json'))),1)
            room={'messages':messages}
            with patch.object(Path,'write_bytes',side_effect=OSError('Disk full')):
                # Different limit yields a new archive and forces its durable write.
                with self.assertRaises(OSError):scope['compact_room_telemetry'](room,keep=10)
            self.assertEqual(room['messages'],messages)


if __name__=='__main__':unittest.main()
