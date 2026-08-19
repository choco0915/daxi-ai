import math
import os
import re
import time
import unicodedata
import xml.etree.ElementTree as ET
from html import unescape
from collections import Counter, defaultdict, deque
from contextlib import asynccontextmanager
from typing import Any, Literal
from urllib.parse import quote, urljoin, urlparse, parse_qs, unquote

import httpx

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import uvicorn

try:
    from openai import AsyncOpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False


APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_MD = os.path.join(APP_DIR, "data.md")
INDEX_HTML = os.path.join(APP_DIR, "index.html")

load_dotenv(os.path.join(APP_DIR, ".env"))

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6")
OPENAI_FALLBACK_MODEL = os.getenv("OPENAI_FALLBACK_MODEL", "gpt-5.6-luna").strip()
WEB_SEARCH_ENABLED = os.getenv("WEB_SEARCH_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}
TOP_K = 6
MIN_RETRIEVAL_SCORE = 0.08
MAX_HISTORY_TURNS = 10
STORYMAP_URL = "https://storymaps.arcgis.com/stories/b704c98b362041c1be364ad2c8ca3d27"
TYCG_ATTRACTIONS_OPEN_DATA = "https://travel.tycg.gov.tw/zh-tw/OpenData/TYCGAttractions"
TYCG_CONSUME_OPEN_DATA_CANDIDATES = (
    "https://travel.tycg.gov.tw/zh-tw/OpenData/TYCGConsume",
    "https://travel.tycg.gov.tw/zh-tw/OpenData/Consume",
)
TYCG_ALBUM_OPEN_DATA_CANDIDATES = (
    "https://travel.tycg.gov.tw/zh-tw/OpenData/TYCGAlbum",
    "https://travel.tycg.gov.tw/zh-tw/OpenData/Album",
)
# 桃園觀光的「景點頁」不一定直接帶相簿連結；對常用大溪景點保留官方相簿頁作為可靠 fallback。
# 這些 URL 都是 travel.tycg.gov.tw 的官方頁面；圖片仍由後端即時解析，不把第三方圖片硬寫進專案。
OFFICIAL_ALBUM_PAGE_MAP: dict[str, str] = {
    "福仁宮": "https://travel.tycg.gov.tw/zh-tw/multimedia/album/3431",
    "大溪老街": "https://travel.tycg.gov.tw/zh-tw/multimedia/album/71",
    "大溪橋": "https://travel.tycg.gov.tw/zh-tw/multimedia/album/2767",
    "武德殿": "https://travel.tycg.gov.tw/zh-tw/multimedia/album/62",
    "大溪木藝生態博物館武德殿": "https://travel.tycg.gov.tw/zh-tw/multimedia/album/62",
}
# 大龍門官方子站部分大溪景點頁會直接帶「照片／環景」內容，
# 當主站 HTML 沒有輸出圖片網址時，作為第二個官方頁面來源。
OFFICIAL_DALONGMEN_PAGE_MAP: dict[str, str] = {
    "福仁宮": "https://travel.tycg.gov.tw/dalongmen/zh-tw/attraction/1172",
}

OFFICIAL_CACHE_SECONDS = 1800

# 官方來源優先。OpenAI web_search 的 allowed_domains 會包含該網域的子網域。
OFFICIAL_WEB_DOMAINS = [
    "tycg.gov.tw",       # 桃園市政府與其子網域（觀光、木博館、大溪大禧等）
    "taiwan.net.tw",     # 交通部觀光署
    "storymaps.arcgis.com",
]

# 公開網站的簡單記憶體限流；Render 重啟時會重置，主要用來避免單一 IP 狂刷 API。
CHAT_RATE_LIMIT = max(1, int(os.getenv("CHAT_RATE_LIMIT", "30")))
CHAT_RATE_WINDOW_SECONDS = max(1, int(os.getenv("CHAT_RATE_WINDOW_SECONDS", "60")))
_request_times: dict[str, deque[float]] = defaultdict(deque)


QUERY_EXPANSIONS: dict[str, str] = {
    "大禧": "六二四 大溪六月二十四 普濟堂 慶典",
    "六月二十四": "六二四 大溪六月二十四 普濟堂 慶典 神將 暗訪",
    "六月24": "六二四 大溪六月二十四 普濟堂 慶典",
    "624": "六二四 大溪六月二十四 普濟堂 慶典",
    "巴洛克": "大溪老街建築 街屋 牌樓 拱門 柱式 山牆 洗石子",
    "牌樓": "大溪老街建築 街屋 巴洛克 山牆 洗石子",
    "老街建築": "大溪老街建築 巴洛克 街屋 山牆 洗石子",
    "豆干": "傳統豆干老店 黃日香 黃大目 廖心蘭 美食",
    "豆乾": "傳統豆干老店 豆干 黃日香 黃大目 廖心蘭 美食",
    "豆花": "傳統甜品與小吃 賴媽媽豆花 美食",
    "吃什麼": "美食 傳統豆干老店 傳統甜品與小吃 伴手禮推薦",
    "好吃": "美食 傳統豆干老店 傳統甜品與小吃 伴手禮推薦",
    "美食": "傳統豆干老店 傳統甜品與小吃 伴手禮推薦",
    "景點": "大溪老街 中正公園 大溪橋 武德殿 大溪公會堂 大溪木藝生態博物館 鳳飛飛故事館",
    "去哪": "景點 大溪老街 中正公園 大溪橋 木藝生態博物館",
    "停車": "交通 停車 月眉停車場 大溪橋頭停車場 停二停車場",
    "開車": "交通 停車 自行開車 大溪交流道 員林路 介壽路",
    "公車": "交通 大眾運輸 桃園客運 台灣好行 大溪客運總站 大溪老街站",
    "客運": "交通 大眾運輸 桃園客運 台灣好行",
    "怎麼去": "交通 大眾運輸 自行開車",
    "交通": "交通 停車 大眾運輸 自行開車",
    "半日": "建議遊覽路線 半日遊 大溪老街 普濟堂 中正公園 大溪橋",
    "一日遊": "建議遊覽路線 歷史文化一日遊 大溪老街 木藝生態博物館 大溪橋",
    "兩天一夜": "建議遊覽路線 兩天一夜",
    "行程": "建議遊覽路線 半日遊 一日遊 兩天一夜",
    "木藝": "大溪木藝 大溪木藝生態博物館 榫接 雕刻 家具",
    "木器": "大溪木藝 大溪木藝生態博物館 木器 家具 榫接 雕刻",
    "神將": "六二四 大溪社頭文化 普濟堂 大仙尪",
    "帽子歌后": "鳳飛飛 鳳飛飛故事館",
    "鳳飛飛": "鳳飛飛 鳳飛飛故事館 祝你幸福 心肝寶貝 掌聲響起",
    "雨天": "無障礙與天候建議 室內場館 武德殿 公會堂 鳳飛飛故事館",
    "下雨": "無障礙與天候建議 室內場館 武德殿 公會堂 鳳飛飛故事館",
    "無障礙": "無障礙與天候建議 老街騎樓 中正公園 木藝博物館",
}

INTENT_TITLE_BOOSTS: dict[str, list[str]] = {
    "巴洛克": ["大溪老街建築"],
    "牌樓": ["大溪老街建築"],
    "老街建築": ["大溪老街建築"],
    "豆干": ["傳統豆干老店"],
    "豆乾": ["傳統豆干老店"],
    "豆花": ["傳統甜品與小吃"],
    "吃什麼": ["傳統豆干老店", "傳統甜品與小吃", "伴手禮推薦"],
    "好吃": ["傳統豆干老店", "傳統甜品與小吃", "伴手禮推薦"],
    "美食": ["傳統豆干老店", "傳統甜品與小吃", "伴手禮推薦"],
    "停車": ["交通、停車與實用注意事項"],
    "開車": ["交通、停車與實用注意事項"],
    "公車": ["交通、停車與實用注意事項"],
    "客運": ["交通、停車與實用注意事項"],
    "交通": ["交通、停車與實用注意事項"],
    "雨天": ["交通、停車與實用注意事項"],
    "下雨": ["交通、停車與實用注意事項"],
    "無障礙": ["交通、停車與實用注意事項"],
    "半日": ["建議遊覽路線"],
    "一日遊": ["建議遊覽路線"],
    "兩天一夜": ["建議遊覽路線"],
    "行程": ["建議遊覽路線"],
    "大禧": ["六二四（大溪六月二十四）"],
    "六月二十四": ["六二四（大溪六月二十四）"],
    "六月24": ["六二四（大溪六月二十四）"],
    "624": ["六二四（大溪六月二十四）"],
    "神將": ["六二四（大溪六月二十四）", "大溪社頭文化"],
    "帽子歌后": ["鳳飛飛"],
    "木藝": ["大溪木藝", "大溪木藝生態博物館"],
    "木器": ["大溪木藝", "大溪木藝生態博物館"],
}

# 對很明確的單一主題，只允許這些章節進入回答，避免「木藝」後面突然跑出武德殿。
FOCUS_TITLE_GROUPS: dict[str, list[str]] = {
    "木藝": ["大溪木藝", "大溪木藝生態博物館"],
    "木器": ["大溪木藝", "大溪木藝生態博物館"],
    "巴洛克": ["大溪老街建築", "大溪老街"],
    "牌樓": ["大溪老街建築", "大溪老街"],
    "豆干": ["傳統豆干老店", "伴手禮推薦"],
    "豆乾": ["傳統豆干老店", "伴手禮推薦"],
    "豆花": ["傳統甜品與小吃"],
    "鳳飛飛": ["鳳飛飛", "鳳飛飛故事館"],
    "六月二十四": ["六二四（大溪六月二十四）", "大溪社頭文化", "普濟堂"],
    "六二四": ["六二四（大溪六月二十四）", "大溪社頭文化", "普濟堂"],
    "停車": ["交通、停車與實用注意事項"],
    "開車": ["交通、停車與實用注意事項"],
    "公車": ["交通、停車與實用注意事項"],
    "客運": ["交通、停車與實用注意事項"],
    "交通": ["交通、停車與實用注意事項"],
    "雨天": ["交通、停車與實用注意事項"],
    "下雨": ["交通、停車與實用注意事項"],
    "無障礙": ["交通、停車與實用注意事項"],
}

STOPWORDS = {
    "請問", "可以", "想要", "想知道", "告訴", "介紹", "一下", "一下子",
    "什麼", "哪些", "怎麼", "如何", "有沒有", "有什麼", "推薦", "附近",
    "大溪", "老街", "我想", "我要", "我們", "你們", "這裡", "那裡",
}

FOLLOWUP_MARKERS = (
    "剛剛", "剛才", "前面", "上面", "剛提到", "你提到", "你推薦", "推薦的",
    "它", "他", "那個", "這個", "那些", "這些", "其中", "深入", "詳細",
    "多介紹", "再介紹", "接著", "繼續", "第一個", "第二個", "第三個", "第四個",
    "照片", "圖片", "相片", "實景", "更多", "再多說", "介紹一下",
    "附近", "周邊", "旁邊", "周遭", "還有什麼", "還有哪裡", "還能去哪", "附近有什麼",
)
ROUTE_MARKERS = ("行程", "路線", "安排", "串聯", "順遊", "順路", "半日", "一日", "兩天", "幾個景點", "一起玩")
NEARBY_MARKERS = ("附近", "周邊", "旁邊", "周遭", "鄰近", "附近有什麼", "附近還有什麼", "還有哪裡", "還能去哪")
WEB_MARKERS = (
    "網路", "上網", "查網路", "官網", "官方", "最新", "現在", "目前", "今天", "近期",
    "營業", "開放", "休館", "票價", "門票", "活動", "交通異動", "電話", "地址",
    "時間", "時刻", "深入", "詳細", "更多", "行程", "路線", "安排",
    "照片", "圖片", "相片", "實景", "外觀", "附近", "周邊", "鄰近",
)

DETAIL_MARKERS = ("詳細", "深入", "完整介紹", "仔細介紹", "多介紹", "進一步", "更多資訊")
IMAGE_MARKERS = ("照片", "圖片", "相片", "實景", "外觀照片", "看看照片", "看照片")

SYSTEM_INSTRUCTIONS = """你是「豆干弟」，一位親切、自然、熟悉大溪在地文化的 AI 導覽員。

【最重要：回答焦點】
1. 只回答「已解析問題」真正要問的主題。即使檢索片段裡還有其他景點，也不要順便展開不相關內容。
2. 若使用者問單一主題（例如「大溪木藝」），正文只談這個主題及直接相關內容；不要因為某片段提到武德殿、公會堂等名稱就額外介紹它們。
3. 只有使用者明確要求「推薦景點、比較、安排路線、幾個景點一起玩」時，才可以同時介紹多個景點。
4. 回答開頭直接進入主題，不要說「我在 data.md 找到」「我幫你查到」「我整理了檢索片段」等系統流程語句。

【資料來源規則】
5. data.md 是主要在地知識來源。穩定的歷史、文化、景點背景優先依 data.md。
6. 若本次有啟用網路搜尋，可以用官方網站補充較新的資訊或 data.md 沒寫到的細節；優先桃園市政府、桃園觀光、大溪木藝生態博物館、大溪大禧、交通部觀光署及指定 StoryMap。
6-1. 若使用者詢問的名詞在 data.md 沒有獨立章節（例如店家、食品、伴手禮），但官方 Open Data 或公開網路搜尋有可靠結果，必須直接回答該名詞，不要因為 data.md 沒有專章就拒答。
6-2. 外部搜尋結果與 data.md 要明確分工：data.md 有內容就優先；data.md 不足的部分才由官方資料或公開網路補充。
7. 網路資料與 data.md 若有差異，對會變動的資訊（開放時間、活動、交通、現況）以官方網站較新的資訊為準；歷史文化敘述則避免擅自推翻 data.md，必要時指出來源差異。
8. 不可捏造沒有出現在 data.md 或網路來源中的事實。

【延續對話】
9. 可以參考最近對話、上次來源與上次推薦來理解「它、那個、第二個、剛剛推薦的幾個」等指涉。
10. 如果使用者說「深入介紹剛剛第二個景點」，只深入第二個；如果說「把剛剛推薦的幾個排成行程」，才整合那些景點安排順序。
11. 行程安排應以使用者指定／前文推薦的景點為核心，不要無故塞入新的景點；若新增可選站點，要清楚標成「可選」。

【詳細介紹與照片】
12. 使用者明確說「詳細、深入、完整介紹」時，不能只重複 data.md 的一小段。請在仍緊扣同一主題的前提下，優先用官方網路來源補足細節；可依資料涵蓋歷史沿革、信仰／文化、建築特色、值得留意之處與參觀實用資訊。
13. 詳細介紹通常以約 300～550 個中文字為目標；若官方來源資訊較少，寧可少寫，也不要臆測。
14. 使用者要求「照片、圖片、相片」時，若工具提供 image results，正文只需簡短說明，照片由介面另外顯示；不要回答成與前一輪完全相同的文字。

【表達方式】
15. 使用繁體中文與臺灣慣用語，以豆干弟導覽口吻自然回答。
16. 可用 1～4 個小標題、少量 emoji、粗體或條列讓內容好讀，但避免過度花俏。
17. 優先精準，再求完整。回答寧可少一點，也不要把低相關內容湊進來。
"""


class HistoryTurn(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(min_length=1, max_length=2500)
    sources: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    history: list[HistoryTurn] = Field(default_factory=list)
    last_recommendations: list[str] = Field(default_factory=list)
    active_topics: list[str] = Field(default_factory=list)
    conversation_id: str = Field(default="", max_length=160)


kb_data: list[dict[str, Any]] = []
idf_map: dict[str, float] = {}
doc_vectors: list[dict[str, float]] = []
doc_norms: list[float] = []
kb_mtime: float | None = None
_official_attractions_cache: list[dict[str, Any]] = []
_official_attractions_cache_at: float = 0.0
_official_consume_cache: list[dict[str, Any]] = []
_official_consume_cache_at: float = 0.0
_public_search_cache: dict[str, tuple[float, list[dict[str, str]]]] = {}
_official_page_image_cache: dict[str, list[dict[str, str]]] = {}
_official_album_cache: list[dict[str, Any]] = []
_official_album_cache_at: float = 0.0
_trusted_image_urls: set[str] = set()
_last_openai_error: str = ""
_last_openai_model_used: str = ""
_last_official_error: str = ""
_last_image_error: str = ""
_openai_quota_blocked_until: float = 0.0
SERVER_STATE_TTL_SECONDS = 4 * 60 * 60
_conversation_states: dict[str, dict[str, Any]] = {}


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").lower()
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[^0-9a-z\u4e00-\u9fff]", "", text)
    return text


def sanitize_error(exc: Exception | str) -> str:
    message = str(exc)
    message = re.sub(r"sk-[A-Za-z0-9_-]+", "[REDACTED_KEY]", message)
    message = re.sub(r"Bearer\s+[A-Za-z0-9._-]+", "Bearer [REDACTED]", message, flags=re.I)
    return message[:500]


def is_quota_error(exc: Exception | str) -> bool:
    text = str(exc).lower()
    return (
        "insufficient_quota" in text
        or "exceeded your current quota" in text
        or ("error code: 429" in text and "quota" in text)
    )


def _clean_conversation_id(value: str) -> str:
    value = re.sub(r"[^0-9A-Za-z._:-]", "", value or "")
    return value[:160]


def _prune_conversation_states() -> None:
    now = time.time()
    stale = [
        key for key, state in _conversation_states.items()
        if now - float(state.get("updated_at", 0.0)) > SERVER_STATE_TTL_SECONDS
    ]
    for key in stale:
        _conversation_states.pop(key, None)


def get_server_conversation_state(conversation_id: str) -> dict[str, Any]:
    conversation_id = _clean_conversation_id(conversation_id)
    if not conversation_id:
        return {}
    _prune_conversation_states()
    state = _conversation_states.get(conversation_id)
    return dict(state) if state else {}


def save_server_conversation_state(
    conversation_id: str,
    *,
    active_topics: list[str],
    recommendations: list[str],
    last_question: str,
    last_answer: str,
) -> None:
    conversation_id = _clean_conversation_id(conversation_id)
    if not conversation_id:
        return
    _conversation_states[conversation_id] = {
        "active_topics": [str(v) for v in active_topics if v][:5],
        "recommendations": [str(v) for v in recommendations if v][:8],
        "last_question": str(last_question or "")[:500],
        "last_answer": str(last_answer or "")[:2500],
        "updated_at": time.time(),
    }


def tokenize(text: str) -> list[str]:
    text = unicodedata.normalize("NFKC", text or "").lower()
    tokens: list[str] = []

    for word in re.findall(r"[a-z0-9]+", text):
        if len(word) >= 2:
            tokens.append(word)

    for seq in re.findall(r"[\u4e00-\u9fff]+", text):
        if seq in STOPWORDS:
            continue
        if 2 <= len(seq) <= 8:
            tokens.append(seq)
        for n in (2, 3, 4):
            if len(seq) >= n:
                tokens.extend(seq[i : i + n] for i in range(len(seq) - n + 1))

    return tokens


def expand_query(question: str) -> str:
    expanded = [question]
    q_norm = normalize_text(question)
    for trigger, extra in QUERY_EXPANSIONS.items():
        if normalize_text(trigger) in q_norm:
            expanded.append(extra)
    return " ".join(expanded)


def parse_data_md(content: str) -> list[dict[str, str]]:
    content = content.replace("\r\n", "\n")
    chunks: list[dict[str, str]] = []
    category = "大溪導覽"
    title: str | None = None
    body: list[str] = []

    def flush() -> None:
        nonlocal title, body
        if not title:
            return
        chunks.append({
            "category": category,
            "title": title.strip(),
            "text": "\n".join(body).strip(),
        })
        title = None
        body = []

    for raw_line in content.split("\n"):
        line = raw_line.rstrip()
        stripped = line.strip()

        if stripped.startswith("# ") and not stripped.startswith("## "):
            flush()
            category = stripped[2:].strip() or "大溪導覽"
            continue

        if stripped.startswith("## ") and not stripped.startswith("### "):
            flush()
            title = stripped[3:].strip()
            continue

        if title is not None:
            body.append(stripped[4:].strip() if stripped.startswith("### ") else line)

    flush()
    return [chunk for chunk in chunks if chunk["title"]]


def build_search_index() -> None:
    global kb_data, idf_map, doc_vectors, doc_norms, kb_mtime

    if not os.path.exists(DATA_MD):
        raise FileNotFoundError(f"找不到知識庫檔案：{DATA_MD}")

    with open(DATA_MD, "r", encoding="utf-8") as f:
        content = f.read()

    chunks = parse_data_md(content)
    if not chunks:
        raise RuntimeError("data.md 沒有可用的 ## 知識章節")

    tokenized_docs: list[list[str]] = []
    document_frequency: Counter[str] = Counter()

    for chunk in chunks:
        weighted_text = (
            f"{chunk['category']} {chunk['category']} "
            f"{chunk['title']} {chunk['title']} {chunk['title']} {chunk['title']} "
            f"{chunk['text']}"
        )
        tokens = tokenize(weighted_text)
        tokenized_docs.append(tokens)
        document_frequency.update(set(tokens))

    n_docs = len(chunks)
    idf = {term: math.log((1 + n_docs) / (1 + df)) + 1.0 for term, df in document_frequency.items()}

    vectors: list[dict[str, float]] = []
    norms: list[float] = []
    for tokens in tokenized_docs:
        counts = Counter(tokens)
        total = max(sum(counts.values()), 1)
        vector = {term: (count / total) * idf.get(term, 1.0) for term, count in counts.items()}
        vectors.append(vector)
        norms.append(math.sqrt(sum(weight * weight for weight in vector.values())) or 1.0)

    kb_data = chunks
    idf_map = idf
    doc_vectors = vectors
    doc_norms = norms
    kb_mtime = os.path.getmtime(DATA_MD)
    print(f"📚 data.md RAG 載入完成：{len(kb_data)} 個知識片段")


def maybe_reload_kb() -> None:
    global kb_mtime
    try:
        current_mtime = os.path.getmtime(DATA_MD)
    except OSError:
        return
    if kb_mtime is None or current_mtime != kb_mtime:
        build_search_index()


def cosine_similarity(query_vector: dict[str, float], query_norm: float, index: int) -> float:
    if query_norm <= 0:
        return 0.0
    doc_vector = doc_vectors[index]
    dot = sum(weight * doc_vector.get(term, 0.0) for term, weight in query_vector.items())
    return dot / (query_norm * doc_norms[index])


def is_route_request(question: str) -> bool:
    q = normalize_text(question)
    return any(normalize_text(marker) in q for marker in ROUTE_MARKERS)


def is_followup_question(question: str) -> bool:
    q = normalize_text(question)
    return any(normalize_text(marker) in q for marker in FOLLOWUP_MARKERS)


def extract_known_titles(text: str) -> list[str]:
    """找出文字裡直接提到的知識庫標題，優先保留較長實體名稱。

    例如「大溪木藝生態博物館」同時包含「大溪木藝」字樣，這裡只保留
    較完整的「大溪木藝生態博物館」，避免延續對話時把兩者誤判成兩個景點。
    """
    norm = normalize_text(text)
    matches: list[tuple[str, str]] = []
    for item in kb_data:
        title = item["title"]
        title_norm = normalize_text(title)
        if title_norm and title_norm in norm:
            matches.append((title, title_norm))

    matches.sort(key=lambda pair: len(pair[1]), reverse=True)
    found: list[str] = []
    kept_norms: list[str] = []
    for title, title_norm in matches:
        if any(title_norm in longer for longer in kept_norms):
            continue
        found.append(title)
        kept_norms.append(title_norm)
    return found


def ordinal_index(question: str) -> int | None:
    q = normalize_text(question)
    mapping = {
        "第一個": 0, "第1個": 0,
        "第二個": 1, "第2個": 1,
        "第三個": 2, "第3個": 2,
        "第四個": 3, "第4個": 3,
        "第五個": 4, "第5個": 4,
    }
    for marker, index in mapping.items():
        if normalize_text(marker) in q:
            return index
    return None


def ordinal_indices(question: str) -> list[int]:
    """支援「第二個跟第三個一起排」這種多選追問。"""
    q = normalize_text(question)
    mapping = [
        (("第一個", "第1個"), 0),
        (("第二個", "第2個"), 1),
        (("第三個", "第3個"), 2),
        (("第四個", "第4個"), 3),
        (("第五個", "第5個"), 4),
    ]
    found: list[int] = []
    for markers, index in mapping:
        if any(normalize_text(marker) in q for marker in markers):
            found.append(index)
    return found


def recent_recommendation_entities(history: list[HistoryTurn], last_recommendations: list[str]) -> list[str]:
    recommendations: list[str] = []
    for rec in last_recommendations:
        if rec and rec not in recommendations:
            recommendations.append(rec)
    if recommendations:
        return recommendations[:8]

    for turn in reversed(history[-MAX_HISTORY_TURNS:]):
        for rec in turn.recommendations:
            if rec and rec not in recommendations:
                recommendations.append(rec)
        if recommendations:
            break
    return recommendations[:8]


def recent_answer_entities(history: list[HistoryTurn]) -> list[str]:
    """取得最近回答真正的主題；代名詞「它／這個」優先指向這裡，而不是推薦按鈕。"""
    entities: list[str] = []
    for turn in reversed(history[-MAX_HISTORY_TURNS:]):
        if turn.role != "assistant":
            continue
        for source in turn.sources:
            if source and source not in entities:
                entities.append(source)
        for title in extract_known_titles(turn.text):
            if title not in entities:
                entities.append(title)
        if entities:
            break
    return entities[:8]


def resolve_question(
    question: str,
    history: list[HistoryTurn],
    last_recommendations: list[str],
    active_topics: list[str] | None = None,
) -> tuple[str, list[str]]:
    """把「它、第二個、剛剛推薦的幾個」解析成可檢索的具體問題。"""
    question = question.strip()
    q_norm = normalize_text(question)

    # 問句若帶有非常明確的意圖（巴洛克、停車、木藝等），意圖比地點背景詞更重要。
    # 例如「大溪老街的巴洛克」不能因為出現「大溪老街」就只鎖定老街總論。
    strong_focus: list[str] = []
    for trigger, titles in FOCUS_TITLE_GROUPS.items():
        if normalize_text(trigger) in q_norm:
            strong_focus.extend(titles)
    if strong_focus and not is_route_request(question):
        deduped = list(dict.fromkeys(strong_focus))
        return question, deduped

    explicit_titles = extract_known_titles(question)
    if explicit_titles:
        return question, explicit_titles

    continuation_by_state = bool(active_topics) and (wants_detail(question) or wants_images(question) or wants_nearby(question))
    if not is_followup_question(question) and not is_route_request(question) and not continuation_by_state:
        return question, []

    rec_entities = recent_recommendation_entities(history, last_recommendations)
    explicit_active = [topic for topic in (active_topics or []) if topic]
    answer_entities = explicit_active or recent_answer_entities(history)

    idx = ordinal_index(question)
    indices = ordinal_indices(question)
    q_norm = normalize_text(question)
    asks_recommendations = any(k in q_norm for k in ("推薦的", "剛剛推薦", "剛才推薦", "那些", "這些", "幾個"))

    if is_route_request(question) and len(indices) >= 2:
        pool = rec_entities or answer_entities
        selected = [pool[i] for i in indices if i < len(pool)][:5]
        if not selected:
            return question, []
    elif idx is not None:
        pool = rec_entities or answer_entities
        if idx >= len(pool):
            return question, []
        selected = [pool[idx]]
    elif is_route_request(question) or asks_recommendations:
        pronoun_anchor = any(k in q_norm for k in ("它", "這個", "那個", "此處", "這裡"))
        if pronoun_anchor and answer_entities:
            pool = list(dict.fromkeys([*answer_entities, *rec_entities]))
        else:
            pool = rec_entities or answer_entities
        if not pool:
            return question, []
        selected = pool[:5]
    else:
        # 「它／這個／深入介紹」通常指上一個回答主題，而不是回答下方的延伸推薦。
        pool = answer_entities or rec_entities
        if not pool:
            return question, []
        selected = pool[:1]

    resolved = f"{question}｜延續前文主題：{'、'.join(selected)}"
    return resolved, selected


def rank_retrieval(question: str) -> list[dict[str, Any]]:
    maybe_reload_kb()
    expanded = expand_query(question)
    query_tokens = tokenize(expanded)
    if not query_tokens:
        return []

    counts = Counter(query_tokens)
    total = max(sum(counts.values()), 1)
    query_vector = {term: (count / total) * idf_map.get(term, 1.0) for term, count in counts.items()}
    query_norm = math.sqrt(sum(weight * weight for weight in query_vector.values())) or 1.0

    q_norm = normalize_text(question)
    ranked: list[dict[str, Any]] = []

    for index, chunk in enumerate(kb_data):
        score = cosine_similarity(query_vector, query_norm, index)
        title_norm = normalize_text(chunk["title"])
        category_norm = normalize_text(chunk["category"])
        text_norm = normalize_text(chunk["text"])

        if title_norm and title_norm == q_norm:
            score += 3.0
        elif title_norm and title_norm in q_norm:
            score += 0.3 if chunk["title"] == "大溪老街" else 1.8
        elif q_norm and len(q_norm) >= 2 and q_norm in title_norm:
            score += 1.0

        for trigger, preferred_titles in INTENT_TITLE_BOOSTS.items():
            if normalize_text(trigger) in q_norm and chunk["title"] in preferred_titles:
                score += 1.25

        if q_norm and len(q_norm) >= 4 and q_norm in text_norm:
            score += 0.8
        if category_norm and category_norm in q_norm:
            score += 0.5

        ranked.append({**chunk, "score": round(score, 6)})

    ranked.sort(key=lambda item: item["score"], reverse=True)
    return ranked


def retrieve(question: str, top_k: int = TOP_K, focus_entities: list[str] | None = None) -> list[dict[str, Any]]:
    """先排名，再用主題焦點過濾，避免低相關片段被一起送進模型。"""
    ranked = rank_retrieval(question)
    if not ranked:
        return []

    q_norm = normalize_text(question)
    route_mode = is_route_request(question)
    focus_entities = focus_entities or []

    # 1) 明確的焦點群組：例如「木藝」只留木藝與木藝博物館，不把武德殿混進來。
    preferred: list[str] = []

    # 對話延續已明確解析出「第二個／它」時，以解析出的實體為最高優先，
    # 不再被一般關鍵字群組擴張成其他章節。
    if focus_entities and not route_mode:
        preferred.extend(focus_entities)
    elif not route_mode:
        explicit_titles = extract_known_titles(question)
        if explicit_titles:
            preferred.extend(explicit_titles[:2])
        elif not any(word in q_norm for word in ("館舍", "展館", "有哪些館", "館群")):
            for trigger, titles in FOCUS_TITLE_GROUPS.items():
                if normalize_text(trigger) in q_norm:
                    preferred.extend(titles)

    if preferred:
        preferred_set = set(preferred)
        focused = [item for item in ranked if item["title"] in preferred_set and item["score"] >= MIN_RETRIEVAL_SCORE]
        if focused:
            return focused[: min(top_k, 3)]

    # 行程若是延續「剛剛推薦的幾個景點」，只帶入那些景點本身 + 路線/交通章節，
    # 不因關鍵字重疊把其他章節（例如只因含「木藝」的片段）混進來。
    if route_mode and focus_entities:
        allowed = set(focus_entities) | {"建議遊覽路線", "交通、停車與實用注意事項"}
        route_hits = [
            item for item in ranked
            if item["title"] in allowed and item["score"] >= MIN_RETRIEVAL_SCORE
        ]
        if route_hits:
            return route_hits[: min(top_k, 6)]

    # 3) 行程模式允許多個片段；單一問答則提高相對門檻，排除弱相關章節。
    best_score = ranked[0]["score"]
    if route_mode:
        threshold = max(MIN_RETRIEVAL_SCORE, best_score * 0.16)
        limit = min(top_k, 5)
    else:
        threshold = max(MIN_RETRIEVAL_SCORE, best_score * 0.38)
        limit = min(top_k, 3)

    hits = [item for item in ranked if item["score"] >= threshold][:limit]

    if not hits:
        top = ranked[0]
        if top["score"] >= MIN_RETRIEVAL_SCORE:
            hits = [top]

    return hits


def build_context(hits: list[dict[str, Any]]) -> str:
    blocks = []
    for i, hit in enumerate(hits, start=1):
        blocks.append(
            f"[片段 {i}]\n"
            f"分類：{hit['category']}\n"
            f"標題：{hit['title']}\n"
            f"內容：\n{hit['text'].strip()}"
        )
    return "\n\n---\n\n".join(blocks)


def build_history_context(history: list[HistoryTurn]) -> str:
    if not history:
        return "（沒有前文）"
    lines: list[str] = []
    for turn in history[-MAX_HISTORY_TURNS:]:
        speaker = "使用者" if turn.role == "user" else "豆干弟"
        extras: list[str] = []
        if turn.sources:
            extras.append(f"來源焦點：{'、'.join(turn.sources[:5])}")
        if turn.recommendations:
            extras.append(f"當時推薦：{'、'.join(turn.recommendations[:5])}")
        suffix = f"（{'；'.join(extras)}）" if extras else ""
        lines.append(f"{speaker}：{turn.text.strip()}{suffix}")
    return "\n".join(lines)


def choose_recommendations(hits: list[dict[str, Any]], question: str, limit: int = 3) -> list[str]:
    selected = {hit["title"] for hit in hits}
    recommendations: list[str] = []

    # 木藝單一主題不要把「武德殿」硬塞成回答正文；推薦則只選真正可延伸的相關主題。
    q_norm = normalize_text(question)
    if "木藝" in q_norm or "木器" in q_norm:
        preferred = ["大溪木藝生態博物館", "大溪老街", "鳳飛飛故事館"]
        for title in preferred:
            if title not in selected and any(item["title"] == title for item in kb_data):
                recommendations.append(title)
        return recommendations[:limit]

    categories = [hit["category"] for hit in hits]
    for category in categories:
        for item in kb_data:
            if item["category"] == category and item["title"] not in selected and item["title"] not in recommendations:
                recommendations.append(item["title"])
                if len(recommendations) >= limit:
                    return recommendations

    for item in kb_data:
        if item["title"] not in selected and item["title"] not in recommendations:
            recommendations.append(item["title"])
            if len(recommendations) >= limit:
                break
    return recommendations


def clean_markdown_for_local(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^\s*[-*]\s+", "• ", text, flags=re.MULTILINE)
    return text.replace("**", "")


def _record_title(record: dict[str, Any] | None, fallback: str = "景點") -> str:
    if not record:
        return fallback
    return str(record.get("name") or fallback).strip() or fallback


def _format_nearby_answer(
    origin: dict[str, Any] | None,
    nearby_records: list[dict[str, Any]],
) -> str:
    origin_name = _record_title(origin, "這個景點")
    lines = [f"📍 **{origin_name}附近可以順遊這幾站**"]
    for index, record in enumerate(nearby_records[:5], start=1):
        name = str(record.get("name") or "附近景點")
        distance = record.get("distance_km")
        distance_text = f"，約 {distance:.1f} 公里" if isinstance(distance, (int, float)) else ""
        summary = str(record.get("summary") or record.get("description") or "").strip()
        if len(summary) > 85:
            summary = summary[:85].rstrip() + "…"
        detail = f" — {summary}" if summary else ""
        lines.append(f"{index}. **{name}**{distance_text}{detail}")
    lines.append("\n如果你願意，我可以直接把上面幾個景點排成 **2 小時、半日或一日** 的順遊路線。")
    return "\n".join(lines)


def _format_local_route_answer(records: list[dict[str, Any]], question: str) -> str:
    if not records:
        return ""
    lines = ["🧭 **豆干弟幫你把剛剛的景點串成一條路線**"]
    for index, record in enumerate(records, start=1):
        name = str(record.get("name") or f"第 {index} 站")
        address = str(record.get("address") or "").strip()
        suffix = f"｜{address}" if address else ""
        lines.append(f"{index}. **{name}**{suffix}")
    if "半日" in question:
        lines.append("\n這條可以當作半日散策的骨架；實際停留時間可依你想拍照、吃東西或看展的比例調整。")
    else:
        lines.append("\n這是依景點位置做的順遊順序；如果你告訴我可用時間，我可以再縮成更精準的版本。")
    return "\n".join(lines)


def local_rag_answer(
    question: str,
    hits: list[dict[str, Any]],
    official_record: dict[str, Any] | None = None,
    available_images: list[dict[str, str]] | None = None,
    nearby_records: list[dict[str, Any]] | None = None,
    route_records: list[dict[str, Any]] | None = None,
    public_results: list[dict[str, str]] | None = None,
) -> str:
    nearby_records = nearby_records or []
    route_records = route_records or []
    public_results = public_results or []

    # 這兩類追問應優先吃「上一輪主題 + 官方資料」，不能先被 hits 是否存在擋掉。
    if wants_nearby(question) and nearby_records:
        return _format_nearby_answer(official_record, nearby_records)

    if is_route_request(question) and route_records:
        return _format_local_route_answer(route_records, question)

    title = _record_title(official_record, hits[0]["title"] if hits else "景點")

    if wants_images(question):
        if available_images:
            return (
                f"📷 **{title}照片**\n\n"
                "已找到官方來源圖片，我放在這則回答下方；點照片可以開啟來源頁面。"
            )
        return (
            f"📷 **{title}照片**\n\n"
            "這一輪仍沒有取得可安全顯示的官方圖片網址。豆干弟不會用不明來源圖片代替。\n\n"
            "你可以點下方的官方來源頁；新版也會把這次圖片抓取失敗原因寫進診斷資訊，方便直接排查。"
        )

    # data.md 沒有獨立章節，但桃園官方「消費／美食」有直接命中的實體時，
    # 例如「月光餅 → 陳媽媽月光餅」，應優先回答官方實體，而不是退回寬泛的美食章節。
    if official_record and official_record.get("entity_type") == "consume":
        name = str(official_record.get("name") or title)
        q_norm = normalize_text(question)
        n_norm = normalize_text(name)
        direct_match = (q_norm and q_norm in n_norm) or (n_norm and n_norm in q_norm)
        if direct_match or not hits or wants_detail(question):
            paragraphs = [f"🍴 **{name}**"]
            detail = str(official_record.get("description") or official_record.get("summary") or "").strip()
            if detail:
                paragraphs.append(detail)
            extras: list[str] = []
            if official_record.get("address"):
                extras.append(f"📍 **地址**：{official_record['address']}")
            if official_record.get("open_time"):
                extras.append(f"🕒 **營業／開放資訊**：{official_record['open_time']}")
            if official_record.get("tel"):
                extras.append(f"☎️ **電話**：{official_record['tel']}")
            if extras:
                paragraphs.append("\n".join(extras))
            if len(paragraphs) == 1 and public_results:
                external = local_external_answer(question, public_results)
                if external:
                    paragraphs.append(external)
            return "\n\n".join(paragraphs).strip()

    # 即使 data.md 沒有該景點，只要官方資料有，就仍可延續上一輪做深入介紹。
    if wants_detail(question) and official_record:
        data_body = clean_markdown_for_local(hits[0]["text"]) if hits else ""
        detail = str(official_record.get("description") or official_record.get("summary") or "").strip()
        paragraphs: list[str] = [f"🏮 **{title}｜深入導覽**"]
        if detail:
            paragraphs.append(detail)
        elif data_body:
            paragraphs.append(data_body)

        extras: list[str] = []
        if official_record.get("address"):
            extras.append(f"📍 **地址**：{official_record['address']}")
        if official_record.get("open_time"):
            extras.append(f"🕒 **開放資訊**：{official_record['open_time']}")
        if official_record.get("tel"):
            extras.append(f"☎️ **電話**：{official_record['tel']}")
        if extras:
            paragraphs.append("\n".join(extras))
        return "\n\n".join(paragraphs).strip()

    # data.md 只有寬泛章節、沒有直接命中這個新名詞時，外部搜尋結果要優先於寬泛 RAG。
    # 例如問「月光餅」不應只回「傳統甜品與小吃」整章，而應直接顯示月光餅的官方／網路結果。
    if public_results and not has_direct_kb_topic(question, hits):
        external = local_external_answer(question, public_results)
        if external:
            return external

    if not hits:
        if official_record:
            detail = str(official_record.get("summary") or official_record.get("description") or "").strip()
            if detail:
                return f"🏮 **{title}**\n\n{detail}"
        external = local_external_answer(question, public_results)
        if external:
            return external
        return (
            f"😅 這題目前 data.md、桃園官方資料與公開網路搜尋都還沒有取得足夠可靠內容來回答「{question}」。\n\n"
            "你可以換一個更完整的名稱，豆干弟會再從官方網站優先搜尋。"
        )

    if len(hits) == 1:
        hit = hits[0]
        body = clean_markdown_for_local(hit["text"])
        if wants_detail(question):
            return f"🏮 **{hit['title']}**\n\n{body}"
        return f"🏮 **{hit['title']}**\n\n{body}"

    parts = ["🏮 **這題的重點可以這樣看**"]
    for hit in hits[:3]:
        body = clean_markdown_for_local(hit["text"])
        if len(body) > 360:
            body = body[:360].rstrip() + "…"
        parts.append(f"**{hit['title']}**\n{body}")
    return "\n\n".join(parts)

def _xml_child_text(element: ET.Element, *names: str) -> str:
    wanted = {name.lower() for name in names}
    for child in list(element):
        tag = child.tag.split("}")[-1].lower()
        if tag in wanted:
            return (child.text or "").strip()
    return ""


async def load_official_attractions() -> list[dict[str, Any]]:
    """讀取桃園觀光導覽網官方 Open Data，並短時間快取。

    這條路徑不依賴 OpenAI，因此 API 額度不足時，詳細景點資料與照片仍可顯示。
    """
    global _official_attractions_cache, _official_attractions_cache_at, _last_official_error
    now = time.time()
    if _official_attractions_cache and now - _official_attractions_cache_at < OFFICIAL_CACHE_SECONDS:
        return _official_attractions_cache

    try:
        timeout = httpx.Timeout(12.0, connect=6.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers={"User-Agent": "Daxi-AI-Guide/5.0"}) as client:
            response = await client.get(TYCG_ATTRACTIONS_OPEN_DATA)
            response.raise_for_status()
            root = ET.fromstring(response.content)
    except Exception as exc:
        _last_official_error = f"{type(exc).__name__}: {sanitize_error(exc)}"
        print(f"⚠️ 桃園觀光官方 Open Data 讀取失敗：{_last_official_error}")
        return _official_attractions_cache

    records: list[dict[str, Any]] = []
    for element in root.iter():
        name = _xml_child_text(element, "Name")
        if not name:
            continue
        record_id = _xml_child_text(element, "Id", "ID", "InfoId", "InfoID")
        pictures: list[dict[str, str]] = []
        for i in range(1, 4):
            image_url = _xml_child_text(element, f"Picture{i}", f"PictureUrl{i}", f"PictureURL{i}")
            if not image_url:
                continue
            pictures.append({
                "image_url": image_url,
                "thumbnail_url": image_url,
                "source_url": (_xml_child_text(element, "TYWebsite") or (f"https://travel.tycg.gov.tw/zh-tw/travel/attraction/{record_id}" if record_id else "https://travel.tycg.gov.tw/")),
                "caption": _xml_child_text(element, f"Picdescribe{i}", f"PictureDescription{i}") or f"{name}｜桃園觀光導覽網官方照片",
            })
        records.append({
            "id": record_id,
            "name": name,
            "summary": _xml_child_text(element, "Toldescribe"),
            "description": _xml_child_text(element, "Description", "Description1"),
            "address": _xml_child_text(element, "Add", "Address"),
            "open_time": _xml_child_text(element, "Opentime", "OpenTime"),
            "tel": _xml_child_text(element, "Tel", "Telephone"),
            "website": _xml_child_text(element, "Website"),
            "ty_website": _xml_child_text(element, "TYWebsite"),
            "px": _xml_child_text(element, "Px", "Longitude"),
            "py": _xml_child_text(element, "Py", "Latitude"),
            "pictures": pictures,
            "source_url": (_xml_child_text(element, "TYWebsite") or (f"https://travel.tycg.gov.tw/zh-tw/travel/attraction/{record_id}" if record_id else "https://travel.tycg.gov.tw/")),
        })

    # 去除因 root.iter() 可能造成的重複記錄。
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for record in records:
        key = (record.get("id", ""), record.get("name", ""))
        if key not in unique:
            unique[key] = record
    _official_attractions_cache = list(unique.values())
    _official_attractions_cache_at = now
    _last_official_error = ""
    print(f"🌐 桃園觀光官方 Open Data 載入：{len(_official_attractions_cache)} 筆景點")
    return _official_attractions_cache


def attraction_match_score(query: str, name: str) -> float:
    q = normalize_text(query)
    n = normalize_text(name)
    if not q or not n:
        return 0.0
    if q == n:
        return 100.0
    if n in q:
        return 80.0 + min(len(n), 20) / 20
    if q in n and len(q) >= 2:
        return 65.0 + min(len(q), 20) / 20
    q_tokens = set(tokenize(query))
    n_tokens = set(tokenize(name))
    if not q_tokens or not n_tokens:
        return 0.0
    return 20.0 * len(q_tokens & n_tokens) / max(len(n_tokens), 1)


async def find_official_attraction(query: str, focus_entities: list[str] | None = None) -> dict[str, Any] | None:
    records = await load_official_attractions()
    if not records:
        return None
    candidate_queries = entity_query_variants(query, focus_entities)
    best: tuple[float, dict[str, Any] | None] = (0.0, None)
    for record in records:
        name = str(record.get("name", ""))
        score = max((attraction_match_score(candidate, name) for candidate in candidate_queries if candidate), default=0.0)
        if score > best[0]:
            best = (score, record)
    return best[1] if best[0] >= 60 else None


async def load_official_consumes() -> list[dict[str, Any]]:
    """讀取桃園觀光導覽網「消費／美食」官方 Open Data。

    這層專門補 data.md 沒有建立獨立章節的店家、食品與伴手禮，
    例如「月光餅」。不依賴 OpenAI API 額度。
    """
    global _official_consume_cache, _official_consume_cache_at, _last_official_error
    now = time.time()
    if _official_consume_cache and now - _official_consume_cache_at < OFFICIAL_CACHE_SECONDS:
        return _official_consume_cache

    root: ET.Element | None = None
    errors: list[str] = []
    timeout = httpx.Timeout(12.0, connect=6.0)
    headers = {"User-Agent": "Mozilla/5.0 Daxi-AI-Guide/10.0"}
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
        for endpoint in TYCG_CONSUME_OPEN_DATA_CANDIDATES:
            try:
                response = await client.get(endpoint)
                response.raise_for_status()
                root = ET.fromstring(response.content)
                if root is not None:
                    break
            except Exception as exc:
                errors.append(f"{endpoint}: {type(exc).__name__}: {sanitize_error(exc)}")

    if root is None:
        if errors:
            _last_official_error = " | ".join(errors[-2:])
        return _official_consume_cache

    records: list[dict[str, Any]] = []
    for element in root.iter():
        name = _xml_child_text(element, "Name")
        if not name:
            continue
        record_id = _xml_child_text(element, "Id", "ID", "InfoId", "InfoID")
        ty_website = _xml_child_text(element, "TYWebsite")
        source_url = ty_website or (
            f"https://travel.tycg.gov.tw/zh-tw/Consume/Detail/{record_id}" if record_id else "https://travel.tycg.gov.tw/zh-tw/consume/list"
        )
        pictures: list[dict[str, str]] = []
        for i in range(1, 4):
            image_url = _xml_child_text(element, f"Picture{i}", f"PictureUrl{i}", f"PictureURL{i}")
            if image_url:
                pictures.append({
                    "image_url": image_url,
                    "thumbnail_url": image_url,
                    "source_url": source_url,
                    "caption": _xml_child_text(element, f"Picdescribe{i}", f"PictureDescription{i}") or f"{name}｜桃園觀光導覽網官方照片",
                })
        records.append({
            "id": record_id,
            "entity_type": "consume",
            "name": name,
            "summary": _xml_child_text(element, "Toldescribe"),
            "description": _xml_child_text(element, "Description", "Description1"),
            "address": _xml_child_text(element, "Add", "Address"),
            "open_time": _xml_child_text(element, "Opentime", "OpenTime"),
            "tel": _xml_child_text(element, "Tel", "Telephone"),
            "website": _xml_child_text(element, "Website"),
            "ty_website": ty_website,
            "px": _xml_child_text(element, "Px", "Longitude"),
            "py": _xml_child_text(element, "Py", "Latitude"),
            "pictures": pictures,
            "source_url": source_url,
        })

    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for record in records:
        key = (str(record.get("id") or ""), str(record.get("name") or ""))
        if key not in unique:
            unique[key] = record
    _official_consume_cache = list(unique.values())
    _official_consume_cache_at = now
    if _official_consume_cache:
        print(f"🍴 桃園觀光官方消費 Open Data 載入：{len(_official_consume_cache)} 筆")
    return _official_consume_cache


def entity_query_variants(query: str, focus_entities: list[str] | None = None) -> list[str]:
    variants: list[str] = [*(focus_entities or []), query]
    cleaned = re.sub(r"[|｜].*$", "", query).strip()
    for phrase in (
        "請問", "可以", "幫我", "介紹一下", "詳細介紹", "深入介紹", "介紹",
        "是什麼", "是甚麼", "有什麼特色", "有什麼", "照片", "圖片", "相片",
        "更多資訊", "詳細一點", "再詳細一點",
    ):
        cleaned = cleaned.replace(phrase, " ")
    cleaned = re.sub(r"[？?！!，,。\s]+", " ", cleaned).strip()
    if cleaned:
        variants.append(cleaned)
    return list(dict.fromkeys(v for v in variants if v))


async def find_official_consume(query: str, focus_entities: list[str] | None = None) -> dict[str, Any] | None:
    records = await load_official_consumes()
    if not records:
        return None
    candidate_queries = entity_query_variants(query, focus_entities)
    best: tuple[float, dict[str, Any] | None] = (0.0, None)
    for record in records:
        name = str(record.get("name", ""))
        score = max((attraction_match_score(candidate, name) for candidate in candidate_queries if candidate), default=0.0)
        # 消費資料名稱常是「陳媽媽月光餅」，查「月光餅」也應視為高可信直接命中。
        nn = normalize_text(name)
        for candidate in candidate_queries:
            qn = normalize_text(candidate)
            if qn and len(qn) >= 2 and qn in nn:
                score = max(score, 78.0)
        if score > best[0]:
            best = (score, record)
    return best[1] if best[0] >= 60 else None


async def find_official_entity(query: str, focus_entities: list[str] | None = None) -> dict[str, Any] | None:
    """景點與美食／店家都當成可延續的官方實體。

    優先沿用 focus entity；若 data.md 沒有該名詞，仍可由桃園官方資料命中。
    """
    attraction = await find_official_attraction(query, focus_entities)
    consume = await find_official_consume(query, focus_entities)
    if attraction and consume:
        candidates = [*(focus_entities or []), query]
        a_score = max(attraction_match_score(c, str(attraction.get("name") or "")) for c in candidates if c)
        c_score = max(attraction_match_score(c, str(consume.get("name") or "")) for c in candidates if c)
        return consume if c_score > a_score else attraction
    return attraction or consume


def _strip_html_text(raw_html: str) -> str:
    text = re.sub(r"(?is)<(script|style|noscript).*?>.*?</\1>", " ", raw_html)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _decode_ddg_result_url(url: str) -> str:
    if not url:
        return ""
    full = urljoin("https://duckduckgo.com", unescape(url))
    parsed = urlparse(full)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        values = parse_qs(parsed.query).get("uddg") or []
        if values:
            return unquote(values[0])
    return full


async def public_web_search(query: str, limit: int = 5) -> list[dict[str, str]]:
    """OpenAI 額度不足時的公開網路搜尋備援。

    先以桃園市政府、桃園觀光與交通部觀光署官方網域搜尋；官方找不到時
    才做一般網路搜尋。結果只使用搜尋結果標題／摘要與原始網址，不假裝是 data.md。
    """
    key = normalize_text(query)
    cached = _public_search_cache.get(key)
    if cached and time.time() - cached[0] < OFFICIAL_CACHE_SECONDS:
        return cached[1][:limit]

    clean_query = re.sub(r"[|｜].*$", "", query).strip()
    search_queries = [
        f'site:travel.tycg.gov.tw 大溪 "{clean_query}"',
        f'site:tycg.gov.tw 大溪 "{clean_query}"',
        f'site:taiwan.net.tw 大溪 "{clean_query}"',
        f'大溪 "{clean_query}"',
    ]
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    timeout = httpx.Timeout(10.0, connect=5.0)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.7",
    }

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
            for search_query in search_queries:
                if len(results) >= limit:
                    break
                try:
                    response = await client.get("https://html.duckduckgo.com/html/", params={"q": search_query})
                    response.raise_for_status()
                    html = response.text
                except Exception:
                    continue

                # DuckDuckGo HTML 版：每個 result 區塊包含 result__a / result__snippet。
                blocks = re.findall(r'(?is)<div[^>]+class="[^"]*result[^"]*"[^>]*>(.*?)</div>\s*</div>', html)
                if not blocks:
                    blocks = re.findall(r'(?is)<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html)
                    for href, title_html in blocks:
                        url = _decode_ddg_result_url(href)
                        if not url or url in seen:
                            continue
                        seen.add(url)
                        host = urlparse(url).netloc.replace("www.", "")
                        results.append({"type": "web", "title": _strip_html_text(title_html), "url": url, "domain": host, "snippet": ""})
                        if len(results) >= limit:
                            break
                    continue

                for block in blocks:
                    link_match = re.search(r'(?is)<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block)
                    if not link_match:
                        continue
                    url = _decode_ddg_result_url(link_match.group(1))
                    if not url or url in seen or not url.startswith(("http://", "https://")):
                        continue
                    snippet_match = re.search(r'(?is)<a[^>]+class="result__snippet"[^>]*>(.*?)</a>|<div[^>]+class="result__snippet"[^>]*>(.*?)</div>', block)
                    snippet_html = (snippet_match.group(1) or snippet_match.group(2)) if snippet_match else ""
                    seen.add(url)
                    host = urlparse(url).netloc.replace("www.", "")
                    results.append({
                        "type": "web",
                        "title": _strip_html_text(link_match.group(2)) or host,
                        "url": url,
                        "domain": host,
                        "snippet": _strip_html_text(snippet_html),
                    })
                    if len(results) >= limit:
                        break
    except Exception:
        pass

    # 官方來源永遠排前面；其次才是一般網路結果。
    def official_rank(item: dict[str, str]) -> tuple[int, int]:
        host = item.get("domain", "").lower()
        official = any(host == d or host.endswith("." + d) for d in OFFICIAL_WEB_DOMAINS)
        return (0 if official else 1, 0)

    results.sort(key=official_rank)
    _public_search_cache[key] = (time.time(), results[:limit])
    return results[:limit]


def build_public_search_context(results: list[dict[str, str]]) -> str:
    if not results:
        return "（沒有額外公開網路搜尋結果）"
    blocks: list[str] = []
    for item in results[:5]:
        snippet = item.get("snippet", "").strip()
        blocks.append(
            f"標題：{item.get('title', '')}\n網址：{item.get('url', '')}"
            + (f"\n摘要：{snippet}" if snippet else "")
        )
    return "\n\n---\n\n".join(blocks)


def local_external_answer(query: str, results: list[dict[str, str]]) -> str:
    if not results:
        return ""
    clean_query = re.sub(r"[|｜].*$", "", query).strip()
    lines = [f"🌐 **{clean_query}｜網路補充**"]
    for item in results[:3]:
        title = item.get("title") or item.get("domain") or "相關資料"
        snippet = item.get("snippet", "").strip()
        if snippet:
            if len(snippet) > 220:
                snippet = snippet[:220].rstrip() + "…"
            lines.append(f"**{title}**\n{snippet}")
        else:
            lines.append(f"**{title}**\n可從下方來源連結查看完整內容。")
    return "\n\n".join(lines)


def _safe_float(value: Any) -> float | None:
    try:
        result = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


async def find_nearby_attractions(
    origin: dict[str, Any] | None,
    limit: int = 5,
    max_distance_km: float = 3.0,
) -> list[dict[str, Any]]:
    """直接用桃園觀光官方景點座標找附近景點，不依賴 OpenAI。"""
    if not origin:
        return []
    origin_lon = _safe_float(origin.get("px"))
    origin_lat = _safe_float(origin.get("py"))
    if origin_lon is None or origin_lat is None:
        return []

    origin_name = normalize_text(str(origin.get("name") or ""))
    origin_id = str(origin.get("id") or "")
    records = await load_official_attractions()
    ranked: list[dict[str, Any]] = []
    for record in records:
        if origin_id and str(record.get("id") or "") == origin_id:
            continue
        if origin_name and normalize_text(str(record.get("name") or "")) == origin_name:
            continue
        lon = _safe_float(record.get("px"))
        lat = _safe_float(record.get("py"))
        if lon is None or lat is None:
            continue
        distance = _haversine_km(origin_lat, origin_lon, lat, lon)
        if 0.03 <= distance <= max_distance_km:
            item = dict(record)
            item["distance_km"] = round(distance, 2)
            ranked.append(item)

    ranked.sort(key=lambda item: item.get("distance_km", 999.0))
    return ranked[:limit]


async def find_official_records_for_entities(entities: list[str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entity in entities[:6]:
        record = await find_official_entity(entity, [entity])
        if not record:
            continue
        key = str(record.get("id") or record.get("name") or "")
        if key and key not in seen:
            seen.add(key)
            records.append(record)
    return records


def order_records_by_nearest(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """用簡單最近鄰方式排順遊順序；沒有座標的景點維持原順序放最後。"""
    if len(records) <= 2:
        return records[:]
    with_coords: list[dict[str, Any]] = []
    without_coords: list[dict[str, Any]] = []
    for record in records:
        if _safe_float(record.get("px")) is None or _safe_float(record.get("py")) is None:
            without_coords.append(record)
        else:
            with_coords.append(record)
    if not with_coords:
        return records[:]

    ordered = [with_coords.pop(0)]
    while with_coords:
        current = ordered[-1]
        current_lon = _safe_float(current.get("px"))
        current_lat = _safe_float(current.get("py"))
        assert current_lon is not None and current_lat is not None
        next_index = min(
            range(len(with_coords)),
            key=lambda idx: _haversine_km(
                current_lat,
                current_lon,
                _safe_float(with_coords[idx].get("py")) or current_lat,
                _safe_float(with_coords[idx].get("px")) or current_lon,
            ),
        )
        ordered.append(with_coords.pop(next_index))
    return [*ordered, *without_coords]


def build_official_context(record: dict[str, Any] | None) -> str:
    if not record:
        return "（本輪未取得桃園觀光官方景點資料）"
    fields = [
        f"官方實體：{record.get('name', '')}",
        f"簡介：{record.get('summary', '')}" if record.get("summary") else "",
        f"詳細描述：{record.get('description', '')}" if record.get("description") else "",
        f"地址：{record.get('address', '')}" if record.get("address") else "",
        f"開放時間：{record.get('open_time', '')}" if record.get("open_time") else "",
        f"電話：{record.get('tel', '')}" if record.get("tel") else "",
        f"官方頁面：{record.get('source_url', '')}" if record.get("source_url") else "",
    ]
    return "\n".join(field for field in fields if field)


def build_official_records_context(records: list[dict[str, Any]]) -> str:
    if not records:
        return "（沒有額外官方景點資料）"
    blocks: list[str] = []
    for record in records[:6]:
        block = build_official_context(record)
        distance = record.get("distance_km")
        if isinstance(distance, (int, float)):
            block += f"\n與目前景點直線距離：約 {distance:.2f} 公里"
        blocks.append(block)
    return "\n\n---\n\n".join(blocks)


def official_source_from_record(record: dict[str, Any] | None) -> dict[str, str] | None:
    if not record or not record.get("source_url"):
        return None
    return {
        "type": "web",
        "title": f"桃園觀光導覽網｜{record.get('name', '官方資料')}",
        "url": str(record["source_url"]),
        "domain": "travel.tycg.gov.tw",
    }


def official_album_source_for_name(name: str) -> dict[str, str] | None:
    name_norm = normalize_text(name)
    for key, url in OFFICIAL_ALBUM_PAGE_MAP.items():
        key_norm = normalize_text(key)
        if key_norm in name_norm or name_norm in key_norm:
            return {
                "type": "web",
                "title": f"桃園觀光官方相簿｜{key}",
                "url": url,
                "domain": "travel.tycg.gov.tw",
            }
    return None


def official_images_from_record(record: dict[str, Any] | None) -> list[dict[str, str]]:
    if not record:
        return []
    pictures = record.get("pictures") or []
    return [pic for pic in pictures if pic.get("image_url")][:4]



def _looks_like_image_url(url: str) -> bool:
    """寬鬆判斷是否可能是圖片 URL。

    桃園觀光頁面可能使用 CDN、lazy-load、srcset、CSS background-image、
    查詢參數或不固定的 /image/ 路徑。真正是否為圖片，後續再用
    HTTP Content-Type 驗證，因此這裡不再只接受少數固定路徑。
    """
    lower = (url or "").lower().strip()
    if not lower.startswith(("http://", "https://", "/")):
        return False
    if any(bad in lower for bad in (
        "favicon", "sprite", "qrcode", "qr-code", "loading", "placeholder",
        "logo", "icon", "avatar", "blank.gif", ".svg", ".ico",
    )):
        return False
    return (
        bool(re.search(r"\.(?:jpe?g|png|webp|gif|avif)(?:$|[?#])", lower))
        or any(token in lower for token in (
            "/image/", "/images/", "/upload/", "/uploads/", "/photo/", "/photos/",
            "/media/", "/file/", "/files/", "photoid=", "imageid=",
        ))
    )

def _register_trusted_images(images: list[dict[str, str]]) -> list[dict[str, str]]:
    registered: list[dict[str, str]] = []
    for image in images:
        url = str(image.get("image_url") or "").strip()
        if not url:
            continue
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            continue
        _trusted_image_urls.add(url)
        item = dict(image)
        item["proxy_url"] = f"/image-proxy?url={quote(url, safe='')}"
        registered.append(item)
    return registered


def _extract_urls_from_element(element: ET.Element) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for node in element.iter():
        values = [node.text or "", *node.attrib.values()]
        for value in values:
            for match in re.findall(r"https?://[^\s<>'\"]+", unescape(value)):
                url = match.rstrip("),.;")
                if url not in seen:
                    seen.add(url)
                    urls.append(url)
    return urls


async def load_official_albums() -> list[dict[str, Any]]:
    """讀取桃園觀光「觀光相簿」Open Data。

    桃園官方把景點基本資料與相簿拆成不同資料集；這裡用寬鬆 XML 解析，
    即使 Photos 內部欄位名稱調整，只要仍包含圖片 URL 就能抓到。
    """
    global _official_album_cache, _official_album_cache_at
    now = time.time()
    if _official_album_cache and now - _official_album_cache_at < OFFICIAL_CACHE_SECONDS:
        return _official_album_cache

    timeout = httpx.Timeout(12.0, connect=6.0)
    headers = {"User-Agent": "Daxi-AI-Guide/10.0"}
    root: ET.Element | None = None
    used_url = ""
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
        for endpoint in TYCG_ALBUM_OPEN_DATA_CANDIDATES:
            try:
                response = await client.get(endpoint)
                response.raise_for_status()
                candidate_root = ET.fromstring(response.content)
                if candidate_root is not None:
                    root = candidate_root
                    used_url = endpoint
                    break
            except Exception:
                continue

    if root is None:
        global _last_image_error
        if not _last_image_error:
            _last_image_error = "桃園觀光相簿 Open Data 端點未回傳可解析 XML；系統將改用官方景點頁／相簿頁抓圖"
        return _official_album_cache

    records: list[dict[str, Any]] = []
    for element in root.iter():
        name = _xml_child_text(element, "Name")
        if not name:
            continue
        urls = [url for url in _extract_urls_from_element(element) if _looks_like_image_url(url)]
        if not urls:
            continue
        source_url = _xml_child_text(element, "TYWebsite", "Website") or used_url
        photos = [
            {
                "image_url": url,
                "thumbnail_url": url,
                "source_url": source_url,
                "caption": f"{name}｜桃園觀光導覽網官方相簿",
            }
            for url in urls[:8]
        ]
        records.append({"name": name, "source_url": source_url, "pictures": photos})

    _official_album_cache = records
    _official_album_cache_at = now
    if records:
        print(f"📷 桃園觀光官方相簿載入：{len(records)} 筆")
    return records


async def find_album_images(query: str, focus_entities: list[str] | None = None) -> list[dict[str, str]]:
    records = await load_official_albums()
    if not records:
        return []
    candidates = [*(focus_entities or []), query]
    ranked: list[tuple[float, dict[str, Any]]] = []
    for record in records:
        score = max(
            (attraction_match_score(candidate, str(record.get("name", ""))) for candidate in candidates if candidate),
            default=0.0,
        )
        if score >= 50:
            ranked.append((score, record))
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    images: list[dict[str, str]] = []
    seen: set[str] = set()
    for _, record in ranked[:3]:
        for image in record.get("pictures") or []:
            url = image.get("image_url", "")
            if url and url not in seen:
                seen.add(url)
                images.append(image)
            if len(images) >= 4:
                return images
    return images


def _extract_image_urls_from_html(html: str, base_url: str) -> list[str]:
    """從官方 HTML、lazy-load、srcset、CSS 與內嵌 JSON 抽出圖片候選網址。"""
    normalized_html = unescape(html or "")
    normalized_html = (
        normalized_html
        .replace("\\/", "/")
        .replace("\\u002F", "/")
        .replace("\\u002f", "/")
        .replace("&amp;", "&")
    )
    raw_candidates: list[str] = []

    patterns = [
        r'<meta[^>]+property=["\'](?:og:image|twitter:image)["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\'](?:og:image|twitter:image)["\']',
        r'<img[^>]+(?:data-src|data-original|data-lazy-src|data-url|data-image|src)=["\']([^"\']+)',
        r'<(?:source|img)[^>]+(?:data-srcset|srcset)=["\']([^"\']+)',
        r'(?:background-image|background)\s*:\s*url\(["\']?([^\)"\']+)',
        r'url\(["\']?([^\)"\']+\.(?:jpe?g|png|webp|gif|avif)(?:\?[^\)"\']*)?)',
        r'["\'](?:image|imageUrl|image_url|photo|photoUrl|photo_url|src|url)["\']\s*:\s*["\']([^"\']+)',
        r'https?://[^\s"\'<>]+\.(?:jpe?g|png|webp|gif|avif)(?:\?[^\s"\'<>]*)?',
        r'(?<![A-Za-z0-9])(/[^\s"\'<>]+\.(?:jpe?g|png|webp|gif|avif)(?:\?[^\s"\'<>]*)?)',
        r'https?://[^\s"\'<>]+/(?:image|images|photo|photos|upload|uploads|media|file|files)/[^\s"\'<>]+',
        r'(?<![A-Za-z0-9])(/(?:image|images|photo|photos|upload|uploads|media|file|files)/[^\s"\'<>]+)',
    ]
    for pattern in patterns:
        for match in re.findall(pattern, normalized_html, flags=re.I):
            if isinstance(match, tuple):
                raw_candidates.extend([str(v) for v in match if v])
            else:
                raw_candidates.append(str(match))

    urls: list[str] = []
    seen: set[str] = set()
    for raw in raw_candidates:
        for candidate in str(raw).split(","):
            candidate = candidate.strip().split()[0].strip('"\'')
            if not candidate or candidate.startswith(("data:", "javascript:", "#")):
                continue
            url = urljoin(base_url, candidate)
            if not _looks_like_image_url(url):
                continue
            if url not in seen:
                seen.add(url)
                urls.append(url)
    return urls[:40]


async def _verify_official_image_candidates(
    candidates: list[str],
    source_page_url: str,
    limit: int = 4,
) -> list[str]:
    """逐一驗證候選 URL 是否真的回傳圖片，避免把 HTML / icon 誤當照片。"""
    if not candidates:
        return []

    verified: list[str] = []
    timeout = httpx.Timeout(10.0, connect=5.0)
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; Daxi-AI-Guide/10.0; +https://travel.tycg.gov.tw/)",
        "Referer": source_page_url,
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    }

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
        for url in candidates[:30]:
            try:
                # GET 比 HEAD 更可靠，部分站台會拒絕 HEAD。只下載前 96KB 即足以確認 MIME。
                async with client.stream("GET", url) as response:
                    if response.status_code >= 400:
                        continue
                    content_type = (response.headers.get("content-type") or "").lower()
                    if not content_type.startswith("image/"):
                        continue
                    # 排除極小的裝飾圖；Content-Length 無值時仍先接受。
                    length = response.headers.get("content-length")
                    if length:
                        try:
                            if int(length) < 8000:
                                continue
                        except ValueError:
                            pass
                verified.append(str(response.url))
                if len(verified) >= limit:
                    break
            except Exception:
                continue

    return verified

def _extract_album_links_from_html(html: str, base_url: str) -> list[str]:
    normalized_html = unescape(html or "").replace("\\/", "/")
    links: list[str] = []
    seen: set[str] = set()
    patterns = [
        r'href=["\']([^"\']*/(?:zh-tw/)?multimedia/album/\d+[^"\']*)["\']',
        r'(?<![A-Za-z0-9])(/zh-tw/multimedia/album/\d+)',
        r'(?<![A-Za-z0-9])(/multimedia/album/\d+)',
    ]
    for pattern in patterns:
        for raw in re.findall(pattern, normalized_html, flags=re.I):
            url = urljoin(base_url, raw)
            if url not in seen:
                seen.add(url)
                links.append(url)
    return links[:3]


async def scrape_official_page_images(record: dict[str, Any] | None) -> list[dict[str, str]]:
    global _last_image_error
    """從桃園觀光景點頁、官方相簿頁與大龍門子站抓取並驗證照片。"""
    if not record:
        return []
    source_url = str(record.get("source_url") or "").strip()
    if not source_url:
        return []
    if source_url in _official_page_image_cache:
        return _official_page_image_cache[source_url]

    timeout = httpx.Timeout(14.0, connect=6.0)
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; Daxi-AI-Guide/10.0; +https://travel.tycg.gov.tw/)",
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.5",
        "Accept": "text/html,application/xhtml+xml",
    }

    record_name = str(record.get("name") or "").strip()
    page_urls: list[str] = [source_url]

    # 先加入已知官方相簿頁。
    for key, known_album_url in OFFICIAL_ALBUM_PAGE_MAP.items():
        if normalize_text(key) in normalize_text(record_name) or normalize_text(record_name) in normalize_text(key):
            if known_album_url not in page_urls:
                page_urls.append(known_album_url)

    # 再加入大龍門官方子站；福仁宮頁在搜尋索引中明確包含「照片／環景」。
    for key, dalongmen_url in OFFICIAL_DALONGMEN_PAGE_MAP.items():
        if normalize_text(key) in normalize_text(record_name) or normalize_text(record_name) in normalize_text(key):
            if dalongmen_url not in page_urls:
                page_urls.append(dalongmen_url)

    fetched_pages: list[tuple[str, str]] = []
    errors: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
            # 先讀既知頁面；每頁再嘗試找更多官方相簿連結。
            queue = list(page_urls)
            seen_pages: set[str] = set()
            while queue and len(seen_pages) < 8:
                page_url = queue.pop(0)
                if page_url in seen_pages:
                    continue
                seen_pages.add(page_url)
                try:
                    response = await client.get(page_url)
                    response.raise_for_status()
                    html = response.text
                    fetched_pages.append((str(response.url), html))
                    for album_url in _extract_album_links_from_html(html, str(response.url)):
                        if album_url not in seen_pages and album_url not in queue:
                            queue.append(album_url)
                except Exception as exc:
                    errors.append(f"{page_url} -> {type(exc).__name__}: {sanitize_error(exc)}")
    except Exception as exc:
        errors.append(f"client -> {type(exc).__name__}: {sanitize_error(exc)}")

    name = record_name or "景點"
    images: list[dict[str, str]] = []
    seen_images: set[str] = set()

    for page_url, page_html in fetched_pages:
        candidates = _extract_image_urls_from_html(page_html, page_url)
        verified_urls = await _verify_official_image_candidates(candidates, page_url, limit=4)
        for image_url in verified_urls:
            if image_url in seen_images:
                continue
            seen_images.add(image_url)
            images.append({
                "image_url": image_url,
                "thumbnail_url": image_url,
                "source_url": page_url,
                "caption": f"{name}｜桃園觀光導覽網官方照片",
            })
            if len(images) >= 4:
                _official_page_image_cache[source_url] = images
                _last_image_error = ""
                return images

    _official_page_image_cache[source_url] = images
    if images:
        _last_image_error = ""
    else:
        detail = "；".join(errors[-3:]) if errors else "官方頁面可讀取，但沒有解析到可驗證的 image/* 圖片"
        _last_image_error = detail
    return images


async def get_official_images(
    query: str,
    record: dict[str, Any] | None,
    focus_entities: list[str] | None = None,
) -> list[dict[str, str]]:
    """依可靠度合併：景點資料內圖片 → 官方相簿 → 官方景點頁。"""
    # 先讀景點資料本身，再直接抓官方景點頁／已知官方相簿頁。
    # 桃園「觀光相簿」Open Data 端點在部分環境會回空，因此把它降為最後備援，
    # 避免相簿 API 失效時阻斷照片顯示。
    page_images = await scrape_official_page_images(record)
    album_images = await find_album_images(query, focus_entities) if len(page_images) < 2 else []
    sources = [
        *official_images_from_record(record),
        *page_images,
        *album_images,
    ]
    combined: list[dict[str, str]] = []
    seen: set[str] = set()
    for image in sources:
        url = str(image.get("image_url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        combined.append(image)
        if len(combined) >= 4:
            break
    return _register_trusted_images(combined)


def wants_detail(question: str) -> bool:
    q = normalize_text(question)
    return any(normalize_text(marker) in q for marker in DETAIL_MARKERS)


def wants_images(question: str) -> bool:
    q = normalize_text(question)
    return any(normalize_text(marker) in q for marker in IMAGE_MARKERS)


def wants_nearby(question: str) -> bool:
    q = normalize_text(question)
    return any(normalize_text(marker) in q for marker in NEARBY_MARKERS)


def explicit_web_request(question: str) -> bool:
    q = normalize_text(question)
    explicit = ("網路", "上網", "查網路", "官網", "官方", "最新", "現在", "目前", "今天", "近期")
    return any(normalize_text(marker) in q for marker in explicit) or wants_detail(question) or wants_images(question)


def should_use_web(question: str, hits: list[dict[str, Any]], resolved_question: str) -> bool:
    if not WEB_SEARCH_ENABLED:
        return False
    q = normalize_text(question)
    if any(normalize_text(marker) in q for marker in WEB_MARKERS):
        return True
    if is_route_request(resolved_question):
        return True
    if not hits:
        return True
    # 低信心時讓官方網路來源補強。
    return hits[0]["score"] < 0.22


def has_direct_kb_topic(question: str, hits: list[dict[str, Any]]) -> bool:
    """判斷問題是否直接命中 data.md 的章節主題，而不是只在正文偶然出現。"""
    q = normalize_text(re.sub(r"[|｜].*$", "", question))
    if not q:
        return False
    for hit in hits:
        title = normalize_text(str(hit.get("title") or ""))
        if title and (title == q or title in q or (q in title and len(q) >= 3)):
            return True
    return False


def should_discover_external(question: str, hits: list[dict[str, Any]], focus_entities: list[str] | None = None) -> bool:
    """data.md 沒有獨立主題時，允許豆干弟往官方資料／公開網路擴充。

    這解決「AI 前面推薦了月光餅，但 data.md 沒有月光餅專章，所以追問時搜尋不到」的問題。
    """
    if not WEB_SEARCH_ENABLED:
        return False
    if not hits:
        return True
    if focus_entities and all(not extract_known_titles(entity) for entity in focus_entities):
        return True
    if not has_direct_kb_topic(question, hits):
        # 短名詞、店家名、食品名最需要外部實體搜尋；較長的一般問題則交由既有 RAG。
        clean = normalize_text(re.sub(r"[|｜].*$", "", question))
        if 2 <= len(clean) <= 28:
            return True
    return False


def web_tool_config(include_images: bool = False, detailed: bool = False) -> dict[str, Any]:
    tool: dict[str, Any] = {
        "type": "web_search",
        "search_context_size": "medium" if detailed else "low",
        "filters": {"allowed_domains": OFFICIAL_WEB_DOMAINS},
        "user_location": {
            "type": "approximate",
            "country": "TW",
            "city": "Taoyuan",
            "region": "Taoyuan",
        },
    }
    if include_images:
        tool["search_content_types"] = ["image", "text"]
        tool["image_settings"] = {"max_results": 4, "caption": True}
    return tool


def extract_web_sources(response: Any) -> list[dict[str, str]]:
    """從 Responses API 的 web_search_call sources / url_citation 取出可點擊來源。"""
    try:
        data = response.model_dump()
    except Exception:
        return []

    found: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(url: str | None, title: str | None = None) -> None:
        if not url or url in seen:
            return
        seen.add(url)
        host = urlparse(url).netloc.replace("www.", "")
        found.append({
            "type": "web",
            "title": (title or host or "官方網站").strip(),
            "url": url,
            "domain": host,
        })

    for item in data.get("output", []) or []:
        if item.get("type") == "web_search_call":
            action = item.get("action") or {}
            for source in action.get("sources", []) or []:
                if isinstance(source, dict):
                    add(source.get("url"), source.get("title"))

        if item.get("type") == "message":
            for content in item.get("content", []) or []:
                for annotation in content.get("annotations", []) or []:
                    if annotation.get("type") == "url_citation":
                        citation = annotation.get("url_citation") or annotation
                        add(citation.get("url"), citation.get("title"))

    return found[:8]


def is_official_source_url(url: str | None) -> bool:
    if not url:
        return False
    try:
        host = urlparse(url).netloc.lower().split(":")[0]
    except Exception:
        return False
    return any(host == domain or host.endswith("." + domain) for domain in OFFICIAL_WEB_DOMAINS)


def extract_web_images(response: Any) -> list[dict[str, str]]:
    """擷取 OpenAI web_search 的 image_result，只保留官方來源頁面的圖片。"""
    try:
        data = response.model_dump()
    except Exception:
        return []

    images: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in data.get("output", []) or []:
        if item.get("type") != "web_search_call":
            continue
        for result in item.get("results", []) or []:
            if not isinstance(result, dict) or result.get("type") != "image_result":
                continue
            image_url = result.get("image_url")
            thumbnail_url = result.get("thumbnail_url")
            source_url = result.get("source_website_url")
            if not image_url or image_url in seen or not is_official_source_url(source_url):
                continue
            seen.add(image_url)
            images.append({
                "image_url": image_url,
                "thumbnail_url": thumbnail_url or image_url,
                "source_url": source_url or "",
                "caption": (result.get("caption") or "官方來源景點照片").strip(),
            })
            if len(images) >= 4:
                return images
    return images


async def openai_rag_answer(
    question: str,
    resolved_question: str,
    hits: list[dict[str, Any]],
    history: list[HistoryTurn],
    use_web: bool,
    official_record: dict[str, Any] | None = None,
    nearby_records: list[dict[str, Any]] | None = None,
    route_records: list[dict[str, Any]] | None = None,
    public_results: list[dict[str, str]] | None = None,
) -> tuple[str, list[dict[str, str]], list[dict[str, str]]]:
    global _openai_quota_blocked_until
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not HAS_OPENAI or not api_key:
        raise RuntimeError("OpenAI SDK 或 OPENAI_API_KEY 未設定")
    if time.time() < _openai_quota_blocked_until:
        raise RuntimeError("OpenAI API 目前為 insufficient_quota，暫時停用模型呼叫並使用本地／官方資料模式")

    client = AsyncOpenAI(api_key=api_key)
    context = build_context(hits) if hits else "（data.md 本輪沒有足夠的高相關片段）"
    history_context = build_history_context(history)
    official_context = build_official_context(official_record)
    nearby_records = nearby_records or []
    route_records = route_records or []
    supplemental_official_context = build_official_records_context(nearby_records or route_records)
    public_results = public_results or []
    public_context = build_public_search_context(public_results)
    detailed = wants_detail(question)
    include_images = wants_images(question)

    extra_requirements: list[str] = []
    if detailed:
        extra_requirements.append(
            "使用者要求詳細介紹：請緊扣同一主題，若官方搜尋有資料，補足歷史沿革、文化／信仰、建築或特色看點與實用資訊；"
            "約 300～550 個中文字，不要只把 data.md 原句再說一次。"
        )
    if include_images:
        extra_requirements.append(
            "使用者要求照片：請以 1～3 句簡短說明即可，介面會另外顯示 image search 結果；不要重複上一輪整段介紹。"
        )
    if wants_nearby(question) and nearby_records:
        extra_requirements.append(
            "使用者問『附近還有什麼』：請直接使用提供的附近官方景點清單回答，列出 3～5 個，保持在同一個原始景點周邊，不要另猜其他地區。"
        )
    if is_route_request(question) and route_records:
        extra_requirements.append(
            "使用者要安排路線：只能以『本輪路線景點資料』為主要站點，按照順遊邏輯安排，不要無故加入新的景點。"
        )

    user_input = (
        f"使用者原始問題：\n{question}\n\n"
        f"已解析問題（用來解決『它、第二個、剛剛推薦的』等指涉）：\n{resolved_question}\n\n"
        f"最近對話：\n{history_context}\n\n"
        f"桃園觀光官方 Open Data（目前主題）：\n{official_context}\n\n"
        f"附近／路線用的官方景點資料（若有）：\n{supplemental_official_context}\n\n"
        f"額外公開網路搜尋結果（data.md 沒有獨立主題時才用；官方來源優先）：\n{public_context}\n\n"
        "本輪 data.md 高相關片段（只使用真正與問題有關的片段；不要因片段順帶提到其他景點就展開）：\n\n"
        f"{context}\n\n"
        "回答時先把『已解析問題』完整答好。若本次有 web_search，網路只用來補充同一主題或核對會變動資訊，"
        "不要因搜尋結果出現附近景點就岔題。\n"
        + ("\n".join(extra_requirements) if extra_requirements else "")
    )

    kwargs: dict[str, Any] = {
        "model": OPENAI_MODEL,
        "reasoning": {"effort": "low"},
        "instructions": SYSTEM_INSTRUCTIONS,
        "input": user_input,
        "max_output_tokens": 1200 if detailed else 850,
    }

    if use_web:
        kwargs["tools"] = [web_tool_config(include_images=include_images, detailed=detailed)]
        # 明確要求詳細、照片或官方／最新資料時，強制真正執行 web_search，避免模型只靠既有片段回答。
        kwargs["tool_choice"] = "required" if explicit_web_request(question) else "auto"
        include_fields = ["web_search_call.action.sources"]
        if include_images:
            include_fields.append("web_search_call.results")
        kwargs["include"] = include_fields

    global _last_openai_model_used
    model_candidates = [OPENAI_MODEL]
    if OPENAI_FALLBACK_MODEL and OPENAI_FALLBACK_MODEL not in model_candidates:
        model_candidates.append(OPENAI_FALLBACK_MODEL)

    response = None
    model_errors: list[str] = []
    for candidate_model in model_candidates:
        try:
            kwargs["model"] = candidate_model
            response = await client.responses.create(**kwargs)
            _last_openai_model_used = candidate_model
            break
        except Exception as exc:
            model_errors.append(f"{candidate_model}: {type(exc).__name__}: {sanitize_error(exc)}")
            if is_quota_error(exc):
                # 配額不足和模型名稱無關；再試 fallback 模型只會再吃一次失敗請求。
                _openai_quota_blocked_until = time.time() + 300
                break

    if response is None:
        raise RuntimeError(" | ".join(model_errors) or "OpenAI 所有模型候選都失敗")

    answer = (response.output_text or "").strip()
    if not answer:
        raise RuntimeError("OpenAI 回傳空白內容")

    web_sources = extract_web_sources(response) if use_web else []
    web_images = extract_web_images(response) if use_web and include_images else []
    if include_images:
        combined: list[dict[str, str]] = []
        seen_images: set[str] = set()
        for image in [*official_images_from_record(official_record), *web_images]:
            url = image.get("image_url", "")
            if url and url not in seen_images:
                seen_images.add(url)
                combined.append(image)
            if len(combined) >= 4:
                break
        web_images = combined
    return answer, web_sources, web_images


def rate_limit_or_raise(request: Request) -> None:
    forwarded = request.headers.get("x-forwarded-for", "")
    ip = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "unknown")
    now = time.time()
    bucket = _request_times[ip]
    cutoff = now - CHAT_RATE_WINDOW_SECONDS
    while bucket and bucket[0] < cutoff:
        bucket.popleft()
    if len(bucket) >= CHAT_RATE_LIMIT:
        raise HTTPException(status_code=429, detail="提問太頻繁了，請稍等一下再問豆干弟。")
    bucket.append(now)


@asynccontextmanager
async def lifespan(_: FastAPI):
    build_search_index()
    yield


app = FastAPI(title="光影大溪 AI 導覽", version="10.0.0", lifespan=lifespan)

static_path = os.path.join(APP_DIR, "static")
if os.path.isdir(static_path):
    app.mount("/static", StaticFiles(directory=static_path), name="static")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    if os.path.exists(INDEX_HTML):
        with open(INDEX_HTML, "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    return HTMLResponse("<h3>伺服器運作中，但找不到 index.html</h3>", status_code=404)


@app.get("/health")
def health() -> dict[str, Any]:
    maybe_reload_kb()
    return {
        "status": "ok",
        "knowledge_chunks": len(kb_data),
        "openai_enabled": bool(HAS_OPENAI and os.getenv("OPENAI_API_KEY", "").strip()),
        "web_search_enabled": WEB_SEARCH_ENABLED,
        "official_web_domains": OFFICIAL_WEB_DOMAINS,
        "model": OPENAI_MODEL if os.getenv("OPENAI_API_KEY", "").strip() else None,
        "fallback_model": OPENAI_FALLBACK_MODEL if os.getenv("OPENAI_API_KEY", "").strip() else None,
    }


@app.get("/init_topics")
def get_init_topics() -> dict[str, list[str]]:
    maybe_reload_kb()
    return {"topics": [item["title"] for item in kb_data]}


@app.get("/image-proxy")
async def image_proxy(url: str = Query(min_length=8, max_length=3000)) -> Response:
    """代理本輪已驗證的官方圖片，避免來源網站防盜連 / referrer 政策造成前端不顯示。"""
    if url not in _trusted_image_urls:
        raise HTTPException(status_code=403, detail="圖片網址尚未通過本輪官方來源驗證")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(status_code=400, detail="不支援的圖片網址")
    try:
        timeout = httpx.Timeout(15.0, connect=6.0)
        headers = {
            "User-Agent": "Mozilla/5.0 Daxi-AI-Guide/10.0",
            "Referer": "https://travel.tycg.gov.tw/",
        }
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
            remote = await client.get(url)
            remote.raise_for_status()
        content_type = remote.headers.get("content-type", "").split(";")[0].strip().lower()
        if not content_type.startswith("image/"):
            raise HTTPException(status_code=415, detail="來源不是圖片")
        if len(remote.content) > 10 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="圖片檔案過大")
        return Response(
            content=remote.content,
            media_type=content_type,
            headers={"Cache-Control": "public, max-age=3600"},
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"官方圖片載入失敗：{exc}") from exc


@app.get("/diagnostics")
def diagnostics() -> dict[str, Any]:
    """公開安全診斷資訊，不回傳 API Key。

    若線上畫面一直顯示「本地 RAG」，這個端點可以直接看出 OpenAI、官方 Open Data
    或圖片抓取最近一次在哪一層失敗，避免所有例外只留在 Render Logs。
    """
    return {
        "app_version": "10.0.0",
        "openai_configured": bool(HAS_OPENAI and os.getenv("OPENAI_API_KEY", "").strip()),
        "model": OPENAI_MODEL,
        "fallback_model": OPENAI_FALLBACK_MODEL or None,
        "last_model_used": _last_openai_model_used or None,
        "web_search_enabled": WEB_SEARCH_ENABLED,
        "last_openai_error": _last_openai_error or None,
        "last_official_error": _last_official_error or None,
        "last_image_error": _last_image_error or None,
        "official_attractions_cached": len(_official_attractions_cache),
        "official_consumes_cached": len(_official_consume_cache),
        "official_albums_cached": len(_official_album_cache),
        "public_search_cache_entries": len(_public_search_cache),
        "trusted_images_cached": len(_trusted_image_urls),
        "openai_quota_blocked": time.time() < _openai_quota_blocked_until,
        "server_conversations_cached": len(_conversation_states),
        "note": (
            "OpenAI API 配額不足；AI/Web Search 會暫停，網站改用 data.md + 桃園官方資料。"
            if "quota" in (_last_openai_error or "").lower()
            else None
        ),
    }


@app.get("/diagnostics/search")
async def diagnostics_search(name: str = Query(min_length=1, max_length=120)) -> dict[str, Any]:
    """測試 data.md 以外名詞的官方／公開網路搜尋。"""
    hits = retrieve(name)
    record = await find_official_entity(name, [name])
    public_results = [] if record else await public_web_search(name, limit=5)
    return {
        "app_version": "10.0.0",
        "query": name,
        "direct_kb_topic": has_direct_kb_topic(name, hits),
        "kb_titles": [hit.get("title") for hit in hits],
        "official_entity": {
            "name": record.get("name"),
            "entity_type": record.get("entity_type") or "attraction",
            "source_url": record.get("source_url"),
        } if record else None,
        "public_results": public_results,
    }


@app.get("/diagnostics/images")
async def diagnostics_images(name: str = Query(min_length=1, max_length=120)) -> dict[str, Any]:
    """安全測試官方照片抓取，不包含任何 API Key。

    例如 /diagnostics/images?name=福仁宮，可直接確認 Render 是否能從
    桃園官方景點頁／相簿頁抓到並驗證 image/*。
    """
    record = await find_official_entity(name, [name])
    images = await get_official_images(name, record, [name]) if record else []
    registered = _register_trusted_images(images)
    matched_gallery = None
    for key, gallery_url in OFFICIAL_ALBUM_PAGE_MAP.items():
        if normalize_text(key) in normalize_text(name) or normalize_text(name) in normalize_text(key):
            matched_gallery = gallery_url
            break
    return {
        "app_version": "10.0.0",
        "query": name,
        "official_record": {
            "name": record.get("name"),
            "source_url": record.get("source_url"),
            "info_id": record.get("info_id"),
        } if record else None,
        "official_gallery_url": matched_gallery,
        "image_count": len(registered),
        "images": registered,
        "last_image_error": _last_image_error or None,
    }


@app.post("/chat")
async def chat(payload: ChatRequest, request: Request) -> dict[str, Any]:
    global _last_openai_error

    rate_limit_or_raise(request)
    question = payload.question.strip()
    history = payload.history[-MAX_HISTORY_TURNS:]

    # V8：除了瀏覽器 localStorage，再由後端依 conversation_id 保存目前主題與推薦。
    # 即使前端因重新整理／舊快取漏傳 active_topics，「照片、再詳細一點、那附近呢」仍可接續。
    server_state = get_server_conversation_state(payload.conversation_id)
    effective_active_topics = [topic for topic in payload.active_topics if topic]
    if not effective_active_topics:
        effective_active_topics = [str(v) for v in server_state.get("active_topics", []) if v]
    effective_recommendations = [rec for rec in payload.last_recommendations if rec]
    if not effective_recommendations:
        effective_recommendations = [str(v) for v in server_state.get("recommendations", []) if v]

    resolved_question, focus_entities = resolve_question(
        question,
        history,
        effective_recommendations,
        effective_active_topics,
    )
    hits = retrieve(resolved_question, focus_entities=focus_entities)
    use_web = should_use_web(question, hits, resolved_question)
    discover_external = should_discover_external(resolved_question, hits, focus_entities)

    # V10：官方實體不再只有「景點」。桃園觀光的美食／消費 Open Data 也納入，
    # 所以「月光餅、某家豆花、某店家」即使 data.md 沒有獨立章節，也可以直接被搜尋與延續。
    official_record: dict[str, Any] | None = None
    if use_web or discover_external or wants_detail(question) or wants_images(question) or wants_nearby(question) or is_route_request(question):
        official_record = await find_official_entity(resolved_question, focus_entities)

    # OpenAI API 沒額度時仍要能搜尋 data.md 外的名詞：
    # 官方 Open Data 找不到才使用公開搜尋，且結果排序仍以官方網域優先。
    public_results: list[dict[str, str]] = []
    if WEB_SEARCH_ENABLED and (discover_external or not hits) and (official_record is None or wants_detail(question)):
        public_results = await public_web_search(resolved_question, limit=5)

    nearby_records: list[dict[str, Any]] = []
    if wants_nearby(question) and official_record:
        nearby_records = await find_nearby_attractions(official_record, limit=5)

    route_records: list[dict[str, Any]] = []
    if is_route_request(question):
        route_entities = focus_entities or recent_recommendation_entities(history, effective_recommendations)
        if route_entities:
            route_records = order_records_by_nearest(await find_official_records_for_entities(route_entities))

    base_images: list[dict[str, str]] = []
    if wants_images(question):
        base_images = await get_official_images(resolved_question, official_record, focus_entities)

    # 推薦結果不是固定從 data.md 隨機補：問附近時直接把「官方座標算出的附近景點」回存成下一輪記憶。
    if nearby_records:
        recommendations = [str(record.get("name") or "").strip() for record in nearby_records if record.get("name")][:5]
    elif route_records:
        recommendations = [str(record.get("name") or "").strip() for record in route_records if record.get("name")][:5]
    elif hits:
        recommendations = choose_recommendations(hits, resolved_question)
    else:
        recommendations = [item["title"] for item in kb_data[:3]]

    data_sources = [
        {
            "type": "data",
            "title": hit["title"],
            "category": hit["category"],
        }
        for hit in hits
    ]
    official_source = official_source_from_record(official_record)
    gallery_source = None
    if wants_images(question):
        gallery_name = str((official_record or {}).get("name") or (focus_entities[0] if focus_entities else resolved_question))
        gallery_source = official_album_source_for_name(gallery_name)
    images: list[dict[str, str]] = list(base_images)
    openai_fallback = False

    try:
        answer, web_sources, web_images = await openai_rag_answer(
            question=question,
            resolved_question=resolved_question,
            hits=hits,
            history=history,
            use_web=use_web,
            official_record=official_record,
            nearby_records=nearby_records,
            route_records=route_records,
            public_results=public_results,
        )
        _last_openai_error = ""
        merged_images: list[dict[str, str]] = []
        seen_image_urls: set[str] = set()
        for image in [*base_images, *web_images]:
            url = str(image.get("image_url") or "").strip()
            if not url or url in seen_image_urls:
                continue
            seen_image_urls.add(url)
            merged_images.append(image)
            if len(merged_images) >= 4:
                break
        images = _register_trusted_images(merged_images)
        mode = "openai-web-rag" if use_web and (web_sources or images or official_source) else "openai-rag"
        sources: list[dict[str, Any]] = [*data_sources]
        if official_source:
            sources.append(official_source)
        if gallery_source and gallery_source.get("url") != (official_source or {}).get("url"):
            sources.append(gallery_source)
        seen_source_urls = {source.get("url") for source in sources if isinstance(source, dict) and source.get("url")}
        for source in web_sources:
            if source.get("url") not in seen_source_urls:
                sources.append(source)
                seen_source_urls.add(source.get("url"))
        for source in public_results:
            if source.get("url") and source.get("url") not in seen_source_urls:
                sources.append({
                    "type": "web",
                    "title": source.get("title") or source.get("domain") or "公開網路來源",
                    "url": source.get("url", ""),
                    "domain": source.get("domain", ""),
                })
                seen_source_urls.add(source.get("url"))
        print(
            f"✅ 回答完成｜原問：{question}｜解析：{resolved_question}｜"
            f"RAG：{', '.join(hit['title'] for hit in hits) or 'none'}｜web={bool(web_sources)}｜images={len(images)}"
        )
    except Exception as exc:
        _last_openai_error = f"{type(exc).__name__}: {sanitize_error(exc)}"
        openai_fallback = True
        print(f"⚠️ OpenAI/Web 回答失敗：{_last_openai_error}")

        # 網路工具失敗時先嘗試純 OpenAI；附近/路線/照片的官方資料則無論如何保留。
        if use_web and hits:
            try:
                answer, _, _ = await openai_rag_answer(
                    question=question,
                    resolved_question=resolved_question,
                    hits=hits,
                    history=history,
                    use_web=False,
                    official_record=official_record,
                    nearby_records=nearby_records,
                    route_records=route_records,
                    public_results=public_results,
                )
                mode = "openai-rag"
                sources = [*data_sources, *([official_source] if official_source else []), *([gallery_source] if gallery_source else [])]
                images = _register_trusted_images(list(base_images))
            except Exception as second_exc:
                _last_openai_error = f"{type(second_exc).__name__}: {sanitize_error(second_exc)}"
                print(f"⚠️ 純 OpenAI 也不可用，改採 deterministic fallback：{_last_openai_error}")
                answer = local_rag_answer(
                    question,
                    hits,
                    official_record,
                    base_images,
                    nearby_records=nearby_records,
                    route_records=route_records,
                    public_results=public_results,
                )
                sources = [*data_sources, *([official_source] if official_source else []), *([gallery_source] if gallery_source else [])]
                sources.extend({
                    "type": "web",
                    "title": item.get("title") or item.get("domain") or "公開網路來源",
                    "url": item.get("url", ""),
                    "domain": item.get("domain", ""),
                } for item in public_results if item.get("url"))
                images = _register_trusted_images(list(base_images))
                mode = "local-web" if (public_results or official_record) else "local-rag"
        else:
            answer = local_rag_answer(
                question,
                hits,
                official_record,
                base_images,
                nearby_records=nearby_records,
                route_records=route_records,
                public_results=public_results,
            )
            sources = [*data_sources, *([official_source] if official_source else []), *([gallery_source] if gallery_source else [])]
            sources.extend({
                "type": "web",
                "title": item.get("title") or item.get("domain") or "公開網路來源",
                "url": item.get("url", ""),
                "domain": item.get("domain", ""),
            } for item in public_results if item.get("url"))
            images = _register_trusted_images(list(base_images))
            mode = "local-web" if (public_results or official_record) else "local-rag"

    # active_topics 只代表「目前正在聊的核心主題」。
    # 問附近後仍保留原景點；推薦清單另存在 recommendations，使用者才能下一句說「第二個」。
    if focus_entities:
        active_topics = list(dict.fromkeys(focus_entities))[:5]
    elif official_record and official_record.get("name"):
        active_topics = [str(official_record["name"])]
    elif public_results:
        active_topics = [re.sub(r"[|｜].*$", "", question).strip()]
    elif hits:
        active_topics = [hits[0]["title"]]
    else:
        active_topics = [topic for topic in effective_active_topics if topic][:5]

    save_server_conversation_state(
        payload.conversation_id,
        active_topics=active_topics,
        recommendations=recommendations,
        last_question=question,
        last_answer=answer,
    )

    return {
        "answer": answer,
        "sources": sources,
        "recommendations": recommendations,
        "mode": mode,
        "web_used": any(source.get("type") == "web" for source in sources),
        "images": images,
        "resolved_question": resolved_question,
        "active_topics": active_topics,
        "storymap_url": STORYMAP_URL,
        "debug": {
            "app_version": "10.0.0",
            "openai_fallback": openai_fallback,
            "image_count": len(images),
            "nearby_count": len(nearby_records),
            "route_count": len(route_records),
            "public_search_count": len(public_results),
            "official_entity_type": (official_record or {}).get("entity_type") or ("attraction" if official_record else None),
        },
    }


if __name__ == "__main__":
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("app:app", host=host, port=port, reload=True)
