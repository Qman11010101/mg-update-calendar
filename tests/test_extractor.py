import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import httpx2
from openai import OpenAI

from mg_update_calendar.extractor import extract_article, main
from mg_update_calendar.models import Article
from mg_update_calendar.llm import LLMClient, LLMConfig


ARTICLE = {
    'game': 'chunithm', 'url': 'https://example.com/news/1', 'date': '2026-09-22',
    'title': '9/25 楽曲追加とイベント開催',
    'body_text': '2026年9月25日より「曲A」「曲B」が追加。コラボは2026年9月25日～2026年11月11日。',
    'body_markdown': '',
}


def entry(**changes):
    data = {
        'service': 'chunithm', 'start_is_deadline': False,
        'event_name': None, 'event_evidence': None,
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

    def test_cli_loads_dotenv_with_environment_precedence(self):
        Path('.env').write_text(
            'OPENAI_API_KEY=dotenv-test-key\nOPENAI_MODEL=dotenv-model\n', encoding='utf-8-sig')
        Path('news_all.json').write_text('[]', encoding='utf-8')
        cases = [
            ({}, [], 'dotenv-test-key', 'dotenv-model'),
            ({'OPENAI_API_KEY': 'env-test-key', 'OPENAI_MODEL': 'env-model'}, [],
             'env-test-key', 'env-model'),
        ]
        for environment, arguments, expected_key, expected_model in cases:
            with self.subTest(environment=environment, arguments=arguments):
                with patch.dict(os.environ, environment, clear=True), contextlib.redirect_stdout(io.StringIO()):
                    code = main(arguments)
                    self.assertEqual(os.environ['OPENAI_API_KEY'], expected_key)
                self.assertEqual(code, 0)
                output = Path('entries.json').read_text(encoding='utf-8')
                self.assertEqual(json.loads(output)['model'], expected_model)
                self.assertNotIn(expected_key, output)

    def extract(self, payload, article=None, status_code=200):
        self.requests = []

        def handler(request):
            self.requests.append(request)
            return httpx2.Response(status_code, json=payload)

        with OpenAI(api_key='test-key', max_retries=0,
                    http_client=httpx2.Client(transport=httpx2.MockTransport(handler))) as client:
            with patch('mg_update_calendar.llm.OpenAI', return_value=client):
                generator = LLMClient(LLMConfig('openai', 'gpt-5.6-luna', 'test-key'))
            return extract_article(generator, Article.model_validate(article or ARTICLE), 8192)

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

    def test_goods_campaign_for_all_games_and_cancellations(self):
        evidence = '2026年9月25日～2026年11月11日、グッズ交換キャンペーンを開催。'
        campaign = entry(type='goods_campaign', title='グッズ交換キャンペーン', songs=[],
                         end='2026-11-11', open_ended=False,
                         date_text='2026年9月25日～2026年11月11日', evidence=evidence)
        for game in ['chunithm', 'chunithm_intl', 'maimai', 'ongeki']:
            with self.subTest(game=game):
                article = ARTICLE | {'game': game, 'body_text': evidence}
                result = self.extract(response_payload({'entries': [campaign], 'review_notes': []}), article)
                self.assertNotEqual(result['status'], 'failed')
                self.assertEqual(result['entries'][0]['type'], 'goods_campaign')
                self.assertEqual(result['entries'][0]['songs'], [])
                self.assertEqual(result['entries'][0]['end'], '2026-11-11')
                body = json.loads(self.requests[0].content)
                definitions = body['text']['format']['schema']['$defs']
                for model, field in [('Entry', 'type'), ('Cancellation', 'target_type')]:
                    self.assertIn('goods_campaign', definitions[model]['properties'][field]['enum'])
                self.assertIn('goods_campaign: グッズキャンペーン', body['instructions'])
                cancellation = {'target_type': 'goods_campaign', 'title': campaign['title'],
                                'songs': [], 'evidence': 'グッズ交換キャンペーンを中止します。',
                                'confidence': 0.95}
                result = self.extract(response_payload({'entries': [], 'cancellations': [cancellation],
                                                       'review_notes': []}),
                                      article | {'body_text': cancellation['evidence']})
                self.assertNotEqual(result['status'], 'failed')
                self.assertEqual(result['entries'], [])
                self.assertEqual(result['cancellations'], [cancellation])

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
                        self.assertEqual(result['entries'], [kept | {'calendar_start': kept['start'], 'calendar_end': kept['end'], 'event_id': None}])
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
                self.assertEqual(result['entries'], [e | {'calendar_start': e['start'], 'calendar_end': e['end'], 'event_id': None} for e in entries])
                self.assertEqual(result['cancellations'], [cancellation])

    def test_service_deadline_boundaries_and_original_times(self):
        cases = [
            ('chunithm', 'chunithm', '00:00', '2026-08-31'),
            ('chunithm', 'chunithm', '02:00', '2026-08-31'),
            ('chunithm', 'chunithm', '02:01', '2026-09-01'),
            ('maimai', 'maimai', '04:00', '2026-08-31'),
            ('maimai', 'maimai', '04:01', '2026-09-01'),
            ('ongeki', 'ongeki', '03:59', '2026-08-31'),
            ('maimai', 'card_maker', '01:59', '2026-08-31'),
            ('maimai', 'card_maker', '03:00', '2026-09-01'),
            ('maimai', None, '01:59', '2026-09-01'),
            ('chunithm_intl', 'chunithm_intl', '01:59', '2026-09-01'),
            ('chunithm_intl', 'card_maker', '01:59', '2026-09-01'),
            ('maimai', 'chunithm', '01:59', '2026-09-01'),
        ]
        for game, service, clock, expected in cases:
            with self.subTest(game=game, service=service, clock=clock):
                item = entry(type='service_change', service=service, start_is_deadline=True,
                             start='2026-09-01', start_time=clock, open_ended=False)
                result = self.extract(response_payload({'entries': [item], 'review_notes': []}),
                                      ARTICLE | {'game': game})
                actual = result['entries'][0]
                self.assertEqual(actual['calendar_start'], expected)
                self.assertEqual(actual['start'], '2026-09-01')
                self.assertEqual(actual['start_time'], clock)
                self.assertEqual(actual['evidence'], item['evidence'])
                if service is None:
                    self.assertEqual(result['status'], 'needs_review')

    def test_same_article_services_and_start_actions_are_independent(self):
        items = [
            entry(type='service_change', service='card_maker', start_is_deadline=True,
                  start='2026-09-02', start_time='01:59', open_ended=False),
            entry(type='service_change', service='maimai', start_time='01:59', open_ended=False),
        ]
        result = self.extract(response_payload({'entries': items, 'review_notes': []}),
                              ARTICLE | {'game': 'maimai'})
        self.assertEqual([e['calendar_start'] for e in result['entries']], ['2026-09-01', '2026-09-25'])
        self.assertEqual(result['source']['game'], 'maimai')
        instructions = json.loads(self.requests[0].content)['instructions']
        self.assertIn('card_maker: 02:00〜07:00', instructions)
        self.assertIn('maimai: 04:00〜07:00', instructions)

    def test_period_end_uses_last_available_day_and_can_become_single_day(self):
        item = entry(type='event', service='maimai', start='2026-09-01', start_time='07:00',
                     end='2026-09-02', end_time='03:59', open_ended=False)
        result = self.extract(response_payload({'entries': [item], 'review_notes': []}),
                              ARTICLE | {'game': 'maimai'})
        self.assertEqual(result['entries'][0]['calendar_end'], '2026-09-01')
        self.assertEqual(result['entries'][0]['end'], '2026-09-02')
        item['end'] = '2026-09-01'
        result = self.extract(response_payload({'entries': [item], 'review_notes': []}),
                              ARTICLE | {'game': 'maimai'})
        self.assertEqual(result['entries'][0]['calendar_end'], '2026-09-01')
        self.assertTrue(any('前日補正' in r for r in result['review_reasons']))

    def test_maintenance_missing_time_and_daytime_deadlines_stay_on_original_date(self):
        for changes in [
            {'type': 'maintenance', 'start_is_deadline': False},
            {'start_time': None}, {'start_time': '07:00'}, {'start_time': '10:00'},
        ]:
            item = entry(type='service_change', start_is_deadline=True, start_time='02:00',
                         start='2026-01-01', open_ended=False)
            item.update(changes)
            result = self.extract(response_payload({'entries': [item], 'review_notes': []}))
            self.assertEqual(result['entries'][0]['calendar_start'], '2026-01-01')
        item = entry(type='service_change', start_is_deadline=True, start_time='01:59',
                     start='2026-01-01', open_ended=False)
        result = self.extract(response_payload({'entries': [item], 'review_notes': []}))
        self.assertEqual(result['entries'][0]['calendar_start'], '2025-12-31')

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
                        entry(open_ended='true'), entry(service='invented'), entry(start_is_deadline='true')]:
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

    def test_event_membership_is_saved_with_program_generated_id(self):
        body = '作品Aのイベントとテクニカルチャレンジを開催。'
        event = entry(type='event', title='作品A', end='2026-11-11', open_ended=False,
                      songs=[], event_name='作品A', event_evidence=body)
        related = event | {'type': 'technical_challenge'}
        article = ARTICLE | {'game': 'ongeki', 'body_text': body}
        event['service'] = related['service'] = 'ongeki'
        result = self.extract(response_payload({'entries': [event, related], 'review_notes': []}), article)
        first, second = result['entries']
        self.assertIsNotNone(first['event_id'])
        self.assertEqual(first['event_id'], second['event_id'])
        request = json.loads(self.requests[0].content)
        properties = request['text']['format']['schema']['$defs']['Entry']['properties']
        self.assertIn('event_name', properties)
        self.assertIn('event_evidence', properties)
        self.assertNotIn('event_id', properties)
        self.assertIn('同じ日程', request['instructions'])
        event['event_evidence'] = '原文にない引用'
        result = self.extract(response_payload({'entries': [event], 'review_notes': []}), article)
        self.assertIsNone(result['entries'][0]['event_id'])
        self.assertTrue(any('自動グループ化しません' in reason for reason in result['review_reasons']))

    def test_content_hash_includes_metadata(self):
        payload = response_payload({'entries': [], 'review_notes': []})
        first = self.extract(payload)
        second = self.extract(payload, ARTICLE | {'title': '変更'})
        self.assertNotEqual(first['content_hash'], second['content_hash'])

    def test_no_arguments_extracts_all_articles_to_default_output(self):
        articles = [ARTICLE, ARTICLE | {'game': 'maimai'}]
        Path('news_all.json').write_text(json.dumps(articles), encoding='utf-8')
        client = OpenAI(api_key='test-key', max_retries=0, http_client=httpx2.Client(
            transport=httpx2.MockTransport(lambda request: httpx2.Response(
                200, json=response_payload({'entries': [], 'review_notes': []})))))
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-key'}, clear=True), \
             patch('mg_update_calendar.llm.OpenAI', return_value=client) as factory, \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main([]), 0)
        factory.assert_called_once_with(api_key='test-key', timeout=120.0, max_retries=2)
        data = json.loads(Path('entries.json').read_text(encoding='utf-8'))
        self.assertEqual(data['model'], 'gpt-5.6-luna')
        self.assertEqual(data['mode'], 'extraction')
        self.assertEqual(data['schema_version'], 4)
        self.assertEqual(data['prompt_version'], '5')
        self.assertEqual([item['source']['game'] for item in data['articles']], ['chunithm', 'maimai'])
        self.assertNotIn('requests', data)

    def test_cli_concurrency_limit_partial_save_and_input_order(self):
        for concurrency in (1, 2, 5):
            with self.subTest(concurrency=concurrency):
                source, target = Path('news_all.json'), Path('entries.json')
                articles = [ARTICLE | {'url': f'https://example.com/news/{i}'}
                            for i in range(concurrency + 2)]
                source.write_text(json.dumps(articles), encoding='utf-8')
                barrier = threading.Barrier(concurrency)
                release_first = threading.Event()
                lock = threading.Lock()
                active = 0
                peak = 0
                saved = []
                from mg_update_calendar.extractor import write_json

                def handler(request):
                    nonlocal active, peak
                    article = json.loads(json.loads(request.content)['input'][0]['content'])
                    index = int(article['url'].rsplit('/', 1)[1])
                    with lock:
                        active += 1
                        peak = max(peak, active)
                    try:
                        if index < concurrency:
                            barrier.wait(timeout=5)
                        if index == 0 and concurrency > 1:
                            if not release_first.wait(timeout=5):
                                raise AssertionError('Later articles must be saved before the first completes')
                        payload = (response_payload(refusal=True) if index == 1 else
                                   response_payload({'entries': [], 'review_notes': []}))
                        return httpx2.Response(200, json=payload)
                    finally:
                        with lock:
                            active -= 1

                def save(path, document):
                    write_json(path, document)
                    urls = [item['source']['url'] for item in json.loads(path.read_text(encoding='utf-8'))['articles']]
                    saved.append(urls)
                    if urls and articles[0]['url'] not in urls:
                        release_first.set()

                client = OpenAI(api_key='test-key', max_retries=0, http_client=httpx2.Client(
                    transport=httpx2.MockTransport(handler)))
                arguments = []
                with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-key'}), \
                     patch('mg_update_calendar.llm.OpenAI', return_value=client), \
                     patch('mg_update_calendar.extractor.CONCURRENCY', concurrency), \
                     patch('mg_update_calendar.extractor.write_json', side_effect=save), \
                     contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    code = main(arguments)
                self.assertEqual(code, 1)
                self.assertEqual(peak, concurrency)
                results = json.loads(target.read_text(encoding='utf-8'))['articles']
                self.assertEqual([item['source']['url'] for item in results], [item['url'] for item in articles])
                self.assertEqual(results[1]['status'], 'failed')
                self.assertEqual(len(saved), len(articles) + 1)
                if concurrency > 1:
                    self.assertTrue(release_first.is_set())
                self.assertTrue(client.is_closed())

    def test_removed_options_do_not_overwrite_output(self):
        Path('news_all.json').write_text(json.dumps([ARTICLE]), encoding='utf-8')
        Path('entries.json').write_text('keep', encoding='utf-8')
        options = [['--dry-run'], ['--model', 'example'], ['--concurrency', '1'],
                   ['--max-articles', '1'], ['--max-output-tokens', '8192'], ['--timeout', '120'],
                   ['--input', 'other.json'], ['--output', 'other.json']]
        for option in options:
            with self.subTest(option=option), contextlib.redirect_stderr(io.StringIO()), \
                 patch('mg_update_calendar.llm.OpenAI') as client:
                with self.assertRaises(SystemExit) as error:
                    main(option)
                self.assertEqual(error.exception.code, 2)
                self.assertEqual(Path('entries.json').read_text(encoding='utf-8'), 'keep')
                client.assert_not_called()

    def test_missing_key_and_invalid_input_do_not_overwrite_output(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path('news_all.json'), Path('entries.json')
            for raw in [[ARTICLE], {'wrong': 'shape'}]:
                source.write_text(json.dumps(raw), encoding='utf-8')
                target.write_text('keep', encoding='utf-8')
                with patch.dict(os.environ, {}, clear=True), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(main([]), 2)
                self.assertEqual(target.read_text(encoding='utf-8'), 'keep')

    def test_cli_continues_after_failure_and_saves_results(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path('news_all.json'), Path('entries.json')
            source.write_text(json.dumps([ARTICLE, ARTICLE | {'url': 'https://example.com/news/2'}]), encoding='utf-8')
            payloads = iter([response_payload(refusal=True), response_payload({'entries': [entry()], 'review_notes': []})])
            client = OpenAI(api_key='test-key', max_retries=0, http_client=httpx2.Client(
                transport=httpx2.MockTransport(lambda request: httpx2.Response(200, json=next(payloads)))))
            with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-key'}), patch('mg_update_calendar.llm.OpenAI', return_value=client), \
                 patch('mg_update_calendar.extractor.CONCURRENCY', 1):
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    code = main([])
            self.assertEqual(code, 1)
            results = json.loads(target.read_text(encoding='utf-8'))['articles']
            self.assertEqual([item['status'] for item in results], ['failed', 'extracted'])


if __name__ == '__main__':
    unittest.main()
