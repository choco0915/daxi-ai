"""不呼叫 OpenAI 的 RAG smoke tests。
執行：python test_rag.py
"""

import unittest

import app


class RagRetrievalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        app.build_search_index()

    def assert_top_contains(self, question: str, expected_title: str, top_n: int = 2) -> None:
        hits = app.retrieve(question)
        titles = [item["title"] for item in hits[:top_n]]
        self.assertIn(expected_title, titles, msg=f"{question!r} => {titles}")

    def test_barok_architecture(self) -> None:
        self.assert_top_contains("大溪老街的巴洛克牌樓有什麼特色？", "大溪老街建築", 1)

    def test_food(self) -> None:
        hits = app.retrieve("大溪有什麼好吃的？")
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
