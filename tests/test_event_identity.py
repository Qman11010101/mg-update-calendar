from datetime import date
import unittest

from mg_update_calendar.event_identity import event_id
from mg_update_calendar.models import Article, Entry


class EventIdentityTests(unittest.TestCase):
    def setUp(self):
        self.article = Article(game="ongeki", url="https://example.com/a", date=date(2026, 9, 1),
                               title="告知", body_text="作品Ａ 第3弾のイベントとログインボーナス。")
        self.entry = Entry(type="event", title="作品Ａ 第3弾", service="ongeki",
                           event_name="作品Ａ 第3弾", event_evidence=self.article.body_text,
                           start_is_deadline=False, start=date(2026, 9, 3), start_time=None,
                           end=date(2026, 10, 28), end_time=None, open_ended=False,
                           songs=[], date_text="", evidence=self.article.body_text, confidence=0.95)

    def test_same_event_in_separate_articles_and_types_has_stable_id(self):
        related = self.entry.model_copy(update={"type": "login_bonus", "title": "開催記念ログインボーナス",
                                               "event_name": "作品A 第3弾"})
        other_article = self.article.model_copy(update={"url": "https://example.com/b", "title": "別作品"})
        self.assertEqual(event_id(self.entry, self.article), event_id(related, other_article))
        self.assertTrue(event_id(self.entry, self.article).startswith("evt_"))

    def test_distinct_events_dates_times_services_and_games_stay_separate(self):
        original = event_id(self.entry, self.article)
        for change in [
            {"event_name": "別作品", "event_evidence": "別作品のイベント。"},
            {"event_name": "作品Ａ 第4弾", "event_evidence": "作品Ａ 第4弾のイベント。"},
            {"event_name": "復刻 作品Ａ 第3弾", "event_evidence": "復刻 作品Ａ 第3弾。"},
            {"start": date(2026, 9, 4)}, {"end": date(2026, 10, 29)},
            {"start_time": "10:00"}, {"end_time": "23:59"}, {"service": "card_maker"},
        ]:
            with self.subTest(change=change):
                candidate = self.entry.model_copy(update=change)
                article = self.article.model_copy(update={"body_text": candidate.event_evidence})
                self.assertNotEqual(original, event_id(candidate, article))
                self.assertIsNotNone(event_id(candidate, article))
        self.assertNotEqual(original, event_id(self.entry.model_copy(update={"service": "maimai"}),
                                               self.article.model_copy(update={"game": "maimai"})))

    def test_uncertain_membership_and_dates_have_no_id(self):
        for change in [
            {"event_name": None}, {"event_name": " "}, {"event_evidence": None},
            {"event_evidence": "開催記念ログインボーナス"}, {"event_name": "別作品"},
            {"confidence": 0.79}, {"service": None}, {"service": "maimai"},
            {"start": None}, {"end": None}, {"end": date(2026, 9, 1)},
            {"open_ended": True}, {"start_is_deadline": True},
            {"end": self.entry.start, "start_time": "12:00", "end_time": "10:00"},
        ]:
            with self.subTest(change=change):
                self.assertIsNone(event_id(self.entry.model_copy(update=change), self.article))


if __name__ == "__main__":
    unittest.main()
