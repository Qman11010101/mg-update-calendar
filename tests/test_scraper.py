import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import requests

from mg_update_calendar import main
from mg_update_calendar.scraper import ScrapeError, make_record, merge_articles, needs_refetch, scrape


GAMES = ['chunithm', 'maimai', 'ongeki']


def record(game, number, date='2026-10-01', body='本文'):
    return make_record(game=game, url=f'https://example.com/{game}/{number}', date_raw=date.replace('-', '.'),
                       title=f'{game} {number}', body_text=body, body_markdown=body)


class ScraperCLITests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(contextlib.chdir(directory))

    def run_cli(self, args, scraped=None, code=0):
        scraped = scraped or {game: [record(game, 1)] for game in GAMES}
        with patch('mg_update_calendar.scraper.scrape') as scrape, \
                contextlib.redirect_stdout(io.StringIO()) as stdout, \
                contextlib.redirect_stderr(io.StringIO()):
            def fake(**kwargs):
                result = scraped[kwargs['game']]
                if isinstance(result, Exception):
                    raise result
                return result
            scrape.side_effect = fake
            self.assertEqual(main(args), code)
        self.stdout = stdout.getvalue()
        output = Path('news_all.json')
        articles = json.loads(output.read_text(encoding='utf-8')) if output.exists() else None
        return scrape.call_args_list, articles

    def test_no_arguments_collects_all_games_to_default_output(self):
        calls, articles = self.run_cli([])
        self.assertEqual([call.kwargs['game'] for call in calls], GAMES)
        self.assertEqual(articles, [record(game, 1) for game in GAMES])
        self.assertEqual(os.listdir(), ['news_all.json'])
        self.assertTrue(all(call.kwargs['fetch_detail'] for call in calls))
        self.assertTrue(all(call.kwargs['max_pages'] == 1 for call in calls))
        self.assertTrue(all(call.kwargs['known'] == {} for call in calls))
        self.assertTrue(all(call.kwargs['refresh_since'] is None for call in calls))
        self.assertTrue(all(call.kwargs['fetcher'] is calls[0].kwargs['fetcher']
                            for call in calls))

    def test_explicit_all_collects_all_games(self):
        calls, articles = self.run_cli(['--game', 'all'])
        self.assertEqual([call.kwargs['game'] for call in calls], GAMES)
        self.assertEqual(articles, [record(game, 1) for game in GAMES])

    def test_explicit_game_collects_only_selected_game(self):
        for game in GAMES:
            with self.subTest(game=game):
                Path('news_all.json').unlink(missing_ok=True)
                calls, articles = self.run_cli(['--game', game])
                self.assertEqual([call.kwargs['game'] for call in calls], [game])
                self.assertEqual(articles, [record(game, 1)])

    def test_max_pages_is_passed_to_all_games(self):
        calls, articles = self.run_cli(['--max-pages', '3'])
        self.assertEqual([call.kwargs['game'] for call in calls], GAMES)
        self.assertTrue(all(call.kwargs['max_pages'] == 3 for call in calls))
        self.assertEqual(articles, [record(game, 1) for game in GAMES])

    def test_known_articles_are_passed_and_kept_after_leaving_the_list(self):
        old = record('maimai', 1, date='2026-09-01')
        Path('news_all.json').write_text(json.dumps([old]), encoding='utf-8')
        calls, articles = self.run_cli(['--game', 'maimai'], {'maimai': [record('maimai', 2)]})
        self.assertEqual(calls[0].kwargs['known'], {old['url']: old})
        self.assertEqual(articles, [record('maimai', 2), old])
        self.assertIn('new=1, updated=0', self.stdout)

    def test_selected_game_keeps_other_games(self):
        known = [record(game, 1) for game in GAMES]
        Path('news_all.json').write_text(json.dumps(known), encoding='utf-8')
        changed = record('maimai', 1, body='修正後')
        _, articles = self.run_cli(['--game', 'maimai'], {'maimai': [changed]})
        self.assertEqual(articles, [known[0], changed, known[2]])
        self.assertIn('new=0, updated=1', self.stdout)

    def test_full_ignores_known_articles(self):
        Path('news_all.json').write_text(json.dumps([record('chunithm', 1)]), encoding='utf-8')
        calls, _ = self.run_cli(['--full'])
        self.assertTrue(all(call.kwargs['known'] == {} for call in calls))

    def test_refresh_days_counts_today_as_the_first_day(self):
        with patch('mg_update_calendar.scraper.date') as today:
            today.today.return_value = __import__('datetime').date(2026, 10, 5)
            calls, _ = self.run_cli(['--refresh-days', '7'])
        self.assertTrue(all(call.kwargs['refresh_since'] == '2026-09-29' for call in calls))

    def test_dry_run_fetches_no_details_and_does_not_write(self):
        known = record('chunithm', 1)
        Path('news_all.json').write_text(json.dumps([known]), encoding='utf-8')
        scraped = {'chunithm': [record('chunithm', 2), known], 'maimai': [], 'ongeki': []}
        calls, articles = self.run_cli(['--dry-run'], scraped)
        self.assertTrue(all(not call.kwargs['fetch_detail'] for call in calls))
        self.assertEqual(articles, [known])
        self.assertIn('new: [chunithm]', self.stdout)
        self.assertIn('new=1, refetch=0', self.stdout)

    def test_failed_game_keeps_known_articles_and_returns_1(self):
        known = [record(game, 1, date='2026-09-01') for game in GAMES]
        Path('news_all.json').write_text(json.dumps(known), encoding='utf-8')
        scraped = {'chunithm': [record('chunithm', 2)], 'maimai': ScrapeError('broken'),
                   'ongeki': [record('ongeki', 2)]}
        calls, articles = self.run_cli([], scraped, code=1)
        self.assertEqual([call.kwargs['game'] for call in calls], GAMES)
        self.assertEqual(articles, [record('chunithm', 2), known[0], known[1], record('ongeki', 2), known[2]])

    def test_failed_game_returns_1_in_dry_run(self):
        scraped = {'chunithm': [], 'maimai': [], 'ongeki': ScrapeError('broken')}
        _, articles = self.run_cli(['--dry-run'], scraped, code=1)
        self.assertIsNone(articles)

    def test_unreadable_known_articles_are_not_overwritten(self):
        for raw in ['broken', '{"wrong": "shape"}', '[{"title": "no url"}]']:
            with self.subTest(raw=raw):
                Path('news_all.json').write_text(raw, encoding='utf-8')
                with patch('mg_update_calendar.scraper.scrape') as scrape, \
                        contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(main([]), 2)
                scrape.assert_not_called()
                self.assertEqual(Path('news_all.json').read_text(encoding='utf-8'), raw)

    def test_removed_options_are_rejected(self):
        for option in [['--no-detail'], ['--max-articles', '1'], ['--interval', '1'],
                       ['--output', 'other.json']]:
            with self.subTest(option=option), contextlib.redirect_stderr(io.StringIO()), \
                 patch('mg_update_calendar.scraper.scrape') as scrape:
                with self.assertRaises(SystemExit) as error:
                    main(option)
                self.assertEqual(error.exception.code, 2)
                scrape.assert_not_called()


class Fetcher:
    def __init__(self):
        self.urls = []

    def get(self, url):
        self.urls.append(url)
        return url


class IncrementalScrapeTests(unittest.TestCase):
    def scrape(self, pages, bodies=None, **kwargs):
        """pagesは一覧ページごとの記事番号。詳細ページはbodiesにある番号ならその本文、なければ「新」で返す。"""
        bodies = bodies or {}
        fetcher = Fetcher()
        lists = {('https://info-chunithm.sega.jp/' if index == 0 else
                  f'https://info-chunithm.sega.jp/page/{index + 1}/'): [record('chunithm', n) for n in numbers]
                 for index, numbers in enumerate(pages)}
        with patch('mg_update_calendar.scraper.parse_list_page', side_effect=lambda html, site: lists.get(html, [])), \
             patch('mg_update_calendar.scraper.parse_article_page',
                   side_effect=lambda html, url, site: record('chunithm', url.rsplit('/', 1)[1],
                                                              body=bodies.get(int(url.rsplit('/', 1)[1]), '新'))), \
             contextlib.redirect_stderr(io.StringIO()):
            results = scrape(game='chunithm', fetcher=fetcher, verbose=False, **kwargs)
        return results, fetcher.urls

    def test_known_articles_are_not_fetched_again(self):
        known = {record('chunithm', 1)['url']: record('chunithm', 1)}
        results, urls = self.scrape([[2, 1]], known=known)
        self.assertEqual(urls, ['https://info-chunithm.sega.jp/', record('chunithm', 2)['url']])
        self.assertEqual(results, [record('chunithm', 2, body='新'), record('chunithm', 1)])

    def test_paging_stops_at_a_page_of_only_known_articles(self):
        known = {record('chunithm', n)['url']: record('chunithm', n) for n in (3, 4)}
        _, urls = self.scrape([[1, 2], [3, 4], [5, 6]], known=known, max_pages=0)
        self.assertEqual(urls, ['https://info-chunithm.sega.jp/', record('chunithm', 1)['url'],
                                record('chunithm', 2)['url'], 'https://info-chunithm.sega.jp/page/2/'])

    def test_recent_and_bodiless_known_articles_are_fetched_again(self):
        known = {item['url']: item for item in [
            record('chunithm', 1, date='2026-10-01'), record('chunithm', 2, date='2026-09-01'),
            record('chunithm', 3, date='2026-09-01', body='')]}
        results, urls = self.scrape([[1, 2, 3]], known=known, refresh_since='2026-09-29')
        self.assertEqual(urls[1:], [record('chunithm', 1)['url'], record('chunithm', 3)['url']])
        self.assertEqual([item['body_text'] for item in results], ['新', '本文', '新'])

    def test_empty_first_page_is_an_error(self):
        with self.assertRaises(ScrapeError):
            self.scrape([[]])
        with self.assertRaises(ScrapeError):
            self.scrape([[]], known={record('chunithm', 1)['url']: record('chunithm', 1)})

    def test_missing_first_page_is_an_error(self):
        fetcher = Fetcher()
        response = requests.Response()
        response.status_code = 404
        fetcher.get = lambda url: (_ for _ in ()).throw(requests.HTTPError(response=response))
        with self.assertRaises(ScrapeError):
            scrape(game='chunithm', fetcher=fetcher, verbose=False)

    def test_missing_later_page_ends_paging(self):
        fetcher = Fetcher()
        get = fetcher.get
        response = requests.Response()
        response.status_code = 404

        def fake(url):
            if url.endswith('/page/2/'):
                raise requests.HTTPError(response=response)
            return get(url)
        fetcher.get = fake
        with patch('mg_update_calendar.scraper.parse_list_page', return_value=[record('chunithm', 1)]), \
             patch('mg_update_calendar.scraper.parse_article_page', return_value=record('chunithm', 1)), \
             contextlib.redirect_stderr(io.StringIO()):
            results = scrape(game='chunithm', fetcher=fetcher, verbose=False, max_pages=0)
        self.assertEqual(results, [record('chunithm', 1)])

    def test_empty_later_page_ends_paging(self):
        results, urls = self.scrape([[1]], max_pages=0)
        self.assertEqual(urls[-1], 'https://info-chunithm.sega.jp/page/2/')
        self.assertEqual(len(results), 1)

    def test_all_fetched_details_without_body_is_an_error(self):
        with self.assertRaises(ScrapeError):
            self.scrape([[1, 2]], bodies={1: '', 2: ''})

    def test_some_details_without_body_are_allowed(self):
        # JSリダイレクト記事は本文が空になるので、1件だけ、または一部だけなら失敗にしない
        results, _ = self.scrape([[1]], bodies={1: ''})
        self.assertEqual(results[0]['body_text'], '')
        results, _ = self.scrape([[1, 2]], bodies={1: ''})
        self.assertEqual([item['body_text'] for item in results], ['', '新'])

    def test_known_articles_without_body_do_not_count_as_fetched(self):
        known = {record('chunithm', n)['url']: record('chunithm', n) for n in (1, 2)}
        results, urls = self.scrape([[1, 2, 3]], bodies={3: ''}, known=known)
        self.assertEqual(urls, ['https://info-chunithm.sega.jp/', record('chunithm', 3)['url']])
        self.assertEqual(len(results), 3)

    def test_needs_refetch(self):
        self.assertFalse(needs_refetch(record('chunithm', 1)))
        self.assertTrue(needs_refetch(record('chunithm', 1, body='')))
        self.assertTrue(needs_refetch(record('chunithm', 1, date='2026-10-01'), '2026-10-01'))
        self.assertFalse(needs_refetch(record('chunithm', 1, date='2026-09-30'), '2026-10-01'))

    def test_merge_orders_by_game_then_newest_date(self):
        known = [record('ongeki', 1, date='2026-09-01'), record('chunithm', 1, date='2026-09-10'),
                 record('chunithm', 2, date='2026-09-20')]
        scraped = {'chunithm': [record('chunithm', 3, date='2026-09-15'), record('chunithm', 2, body='新')]}
        merged = merge_articles(known, scraped)
        self.assertEqual([(item['game'], item['url'].rsplit('/', 1)[1], item['body_text']) for item in merged],
                         [('chunithm', '2', '新'), ('chunithm', '3', '本文'), ('chunithm', '1', '本文'),
                          ('ongeki', '1', '本文')])


if __name__ == '__main__':
    unittest.main()
