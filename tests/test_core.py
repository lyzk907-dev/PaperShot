import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import core


def config():
    return {**core.DEFAULTS, 'api_key': 'test-secret', 'base_url': 'https://example.com/v1',
            'model': 'test-model', 'keywords': 'agent memory', 'smtp_host': 'smtp.example.com',
            'smtp_user': 'test@example.com', 'smtp_password': 'mail-secret',
            'sender': 'test@example.com', 'recipient': 'reader@example.com'}


def paper(ident='2610.00001'):
    return {'id': ident, 'version': ident + 'v2', 'title': 'Agent memory',
            'abstract': 'A new approach.', 'authors': 'A. Author', 'published': '2026-10-15',
            'url': 'https://arxiv.org/abs/' + ident + 'v2'}


class CoreTests(unittest.TestCase):
    def setUp(self):
        temp_root = Path(__file__).resolve().parents[1] / '.test-tmp'
        temp_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=temp_root)
        self.store = core.Store(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    @unittest.skipUnless(os.name == 'nt', 'Windows DPAPI')
    def test_credentials_are_encrypted_and_roundtrip(self):
        self.store.save(config())
        content = (Path(self.temp.name) / 'settings.json').read_text(encoding='utf-8')
        self.assertNotIn('test-secret', content)
        self.assertNotIn('mail-secret', content)
        self.assertEqual(self.store.load(), config())

    @unittest.skipUnless(os.name == 'nt', 'Windows DPAPI')
    def test_old_settings_migrate_without_losing_credentials(self):
        self.store.save(config())
        path = Path(self.temp.name) / 'settings.json'
        old = json.loads(path.read_text(encoding='utf-8'))
        old.pop('schedule_mode')
        path.write_text(json.dumps(old), encoding='utf-8')
        loaded = self.store.load()
        self.assertEqual(loaded['api_key'], 'test-secret')
        self.assertEqual(loaded['schedule_mode'], '当天首次联网即发送')

    def test_feed_version_canonicalization_and_invalid_id(self):
        feed = b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/2610.00001v2</id><title>Test</title><summary>Abstract</summary><published>2026-10-15T00:00:00Z</published><author><name>A</name></author></entry><entry><id>https://evil.example</id></entry></feed>'''
        papers = core.parse_feed(feed)
        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0]['id'], '2610.00001')
        self.assertEqual(papers[0]['version'], '2610.00001v2')

    def test_query_escapes_keywords_and_filters_date_and_category(self):
        c = {**config(), 'keywords': 'agent memory, retrieval', 'categories': 'cs.AI, cs.CL'}
        q = core.query(c)
        self.assertIn('ti:"agent memory"', q)
        self.assertIn('cat:cs.CL', q)
        self.assertIn('submittedDate:[', q)
        with self.assertRaises(core.DigestError):
            core.query({**c, 'categories': 'cs.AI) OR all:*'})

    def test_rank_rejects_hallucinated_ids_and_missing_scores(self):
        with patch('core.llm', return_value='[{"id":"invented","score":10}]'):
            with self.assertRaises(core.DigestError):
                core.rank(config(), [paper()], lambda x: None)

    def test_rank_total_count_is_global(self):
        papers = [paper(f'2610.{i:05d}') for i in range(25)]
        def responder(c, system, prompt, tokens):
            batch = json.loads(prompt.split('论文数据：\n')[1])
            return json.dumps([{'id': p['id'], 'score': 8, 'reason': '相关'} for p in batch])
        with patch('core.llm', side_effect=responder):
            ranked = core.rank(config(), papers, lambda x: None)
        self.assertEqual(len(ranked), 10)

    def test_source_falls_back_honestly(self):
        with patch('core.arxiv_get', side_effect=core.DigestError('unavailable')):
            text, basis = core.source(paper(), True)
        self.assertEqual(text, paper()['abstract'])
        self.assertIn('仅依据摘要', basis)

    def test_partial_success_marks_only_summarized_papers(self):
        ps = [{**paper(), 'score': 8, 'reason': '相关'}, {**paper('2610.00002'), 'score': 8, 'reason': '相关'}]
        with patch('core.fetch', return_value=ps), patch('core.rank', return_value=ps), \
             patch('core.source', return_value=('text', '仅依据摘要')), \
             patch('core.llm', side_effect=['背景与动机：示例总结', core.DigestError('failed')]):
            ident = core.generate(config(), self.store, lambda x: None)
        self.assertEqual(self.store.seen(), {'2610.00001'})
        self.assertIn('成功总结 1 篇，失败 1 篇', self.store.get(ident)['content'])

    def test_all_failures_do_not_mark_seen(self):
        ps = [{**paper(), 'score': 8, 'reason': '相关'}]
        with patch('core.fetch', return_value=ps), patch('core.rank', return_value=ps), \
             patch('core.source', return_value=('text', '仅依据摘要')), \
             patch('core.llm', side_effect=core.DigestError('failed')):
            with self.assertRaises(core.DigestError):
                core.generate(config(), self.store, lambda x: None)
        self.assertEqual(self.store.seen(), set())
        self.assertEqual(self.store.history(), [])

    def test_daily_email_failure_preserves_digest_and_retries_without_generation(self):
        day = core.now().date().isoformat()
        ident = self.store.add('saved summary', ['2610.00001'], 'daily', day)
        with patch('core.send_email', side_effect=core.DigestError('SMTP failure')), patch('core.generate') as generate:
            with self.assertRaises(core.DigestError):
                core.run_daily(config(), self.store, lambda x: None)
            generate.assert_not_called()
        self.assertFalse(self.store.get(ident)['sent'])
        with patch('core.send_email') as send, patch('core.generate') as generate:
            result = core.run_daily(config(), self.store, lambda x: None)
            send.assert_called_once()
            generate.assert_not_called()
        self.assertEqual(result, ident)
        self.assertTrue(self.store.get(ident)['sent'])
        with patch('core.send_email') as send:
            core.run_daily(config(), self.store, lambda x: None)
            send.assert_not_called()

    def test_security_and_time_validation(self):
        for key, value in [('base_url', 'http://example.com/v1'), ('schedule_time', '25:00')]:
            with self.assertRaises(core.DigestError):
                core.validate({**config(), key: value})
        core.validate({**config(), 'base_url': 'http://localhost:8000/v1'})
        with self.assertRaises(core.DigestError):
            core.validate_email({**config(), 'recipient': 'a@example.com\nBcc:x@x.com'})

    def test_first_online_mode_ignores_scheduled_time(self):
        c = {**config(), 'schedule_enabled': True, 'schedule_time': '23:00'}
        self.assertTrue(core.daily_due(c, None, datetime(2026, 10, 16, 7, tzinfo=core.CHINA)))
        self.assertFalse(core.daily_due(c, {'sent': 1}, core.now()))
        self.assertFalse(core.daily_due({**c, 'schedule_enabled': False}, None, core.now()))

    def test_timed_mode_waits_until_due_then_allows_catchup(self):
        c = {**config(), 'schedule_enabled': True, 'schedule_mode': '到达指定时间后发送'}
        self.assertFalse(core.daily_due(c, None, datetime(2026, 10, 16, 7, 59, tzinfo=core.CHINA)))
        self.assertTrue(core.daily_due(c, None, datetime(2026, 10, 16, 8, 0, tzinfo=core.CHINA)))
        self.assertTrue(core.daily_due(c, {'sent': 0}, datetime(2026, 10, 16, 22, tzinfo=core.CHINA)))

    def test_reconnection_bypasses_retry_backoff(self):
        policy = core.NetworkRetry()
        self.assertTrue(policy.ready(True, 100))
        policy.attempted(100)
        self.assertFalse(policy.ready(True, 110))
        self.assertFalse(policy.ready(False, 120))
        self.assertTrue(policy.ready(True, 130))
        policy.attempted(130)
        self.assertFalse(policy.ready(True, 140))
        self.assertTrue(policy.ready(True, 3730))

    def test_saved_digest_only_requires_smtp_for_reconnect(self):
        with patch('core.socket.create_connection') as connect:
            self.assertTrue(core.services_reachable(config(), has_digest=True))
            connect.assert_called_once_with(('smtp.example.com', 465), timeout=3)
        with patch('core.socket.create_connection') as connect:
            self.assertTrue(core.services_reachable(config(), has_digest=False))
            self.assertEqual(connect.call_count, 3)
        with patch('core.socket.create_connection', side_effect=OSError('offline')):
            self.assertFalse(core.services_reachable(config(), has_digest=True))


if __name__ == '__main__':
    unittest.main()
