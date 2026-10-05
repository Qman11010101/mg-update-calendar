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

from mg_update_calendar.extractor import content_hash, extract_article, main
from mg_update_calendar.prompts import PROMPT_VERSION
from mg_update_calendar.models import Article, Cancellation, Entry, display_title, subject_key
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
        'type': 'song_add', 'subject': None, 'label': '楽曲追加', 'official_name': None, 'start': '2026-09-25',
        'start_time': None, 'end': None, 'end_time': None, 'open_ended': True,
        'songs': ['曲A', '曲B'], 'date_text': '2026年9月25日より',
        'evidence': '「曲A」「曲B」が追加。', 'confidence': 0.95,
    }
    return data | changes


def wire_extraction(extraction):
    return {'entries': extraction['entries'], 'cancellations': extraction.get('cancellations', []),
            'notes': extraction.get('notes', []), 'review_notes': extraction['review_notes']}


def response_payload(extraction=None, status='completed', refusal=False):
    if extraction is not None:
        extraction = wire_extraction(extraction)
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
        event = entry(type='event', subject='作品A', label='コラボイベント', end='2026-11-11', open_ended=False, songs=[],
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
                    self.assertEqual(set(allowed), set(definitions['Cancellation']['properties']['target_type']['enum']))
                    self.assertIn(game, body['instructions'])

    def test_goods_campaign_for_all_games_and_cancellations(self):
        evidence = '2026年9月25日～2026年11月11日、グッズ交換キャンペーンを開催。'
        campaign = entry(type='goods_campaign', label='グッズ交換キャンペーン', songs=[],
                         end='2026-11-11', open_ended=False,
                         date_text='2026年9月25日～2026年11月11日', evidence=evidence)
        for game in ['chunithm', 'maimai', 'ongeki']:
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
                cancellation = {'target_type': 'goods_campaign', 'subject': None, 'label': campaign['label'], 'official_name': None,
                                'songs': [], 'evidence': 'グッズ交換キャンペーンを中止します。',
                                'confidence': 0.95}
                result = self.extract(response_payload({'entries': [], 'cancellations': [cancellation],
                                                       'review_notes': []}),
                                      article | {'body_text': cancellation['evidence']})
                self.assertNotEqual(result['status'], 'failed')
                self.assertEqual(result['entries'], [])
                self.assertEqual(result['cancellations'], [{'title': 'グッズ交換キャンペーン'} | cancellation])

    def test_chunithm_login_bonus_is_extracted_and_allowed_by_schema(self):
        quote = '2026年7月2日～7月15日の期間中に特別なログインボーナスが登場します！'
        bonus = entry(type='login_bonus', subject='Mate', label='ログインボーナス', official_name='【祝】Mate ログインボーナス', songs=[],
                      start='2026-07-02', end='2026-07-15', open_ended=False,
                      date_text='2026年7月2日～7月15日', evidence=quote)
        result = self.extract(response_payload({'entries': [entry(), bonus], 'review_notes': []}),
                              ARTICLE | {'body_text': ARTICLE['body_text'] + quote})
        self.assertEqual(result['status'], 'extracted')
        self.assertEqual(result['attempts'], 1)
        self.assertEqual([e['type'] for e in result['entries']], ['song_add', 'login_bonus'])
        schema = json.loads(self.requests[0].content)['text']['format']['schema']
        for model, field in [('Entry', 'type'), ('Cancellation', 'target_type')]:
            self.assertIn('login_bonus', schema['$defs'][model]['properties'][field]['enum'])
        cancellation = {'target_type': 'login_bonus', 'subject': 'Mate', 'label': 'ログインボーナス', 'official_name': bonus['official_name'], 'songs': [],
                        'evidence': 'ログインボーナスを中止します。', 'confidence': 0.95}
        result = self.extract(response_payload({'entries': [], 'cancellations': [cancellation],
                                               'review_notes': []}),
                              ARTICLE | {'body_text': cancellation['evidence']})
        self.assertIsNone(result['error'])
        self.assertEqual(result['cancellations'], [{'title': '【祝】Mate ログインボーナス'} | cancellation])

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
        cancellation = {'target_type': 'song_add', 'subject': '曲A', 'label': '収録見合わせ', 'official_name': None,
                        'songs': ['曲A'], 'evidence': '曲Aの収録を見合わせます。', 'confidence': 0.95}
        article = ARTICLE | {'body_text': cancellation['evidence']}
        result = self.extract(response_payload({'entries': [], 'cancellations': [cancellation], 'review_notes': []}), article)
        self.assertEqual(result['entries'], [])
        self.assertEqual(result['cancellations'], [{'title': '「曲A」収録見合わせ'} | cancellation])
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
                        self.assertEqual(result['entries'], [{'title': '楽曲追加'} | kept | {'calendar_start': kept['start'], 'calendar_end': kept['end']}])
                        self.assertEqual(result['error'], None)
                        self.assertIn('曲名は画像内にあります。', result['review_reasons'])

    def test_only_empty_song_entry_becomes_successful_empty_extraction(self):
        result = self.extract(response_payload({
            'entries': [entry(label='新曲を大量追加！', songs=[])], 'review_notes': [],
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
                for item in entries:
                    if item['type'] == 'event':
                        item.update(subject='作品A', label='コラボイベント', evidence=ARTICLE['body_text'], end='2026-11-11', open_ended=False)
                cancellation = {'target_type': 'song_add', 'subject': None, 'label': '収録見合わせ', 'official_name': None,
                                'songs': [], 'evidence': ARTICLE['body_text'], 'confidence': 0.95}
                result = self.extract(response_payload({
                    'entries': entries, 'cancellations': [cancellation], 'review_notes': [],
                }), ARTICLE | {'game': game})
                self.assertCountEqual([e['type'] for e in result['entries']], [e['type'] for e in entries])
                self.assertTrue(all(e['songs'] == [] for e in result['entries']))
                for expected in entries:
                    actual = next(e for e in result['entries'] if e['type'] == expected['type'])
                    for field in ('start', 'end', 'subject', 'label', 'open_ended'):
                        self.assertEqual(actual[field], expected[field])
                self.assertEqual(result['cancellations'], [{'title': '収録見合わせ'} | cancellation])

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
        item = entry(type='event', subject='作品A', label='コラボイベント', evidence=ARTICLE['body_text'], service='maimai', start='2026-09-01', start_time='07:00',
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

    def test_song_entries_with_end_date_need_review(self):
        result = self.extract(response_payload({'entries': [
            entry(type='song_unlock', label='楽曲一般開放', end='2026-11-11', open_ended=False)], 'review_notes': []}))
        self.assertEqual(result['status'], 'needs_review')
        self.assertTrue(any('楽曲・譜面追加に終了日' in reason for reason in result['review_reasons']))
        self.assertEqual(result['entries'][0]['end'], '2026-11-11')

    def test_unknown_dates_and_low_confidence_are_preserved(self):
        result = self.extract(response_payload({'entries': [entry(start=None, date_text='', confidence=0.4)], 'review_notes': ['年が不明']}))
        self.assertEqual(result['status'], 'needs_review')
        self.assertIsNone(result['entries'][0]['start'])
        self.assertIn('年が不明', result['review_reasons'])

    def test_markdown_quote_keeps_original_whitespace(self):
        article = ARTICLE | {'body_markdown': '2026年9月25日\nより「曲A」が追加。'}
        result = self.extract(response_payload({'entries': [entry(date_text='2026年9月25日\nより')], 'review_notes': []}), article)
        self.assertEqual(result['status'], 'extracted')

    def test_quote_ignores_whitespace_and_markdown_differences(self):
        article = ARTICLE | {'body_markdown': '## でらっくす譜面追加\n\n**曲A**  \n「作品B」より'}
        result = self.extract(response_payload({'entries': [
            entry(date_text='2026年9月25日\nより', evidence='でらっくす譜面追加\n曲A\n「作品Ｂ」より')], 'review_notes': []}), article)
        self.assertEqual(result['status'], 'extracted')

    def test_quote_of_only_markup_is_not_evidence(self):
        result = self.extract(response_payload({'entries': [entry(evidence='## **')], 'review_notes': []}))
        self.assertEqual(result['status'], 'needs_review')
        self.assertTrue(any('evidenceの原文根拠' in reason for reason in result['review_reasons']))

    def test_notes_are_kept_without_review(self):
        result = self.extract(response_payload({'entries': [entry()], 'notes': ['年は公開日から補完しました。'],
                                                'review_notes': []}))
        self.assertEqual(result['status'], 'extracted')
        self.assertEqual(result['notes'], ['年は公開日から補完しました。'])
        self.assertEqual(result['review_reasons'], [])

    def test_empty_body_needs_review(self):
        result = self.extract(
            response_payload({'entries': [], 'review_notes': []}),
            ARTICLE | {'body_text': ''},
        )
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

    def test_events_and_other_announcements_are_independent(self):
        body = '作品Aのイベントとテクニカルチャレンジを開催。'
        event = entry(type='event', subject='作品A', label='イベント', end='2026-11-11', open_ended=False,
                      songs=[], evidence=body, service='ongeki')
        challenge = event | {'type': 'technical_challenge', 'end': '2026-12-01'}
        result = self.extract(response_payload({'entries': [event, challenge], 'review_notes': []}),
                              ARTICLE | {'game': 'ongeki', 'body_text': body})
        self.assertIsNone(result['error'])
        self.assertEqual(result['attempts'], 1)
        self.assertEqual([e['end'] for e in result['entries']], ['2026-11-11', '2026-12-01'])
        request = json.loads(self.requests[0].content)
        schema = request['text']['format']['schema']
        self.assertEqual(set(schema['properties']), {'entries', 'cancellations', 'notes', 'review_notes'})
        for key in ('parent_ref', 'event_ref', 'relation_evidence', 'event_name', 'event_evidence',
                    'event_id', 'event_parent_id'):
            self.assertNotIn(key, schema['$defs']['Entry']['properties'])
            self.assertTrue(all(key not in e for e in result['entries']))
        self.assertIn('event', schema['$defs']['Entry']['properties']['type']['enum'])
        self.assertNotIn('events', result)

    def test_collab_contents_are_merged_into_the_matching_event(self):
        body = '作品Aちほー2と作品Bちほー2がオープン。作品Aのコラボ第2弾と作品Aのリバイバルを開催。'
        maimai = ARTICLE | {'game': 'maimai', 'body_text': body}
        base = entry(service='maimai', songs=[], evidence=body, open_ended=False, label='イベント')
        collab = base | {'type': 'event', 'subject': '作品A 第2弾', 'label': 'コラボイベント'}
        revival = base | {'type': 'event', 'subject': '作品A', 'label': 'リバイバルイベント', 'end': '2026-11-11'}
        area = base | {'type': 'area_add', 'subject': '作品Aちほー2', 'label': 'ちほー追加',
                       'start_time': '10:00', 'end': '2026-11-11'}
        other_area = area | {'subject': 'k4sen ＆ 作品Aちほー2'}
        result = self.extract(response_payload({'entries': [collab, revival, area, other_area], 'review_notes': []}),
                              maimai)
        self.assertEqual([(e['type'], e['subject']) for e in result['entries']],
                         [('event', '作品A 第2弾'), ('event', '作品A'), ('area_add', 'k4sen ＆ 作品Aちほー2')])
        merged = result['entries'][0]
        self.assertEqual((merged['start_time'], merged['end'], merged['open_ended']), ('10:00', '2026-11-11', False))
        self.assertEqual(len(result['notes']), 1)
        self.assertIn('作品Aちほー2', result['notes'][0])

        for changes in ({'start': '2026-09-26'}, {'end': '2026-12-01'}, {'subject': '作品Aちほー3'}):
            with self.subTest(changes=changes):
                result = self.extract(response_payload({'entries': [collab | {'end': '2026-11-11'}, area | changes],
                                                        'review_notes': []}), maimai)
                self.assertEqual([e['type'] for e in result['entries']], ['event', 'area_add'])

        chiho_event = base | {'type': 'event', 'subject': '天界ちほー9', 'end': '2026-11-11'}
        chiho = area | {'subject': '天界ちほー9', 'end': None}
        result = self.extract(response_payload({'entries': [chiho_event, chiho], 'review_notes': []}), maimai)
        self.assertEqual([(e['type'], e['start_time'], e['end']) for e in result['entries']],
                         [('area_add', '10:00', '2026-11-11')])

        map_entry = base | {'type': 'map_add', 'subject': '作品C 第二弾', 'label': 'マップ追加', 'service': 'chunithm'}
        event = map_entry | {'type': 'event', 'label': 'コラボイベント', 'end': '2026-10-21'}
        result = self.extract(response_payload({'entries': [event, map_entry], 'review_notes': []}),
                              ARTICLE | {'body_text': body})
        self.assertEqual([(e['type'], e['end']) for e in result['entries']], [('event', '2026-10-21')])

    def test_content_hash_includes_metadata(self):
        payload = response_payload({'entries': [], 'review_notes': []})
        first = self.extract(payload)
        second = self.extract(payload, ARTICLE | {'title': '変更'})
        self.assertNotEqual(first['content_hash'], second['content_hash'])

    def test_no_arguments_extracts_all_articles_to_default_output(self):
        articles = [ARTICLE, ARTICLE | {'game': 'maimai', 'url': 'https://example.com/news/2'}]
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
        self.assertEqual(data['schema_version'], 7)
        self.assertEqual(data['prompt_version'], '27')
        self.assertEqual([item['source']['game'] for item in data['articles']], ['chunithm', 'maimai'])
        self.assertNotIn('requests', data)

    def test_cli_concurrency_limit_partial_save_and_input_order(self):
        for concurrency in (1, 2, 5):
            with self.subTest(concurrency=concurrency):
                source, target = Path('news_all.json'), Path('entries.json')
                target.unlink(missing_ok=True)
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
        options = [['--model', 'example'], ['--concurrency', '1'],
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


def news(number, **changes):
    return ARTICLE | {'url': f'https://example.com/news/{number}'} | changes


def previous_result(article, **changes):
    return {'source': {'game': article['game'], 'url': article['url'], 'date': article['date'],
                       'title': article['title']},
            'content_hash': content_hash(Article.model_validate(article)), 'status': 'extracted',
            'entries': [{'title': '前回', 'calendar_start': '2026-09-25', 'calendar_end': None}],
            'prompt_version': PROMPT_VERSION} | changes


class IncrementalExtractionTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(contextlib.chdir(directory))

    def run_cli(self, articles, previous, arguments=(), payload=None, environment=None):
        Path('news_all.json').write_text(json.dumps(articles), encoding='utf-8')
        if previous is not None:
            Path('entries.json').write_text(json.dumps(previous), encoding='utf-8')
        self.extracted = []

        def handler(request):
            self.extracted.append(json.loads(json.loads(request.content)['input'][0]['content'])['url'])
            return httpx2.Response(200, json=payload or response_payload({'entries': [entry()], 'review_notes': []}))

        client = OpenAI(api_key='test-key', max_retries=0, http_client=httpx2.Client(
            transport=httpx2.MockTransport(handler)))
        environment = {'OPENAI_API_KEY': 'test-key'} if environment is None else environment
        with patch.dict(os.environ, environment, clear=True), \
             patch('mg_update_calendar.llm.OpenAI', return_value=client), \
             patch('mg_update_calendar.extractor.CONCURRENCY', 1), \
             contextlib.redirect_stdout(io.StringIO()) as stdout, contextlib.redirect_stderr(io.StringIO()) as stderr:
            self.code = main(list(arguments))
        self.stdout, self.stderr = stdout.getvalue(), stderr.getvalue()
        return json.loads(Path('entries.json').read_text(encoding='utf-8'))

    def document(self, *results, schema_version=7, model='gpt-5.6-luna'):
        return {'schema_version': schema_version, 'prompt_version': PROMPT_VERSION, 'provider': 'openai',
                'model': model, 'mode': 'extraction', 'articles': list(results)}

    def test_only_new_and_changed_articles_are_extracted_and_others_are_kept(self):
        kept, changed, orphan = news(1), news(2), news(9)
        previous = self.document(previous_result(kept), previous_result(changed | {'title': '旧'}),
                                 previous_result(orphan), schema_version=6)
        data = self.run_cli([kept, changed, news(3)], previous)
        self.assertEqual(self.code, 0)
        self.assertEqual(self.extracted, [changed['url'], news(3)['url']])
        self.assertEqual(data['schema_version'], 7)
        self.assertEqual([item['source']['url'] for item in data['articles']],
                         [kept['url'], changed['url'], news(3)['url'], orphan['url']])
        self.assertEqual(data['articles'][0], previous_result(kept) | {'provider': 'openai', 'model': 'gpt-5.6-luna'})
        self.assertEqual(data['articles'][1]['entries'][0]['songs'], ['曲A', '曲B'])
        self.assertEqual((data['articles'][2]['provider'], data['articles'][2]['model']), ('openai', 'gpt-5.6-luna'))
        self.assertIn('[changed]', self.stderr)
        self.assertIn('  - 前回 2026-09-25', self.stderr)
        self.assertIn('  + 楽曲追加 2026-09-25', self.stderr)
        self.assertIn('extracted=2, reused=1, failed=0', self.stdout)

    def test_prompt_model_and_failure_trigger_extraction(self):
        articles = [news(1), news(2), news(3), news(4)]
        previous = self.document(previous_result(articles[0], prompt_version='0'),
                                 previous_result(articles[1], model='other-model'),
                                 previous_result(articles[2], status='failed'),
                                 previous_result(articles[3]))
        for item in previous['articles'][1:]:
            item.setdefault('provider', 'openai')
            item.setdefault('model', 'gpt-5.6-luna')
        self.run_cli(articles, previous, ['--dry-run'])
        self.assertEqual(self.stdout.splitlines()[:3],
                         [f'{reason}: [chunithm] 2026-09-22 {ARTICLE["title"]} {article["url"]}'
                          for reason, article in zip(['prompt', 'model', 'failed'], articles)])
        self.assertIn('extract=3, reuse=1', self.stdout)

    def test_full_and_url_force_extraction(self):
        articles = [news(1), news(2)]
        previous = self.document(*[previous_result(article) for article in articles])
        self.run_cli(articles, previous, ['--url', news(2)['url']])
        self.assertEqual(self.extracted, [news(2)['url']])
        self.run_cli(articles, None, ['--full'])
        self.assertEqual(self.extracted, [news(1)['url'], news(2)['url']])

    def test_unknown_url_is_rejected(self):
        Path('news_all.json').write_text(json.dumps([news(1)]), encoding='utf-8')
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-key'}, clear=True), \
             contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            main(['--url', news(2)['url']])
        self.assertEqual(error.exception.code, 2)
        self.assertFalse(Path('entries.json').exists())

    def test_failure_keeps_the_previous_successful_result(self):
        article = news(1)
        before = previous_result(article | {'title': '旧'})
        data = self.run_cli([article], self.document(before), payload=response_payload(refusal=True))
        self.assertEqual(self.code, 1)
        self.assertEqual(data['articles'][0]['entries'], before['entries'])
        self.assertIn('前回の結果を残します', self.stderr)

    def test_dry_run_and_full_reuse_need_no_key_or_llm(self):
        article = news(1)
        previous = self.document(previous_result(article) | {'provider': 'openai', 'model': 'gpt-5.6-luna'})
        Path('entries.json').write_text(json.dumps(previous), encoding='utf-8')
        self.run_cli([article, news(2)], None, ['--dry-run'], environment={})
        self.assertEqual(self.code, 0)
        self.assertEqual(json.loads(Path('entries.json').read_text(encoding='utf-8')), previous)
        self.assertIn('new: ', self.stdout)
        data = self.run_cli([article], None, environment={})
        self.assertEqual(self.code, 0)
        self.assertEqual(self.extracted, [])
        self.assertEqual(data['articles'], previous['articles'])

    def test_unreadable_previous_output_is_not_overwritten(self):
        Path('news_all.json').write_text(json.dumps([news(1)]), encoding='utf-8')
        for raw in ['broken', '{"schema_version": 5, "mode": "extraction", "articles": []}', '{"schema_version": 7, "mode": "extraction", "articles": [{}]}']:
            with self.subTest(raw=raw):
                Path('entries.json').write_text(raw, encoding='utf-8')
                with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-key'}, clear=True), \
                     patch('mg_update_calendar.llm.OpenAI') as client, contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(main([]), 2)
                client.assert_not_called()
                self.assertEqual(Path('entries.json').read_text(encoding='utf-8'), raw)


class DisplayTitleTests(unittest.TestCase):
    def test_subject_key_ignores_spacing_and_brackets(self):
        self.assertEqual(subject_key('ゴシックは魔法乙女【第3弾】'), subject_key('ゴシックは魔法乙女 第3弾'))
        self.assertEqual(subject_key('Shooter’s Dream《⊿TRiEDGE》'), subject_key('Shooter’s Dream 《⊿TRiEDGE》'))
        self.assertNotEqual(subject_key('クラッシュフィーバー'), subject_key('クラッシュフィーバー 第二弾'))
        self.assertIsNone(subject_key(' 「」 '))

    def title(self, **changes):
        return display_title(Entry.model_validate(entry(**{'type': 'event'} | changes)))

    def test_titles_are_built_from_subject_label_and_official_name(self):
        cases = [
            ({'subject': 'クラッシュフィーバー 第二弾', 'label': 'コラボイベント'}, '「クラッシュフィーバー 第二弾」コラボイベント'),
            ({'subject': '「Mate ep. III」', 'label': 'マップ追加'}, '「Mate ep. III」マップ追加'),
            ({'subject': '『いよわ』', 'label': 'リバイバルイベント'}, '「いよわ」リバイバルイベント'),
            ({'subject': 'いよわ', 'label': 'ログインボーナス',
              'official_name': 'いよわ　イベント開催記念ログインボーナス'}, 'いよわ　イベント開催記念ログインボーナス'),
            ({'subject': '第9回「皇帝イベント」 ～盟帝～', 'label': 'イベント'}, '第9回「皇帝イベント」 ～盟帝～'),
            ({'subject': '「作品A」と「作品B」', 'label': 'コラボイベント'}, '「「作品A」と「作品B」」コラボイベント'),
            ({'subject': 'ストリートファイター 6', 'label': 'リバイバルイベント',
              'official_name': '『ストリートファイター 6』リバイバルイベント'}, '「ストリートファイター 6」リバイバルイベント'),
            ({'subject': 'いよわ', 'label': 'シルバージュエルイベント',
              'official_name': 'シルバージュエルイベント「いよわ」'}, '「いよわ」シルバージュエルイベント'),
            ({'subject': 'ゴシックは魔法乙女 第3弾', 'label': 'テクニカルチャレンジ',
              'official_name': 'テクニカルチャレンジ「ゴシックは魔法乙女【第3弾】」'}, '「ゴシックは魔法乙女 第3弾」テクニカルチャレンジ'),
            ({'subject': 'いずれ菖蒲か杜若', 'label': 'チュウニズムクエスト',
              'official_name': 'チュウニズムクエスト'}, '「いずれ菖蒲か杜若」チュウニズムクエスト'),
            ({'subject': 'サークルフェスタ シーズン3', 'label': 'イベント',
              'official_name': 'サークルフェスタ シーズン3'}, '「サークルフェスタ シーズン3」イベント'),
            ({'subject': '9月度', 'label': 'マンスリーミッション',
              'official_name': '9月度 マンスリーミッション'}, '9月度 マンスリーミッション'),
            ({'subject': 'すたんぷカード選択', 'label': '一部すたんぷカード選択終了'}, '一部すたんぷカード選択終了'),
            ({'subject': '「maimai」『オンゲキ』楽曲連動', 'label': 'イベント'}, '「「maimai」「オンゲキ」楽曲連動」イベント'),
            ({'subject': ' ', 'label': 'Aime新規登録機能終了', 'songs': []}, 'Aime新規登録機能終了'),
        ]
        for changes, expected in cases:
            with self.subTest(changes=changes):
                self.assertEqual(self.title(**changes), expected)

    def test_titles_follow_the_format_of_each_type(self):
        cases = [
            ({'type': 'friend_battle', 'subject': 'シーズン29', 'label': 'オトモダチ対戦'}, 'オトモダチ対戦 シーズン29'),
            ({'type': 'friend_battle', 'subject': 'オトモダチ対戦 シーズン29', 'label': 'オトモダチ対戦'}, 'オトモダチ対戦 シーズン29'),
            ({'type': 'area_add', 'subject': 'BLACK ROSEちほー11', 'label': 'ちほー追加'}, 'BLACK ROSEちほー11'),
            ({'type': 'area_add', 'subject': '天界ちほー9', 'label': '追加'}, '天界ちほー9'),
            ({'type': 'area_add', 'subject': '天界ちほー9', 'label': '拡張'}, '天界ちほー9 拡張'),
            ({'type': 'area_add', 'subject': '天界ちほー9', 'label': '追加・拡張'}, '天界ちほー9 追加・拡張'),
            ({'type': 'map_add', 'subject': 'Mate ep. III', 'label': 'マップ追加'}, '「Mate ep. III」マップ'),
            ({'type': 'map_add', 'subject': 'Mate ep. III', 'label': 'マップ拡張'}, '「Mate ep. III」マップ拡張'),
            ({'type': 'chapter_add', 'subject': 'O.N.G.E.K.I. 8th Anniversary', 'label': 'チャプター追加'},
             '「O.N.G.E.K.I. 8th Anniversary」チャプター'),
            ({'type': 'area_add', 'subject': 'ヒメヒナちほー', 'label': 'ちほー復刻'}, 'ヒメヒナちほー 復刻'),
            ({'type': 'goods_campaign', 'subject': 'デジタルアイテムキャンペーン 第3弾', 'label': 'グッズキャンペーン'},
             'デジタルアイテムキャンペーン 第3弾'),
            ({'type': 'goods_campaign', 'subject': 'オンゲキ Re:Fresh', 'label': 'オリジナルグッズプレゼントキャンペーン 第14弾'},
             'オンゲキ Re:Fresh オリジナルグッズプレゼントキャンペーン 第14弾'),
            ({'type': 'version_launch', 'subject': '『CHUNITHM Mate』', 'label': '稼働'}, 'CHUNITHM Mate 稼働'),
            ({'type': 'service_change', 'subject': 'でらっくすパス新規販売停止', 'label': 'サービス変更'}, 'でらっくすパス新規販売停止'),
            ({'type': 'service_change', 'subject': 'カードメイカー CHUNITHMガチャ機能', 'label': '提供終了'},
             'カードメイカー CHUNITHMガチャ機能 提供終了'),
            ({'type': 'other', 'subject': 'まじかるパス', 'label': 'キャラクター追加'}, 'まじかるパス キャラクター追加'),
            ({'type': 'avatar_costume', 'subject': 'Mate ep. II', 'label': 'アバターコスチューム'}, 'アバターコスチューム'),
        ]
        for changes, expected in cases:
            with self.subTest(changes=changes):
                self.assertEqual(self.title(**changes), expected)

    def test_song_titles_use_only_the_label_and_parent_subject(self):
        cases = [
            ({'type': 'song_add', 'subject': None, 'label': '楽曲追加'}, '楽曲追加'),
            ({'type': 'song_add', 'subject': None, 'label': '楽曲追加', 'songs': ['曲A', ' ']}, '楽曲追加'),
            ({'type': 'song_add', 'subject': '曲A', 'label': '楽曲追加', 'songs': ['曲A']}, '楽曲追加'),
            ({'type': 'song_add', 'subject': 'Rotaeno', 'label': '楽曲追加', 'songs': ['曲A', '曲B']}, '「Rotaeno」楽曲追加'),
            ({'type': 'ultima_add', 'subject': '「いよわ」', 'label': 'ULTIMA譜面追加', 'songs': ['曲A']}, '「いよわ」ULTIMA譜面追加'),
            ({'type': 'avatar_costume', 'subject': 'マップA', 'label': 'アバターコスチューム'}, 'アバターコスチューム'),
            ({'type': 'standard_chart_add', 'subject': 'オトモダチ対戦 シーズン29', 'label': 'スタンダード譜面追加'},
             '「オトモダチ対戦 シーズン29」スタンダード譜面追加'),
            ({'type': 'ultima_add', 'subject': '曲A', 'label': 'ULTIMA譜面追加',
              'official_name': '「曲A」ULTIMA譜面追加'}, 'ULTIMA譜面追加'),
        ]
        for changes, expected in cases:
            with self.subTest(changes=changes):
                self.assertEqual(self.title(**changes), expected)

    def test_cancellation_titles_use_the_format_of_the_target_type(self):
        cancellation = Cancellation(target_type='friend_battle', subject='シーズン29', label='オトモダチ対戦',
                                    official_name=None, songs=[], evidence='中止', confidence=0.9)
        self.assertEqual(display_title(cancellation), 'オトモダチ対戦 シーズン29')


if __name__ == '__main__':
    unittest.main()
