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



if __name__ == "__main__":
    unittest.main(verbosity=2)
