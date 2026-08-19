"""不呼叫 OpenAI 的 RAG / 對話脈絡 smoke tests。
執行：python test_rag.py
"""

import unittest

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
