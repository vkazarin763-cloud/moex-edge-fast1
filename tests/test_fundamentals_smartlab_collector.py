import unittest
from research_agent.fundamentals.smartlab_collector import PostParser, matched_tickers, normalize_post, collect

class SmartLabCollectorTests(unittest.TestCase):
    def test_extracts_post_metadata_and_text(self):
        html='<div class="tgme_widget_message_wrap" data-post="newssmartlab/123"><a class="tgme_widget_message_date" href="https://t.me/newssmartlab/123"><time datetime="2026-11-25T12:30:00+00:00"></time></a><div class="tgme_widget_message_text">Выручка #SBER выросла, чистая прибыль +10%</div></div>'
        p=PostParser(); p.feed(html); p.close()
        self.assertEqual(len(p.posts),1)
        post=normalize_post(p.posts[0])
        self.assertEqual(post["post_id"],"newssmartlab/123")
        self.assertEqual(post["published_at"],"2026-11-25T12:30:00+00:00")
        self.assertEqual(post["tickers"],["SBER"])
        self.assertTrue(post["reporting_related"])
        self.assertEqual(post["verification_status"],"unverified_news_lead")
    def test_short_ticker_requires_explicit_prefix(self):
        self.assertEqual(matched_tickers("Акции Т выросли сегодня"),[])
        self.assertEqual(matched_tickers("Дивиденды #T и #SBER"),["SBER","T"])
    def test_collect_filters_posts_without_ticker(self):
        html='<div class="tgme_widget_message_wrap" data-post="newssmartlab/1"><div class="tgme_widget_message_text">#ROSN опубликовала отчётность по МСФО</div></div><div class="tgme_widget_message_wrap" data-post="newssmartlab/2"><div class="tgme_widget_message_text">Общий обзор рынка без тикера</div></div>'
        r=collect(lambda:html)
        self.assertEqual(r["preview_posts_seen"],2)
        self.assertEqual(r["ticker_matched_posts"],1)
        self.assertEqual(r["reporting_related_posts"],1)
        self.assertEqual(r["posts"][0]["tickers"],["ROSN"])
if __name__=="__main__": unittest.main()
