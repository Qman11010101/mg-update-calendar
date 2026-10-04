import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx2
from openai import OpenAI

from mg_update_calendar.extractor import extract_article, main
from mg_update_calendar.models import Article


ARTICLE = {
    'game': 'chunithm', 'url': 'https://example.com/news/1', 'date': '2026-09-22',
    'title': '9/25 楽曲追加とイベント開催',
    'body_text': '2026年9月25日より「曲A」「曲B」が追加。コラボは2026年9月25日～2026年11月11日。',
    'body_markdown': '',
}


def entry(**changes):
    data = {
        'type': 'song_add', 'title': '楽曲追加（2曲）', 'start': '2026-09-25',
        'start_time': None, 'end': None, 'end_time': None, 'open_ended': True,
        'songs': ['曲A', '曲B'], 'date_text': '2026年9月25日より',
        'evidence': '「曲A」「曲B」が追加。', 'confidence': 0.95,
    }
    return data | changes


def response_payload(extraction=None, status='completed', refusal=False):
    if extraction is not None:
        extraction = {'cancellations': []} | extraction
    content = ({'type': 'refusal', 'refusal': 'refused'} if refusal else
               {'type': 'output_text', 'text': json.dumps(extraction, ensure_ascii=False), 'annotations': []})
    return {
        'id': 'resp_test', 'object': 'response', 'created_at': 1, 'model': 'gpt-5.6-luna',
        'status': status, 'output': [{'type': 'message', 'id': 'msg_test', 'role': 'assistant',
                                   'status': 'completed', 'content': [content]}],
    }


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(contextlib.chdir(directory))

    def test_cli_loads_dotenv_with_environment_and_argument_precedence(self):
        Path('.env').write_text(
            'OPENAI_API_KEY=dotenv-test-key\nOPENAI_MODEL=dotenv-model\n', encoding='utf-8-sig')
        Path('news.json').write_text('[]', encoding='utf-8')
        cases = [
            ({}, [], 'dotenv-test-key', 'dotenv-model'),
            ({'OPENAI_API_KEY': 'env-test-key', 'OPENAI_MODEL': 'env-model'}, [],
             'env-test-key', 'env-model'),
            ({'OPENAI_MODEL': 'env-model'}, ['--model', 'cli-model'], 'dotenv-test-key', 'cli-model'),
        ]
        for environment, arguments, expected_key, expected_model in cases:
            with self.subTest(environment=environment, arguments=arguments):
                with patch.dict(os.environ, environment, clear=True), contextlib.redirect_stdout(io.StringIO()):
                    code = main(['-i', 'news.json', '-o', 'out.json', '--dry-run', *arguments])
                    self.assertEqual(os.environ['OPENAI_API_KEY'], expected_key)
                self.assertEqual(code, 0)
                output = Path('out.json').read_text(encoding='utf-8')
                self.assertEqual(json.loads(output)['model'], expected_model)
                self.assertNotIn(expected_key, output)

    def extract(self, payload, article=None, status_code=200):
        self.requests = []

        def handler(request):
            self.requests.append(request)
            return httpx2.Response(status_code, json=payload)

        with OpenAI(api_key='test-key', max_retries=0,
                    http_client=httpx2.Client(transport=httpx2.MockTransport(handler))) as client:
            return extract_article(client, Article.model_validate(article or ARTICLE), 'gpt-5.6-luna', 8192)

    def test_multiple_entries_and_strict_request_through_sdk(self):
        event = entry(type='event', title='コラボ', end='2026-11-11', open_ended=False, songs=[],
                      date_text='2026年9月25日～2026年11月11日', evidence='コラボは2026年9月25日～2026年11月11日。')
        result = self.extract(response_payload({'entries': [entry(), event], 'review_notes': []}))
        self.assertEqual(result['status'], 'extracted')
        self.assertEqual(result['entries'][0]['songs'], ['曲A', '曲B'])
        self.assertIsNone(result['entries'][0]['end'])
        self.assertEqual(result['source']['url'], ARTICLE['url'])
        request = self.requests[0]
        self.assertEqual(request.url.path, '/v1/responses')
        body = json.loads(request.content)
        self.assertEqual(body['model'], 'gpt-5.6-luna')
        self.assertTrue(body['text']['format']['strict'])
        self.assertFalse(body['store'])

        def check_schema(node):
            if isinstance(node, dict):
                if node.get('type') == 'object':
                    self.assertFalse(node['additionalProperties'])
                    self.assertEqual(set(node['required']), set(node['properties']))
                for value in node.values():
                    check_schema(value)
            elif isinstance(node, list):
                for value in node:
                    check_schema(value)
        check_schema(body['text']['format']['schema'])

    def test_game_specific_chart_types_and_request_schemas(self):
        cases = {
            'chunithm': ['ultima_add', 'worlds_end_add'],
            'chunithm_intl': ['ultima_add', 'worlds_end_add'],
            'maimai': ['remaster_add', 'dx_chart_add', 'standard_chart_add', 'utage_add'],
            'ongeki': ['lunatic_add'],
        }
        for game, kinds in cases.items():
            for kind in kinds:
                with self.subTest(game=game, kind=kind):
                    result = self.extract(response_payload({'entries': [entry(type=kind)], 'review_notes': []}),
                                          ARTICLE | {'game': game})
                    self.assertNotEqual(result['status'], 'failed')
                    body = json.loads(self.requests[0].content)
                    definitions = body['text']['format']['schema']['$defs']
                    allowed = definitions['Entry']['properties']['type']['enum']
                    self.assertIn(kind, allowed)
                    self.assertNotIn('chart_add', allowed)
                    self.assertNotIn('song_withdrawn', allowed)
                    self.assertEqual(allowed, definitions['Cancellation']['properties']['target_type']['enum'])
                    self.assertIn(game, body['instructions'])

    def test_wrong_game_and_removed_types_are_rejected(self):
        for game, kind in [('chunithm', 'utage_add'), ('maimai', 'ultima_add'),
                           ('ongeki', 'worlds_end_add'), ('maimai', 'login_bonus'),
                           ('chunithm', 'chart_add'), ('chunithm', 'song_withdrawn')]:
            with self.subTest(game=game, kind=kind):
                result = self.extract(response_payload({'entries': [entry(type=kind)], 'review_notes': []}),
                                      ARTICLE | {'game': game})
                self.assertEqual(result['status'], 'failed')
                self.assertEqual(result['entries'], [])

    def test_cancellations_are_separate_and_need_matching(self):
        cancellation = {'target_type': 'song_add', 'title': '曲Aの収録見合わせ',
                        'songs': ['曲A'], 'evidence': '曲Aの収録を見合わせます。', 'confidence': 0.95}
        article = ARTICLE | {'body_text': cancellation['evidence']}
        result = self.extract(response_payload({'entries': [], 'cancellations': [cancellation], 'review_notes': []}), article)
        self.assertEqual(result['entries'], [])
        self.assertEqual(result['cancellations'], [cancellation])
        self.assertEqual(result['status'], 'needs_review')
        self.assertTrue(any('照合' in reason for reason in result['review_reasons']))
        for changes in [{'target_type': 'utage_add'}, {'evidence': ''}]:
            with self.subTest(changes=changes):
                result = self.extract(response_payload({'entries': [], 'cancellations': [cancellation | changes],
                                                       'review_notes': []}), article)
                self.assertEqual(result['status'], 'failed')
        result = self.extract(response_payload({'entries': [], 'cancellations': [cancellation | {
            'target_type': 'other', 'evidence': '架空', 'confidence': 0.2}], 'review_notes': []}), article)
        self.assertTrue(any('原文根拠' in reason for reason in result['review_reasons']))
        self.assertTrue(any('種類が不明' in reason for reason in result['review_reasons']))
        self.assertTrue(any('confidence' in reason for reason in result['review_reasons']))

    def test_song_entries_without_song_names_are_removed(self):
        cases = {
            'chunithm': ['song_add', 'song_unlock', 'ultima_add', 'worlds_end_add'],
            'chunithm_intl': ['song_add', 'song_unlock', 'ultima_add', 'worlds_end_add'],
            'maimai': ['song_add', 'song_unlock', 'remaster_add', 'dx_chart_add',
                       'standard_chart_add', 'utage_add'],
            'ongeki': ['song_add', 'song_unlock', 'lunatic_add'],
        }
        for game, kinds in cases.items():
            for kind in kinds:
                for songs in [[], ['', ' \t', '\u3000']]:
                    with self.subTest(game=game, kind=kind, songs=songs):
                        kept = entry(type=kind, songs=['', '曲A'])
                        result = self.extract(response_payload({
                            'entries': [entry(type=kind, songs=songs), kept],
                            'review_notes': ['曲名は画像内にあります。'],
                        }), ARTICLE | {'game': game})
                        self.assertEqual(result['entries'], [kept])
                        self.assertEqual(result['error'], None)
                        self.assertIn('曲名は画像内にあります。', result['review_reasons'])

    def test_only_empty_song_entry_becomes_successful_empty_extraction(self):
        result = self.extract(response_payload({
            'entries': [entry(title='新曲を大量追加！', songs=[])], 'review_notes': [],
        }))
        self.assertEqual(result['entries'], [])
        self.assertEqual(result['status'], 'extracted')

    def test_non_song_entries_and_cancellations_without_songs_are_preserved(self):
        from mg_update_calendar.models import GAME_ENTRY_TYPES

        song_types = {'song_add', 'song_unlock', 'ultima_add', 'worlds_end_add',
                      'remaster_add', 'dx_chart_add', 'standard_chart_add', 'utage_add', 'lunatic_add'}
        for game, kinds in GAME_ENTRY_TYPES.items():
            with self.subTest(game=game):
                entries = [entry(type=kind, songs=[]) for kind in kinds if kind not in song_types]
                cancellation = {'target_type': 'song_add', 'title': '収録見合わせ',
                                'songs': [], 'evidence': ARTICLE['body_text'], 'confidence': 0.95}
                result = self.extract(response_payload({
                    'entries': entries, 'cancellations': [cancellation], 'review_notes': [],
                }), ARTICLE | {'game': game})
                self.assertEqual(result['entries'], entries)
                self.assertEqual(result['cancellations'], [cancellation])

    def test_empty_extraction_is_success(self):
        result = self.extract(response_payload({'entries': [], 'review_notes': []}))
        self.assertEqual(result['status'], 'extracted')
        self.assertEqual(result['entries'], [])

    def test_refusal_and_incomplete_are_failures(self):
        for payload, error in [(response_payload(refusal=True), 'refusal'),
                               (response_payload({'entries': [], 'review_notes': []}, status='incomplete'), 'response_incomplete')]:
            with self.subTest(error=error):
                result = self.extract(payload)
                self.assertEqual(result['status'], 'failed')
                self.assertEqual(result['error'], error)

    def test_invalid_schema_dates_times_and_types_are_failures(self):
        for invalid in [entry(start='2026-02-30'), entry(start_time='24:00'),
                        entry(type='invented'), entry(confidence=1.1), entry(extra='oops'),
                        entry(open_ended='true')]:
            with self.subTest(invalid=invalid):
                result = self.extract(response_payload({'entries': [invalid], 'review_notes': []}))
                self.assertEqual(result['error'], 'invalid_structured_output')

    def test_unverifiable_quotes_and_date_conflicts_need_review(self):
        result = self.extract(response_payload({'entries': [entry(evidence='架空の文章', end='2026-09-01')], 'review_notes': []}))
        self.assertEqual(result['status'], 'needs_review')
        self.assertTrue(any('evidence' in reason for reason in result['review_reasons']))
        self.assertTrue(any('終了日が開始日より前' in reason for reason in result['review_reasons']))

    def test_unknown_dates_and_low_confidence_are_preserved(self):
        result = self.extract(response_payload({'entries': [entry(start=None, date_text='', confidence=0.4)], 'review_notes': ['年が不明']}))
        self.assertEqual(result['status'], 'needs_review')
        self.assertIsNone(result['entries'][0]['start'])
        self.assertIn('年が不明', result['review_reasons'])

    def test_markdown_quote_keeps_original_whitespace(self):
        article = ARTICLE | {'body_markdown': '2026年9月25日\nより「曲A」が追加。'}
        result = self.extract(response_payload({'entries': [entry(date_text='2026年9月25日\nより')], 'review_notes': []}), article)
        self.assertEqual(result['status'], 'extracted')

    def test_empty_body_and_international_need_review(self):
        for article in [ARTICLE | {'body_text': ''}, ARTICLE | {'game': 'chunithm_intl'}]:
            with self.subTest(article=article):
                result = self.extract(response_payload({'entries': [], 'review_notes': []}), article)
                self.assertEqual(result['status'], 'needs_review')

    def test_api_error_does_not_leak_body(self):
        result = self.extract({'error': {'message': 'secret-key', 'type': 'authentication_error'}}, status_code=401)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['error'], 'AuthenticationError')
        self.assertNotIn('secret-key', json.dumps(result))

    def test_empty_publication_date_is_supported(self):
        result = self.extract(response_payload({'entries': [entry()], 'review_notes': []}), ARTICLE | {'date': ''})
        self.assertEqual(result['status'], 'needs_review')
        self.assertIsNone(result['source']['date'])

    def test_content_hash_includes_metadata(self):
        payload = response_payload({'entries': [], 'review_notes': []})
        first = self.extract(payload)
        second = self.extract(payload, ARTICLE | {'title': '変更'})
        self.assertNotEqual(first['content_hash'], second['content_hash'])

    def test_dry_run_without_key_and_with_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / 'news.json', Path(directory) / 'requests.json'
            source.write_text(json.dumps([ARTICLE, ARTICLE]), encoding='utf-8')
            with patch.dict(os.environ, {}, clear=True), patch('mg_update_calendar.extractor.OpenAI') as client:
                with contextlib.redirect_stdout(io.StringIO()):
                    code = main(['--input', str(source), '--output', str(target), '--dry-run', '--max-articles', '1'])
            self.assertEqual(code, 0)
            client.assert_not_called()
            data = json.loads(target.read_text(encoding='utf-8'))
            self.assertEqual(data['mode'], 'dry_run')
            self.assertEqual(len(data['requests']), 1)
            self.assertEqual(data['articles'], [])
            self.assertEqual(json.loads(data['requests'][0]['input'][0]['content'])['title'], ARTICLE['title'])

    def test_missing_key_and_invalid_input_do_not_overwrite_output(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / 'news.json', Path(directory) / 'out.json'
            for raw in [[ARTICLE], {'wrong': 'shape'}]:
                source.write_text(json.dumps(raw), encoding='utf-8')
                target.write_text('keep', encoding='utf-8')
                with patch.dict(os.environ, {}, clear=True), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(main(['-i', str(source), '-o', str(target)]), 2)
                self.assertEqual(target.read_text(encoding='utf-8'), 'keep')

    def test_cli_continues_after_failure_and_saves_results(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / 'news.json', Path(directory) / 'out.json'
            source.write_text(json.dumps([ARTICLE, ARTICLE | {'url': 'https://example.com/news/2'}]), encoding='utf-8')
            payloads = iter([response_payload(refusal=True), response_payload({'entries': [entry()], 'review_notes': []})])
            client = OpenAI(api_key='test-key', max_retries=0, http_client=httpx2.Client(
                transport=httpx2.MockTransport(lambda request: httpx2.Response(200, json=next(payloads)))))
            with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-key'}), patch('mg_update_calendar.extractor.OpenAI', return_value=client):
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    code = main(['-i', str(source), '-o', str(target)])
            self.assertEqual(code, 1)
            results = json.loads(target.read_text(encoding='utf-8'))['articles']
            self.assertEqual([item['status'] for item in results], ['failed', 'extracted'])


if __name__ == '__main__':
    unittest.main()
