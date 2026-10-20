"""Revenue truth boundaries; all network and authentication calls are mocked."""
import copy
import json
import sys
import tempfile
import unittest
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent))
import revenue as r

START, END = date(2026, 10, 17), date(2026, 10, 19)
NOW = datetime(2026, 10, 19, 11, tzinfo=r.KST)


def response(data, status=200, text='', url='https://replyalba.com/mobile/partner/stat.php'):
    res = MagicMock(status_code=status, ok=status == 200, text=text, url=url)
    res.json.return_value = data
    return res


def report(rows='', start=START, end=END):
    return (f'<a href="/logout">로그아웃</a><input name="sdate" value="{start}">'
            f'<input name="edate" value="{end}"><table><tr>'
            '<th>번호</th><th>광고명</th><th>신청일자</th><th>수익금</th><th>보기</th>'
            '</tr>' + rows + '</table>')


class RevenueTests(unittest.TestCase):
    def test_coupang_nonempty_historical_gap_zero_today_pending(self):
        payload = {'rCode': '0', 'data': [{'date': '20261017', 'commission': 597}]}
        with patch.object(r.requests, 'get', return_value=response(payload)):
            got = r.coupang({'COUPANG_ACCESS_KEY': 'fake', 'COUPANG_SECRET_KEY': 'fake'}, START, END, NOW)
        self.assertEqual(got['daily'], {'2026-10-17': '597', '2026-10-18': '0'})
        self.assertEqual(got['pendingDates'], ['2026-10-19'])

    def test_coupang_empty_success_zero_and_failure_not_zero(self):
        cfg = {'COUPANG_ACCESS_KEY': 'fake', 'COUPANG_SECRET_KEY': 'fake'}
        for payload in ({'rCode': 'error', 'data': []}, {'rCode': 0, 'data': [], 'hasNext': True},
                        {'rCode': 0, 'data': [], 'nextCursor': 'more'}):
            with patch.object(r.requests, 'get', return_value=response(payload)), self.assertRaises(ValueError):
                r.coupang(cfg, START, END, NOW)
        with patch.object(r.requests, 'get', return_value=response({'rCode': 0, 'data': []})):
            got = r.coupang(cfg, START, END, NOW)
        self.assertEqual(got['daily'], {'2026-10-17': '0', '2026-10-18': '0'})

    def test_adpost_identity_and_placeholder(self):
        channels = [{'publisherId': '900', 'alias': 'nblog.actual_blog'}]
        self.assertEqual(r._adpost_identity(channels, '900', 'account', 'https://blog.naver.com/actual_blog'), channels)
        with self.assertRaises(r.RevenueSourceError):
            r._adpost_identity(channels, '901', 'account')
        with self.assertRaises(r.RevenueSourceError) as cm:
            r._adpost_identity([], '900', 'account')
        self.assertEqual(cm.exception.status, 'not_enrolled')
        got = r.parse_adpost_rows([{'date': '20261019', 'revenueAmount': 0}], START, END)
        self.assertEqual(got['daily'], {})
        self.assertEqual(got['pendingDates'], ['2026-10-19'])

    def test_adpost_only_owned_tab_closed_even_on_error(self):
        for reused in (False, True):
            for failed in (False, True):
                editor = MagicMock(url='https://blog.naver.com/PostWriteForm.naver')
                existing = MagicMock(url='https://adpost.naver.com/main')
                owned = MagicMock(url='about:blank')
                context = MagicMock(pages=[editor] + ([existing] if reused else []))
                context.new_page.return_value = owned
                pw = MagicMock()
                pw.chromium.connect_over_cdp.return_value.contexts = [context]
                manager = MagicMock()
                manager.__enter__.return_value = pw
                with patch('playwright.sync_api.sync_playwright', return_value=manager), patch.object(
                        r, '_adpost_report', side_effect=ValueError('safe') if failed else None,
                        return_value=([], '900', [{'alias': 'nblog.account'}])):
                    if failed:
                        with self.assertRaises(ValueError):
                            r.adpost(START, END, {}, 'account')
                    else:
                        r.adpost(START, END, {}, 'account')
                editor.close.assert_not_called()
                existing.close.assert_not_called()
                self.assertEqual(owned.close.call_count, int(not reused))

    def test_adpost_observed_login_drives_dynamic_publisher(self):
        page = MagicMock(url='https://adpost.naver.com/main')
        identity = {'isLoggedIn': True, 'isNaverLoggedIn': True, 'isRegistered': False,
                    'naverId': 'test_account', 'publisherId': 987654}
        with patch.object(r, 'browser_json', side_effect=[identity,
                [{'publisherId': 987654, 'alias': 'nblog.different_blog_name'}], []]) as fetch:
            _, publisher, _ = r._adpost_report(page, {'NAVER_test_ID': 'test_account'}, 'test', START, END)
        self.assertEqual(publisher, '987654')
        self.assertEqual(fetch.call_args_list[1].args[1], '/api/publishers/987654/channels')
        with patch.object(r, 'browser_json', return_value=dict(identity, naverId='wrong')):
            with self.assertRaises(r.RevenueSourceError):
                r._adpost_report(page, {'NAVER_test_ID': 'test_account'}, 'test', START, END)

    def test_reply_configured_origin_and_pagination_canonical_dates(self):
        url = 'https://replyalba.com/mobile/partner/stat.php?page=2&sdate=old&edate=old&sdate=duplicate'
        canonical = r._reply_report_url(url, START, END)
        self.assertEqual(canonical.count('sdate='), 1)
        self.assertEqual(canonical.count('edate='), 1)
        self.assertEqual(r._reply_report_url(canonical, START, END), canonical)
        html = report() + '<a href="?edate=old&page=2&sdate=old">2</a>'
        _, pages = r.parse_reply_report(html, url, START, END)
        self.assertEqual(pages, {canonical})
        with self.assertRaises(r.RevenueSourceError):
            r._reply_url('https://replyalba.com/', 'https://untrusted.invalid/')

    def test_duplicate_publisher_excluded_even_old_summary(self):
        sources = [dict(id='a', category='adpost', status='collected', publisherId='7',
                        currency='KRW', daily={'2026-10-18': '10'}),
                   dict(id='b', category='adpost', status='collected', publisherId='7',
                        currency='KRW', daily={'2026-10-18': '10'})]
        r.deduplicate_adpost_sources(sources)
        self.assertEqual(sources[1]['daily'], {})
        self.assertEqual(sources[1]['previousObservedDaily'], {'2026-10-18': '10'})
        r.deduplicate_adpost_sources(sources)
        self.assertEqual(sources[1]['previousObservedDaily'], {'2026-10-18': '10'})
        self.assertEqual(r.period(sources, date(2026, 10, 18), date(2026, 10, 18))['amounts'], {'KRW': '10'})

    def test_toss_full_summary_pagination_and_date_validation(self):
        data = {'resultType': 'SUCCESS', 'success': {'fromDate': str(START), 'toDate': str(START),
                'summary': {'expectedCommissionAmount': 0, 'confirmedCommissionAmount': 0},
                'items': [], 'hasNext': True}}
        got = r.parse_toss_performance(data, str(START))
        self.assertEqual(got['amount'], '0')
        self.assertTrue(got['detailPagesRemaining'])
        with self.assertRaises(r.RevenueSourceError):
            r.parse_toss_performance(data, str(END))
        with self.assertRaises(r.RevenueSourceError):
            r.parse_toss_performance({'resultType': 'FAIL'}, str(START))

    def test_toss_token_reuse_and_auth_failure(self):
        cfg = {'TOSS_ACCESS_KEY': 'fake-access', 'TOSS_SECRET_KEY': 'fake-secret'}
        sess = MagicMock()
        sess.post.return_value = response({'access_token': 'test-only', 'token_type': 'Bearer',
                                          'expires_in': 3600, 'scope': 'sharelink:read'})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'token.json'
            self.assertEqual(r._toss_access_token(cfg, sess, path), 'test-only')
            self.assertEqual(r._toss_access_token(cfg, sess, path), 'test-only')
            self.assertEqual(sess.post.call_count, 1)
            sess.post.return_value = response({}, 403)
            with self.assertRaises(r.RevenueSourceError):
                r._toss_access_token(cfg, sess, Path(tmp) / 'different.json')

    def test_reply_report_only_earnings_and_auth_range_failures(self):
        html = report('<tr><td>1</td><td>private label</td><td>2026-10-18</td><td>1,234원</td><td></td></tr>')
        rows, pages = r.parse_reply_report(html, 'https://replyalba.com/mobile/partner/stat.php', START, END)
        self.assertEqual(rows, [{'rowId': '1', 'date': '2026-10-18', 'amount': '1234'}])
        self.assertEqual(pages, set())
        for invalid in ('<script>alert("login");location.href="login";</script>', report().replace(str(START), '2026-09-17')):
            with self.assertRaises(r.RevenueSourceError):
                r.parse_reply_report(invalid, 'https://replyalba.com/mobile/partner/stat.php', START, END)

    def test_reply_fresh_login_complete_empty_range_zero_today_pending(self):
        login = '<form id="loginFrm"><input type="hidden" name="mode" value="login"></form><script>"../../proc/member.php"</script>'
        landing = '<a href="/mobile/partner/stat.php">실적/수익</a>'
        session = MagicMock()
        session.__enter__.return_value = session
        session.post.return_value = response({'res': True, 'url': '/mobile/main/'})
        session.get.side_effect = [response({}, text=login, url='https://replyalba.com/mobile/main/login.partner.php'),
                                   response({}, text=landing, url='https://replyalba.com/mobile/main/'), response({}, text=report())]
        with patch.object(r.requests, 'Session', return_value=session):
            got = r.replyalba({'REPLYALBA_ID': 'fake', 'REPLYALBA_PW': 'fake'}, START, END, NOW)
        self.assertEqual(got['daily'], {'2026-10-17': '0', '2026-10-18': '0'})
        self.assertEqual(got['identityEvidence'], 'fresh_credential_login')
        self.assertEqual(got['pendingDates'], ['2026-10-19'])
        self.assertTrue(got['queryComplete'])

    def test_period_configuration_zero_unknown_pending_distinct(self):
        base = {'id': 'trip', 'currency': 'KRW', 'daily': {}}
        config = r.affiliate_configuration({'TRIP_AID': 'fake', 'TRIP_SID': 'fake'}, 'trip')
        self.assertEqual(r.period([dict(base, **config)], START, END)['amounts'], {})
        self.assertEqual(r.period([dict(base, **config)], START, END)['status'], 'configured_no_report_api')
        zero = dict(base, status='collected', daily={str(START): '0'})
        self.assertEqual(r.period([zero], START, START)['amounts'], {'KRW': '0'})
        unrelated = dict(base, id='coupang', status='collected', pendingDates=[])
        pending = dict(base, id='replyalba', status='collected', pendingDates=[str(END)])
        self.assertNotIn('D+1', r.period([unrelated, pending], END, END)['reason'])

    def test_busy_lock_makes_no_requests(self):
        @contextmanager
        def busy(*args):
            yield False
        with patch.object(r, 'collector_lock', busy), patch.object(r, 'revenue_config') as cfg:
            self.assertEqual(r.collect(NOW), {'status': 'busy'})
            cfg.assert_not_called()

    def test_only_verified_optional_non_enrollment_exempt_from_completeness(self):
        primary = dict(id='primary', currency='KRW', status='collected', daily={str(START): '385'})
        optional = dict(id='optional', currency='KRW', optional=True, status='not_enrolled', daily={})
        got = r.period([primary, optional], START, START)
        self.assertTrue(got['complete'])
        self.assertEqual(got['status'], 'collected')
        self.assertEqual(r.period([optional], START, START)['status'], 'not_enrolled')
        for status in ('auth_required', 'error'):
            got = r.period([primary, dict(optional, status=status)], START, START)
            self.assertFalse(got['complete'])
            self.assertEqual(got['status'], 'partial')


class GrowthPageEvidenceTests(unittest.TestCase):
    def test_page_revenue_uses_url_earnings_and_rejects_truncation(self):
        data = {'headers': [{'name': 'PAGE_URL'}, {'name': 'ESTIMATED_EARNINGS', 'currencyCode': 'USD'}],
                'totalMatchedRows': 1, 'rows': [{'cells': [{'value': 'https://www.example.org/repair'}, {'value': '0.42'}]}]}
        client = MagicMock()
        client.get.side_effect = [response({'timeZone': {'id': 'Asia/Seoul'}, 'state': 'READY'}), response(data)]
        cfg = {'TEST_' + key: 'mock' for key in ('ACCOUNT_ID', 'REFRESH_TOKEN', 'CLIENT_ID', 'CLIENT_SECRET')}
        with patch('google.oauth2.credentials.Credentials'), patch('google.auth.transport.requests.AuthorizedSession') as session:
            session.return_value.__enter__.return_value = client
            rows = r.adsense_page_performance(cfg, START, END, ['example.org'], 'TEST')
            self.assertEqual(rows[0]['estimatedRevenue'], 0.42)
            self.assertEqual(client.get.call_args.kwargs['params']['dimensions'], ['PAGE_URL'])
            data['totalMatchedRows'] = 2
            client.get.side_effect = [response({'timeZone': {'id': 'Asia/Seoul'}, 'state': 'READY'}), response(data)]
            with self.assertRaises(ValueError):
                r.adsense_page_performance(cfg, START, END, ['example.org'], 'TEST')

    def test_page_revenue_failure_is_unknown_not_zero(self):
        with patch.object(r, 'adsense_page_performance', side_effect=ValueError('unavailable')):
            result = r.collect_page_revenue({}, {'sj': {'sites': ['example.org']}}, NOW)
        self.assertFalse(result['complete'])
        self.assertEqual(result['pages'], [])
        self.assertEqual(result['start'], '2026-10-12')
        self.assertEqual(result['end'], '2026-10-18')

    def test_ga_week_is_complete_enumeration_without_title_dimension(self):
        import traffic
        with patch.object(traffic, 'ga_report', return_value=([(['/repair'], [4, 5])], False)) as report:
            result = traffic.collect_growth_pages(None, '123', {}, 'example.org', NOW)
        self.assertTrue(result['fullEnumeration'])
        self.assertEqual(result['pages'][0]['sessions'], 4)
        self.assertEqual(report.call_args.args[2]['dimensions'], [{'name': 'pagePath'}])
        self.assertEqual(result['end'], '2026-10-18')
        with patch.object(traffic, 'ga_report', return_value=([], True)):
            self.assertFalse(traffic.collect_growth_pages(None, '123', {}, 'example.org', NOW)['complete'])


class GrowthRevenueTests(unittest.TestCase):
    def test_failed_source_retries_after_thirty_minutes_using_effective_config(self):
        windows = r.growth_windows()
        cfg = {'TEST_' + key: 'mock' for key in ('ACCOUNT_ID', 'REFRESH_TOKEN', 'CLIENT_ID', 'CLIENT_SECRET')}
        accounts = {'sj': {'sites': ['example.org'], 'env_prefix': 'TEST'}}
        for age, expected_calls in ((10, 0), (31, 1)):
            with self.subTest(age=age), tempfile.TemporaryDirectory() as tmp:
                data = Path(tmp)
                cached = {'windows': windows, 'status': 'partial',
                          'checkedAt': (datetime.now(timezone.utc) - timedelta(minutes=age)).isoformat(),
                          'sources': {'sj': {'status': 'error'}}}
                snapshot = data / 'revenue.json'
                snapshot.write_text(json.dumps({'growth': cached}), encoding='utf-8')
                config = data / 'metrics-config.json'
                config.write_text(json.dumps({'adsense_accounts': accounts}), encoding='utf-8')
                with patch.object(r, 'DATA', data), patch.object(r, 'SNAPSHOT', snapshot), \
                        patch.object(r, 'CONFIG', config), patch.object(r, 'revenue_config', return_value=cfg), \
                        patch.object(r, 'adsense_growth', return_value=[]) as fetch, \
                        patch.object(r, 'import_growth_daily', return_value={'status': 'imported', 'rows': 0}):
                    got = r.collect_growth_revenue()
                self.assertEqual(fetch.call_count, expected_calls)
                if expected_calls:
                    self.assertEqual(fetch.call_args.args[0], cfg)
                    self.assertEqual(got['sources']['sj']['status'], 'collected')
                else:
                    self.assertEqual(got, cached)

    def test_observed_host_rows_import_without_missing_days_or_scope_assumptions(self):
        from server import growth
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            db_path = data / 'growth.sqlite3'
            with growth.connect(db_path) as db:
                db.executemany('INSERT INTO sites VALUES (?,?,?,?)',
                               [(domain, 'https://' + domain, 'cf', 'test')
                                for domain in ('example.org', 'healthcox.com')])
            source = {'status': 'collected', 'checkedAt': '2026-10-19T12:00:00+00:00',
                      'domains': ['example.org', 'healthcox.com', 'unregistered.org'],
                      'rows': [{'domain': 'example.org', 'host': 'www.example.org',
                                'date': '2026-10-12', 'revenue': '0.01'},
                               {'domain': 'example.org', 'host': 'example.org',
                                'date': '2026-10-12', 'revenue': '0.02'},
                               {'domain': 'example.org', 'host': 'example.org',
                                'date': '2026-10-14', 'revenue': '0'},
                               {'domain': 'healthcox.com', 'host': 'healthcox.com',
                                'date': '2026-10-12', 'revenue': '0.04'},
                               {'domain': 'healthcox.com', 'host': 'healthcox.com',
                                'date': '2026-10-13', 'revenue': '0.05'},
                               {'domain': 'unregistered.org', 'host': 'unregistered.org',
                                'date': '2026-10-12', 'revenue': '100'}]}
            result = {'sources': {'sj': source}}
            with patch.object(r, 'DATA', data), patch('metrics.DATA', data):
                got = r.import_growth_daily(result)
                r.import_growth_daily(result)
            self.assertEqual(got['rows'], 4)
            with growth.connect(db_path) as db:
                rows = [dict(row) for row in db.execute('SELECT * FROM daily_metrics ORDER BY site_id,day')]
                self.assertEqual(growth.revenue_goal(db, date(2026, 10, 18))['status'], 'unknown')
            self.assertEqual(len(rows), 4)
            self.assertEqual(rows[0]['value'], 0.03)
            self.assertEqual(rows[1]['value'], 0)
            self.assertEqual([row['complete'] for row in rows], [1, 1, 0, 1])
            self.assertEqual({row['revenue_scope'] for row in rows}, {'unknown'})
            self.assertEqual({row['source_timezone'] for row in rows}, {'America/Los_Angeles'})
            self.assertEqual({row['currency'] for row in rows}, {'USD'})
            self.assertFalse(any(row['site_id'] == 'example.org' and row['day'] == '2026-10-13' for row in rows))

    def test_warning_report_is_not_complete_evidence(self):
        data = {'headers': [{'name': 'DATE'}, {'name': 'DOMAIN_CODE'},
                            {'name': 'ESTIMATED_EARNINGS', 'currencyCode': 'USD'}, {'name': 'PAGE_VIEWS'}],
                'rows': [], 'totalMatchedRows': 0, 'warnings': ['DATA_DELAYED']}
        with self.assertRaises(ValueError):
            r.parse_growth_report(data, ['example.org'], '2026-10-01', '2026-10-18')


if __name__ == '__main__':
    unittest.main()
