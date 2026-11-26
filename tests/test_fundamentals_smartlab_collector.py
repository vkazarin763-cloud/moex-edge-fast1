import unittest
from research_agent.fundamentals.smartlab_collector import (
    ArticleParser, PostParser, matched_tickers, normalize_post, collect, topic_tags
)

class SmartLabCollectorTests(unittest.TestCase):
    def test_extracts_post_metadata_text_and_article_link(self):
        html = '<div class="tgme_widget_message_wrap" data-post="newssmartlab/123"><a class="tgme_widget_message_date" href="https://t.me/newssmartlab/123"><time datetime="2026-11-25T12:30:00+00:00"></time></a><div class="tgme_widget_message_text">Выручка #SBER выросла <a href="https://smartlab.news/i/123">Читать далее</a></div></div>'
        p = PostParser(); p.feed(html); p.close()
        self.assertEqual(len(p.posts), 1)
        post = normalize_post(p.posts[0])
        self.assertEqual(post["post_id"], "newssmartlab/123")
        self.assertEqual(post["published_at"], "2026-11-25T12:30:00+00:00")
        self.assertEqual(post["tickers"], ["SBER"])
        self.assertIn("revenue_profit", post["topic_tags"])
        self.assertEqual(post["linked_articles"][0]["url"], "https://smartlab.news/i/123")

    def test_short_ticker_requires_explicit_prefix(self):
        self.assertEqual(matched_tickers("Акции Т выросли сегодня"), [])
        self.assertEqual(matched_tickers("Дивиденды #T, #SBER и $ROSN"), ["ROSN", "SBER", "T"])

    def test_article_parser_finds_document_candidate_link(self):
        html = '<html><head><title>Результаты #SBER</title><meta name="description" content="Отчёт МСФО"></head><body><a href="https://issuer.example/results.pdf">Отчёт МСФО PDF</a></body></html>'
        p = ArticleParser(); p.feed(html); p.close()
        self.assertEqual(" ".join(p.title), "Результаты #SBER")
        self.assertEqual(p.description, "Отчёт МСФО")

    def test_collect_paginates_and_checks_article_links(self):
        first = '<div class="tgme_widget_message_wrap" data-post="newssmartlab/200"><div class="tgme_widget_message_text">#SBER дивиденды <a href="https://smartlab.news/i/55">Источник</a></div></div>'
        second = '<div class="tgme_widget_message_wrap" data-post="newssmartlab/150"><div class="tgme_widget_message_text">#ROSN отчётность МСФО</div></div>'
        article = '<html><head><title>Отчёт Сбербанка</title></head><body><a href="https://issuer.example/report.pdf">Отчёт МСФО PDF</a></body></html>'
        seen = []
        def fake_fetch(url):
            seen.append(url)
            if "before=" in url:
                return second
            if url == "https://smartlab.news/i/55":
                return article
            return first
        result = collect(fake_fetch, max_pages=2)
        self.assertEqual(result["pagination"]["pages_fetched"], 2)
        self.assertEqual(result["preview_posts_seen"], 2)
        self.assertEqual(result["ticker_matched_posts"], 2)
        self.assertEqual(result["linked_articles_checked"], 1)
        self.assertEqual(result["articles_with_candidate_document_links"], 1)
        self.assertTrue(any("before=199" in url for url in seen))
        self.assertEqual(result["posts"][0]["article_details"][0]["candidate_primary_document_links"][0]["url"], "https://issuer.example/report.pdf")

    def test_topic_classification(self):
        self.assertEqual(topic_tags("Компания объявила дивиденды и опубликовала отчёт МСФО"),
                         ["dividends", "financial_report"])
if __name__ == "__main__":
    unittest.main()
