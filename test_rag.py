"""不呼叫 OpenAI 的 RAG / 對話脈絡 smoke tests。
執行：python test_rag.py
"""

import unittest
import time

import app


class RagRetrievalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        app.build_search_index()

    def assert_top_contains(self, question: str, expected_title: str, top_n: int = 2) -> None:
        resolved, focus = app.resolve_question(question, [], [])
        hits = app.retrieve(resolved, focus_entities=focus)
        titles = [item["title"] for item in hits[:top_n]]
        self.assertIn(expected_title, titles, msg=f"{question!r} => {titles}")

    def test_barok_architecture(self) -> None:
        self.assert_top_contains("大溪老街的巴洛克牌樓有什麼特色？", "大溪老街建築", 1)

    def test_food(self) -> None:
        resolved, focus = app.resolve_question("大溪有什麼好吃的？", [], [])
        hits = app.retrieve(resolved, focus_entities=focus)
        titles = {item["title"] for item in hits[:4]}
        self.assertIn("傳統豆干老店", titles)
        self.assertIn("傳統甜品與小吃", titles)

    def test_624(self) -> None:
        self.assert_top_contains("六月二十四是什麼活動？", "六二四（大溪六月二十四）", 1)

    def test_parking(self) -> None:
        self.assert_top_contains("開車去大溪老街可以停哪裡？", "交通、停車與實用注意事項", 1)

    def test_fong_fei_fei(self) -> None:
        self.assert_top_contains("鳳飛飛有哪些代表歌曲？", "鳳飛飛", 1)

    def test_rainy_day(self) -> None:
        self.assert_top_contains("下雨天可以去哪？", "交通、停車與實用注意事項", 1)

    def test_half_day_route(self) -> None:
        self.assert_top_contains("第一次去大溪怎麼排半日遊？", "建議遊覽路線", 1)

    def test_unknown_question(self) -> None:
        self.assertEqual(app.retrieve("火星基地在哪裡？"), [])

    def test_wood_art_does_not_pull_wude_hall(self) -> None:
        resolved, focus = app.resolve_question("大溪木藝有什麼特色？", [], [])
        titles = [h["title"] for h in app.retrieve(resolved, focus_entities=focus)]
        self.assertIn("大溪木藝", titles)
        self.assertNotIn("武德殿", titles)

    def test_followup_second_recommendation(self) -> None:
        history = [
            app.HistoryTurn(
                role="assistant",
                text="你也可以接著看看大溪橋、中正公園和大溪木藝生態博物館。",
                sources=["大溪橋"],
                recommendations=["大溪橋", "中正公園", "大溪木藝生態博物館"],
            )
        ]
        question = "深入介紹第二個"
        resolved, focus = app.resolve_question(
            question,
            history,
            ["大溪橋", "中正公園", "大溪木藝生態博物館"],
        )
        self.assertEqual(focus, ["中正公園"])
        titles = [h["title"] for h in app.retrieve(resolved, focus_entities=focus)]
        self.assertEqual(titles, ["中正公園"])

    def test_followup_multiple_ordinals_for_route(self) -> None:
        recs = ["大溪橋", "中正公園", "大溪木藝生態博物館"]
        resolved, focus = app.resolve_question("把第二個跟第三個排成兩小時路線", [], recs, ["福仁宮"])
        self.assertEqual(focus, ["中正公園", "大溪木藝生態博物館"])
        self.assertIn("中正公園", resolved)
        self.assertIn("大溪木藝生態博物館", resolved)

    def test_followup_route_uses_previous_recommendations(self) -> None:
        history = [
            app.HistoryTurn(
                role="assistant",
                text="推薦大溪橋、中正公園、大溪木藝生態博物館。",
                recommendations=["大溪橋", "中正公園", "大溪木藝生態博物館"],
            )
        ]
        question = "幫我把剛剛推薦的幾個景點排成半日行程"
        resolved, focus = app.resolve_question(
            question,
            history,
            ["大溪橋", "中正公園", "大溪木藝生態博物館"],
        )
        titles = [h["title"] for h in app.retrieve(resolved, focus_entities=focus)]
        self.assertIn("大溪橋", titles)
        self.assertIn("中正公園", titles)
        self.assertIn("大溪木藝生態博物館", titles)
        self.assertIn("建議遊覽路線", titles)
        self.assertNotIn("大溪木藝", titles)

    def test_detailed_local_answer_uses_official_record(self) -> None:
        resolved, focus = app.resolve_question("詳細介紹福仁宮", [], [])
        hits = app.retrieve(resolved, focus_entities=focus)
        record = {
            "name": "福仁宮",
            "description": "官方詳細描述測試",
            "address": "桃園市大溪區和平路100號",
            "open_time": "04:00~20:30",
            "tel": "03-3871235",
            "pictures": [],
        }
        answer = app.local_rag_answer("詳細介紹福仁宮", hits[:1], record)
        self.assertIn("官方詳細描述測試", answer)
        self.assertIn("和平路100號", answer)

    def test_official_image_result_parser(self) -> None:
        class FakeResponse:
            def model_dump(self):
                return {
                    "output": [{
                        "type": "web_search_call",
                        "results": [{
                            "type": "image_result",
                            "image_url": "https://cdn.example/furen.jpg",
                            "thumbnail_url": "https://cdn.example/furen-thumb.jpg",
                            "source_website_url": "https://travel.tycg.gov.tw/zh-tw/travel/attraction/1172",
                            "caption": "福仁宮",
                        }],
                    }]
                }

        images = app.extract_web_images(FakeResponse())
        self.assertEqual(len(images), 1)
        self.assertEqual(images[0]["caption"], "福仁宮")

    def test_active_topic_continues_for_photo_request(self) -> None:
        resolved, focus = app.resolve_question("照片", [], [], ["福仁宮"])
        self.assertEqual(focus, ["福仁宮"])
        self.assertIn("福仁宮", resolved)
        titles = [h["title"] for h in app.retrieve(resolved, focus_entities=focus)]
        self.assertEqual(titles, ["福仁宮"])

    def test_active_topic_continues_for_detail_request(self) -> None:
        resolved, focus = app.resolve_question("再詳細一點", [], [], ["大溪木藝生態博物館"])
        self.assertEqual(focus, ["大溪木藝生態博物館"])
        titles = [h["title"] for h in app.retrieve(resolved, focus_entities=focus)]
        self.assertEqual(titles, ["大溪木藝生態博物館"])

    def test_registered_image_has_proxy_url(self) -> None:
        images = app._register_trusted_images([{
            "image_url": "https://travel.tycg.gov.tw/upload/furen.jpg",
            "thumbnail_url": "https://travel.tycg.gov.tw/upload/furen.jpg",
            "source_url": "https://travel.tycg.gov.tw/zh-tw/travel/attraction/1172",
            "caption": "福仁宮",
        }])
        self.assertEqual(len(images), 1)
        self.assertTrue(images[0]["proxy_url"].startswith("/image-proxy?url="))


class ConversationAndOfficialFallbackTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        app.build_search_index()

    def setUp(self) -> None:
        self.old_cache = list(app._official_attractions_cache)
        self.old_cache_at = app._official_attractions_cache_at
        app._official_attractions_cache = [
            {
                "id": "1172", "name": "福仁宮", "px": "121.2860", "py": "24.8840",
                "summary": "福仁宮官方摘要", "description": "福仁宮官方詳細內容",
                "address": "桃園市大溪區和平路100號", "open_time": "04:00~20:30",
                "tel": "03-3883261", "pictures": [],
                "source_url": "https://travel.tycg.gov.tw/zh-tw/travel/attraction/1172",
            },
            {
                "id": "2001", "name": "大溪老街", "px": "121.2870", "py": "24.8850",
                "summary": "大溪老街官方摘要", "description": "", "address": "大溪區",
                "open_time": "", "tel": "", "pictures": [],
                "source_url": "https://travel.tycg.gov.tw/zh-tw/travel/attraction/414",
            },
            {
                "id": "2002", "name": "中正公園", "px": "121.2850", "py": "24.8860",
                "summary": "中正公園官方摘要", "description": "", "address": "大溪區",
                "open_time": "", "tel": "", "pictures": [],
                "source_url": "https://travel.tycg.gov.tw/",
            },
            {
                "id": "2003", "name": "大溪橋", "px": "121.2880", "py": "24.8860",
                "summary": "大溪橋官方摘要", "description": "", "address": "大溪區",
                "open_time": "", "tel": "", "pictures": [],
                "source_url": "https://travel.tycg.gov.tw/",
            },
        ]
        app._official_attractions_cache_at = time.time()

    def tearDown(self) -> None:
        app._official_attractions_cache = self.old_cache
        app._official_attractions_cache_at = self.old_cache_at

    def test_nearby_followup_keeps_active_topic(self) -> None:
        resolved, focus = app.resolve_question("那附近還有什麼？", [], [], ["福仁宮"])
        self.assertEqual(focus, ["福仁宮"])
        self.assertIn("福仁宮", resolved)

    async def test_nearby_fallback_works_without_openai(self) -> None:
        origin = await app.find_official_attraction("福仁宮", ["福仁宮"])
        nearby = await app.find_nearby_attractions(origin, limit=5)
        self.assertGreaterEqual(len(nearby), 2)
        answer = app.local_rag_answer("那附近還有什麼？", [], origin, [], nearby_records=nearby)
        self.assertIn("大溪老街", answer)
        self.assertIn("中正公園", answer)

    async def test_official_only_detail_works_without_local_hit(self) -> None:
        record = await app.find_official_attraction("福仁宮", ["福仁宮"])
        answer = app.local_rag_answer("再詳細一點", [], record)
        self.assertIn("福仁宮官方詳細內容", answer)
        self.assertIn("和平路100號", answer)

    def test_album_html_image_extraction(self) -> None:
        html = '<img data-src="/image/12345/480x360"><script>const p="https://travel.tycg.gov.tw/image/88888/1280x720";</script>'
        urls = app._extract_image_urls_from_html(html, "https://travel.tycg.gov.tw/zh-tw/multimedia/album/3431")
        self.assertIn("https://travel.tycg.gov.tw/image/12345/480x360", urls)
        self.assertIn("https://travel.tycg.gov.tw/image/88888/1280x720", urls)

    def test_known_furen_album_fallback_exists(self) -> None:
        self.assertEqual(
            app.OFFICIAL_ALBUM_PAGE_MAP.get("福仁宮"),
            "https://travel.tycg.gov.tw/zh-tw/multimedia/album/3431",
        )

    def test_broad_html_image_extraction(self):
        html = r"""
        <div style="background-image:url('/assets/photo/furen-main.jpg?x=1')"></div>
        <img data-src="https://travel.tycg.gov.tw/cdn/photos/furen-2.webp">
        <script>window.x={"imageUrl":"/uploads/furen-3.png"}</script>
        """
        urls = app._extract_image_urls_from_html(html, "https://travel.tycg.gov.tw/zh-tw/multimedia/album/3431")
        self.assertTrue(any("furen-main.jpg" in url for url in urls))
        self.assertTrue(any("furen-2.webp" in url for url in urls))
        self.assertTrue(any("furen-3.png" in url for url in urls))

    def test_official_album_source_for_furen(self):
        source = app.official_album_source_for_name("福仁宮")
        self.assertIsNotNone(source)
        self.assertIn("multimedia/album/3431", source["url"])


class ExternalKnowledgeFallbackTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        app.build_search_index()

    def test_v15_bundled_official_catalog_is_available(self) -> None:
        items, snapshot_date = app._load_bundled_daxi_catalog()
        self.assertGreaterEqual(len(items), 200)
        self.assertTrue(snapshot_date)
        names = {item.get("name") for item in items}
        self.assertIn("陳媽媽月光餅", names)

    def test_v15_mooncake_alias_matches_bundled_catalog(self) -> None:
        items, _ = app._load_bundled_daxi_catalog()
        mooncake = next(item for item in items if item.get("name") == "陳媽媽月光餅")
        self.assertGreaterEqual(app._catalog_match_score("月光餅", mooncake), 90)
        record = app._record_from_catalog_item(mooncake)
        self.assertEqual(record.get("name"), "陳媽媽月光餅")
        self.assertIn("和平路87號", record.get("address", ""))

    def setUp(self) -> None:
        self.old_consume_cache = list(app._official_consume_cache)
        self.old_consume_at = app._official_consume_cache_at
        app._official_consume_cache = [
            {
                "id": "1947",
                "entity_type": "consume",
                "name": "陳媽媽月光餅",
                "summary": "桃園觀光官方月光餅店家摘要",
                "description": "以月光餅為招牌的官方消費資訊。",
                "address": "桃園市大溪區和平路87號",
                "open_time": "09:00-18:00",
                "tel": "03-3882451",
                "pictures": [],
                "source_url": "https://travel.tycg.gov.tw/zh-tw/consume/detail/1947",
            }
        ]
        app._official_consume_cache_at = time.time()

    def tearDown(self) -> None:
        app._official_consume_cache = self.old_consume_cache
        app._official_consume_cache_at = self.old_consume_at

    async def test_unknown_kb_term_can_match_official_consume(self) -> None:
        record = await app.find_official_entity("月光餅", [])
        self.assertIsNotNone(record)
        self.assertEqual(record["name"], "陳媽媽月光餅")
        self.assertEqual(record["entity_type"], "consume")

    async def test_consume_record_beats_broad_kb_chapter(self) -> None:
        hits = app.retrieve("月光餅")
        record = await app.find_official_entity("月光餅", [])
        answer = app.local_rag_answer("月光餅", hits, record)
        self.assertIn("陳媽媽月光餅", answer)
        self.assertIn("和平路87號", answer)

    def test_public_results_beat_broad_kb_when_no_direct_topic(self) -> None:
        hits = app.retrieve("月光餅")
        self.assertFalse(app.has_direct_kb_topic("月光餅", hits))
        answer = app.local_rag_answer(
            "月光餅",
            hits,
            None,
            public_results=[{
                "title": "陳媽媽月光餅 - 桃園觀光導覽網",
                "url": "https://travel.tycg.gov.tw/zh-tw/consume/detail/1947",
                "domain": "travel.tycg.gov.tw",
                "snippet": "月光餅是大溪老街的特色食品之一。",
            }],
        )
        self.assertIn("網路補充", answer)
        self.assertIn("月光餅", answer)

    def test_external_topic_can_continue_to_photo(self) -> None:
        resolved, focus = app.resolve_question("照片", [], [], ["陳媽媽月光餅"])
        self.assertEqual(focus, ["陳媽媽月光餅"])
        self.assertIn("陳媽媽月光餅", resolved)

    def test_consume_list_html_parser(self) -> None:
        html = """
        <div class='card'><a href='/zh-tw/consume/detail/1947'><h3>陳媽媽月光餅</h3></a></div>
        <div class='card'><a href='/zh-tw/consume/detail/1934'>永安61庭園咖啡</a></div>
        """
        items = app._extract_consume_detail_links(html, "https://travel.tycg.gov.tw/zh-tw/Consume/List")
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["name"], "陳媽媽月光餅")
        self.assertIn("/consume/detail/1947", items[0]["url"].lower())

    def test_consume_detail_html_parser(self) -> None:
        html = """
        <html><head><title>陳媽媽月光餅 | 桃園觀光導覽網</title>
        <meta name='description' content='陳媽媽手工月光餅外表樸實，QQ外皮是大溪特色。'></head>
        <body><h2>陳媽媽月光餅</h2>電話 03-3882451 地址 桃園市大溪區和平路87號 營業時間 星期三：09:00 - 18:00 特色介紹 月光餅</body></html>
        """
        record = app._parse_consume_detail_html("https://travel.tycg.gov.tw/zh-tw/consume/detail/1947", html)
        self.assertEqual(record["name"], "陳媽媽月光餅")
        self.assertIn("和平路87號", record["address"])
        self.assertEqual(record["tel"], "03-3882451")
        self.assertIn("大溪特色", record["description"])

    def test_bing_result_parser(self) -> None:
        html = """<ol><li class='b_algo'><h2><a href='https://travel.tycg.gov.tw/zh-tw/Consume/Detail/1947'>陳媽媽月光餅</a></h2><div><p>桃園大溪月光餅官方介紹</p></div></li></ol>"""
        results = app._extract_bing_results(html)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["domain"], "travel.tycg.gov.tw")
        self.assertIn("月光餅", results[0]["title"])

    def test_unknown_term_does_not_dump_broad_kb_when_external_search_fails(self) -> None:
        hits = app.retrieve("月光餅")
        answer = app.local_rag_answer("月光餅", hits, None, public_results=[])
        self.assertIn("月光餅", answer)
        self.assertNotIn("木藝類", answer)

    def test_region_page_consume_parser(self) -> None:
        html = """
        <section><h3>大溪區</h3>
        <a href='/zh-tw/consume/detail/1947'>陳媽媽月光餅</a>
        <a href='/zh-tw/travel/attraction/414'>大溪老街</a>
        </section>
        """
        items = app._extract_consume_detail_links(html, app.TYCG_REGION_LIST_URL)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["name"], "陳媽媽月光餅")
        self.assertTrue(items[0]["url"].endswith("/zh-tw/consume/detail/1947"))

    def test_bing_rss_parser(self) -> None:
        rss = """<?xml version='1.0' encoding='UTF-8'?>
        <rss><channel><item>
          <title>陳媽媽月光餅 - 桃園觀光導覽網</title>
          <link>https://travel.tycg.gov.tw/zh-tw/consume/detail/1947</link>
          <description>桃園市大溪區和平路87號，招牌菜月光餅。</description>
        </item></channel></rss>"""
        results = app._extract_bing_rss_results(rss)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["domain"], "travel.tycg.gov.tw")
        self.assertIn("月光餅", results[0]["title"])


    def test_public_result_rejects_irrelevant_foreign_page(self) -> None:
        item = {
            "title": "C7DC - Challenge des 7 défis capitaux",
            "url": "https://example.fr/challenge",
            "domain": "example.fr",
            "snippet": "La version 2025 du challenge...",
        }
        self.assertFalse(app._public_result_is_relevant(item, "大溪有哪些必吃美食？", allow_general=True))

    def test_public_result_rejects_mars_for_mooncake(self) -> None:
        item = {
            "title": "Mars - Wikipedia",
            "url": "https://en.wikipedia.org/wiki/Mars",
            "domain": "en.wikipedia.org",
            "snippet": "Mars formed along with the other planets...",
        }
        self.assertFalse(app._public_result_is_relevant(item, "月光餅", allow_general=True))

    def test_public_result_accepts_official_mooncake(self) -> None:
        item = {
            "title": "陳媽媽月光餅 - 桃園觀光導覽網",
            "url": "https://travel.tycg.gov.tw/zh-tw/consume/detail/1947",
            "domain": "travel.tycg.gov.tw",
            "snippet": "桃園市大溪區和平路87號，招牌菜月光餅。",
        }
        self.assertTrue(app._public_result_is_relevant(
            item, "月光餅", expected_domains=("travel.tycg.gov.tw",)
        ))

    def test_broad_food_question_stays_in_kb(self) -> None:
        hits = app.retrieve("大溪有哪些必吃美食？")
        self.assertTrue(hits)
        self.assertFalse(app.should_discover_external("大溪有哪些必吃美食？", hits, []))

    def test_specific_mooncake_still_discovers_external(self) -> None:
        hits = app.retrieve("月光餅")
        self.assertTrue(hits)
        self.assertTrue(app.should_discover_external("月光餅", hits, []))


    def test_v14_daxi_nearby_shopping_parser(self) -> None:
        html = """
        <nav><a href='?page=1'>1</a><a href='?page=9'>9</a></nav>
        <article><a href='/zh-tw/consume/detail/1947' title='陳媽媽月光餅'><img alt='陳媽媽月光餅'></a><span>191 公尺</span></article>
        <article><a href='/zh-tw/consume/detail/2222'><strong>小鎮豆花</strong></a><span>56 公尺</span></article>
        """
        items = app._extract_consume_detail_links(html, app.TYCG_DAXI_NEARBY_SHOPPING_URL)
        self.assertEqual(app._extract_max_page(html), 9)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["name"], "陳媽媽月光餅")
        self.assertTrue(items[0]["url"].endswith("/zh-tw/consume/detail/1947"))

    def test_v14_partial_product_name_matches_store_name(self) -> None:
        self.assertGreaterEqual(app.attraction_match_score("月光餅", "陳媽媽月光餅"), 60)


if __name__ == "__main__":
    unittest.main(verbosity=2)
