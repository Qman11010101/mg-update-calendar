import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from mg_update_calendar import main


GAMES = ['chunithm', 'maimai', 'ongeki', 'chunithm_intl']


class ScraperCLITests(unittest.TestCase):
    def run_cli(self, args, output):
        with tempfile.TemporaryDirectory() as directory:
            with contextlib.chdir(directory), \
                    patch('mg_update_calendar.scraper.scrape') as scrape, \
                    contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()):
                scrape.side_effect = lambda **kwargs: [{'game': kwargs['game']}]
                self.assertEqual(main(args), 0)
                articles = json.loads(Path(output).read_text(encoding='utf-8'))
                self.assertEqual(os.listdir(), [output])
                return scrape.call_args_list, articles

    def test_no_arguments_collects_all_games_to_default_output(self):
        calls, articles = self.run_cli([], 'news_all.json')
        self.assertEqual([call.kwargs['game'] for call in calls], GAMES)
        self.assertEqual(articles, [{'game': game} for game in GAMES])
        self.assertTrue(all(call.kwargs['fetch_detail'] for call in calls))
        self.assertTrue(all(call.kwargs['max_pages'] == 1 for call in calls))
        self.assertTrue(all(call.kwargs['fetcher'] is calls[0].kwargs['fetcher']
                            for call in calls))

    def test_explicit_all_collects_all_games(self):
        calls, articles = self.run_cli(['--game', 'all'], 'news_all.json')
        self.assertEqual([call.kwargs['game'] for call in calls], GAMES)
        self.assertEqual(articles, [{'game': game} for game in GAMES])

    def test_explicit_game_collects_only_selected_game(self):
        for game in GAMES:
            with self.subTest(game=game):
                calls, articles = self.run_cli(['--game', game], 'news_all.json')
                self.assertEqual([call.kwargs['game'] for call in calls], [game])
                self.assertEqual(articles, [{'game': game}])

    def test_max_pages_is_passed_to_all_games(self):
        calls, articles = self.run_cli(['--max-pages', '3'], 'news_all.json')
        self.assertEqual([call.kwargs['game'] for call in calls], GAMES)
        self.assertTrue(all(call.kwargs['max_pages'] == 3 for call in calls))
        self.assertEqual(articles, [{'game': game} for game in GAMES])

    def test_removed_options_are_rejected(self):
        for option in [['--no-detail'], ['--max-articles', '1'], ['--interval', '1'],
                       ['--output', 'other.json']]:
            with self.subTest(option=option), contextlib.redirect_stderr(io.StringIO()), \
                 patch('mg_update_calendar.scraper.scrape') as scrape:
                with self.assertRaises(SystemExit) as error:
                    main(option)
                self.assertEqual(error.exception.code, 2)
                scrape.assert_not_called()


if __name__ == '__main__':
    unittest.main()
