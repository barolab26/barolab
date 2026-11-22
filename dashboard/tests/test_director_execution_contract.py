import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agents import crew_reasoning as crew
from common import project_autonomy as autonomy, operating_plan as operating
from common.collection_observability import write, load
from server import agent_tools as tools


class DirectorExecutionContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / 'dashboard/data'
        self.data.mkdir(parents=True)
        self.queue = self.data / 'publication-conferences'
        self.queue.mkdir(parents=True)
        self.goals_dir = self.data / 'crew-goals'
        self.goals_dir.mkdir(parents=True)
        self.staff_dir = self.data / 'staff-requests'
        self.staff_dir.mkdir(parents=True)
        self.config = self.data / 'project-autonomy.json'
        write(self.config, {'enabled': True, 'projects': ['cf_blog', 'naver_blog']})
        self.state_path = self.data / 'operating-plan.json'
        write(self.state_path, {'publications': {}, 'accounts': {}})
        self.cf_sched_path = self.data / 'cf/daily_schedule.json'
        write(self.cf_sched_path, {'date': '2026-11-07', 'items': []})
        write(self.data / 'daily_schedule.json', {'operatingMode': 'adaptive', 'naver': {'soul5373': {'slots': ['10:30']}}})
        naver_dir = self.data / 'naver'
        naver_dir.mkdir(parents=True)
        write(naver_dir / 'automation-journal.json', {'attempts': []})
        write(naver_dir / 'public-verification.json', {'evidence': []})

        for target, attr, val in [
            (autonomy, 'ROOT', self.root),
            (autonomy, 'CONFIG', self.config),
            (operating, 'ROOT', self.root),
            (operating, 'DATA', self.data),
            (operating, 'STATE', self.state_path),
            (crew, 'ROOT', self.root),
            (crew, 'GOALS', self.goals_dir),
            (tools, 'STAFF_REQUEST_DIR', self.staff_dir),
        ]:
            p = patch.object(target, attr, val)
            p.start()
            self.addCleanup(p.stop)

        event_patch = patch('common.crew_chat_bridge.emit_work_event', return_value={'id': 'isolated-test-event'})
        event_patch.start()
        self.addCleanup(event_patch.stop)
        agenda_patch = patch('common.work_agenda.enabled', return_value=False)
        agenda_patch.start()
        self.addCleanup(agenda_patch.stop)

        q_patch = patch('common.conference_dispatch.QUEUE', self.queue)
        q_patch.start()
        self.addCleanup(q_patch.stop)

    def test_read_agent_status_works_without_execution_permission_and_handles_project_status(self):
        row = {
            'id': 'goal-read-test',
            'actor': 'jarvis',
            'status': 'ready',
            'origin': 'evidence-review',
            'permissions': {'execute': False, 'repair': False, 'projects': ['naver_blog']},
            'observations': [],
            'decisions': 0
        }
        action = {'agent': 'trace', 'tool': 'read_agent_status', 'args': {'project': 'naver_blog'}}
        with patch('server.project_health.observed_projects', return_value=[{'id': 'naver_blog', 'status': 'ok'}]), \
             patch('common.recovery_evidence.failure_targets', return_value=[]):
            result = crew.tool_call(row, 'dispatch', action)
            self.assertTrue(result['ok'])
            self.assertEqual(result['status'], 'observed')
            self.assertEqual(result['project'], 'naver_blog')
            self.assertNotIn('operatingActions', row)

            status_res = crew.tool_call(row, 'project_status', {'project': 'naver_blog'})
            self.assertTrue(status_res['ok'])
            self.assertEqual(status_res['status'], 'observed')
            self.assertEqual(status_res['project'], 'naver_blog')

    def test_read_agent_status_and_project_status_reject_unauthorized_scope_and_missing_project(self):
        row = {
            'id': 'goal-scope-test',
            'actor': 'jarvis',
            'status': 'ready',
            'origin': 'evidence-review',
            'permissions': {'execute': False, 'repair': False, 'projects': ['naver_blog']},
            'observations': [],
            'decisions': 0
        }
        unauthorized_action = {'agent': 'trace', 'tool': 'read_agent_status', 'args': {'project': 'cf_blog'}}
        with self.assertRaisesRegex(ValueError, 'CEO project scope'):
            crew.tool_call(row, 'dispatch', unauthorized_action)

        empty_args_action = {'agent': 'trace', 'tool': 'read_agent_status', 'args': {}}
        with self.assertRaisesRegex(ValueError, 'Project parameter required'):
            crew.tool_call(row, 'dispatch', empty_args_action)

        with self.assertRaisesRegex(ValueError, 'CEO project scope'):
            crew.tool_call(row, 'project_status', {'project': 'cf_blog'})

        with self.assertRaisesRegex(ValueError, 'Project parameter required'):
            crew.tool_call(row, 'project_status', {})

        mutating_action = {'agent': 'publi', 'tool': 'run_project_cycle', 'args': {'project': 'naver_blog'}}
        with self.assertRaisesRegex(ValueError, 'Evidence review permits read-only evidence tools only'):
            crew.tool_call(row, 'dispatch', mutating_action)

    def test_direct_execute_agent_tool_rejects_unauthorized_actor_and_missing_project(self):
        with self.assertRaisesRegex(ValueError, 'Tool is assigned to publi'):
            tools.execute_agent_tool('trace', 'run_project_cycle', project='naver_blog')

        with self.assertRaisesRegex(ValueError, 'Invalid recipient'):
            tools.execute_agent_tool('unauthorized_worker', 'run_project_cycle', project='naver_blog')

        with self.assertRaisesRegex(ValueError, 'Tool not authorized for autonomous delegation'):
            tools.execute_agent_tool('publi', 'run_project_cycle')

        with self.assertRaisesRegex(ValueError, 'Invalid allocation identity'):
            tools.execute_agent_tool('publi', 'run_project_cycle', project='naver_blog', allocation_id='invalid-id')

    def test_exact_allocation_propagates_and_preserves_cf_prepare_action(self):
        alloc_id = 'a' * 64
        write(self.state_path, {
            'publications': {
                alloc_id: {
                    'id': alloc_id,
                    'project': 'cf_blog',
                    'account': 'soulnote.kr',
                    'day': '2026-11-07',
                    'slot': '10:00',
                    'status': 'allocated',
                }
            }
        })
        cf_prepare_choice = {'action': 'cf-prepare', 'account': 'soulnote.kr', 'date': '2026-11-07', 'slot': '10:00'}

        with patch('common.work_agenda.enabled', return_value=False), \
             patch('common.conference_dispatch.concrete_requests', return_value=[cf_prepare_choice]), \
             patch('common.conference_dispatch.request', return_value={'agendaId': 'b' * 64, 'requestedAt': 12345.0}) as req_mock:
            result = autonomy.run_project_cycle('cf_blog', allocation_id=alloc_id)

        req_mock.assert_called_once_with('parameters', cf_prepare_choice, one=True, automatic=False)
        self.assertTrue(result['ok'])
        self.assertEqual(result['status'], 'awaiting_completion')
        self.assertEqual(result['allocationId'], alloc_id)
        self.assertEqual(result['conferenceAgendaId'], 'b' * 64)
        self.assertEqual(result['conferenceRequestedAt'], 12345.0)
        self.assertFalse(result['publicationVerified'])

    def test_cf_completed_preparation_advances_to_publication_when_eligible(self):
        alloc_id = '9' * 64
        write(self.state_path, {
            'publications': {
                alloc_id: {
                    'id': alloc_id,
                    'project': 'cf_blog',
                    'account': 'soulnote.kr',
                    'day': '2026-11-07',
                    'slot': '10:00',
                    'status': 'allocated',
                }
            }
        })
        prep_args = {'action': 'cf-prepare', 'account': 'soulnote.kr', 'date': '2026-11-07', 'slot': '10:00'}
        prep_key = hashlib.sha256(json.dumps(['parameters', prep_args], sort_keys=True).encode()).hexdigest()
        write(self.queue / (prep_key + '.json'), {
            'agendaId': prep_key,
            'kind': 'parameters',
            'arguments': prep_args,
            'status': 'completed',
            'requestedAt': 555.0,
            'preparation': {'preparationVerified': True},
            'outcomes': []
        })
        pub_choice = {'action': 'cf', 'account': 'soulnote.kr', 'date': '2026-11-07', 'slot': '10:00'}

        with patch('common.work_agenda.enabled', return_value=False), \
             patch('common.conference_dispatch.concrete_requests', return_value=[pub_choice]), \
             patch('common.conference_dispatch.request', return_value={'agendaId': 'c' * 64, 'requestedAt': 666.0}) as req_mock:
            result = autonomy.run_project_cycle('cf_blog', allocation_id=alloc_id)

        req_mock.assert_called_once_with('parameters', pub_choice, one=True, automatic=False)
        self.assertTrue(result['ok'])
        self.assertEqual(result['status'], 'awaiting_completion')
        self.assertEqual(result['conferenceAgendaId'], 'c' * 64)
        self.assertEqual(result['conferenceRequestedAt'], 666.0)
        self.assertEqual(result['allocationId'], alloc_id)

    def test_manager_dispatch_phase_advancement_and_duplicate_prevention(self):
        alloc_id = '8' * 64
        write(self.state_path, {
            'publications': {
                alloc_id: {
                    'id': alloc_id,
                    'project': 'cf_blog',
                    'account': 'soulnote.kr',
                    'day': '2026-11-07',
                    'slot': '11:00',
                    'status': 'allocated',
                }
            }
        })
        row = {
            'id': '9' * 64,
            'actor': 'jarvis',
            'status': 'ready',
            'origin': 'company-manager',
            'permissions': {'execute': True, 'repair': False, 'projects': ['cf_blog']},
            'observations': [],
            'decisions': 0
        }
        action = {'agent': 'publi', 'tool': 'run_project_cycle', 'args': {'project': 'cf_blog', 'allocation_id': alloc_id}}
        prep_args = {'action': 'cf-prepare', 'account': 'soulnote.kr', 'date': '2026-11-07', 'slot': '11:00'}
        prep_key = hashlib.sha256(json.dumps(['parameters', prep_args], sort_keys=True).encode()).hexdigest()
        write(self.queue / (prep_key + '.json'), {
            'agendaId': prep_key,
            'kind': 'parameters',
            'arguments': prep_args,
            'status': 'completed',
            'requestedAt': 111.0,
            'preparation': {'preparationVerified': True},
            'outcomes': []
        })

        with patch('common.work_agenda.enabled', return_value=False), \
             patch('common.conference_dispatch.concrete_requests', return_value=[]):
            prep_disp = crew.tool_call(row, 'dispatch', action)
            self.assertEqual(prep_disp['status'], 'queued')

            repeated = crew.tool_call(row, 'dispatch', action)
            self.assertEqual(repeated['requestId'], prep_disp['requestId'])
            receipt_path = self.staff_dir / (hashlib.sha256(prep_disp['requestId'].encode()).hexdigest() + '.json')
            receipt = load(receipt_path)
            receipt['status'] = 'completed'
            write(receipt_path, receipt)
            with self.assertRaisesRegex(ValueError, 'Same action already executed'):
                crew.tool_call(row, 'dispatch', action)

        pub_choice = {'action': 'cf', 'account': 'soulnote.kr', 'date': '2026-11-07', 'slot': '11:00'}
        with patch('common.work_agenda.enabled', return_value=False), \
             patch('common.conference_dispatch.concrete_requests', return_value=[pub_choice]):
            pub_disp = crew.tool_call(row, 'dispatch', action)
            self.assertEqual(pub_disp['status'], 'queued')
            self.assertNotEqual(pub_disp['requestId'], prep_disp['requestId'])

            repeated = crew.tool_call(row, 'dispatch', action)
            self.assertEqual(repeated['requestId'], pub_disp['requestId'])

    def test_allocation_missing_mismatched_and_waiting_predecessor_return_actionable_evidence_never_substitute(self):
        missing_res = autonomy.run_project_cycle('cf_blog', allocation_id='f' * 64)
        self.assertFalse(missing_res['ok'])
        self.assertEqual(missing_res['status'], 'held')
        self.assertEqual(missing_res['reason'], 'allocation_not_found')
        self.assertEqual(missing_res['allocationId'], 'f' * 64)

        alloc_id = 'c' * 64
        write(self.state_path, {
            'publications': {
                alloc_id: {
                    'id': alloc_id,
                    'project': 'naver_blog',
                    'account': 'soul5373',
                    'day': '2026-11-07',
                    'slot': '11:00',
                    'status': 'allocated',
                }
            }
        })
        mismatch_res = autonomy.run_project_cycle('cf_blog', allocation_id=alloc_id)
        self.assertFalse(mismatch_res['ok'])
        self.assertEqual(mismatch_res['status'], 'held')
        self.assertEqual(mismatch_res['reason'], 'allocation_project_mismatch')
        self.assertEqual(mismatch_res['allocationId'], alloc_id)

        cf_alloc_id = 'd' * 64
        write(self.state_path, {
            'publications': {
                cf_alloc_id: {
                    'id': cf_alloc_id,
                    'project': 'cf_blog',
                    'account': 'soulnote.kr',
                    'day': '2026-11-07',
                    'slot': '14:00',
                    'status': 'allocated',
                }
            }
        })
        write(self.cf_sched_path, {
            'date': '2026-11-07',
            'items': [{'domain': 'soulnote.kr', 'allocationId': 'other' + '0' * 59, 'status': 'queued'}]
        })
        dep_res = autonomy.run_project_cycle('cf_blog', allocation_id=cf_alloc_id)
        self.assertFalse(dep_res['ok'])
        self.assertEqual(dep_res['status'], 'waiting_existing_work')
        self.assertEqual(dep_res['dependency'], 'soulnote.kr')
        self.assertEqual(dep_res['dependencyStatus'], 'queued')
        self.assertEqual(dep_res['allocationId'], cf_alloc_id)

        write(self.cf_sched_path, {'date': '2026-11-07', 'items': []})
        other_choice = {'action': 'cf-prepare', 'account': 'othernote.kr', 'date': '2026-11-07', 'slot': '15:00'}
        with patch('common.work_agenda.enabled', return_value=False), \
             patch('common.conference_dispatch.concrete_requests', return_value=[other_choice]), \
             patch('common.conference_dispatch.request') as req_mock:
            ineligible_res = autonomy.run_project_cycle('cf_blog', allocation_id=cf_alloc_id)
        req_mock.assert_not_called()
        self.assertFalse(ineligible_res['ok'])
        self.assertEqual(ineligible_res['status'], 'held')
        self.assertEqual(ineligible_res['reason'], 'allocation_slot_not_currently_eligible')
        self.assertEqual(ineligible_res['allocationId'], cf_alloc_id)

    def test_existing_receipt_reuse_queued_running_and_no_replay_of_failed_or_unknown(self):
        alloc_id = 'e' * 64
        write(self.state_path, {
            'publications': {
                alloc_id: {
                    'id': alloc_id,
                    'project': 'naver_blog',
                    'account': 'soul5373',
                    'day': '2026-11-07',
                    'slot': '16:00',
                    'status': 'allocated',
                }
            }
        })
        native_args = {'action': 'naver', 'account': 'soul5373', 'date': '2026-11-07', 'slot': '16:00'}
        receipt_key = hashlib.sha256(json.dumps(['parameters', native_args], sort_keys=True).encode()).hexdigest()
        receipt_path = self.queue / (receipt_key + '.json')

        running_doc = {
            'agendaId': receipt_key,
            'kind': 'parameters',
            'arguments': native_args,
            'status': 'running',
            'requestedAt': 777.0,
            'attempts': 1
        }
        write(receipt_path, running_doc)

        with patch('common.work_agenda.enabled', return_value=False), \
             patch('common.conference_dispatch.request') as req_mock:
            reused_res = autonomy.run_project_cycle('naver_blog', allocation_id=alloc_id)
        req_mock.assert_not_called()
        self.assertTrue(reused_res['ok'])
        self.assertEqual(reused_res['status'], 'awaiting_completion')
        self.assertEqual(reused_res['conferenceAgendaId'], receipt_key)
        self.assertEqual(reused_res['conferenceRequestedAt'], 777.0)
        self.assertEqual(reused_res['allocationId'], alloc_id)

        failed_doc = {
            'agendaId': receipt_key,
            'kind': 'parameters',
            'arguments': native_args,
            'status': 'failed',
            'failureReason': 'browser_crashed',
            'requestedAt': 777.0,
            'attempts': 2
        }
        write(receipt_path, failed_doc)
        with patch('common.work_agenda.enabled', return_value=False), \
             patch('common.conference_dispatch.request') as req_mock:
            failed_res = autonomy.run_project_cycle('naver_blog', allocation_id=alloc_id)
        req_mock.assert_not_called()
        self.assertFalse(failed_res['ok'])
        self.assertEqual(failed_res['status'], 'held')
        self.assertEqual(failed_res['reason'], 'browser_crashed')
        self.assertEqual(failed_res['conferenceRequestedAt'], 777.0)
        self.assertEqual(failed_res['attempts'], 2)
        self.assertEqual(failed_res['allocationId'], alloc_id)

    def test_existing_completed_receipt_resolves_via_terminal_result_and_preparation_is_not_publication(self):
        alloc_id = '1' * 64
        write(self.state_path, {
            'publications': {
                alloc_id: {
                    'id': alloc_id,
                    'project': 'cf_blog',
                    'account': 'soulnote.kr',
                    'day': '2026-11-07',
                    'slot': '18:00',
                    'status': 'allocated',
                }
            }
        })
        native_args = {'action': 'cf-prepare', 'account': 'soulnote.kr', 'date': '2026-11-07', 'slot': '18:00'}
        receipt_key = hashlib.sha256(json.dumps(['parameters', native_args], sort_keys=True).encode()).hexdigest()
        receipt_path = self.queue / (receipt_key + '.json')
        write(receipt_path, {
            'agendaId': receipt_key,
            'kind': 'parameters',
            'arguments': native_args,
            'status': 'completed',
            'requestedAt': 888.0,
            'preparation': {'preparationVerified': True},
            'outcomes': []
        })

        with patch('common.work_agenda.enabled', return_value=False), \
             patch('common.conference_dispatch.concrete_requests', return_value=[]), \
             patch('common.conference_dispatch.request') as req_mock:
            result = autonomy.run_project_cycle('cf_blog', allocation_id=alloc_id)
        req_mock.assert_not_called()
        self.assertTrue(result['ok'])
        self.assertEqual(result['status'], 'completed')
        self.assertTrue(result['preparationVerified'])
        self.assertFalse(result['publicationVerified'])
        self.assertFalse(result['reservationVerified'])
        self.assertEqual(result['allocationId'], alloc_id)
        self.assertEqual(result['conferenceAgendaId'], receipt_key)
        self.assertEqual(result['conferenceRequestedAt'], 888.0)
        self.assertEqual(result['nextCondition'], 'waiting_cf_publication_slot_eligibility')

    def test_terminal_result_rejects_mismatched_receipt_and_no_work_cannot_complete_allocation(self):
        alloc_id = '2' * 64
        write(self.state_path, {
            'publications': {
                alloc_id: {
                    'id': alloc_id,
                    'project': 'naver_blog',
                    'account': 'soul5373',
                    'day': '2026-11-07',
                    'slot': '19:00',
                    'status': 'allocated',
                }
            }
        })
        diff_args = {'action': 'naver', 'account': 'other_acc', 'date': '2026-11-07', 'slot': '19:00'}
        diff_key = hashlib.sha256(json.dumps(['parameters', diff_args], sort_keys=True).encode()).hexdigest()
        diff_path = self.queue / (diff_key + '.json')
        write(diff_path, {
            'agendaId': diff_key,
            'kind': 'parameters',
            'arguments': diff_args,
            'status': 'completed',
            'requestedAt': 999.0,
            'outcomes': [{'publicationVerified': True}]
        })

        mismatch_term, _ = autonomy.terminal_result({
            'project': 'naver_blog',
            'allocationId': alloc_id,
            'conferenceAgendaId': diff_key,
            'conferenceRequestedAt': 999.0
        })
        self.assertFalse(mismatch_term['ok'])
        self.assertEqual(mismatch_term['status'], 'unknown')
        self.assertEqual(mismatch_term['reason'], 'allocation_receipt_target_mismatch')
        self.assertFalse(mismatch_term['publicationVerified'])

        match_args = {'action': 'naver', 'account': 'soul5373', 'date': '2026-11-07', 'slot': '19:00'}
        match_key = hashlib.sha256(json.dumps(['parameters', match_args], sort_keys=True).encode()).hexdigest()
        match_path = self.queue / (match_key + '.json')
        write(match_path, {
            'agendaId': match_key,
            'kind': 'parameters',
            'arguments': match_args,
            'status': 'completed',
            'requestedAt': 999.0,
            'outcomes': []
        })

        nowork_term, _ = autonomy.terminal_result({
            'project': 'naver_blog',
            'allocationId': alloc_id,
            'conferenceAgendaId': match_key,
            'conferenceRequestedAt': 999.0
        })
        self.assertFalse(nowork_term['ok'])
        self.assertEqual(nowork_term['status'], 'no_work')
        self.assertEqual(nowork_term['reason'], 'allocation_unfulfilled_no_work')
        self.assertFalse(nowork_term['publicationVerified'])
        self.assertFalse(nowork_term['reservationVerified'])

    def test_terminal_result_preserves_attempts_and_requested_at_on_failure(self):
        alloc_id = '7' * 64
        write(self.state_path, {
            'publications': {
                alloc_id: {
                    'id': alloc_id,
                    'project': 'naver_blog',
                    'account': 'soul5373',
                    'day': '2026-11-07',
                    'slot': '20:00',
                    'status': 'allocated',
                }
            }
        })
        native_args = {'action': 'naver', 'account': 'soul5373', 'date': '2026-11-07', 'slot': '20:00'}
        receipt_key = hashlib.sha256(json.dumps(['parameters', native_args], sort_keys=True).encode()).hexdigest()
        receipt_path = self.queue / (receipt_key + '.json')
        write(receipt_path, {
            'agendaId': receipt_key,
            'kind': 'parameters',
            'arguments': native_args,
            'status': 'failed',
            'failureReason': 'session_expired',
            'requestedAt': 4321.0,
            'attempts': 3
        })

        term, _ = autonomy.terminal_result({
            'project': 'naver_blog',
            'allocationId': alloc_id,
            'conferenceAgendaId': receipt_key,
            'conferenceRequestedAt': 4321.0
        })
        self.assertFalse(term['ok'])
        self.assertEqual(term['status'], 'failed')
        self.assertEqual(term['conferenceRequestedAt'], 4321.0)
        self.assertEqual(term['attempts'], 3)
        self.assertEqual(term['reason'], 'session_expired')
        self.assertEqual(term['allocationId'], alloc_id)

    def test_cf_publication_receipt_takes_precedence_over_preparation_receipt(self):
        alloc_id = '3' * 64
        write(self.state_path, {
            'publications': {
                alloc_id: {
                    'id': alloc_id,
                    'project': 'cf_blog',
                    'account': 'soulnote.kr',
                    'day': '2026-11-07',
                    'slot': '12:00',
                    'status': 'allocated',
                }
            }
        })
        prep_args = {'action': 'cf-prepare', 'account': 'soulnote.kr', 'date': '2026-11-07', 'slot': '12:00'}
        prep_key = hashlib.sha256(json.dumps(['parameters', prep_args], sort_keys=True).encode()).hexdigest()
        prep_path = self.queue / (prep_key + '.json')
        write(prep_path, {
            'agendaId': prep_key,
            'kind': 'parameters',
            'arguments': prep_args,
            'status': 'completed',
            'requestedAt': 100.0,
            'preparation': {'preparationVerified': True},
            'outcomes': []
        })

        pub_args = {'action': 'cf', 'account': 'soulnote.kr', 'date': '2026-11-07', 'slot': '12:00'}
        pub_key = hashlib.sha256(json.dumps(['parameters', pub_args], sort_keys=True).encode()).hexdigest()
        pub_path = self.queue / (pub_key + '.json')
        write(pub_path, {
            'agendaId': pub_key,
            'kind': 'parameters',
            'arguments': pub_args,
            'status': 'running',
            'requestedAt': 200.0,
            'attempts': 1
        })

        with patch('common.work_agenda.enabled', return_value=False), \
             patch('common.conference_dispatch.request') as req_mock:
            result = autonomy.run_project_cycle('cf_blog', allocation_id=alloc_id)
        req_mock.assert_not_called()
        self.assertTrue(result['ok'])
        self.assertEqual(result['status'], 'awaiting_completion')
        self.assertEqual(result['conferenceAgendaId'], pub_key)
        self.assertEqual(result['conferenceRequestedAt'], 200.0)
        self.assertFalse(result['publicationVerified'])

        write(pub_path, {
            'agendaId': pub_key,
            'kind': 'parameters',
            'arguments': pub_args,
            'status': 'failed',
            'failureReason': 'upload_timed_out',
            'requestedAt': 200.0,
            'attempts': 2
        })
        with patch('common.work_agenda.enabled', return_value=False), \
             patch('common.conference_dispatch.request') as req_mock:
            failed_res = autonomy.run_project_cycle('cf_blog', allocation_id=alloc_id)
        req_mock.assert_not_called()
        self.assertFalse(failed_res['ok'])
        self.assertEqual(failed_res['status'], 'held')
        self.assertEqual(failed_res['conferenceAgendaId'], pub_key)
        self.assertEqual(failed_res['reason'], 'upload_timed_out')
        self.assertEqual(failed_res['attempts'], 2)

    def test_process_terminal_result_exact_argument_identity(self):
        alloc_id = '4' * 64
        proc_dir = self.data / 'ego-processes' / 'test-proc'
        proc_dir.mkdir(parents=True)
        receipt_path = proc_dir / 'receipt.json'
        with patch('server.agent_tools.EGO_PROCESS_DIR', self.data / 'ego-processes'):
            write(receipt_path, {
                'pid': 12345,
                'status': 'exited',
                'exitCode': 0,
                'action': {
                    'tool': 'run_project_cycle',
                    'argumentsComplete': True,
                    'args': {'project': 'cf_blog', 'allocation_id': alloc_id}
                }
            })
            term, _ = autonomy.terminal_result({
                'project': 'cf_blog',
                'allocationId': alloc_id,
                'pid': 12345,
                'receiptPath': str(receipt_path)
            })
            self.assertTrue(term['ok'])
            self.assertEqual(term['status'], 'completed')
            self.assertEqual(term['allocationId'], alloc_id)

            write(receipt_path, {
                'pid': 12345,
                'status': 'exited',
                'exitCode': 0,
                'action': {
                    'tool': 'run_project_cycle',
                    'argumentsComplete': True,
                    'args': {'project': 'cf_blog', 'allocation_id': 'diff' + '0' * 60}
                }
            })
            with self.assertRaisesRegex(ValueError, 'Process identity mismatch'):
                autonomy.terminal_result({
                    'project': 'cf_blog',
                    'allocationId': alloc_id,
                    'pid': 12345,
                    'receiptPath': str(receipt_path)
                })

            write(receipt_path, {
                'pid': 12345,
                'status': 'exited',
                'exitCode': 0,
                'action': {
                    'tool': 'run_project_cycle',
                    'argumentsComplete': True,
                    'args': {'project': 'cf_blog'}
                }
            })
            with self.assertRaisesRegex(ValueError, 'Process identity mismatch'):
                autonomy.terminal_result({
                    'project': 'cf_blog',
                    'allocationId': alloc_id,
                    'pid': 12345,
                    'receiptPath': str(receipt_path)
                })


    def test_exact_completed_publication_survives_domain_rotation(self):
        allocation_id = 'a' * 64
        arguments = {'action': 'cf', 'account': 'soulnote.kr', 'date': '2026-11-07', 'slot': '11:00'}
        identity = hashlib.sha256(json.dumps(['parameters', arguments], sort_keys=True).encode()).hexdigest()
        write(self.state_path, {'publications': {allocation_id: {
            'id': allocation_id, 'project': 'cf_blog', 'account': 'soulnote.kr',
            'day': '2026-11-07', 'slot': '11:00', 'status': 'allocated'}}})
        write(self.cf_sched_path, {'date': '2026-11-07', 'items': [{
            'domain': 'soulnote.kr', 'allocationId': 'b' * 64, 'status': 'queued'}]})
        write(self.queue / (identity + '.json'), {'agendaId': identity,
            'kind': 'parameters', 'arguments': arguments, 'status': 'completed',
            'requestedAt': 123.0, 'attempts': 2,
            'outcomes': [{'publicationVerified': True}]})
        with patch('common.work_agenda.enabled', return_value=False), patch('common.conference_dispatch.request') as submit:
            result = autonomy.run_project_cycle('cf_blog', allocation_id=allocation_id)
        submit.assert_not_called()
        self.assertEqual(result['conferenceAgendaId'], identity)
        self.assertEqual(result['conferenceRequestedAt'], 123.0)
        self.assertEqual(result['attempts'], 2)
        self.assertEqual(result['status'], 'completed')
        self.assertTrue(result['publicationVerified'])

    def test_active_preparation_survives_domain_rotation(self):
        allocation_id = 'a' * 64
        arguments = {'action': 'cf-prepare', 'account': 'soulnote.kr', 'date': '2026-11-07', 'slot': '11:00'}
        identity = hashlib.sha256(json.dumps(['parameters', arguments], sort_keys=True).encode()).hexdigest()
        write(self.state_path, {'publications': {allocation_id: {
            'id': allocation_id, 'project': 'cf_blog', 'account': 'soulnote.kr',
            'day': '2026-11-07', 'slot': '11:00', 'status': 'allocated'}}})
        write(self.cf_sched_path, {'date': '2026-11-07', 'items': [{
            'domain': 'soulnote.kr', 'allocationId': 'b' * 64, 'status': 'queued'}]})
        for status in ('queued', 'running'):
            with self.subTest(status=status):
                write(self.queue / (identity + '.json'), {'agendaId': identity,
                    'kind': 'parameters', 'arguments': arguments, 'status': status,
                    'requestedAt': 123.0, 'attempts': 2})
                with patch('common.work_agenda.enabled', return_value=False), patch('common.conference_dispatch.request') as submit:
                    result = autonomy.run_project_cycle('cf_blog', allocation_id=allocation_id)
                submit.assert_not_called()
                self.assertEqual(result['conferenceAgendaId'], identity)
                self.assertEqual(result['conferenceRequestedAt'], 123.0)
                self.assertEqual(result['status'], 'awaiting_completion')


if __name__ == '__main__':
    unittest.main()
