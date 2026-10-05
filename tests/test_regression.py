import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from mg_update_calendar.regression import DEFAULT_CASES, evaluate, load_cases, main, matches

ROOT = Path(__file__).resolve().parents[1]


def entry(**changes):
    data = {'type': 'song_add', 'title': '楽曲追加', 'subject': None, 'label': '楽曲追加', 'start': '2026-09-25',
            'end': None, 'songs': [{'title': '曲A', 'artist': None}, {'title': '曲B', 'artist': None}]}
    return data | changes


class RegressionTests(unittest.TestCase):
    def test_patterns_match_fields_and_included_songs(self):
        self.assertTrue(matches(entry(), {'type': 'song_add', 'start': '2026-09-25'}))
        self.assertTrue(matches(entry(), {'songs_include': ['曲B']}))
        self.assertFalse(matches(entry(), {'songs_include': ['曲B', '曲C']}))
        self.assertFalse(matches(entry(), {'start': '2025-09-25'}))
        self.assertTrue(matches(entry(), {'end': None}))

    def test_expect_forbid_count_and_status_are_checked(self):
        case = {'url': 'u', 'status': 'extracted',
                'expect': [{'type': 'song_add'}, {'type': 'event'}],
                'forbid': [{'type': 'version_launch'}],
                'count': {'song_add': [1, 1]}}
        result = {'status': 'needs_review',
                  'entries': [entry(), entry(), entry(type='version_launch', title='X 稼働')]}
        failures = evaluate(case, result)
        self.assertEqual(len(failures), 4)
        self.assertTrue(any('needs_review' in item for item in failures))
        self.assertTrue(any('type=event' in item for item in failures))
        self.assertTrue(any('X 稼働' in item for item in failures))
        self.assertTrue(any('song_addが2件' in item for item in failures))
        self.assertEqual(evaluate(case, {'status': 'extracted', 'entries': [entry(), entry(type='event')]}), [])
        self.assertEqual(evaluate(case, {'status': 'failed', 'error': 'refusal', 'entries': []}),
                         ['抽出に失敗しました: refusal'])

    def test_case_file_is_valid(self):
        cases = load_cases(ROOT / DEFAULT_CASES)
        self.assertTrue(cases)
        self.assertTrue(all(case.get('reason') and (case.get('expect') or case.get('forbid')) for case in cases))

    def test_unknown_fields_and_duplicates_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'cases.json'
            for cases in ([{'url': 'u', 'expect': [{'titel': 'x'}]}],
                          [{'url': 'u', 'expect': []}, {'url': 'u', 'expect': []}]):
                with self.subTest(cases=cases):
                    path.write_text(json.dumps(cases, ensure_ascii=False), encoding='utf-8')
                    with self.assertRaises(ValueError):
                        load_cases(path)

    def test_existing_results_are_checked_without_llm(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.chdir(directory):
            Path('cases.json').write_text(json.dumps([
                {'url': 'u1', 'reason': '通る', 'expect': [{'type': 'song_add'}]},
                {'url': 'u2', 'reason': '落ちる', 'expect': [{'type': 'event'}]},
            ]), encoding='utf-8')
            articles = [{'source': {'url': url}, 'status': 'extracted', 'entries': [entry()]} for url in ('u1', 'u2')]
            Path('entries.json').write_text(json.dumps({'articles': articles}), encoding='utf-8')
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(['--cases', 'cases.json', '--from', 'entries.json'])
            self.assertEqual(code, 1)
            self.assertIn('1/2 cases passed', output.getvalue())
            Path('runs.json').write_text(json.dumps({'runs': {'u1': [articles[0], articles[0]]}}), encoding='utf-8')
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(['--cases', 'cases.json', '--from', 'runs.json', '--case', 'u1'])
            self.assertEqual(code, 0)
            self.assertIn('OK  2/2 u1', output.getvalue())


if __name__ == '__main__':
    unittest.main()
