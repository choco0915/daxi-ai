# 光影大溪－豆干弟 AI 導覽 V8

這是一套以 `data.md` 為核心知識庫、桃園觀光官方資料為補充來源，並可選擇使用 OpenAI Responses API / Web Search 的大溪智慧導覽網站。

## V8 重點修正

- **後端對話狀態**：每個聊天視窗會把 `conversation_id` 傳給 FastAPI；後端同步保存目前主題與上一輪推薦，因此「照片」「再詳細一點」「那附近呢」「第二個」不再只依賴瀏覽器猜上下文。
- **OpenAI quota fallback**：偵測 `insufficient_quota` 後會暫停重複模型呼叫 5 分鐘，直接使用 `data.md + 桃園官方 Open Data/景點頁`，不會對 `gpt-5.6` 與 fallback model 重複送出必定失敗的要求。
- **照片路徑調整**：官方景點資料 → 官方景點頁／官方相簿頁 → 桃園相簿 Open Data（備援）。相簿 Open Data 回空時不再阻斷景點頁抓圖。
- **診斷資訊**：`/diagnostics` 顯示 quota 狀態、後端保存中的對話數、官方資料與照片抓取狀態，不會顯示 API Key。

## 目前最重要的 OpenAI 設定

如果 `/diagnostics` 出現：

```text
insufficient_quota
You exceeded your current quota
```

代表 **API Key 本身有讀到，但 API 帳戶目前沒有可用 API 額度／billing quota**。這不是 Render、RAG 或模型名稱造成的。

請到 OpenAI API Platform 的 Billing 設定 API 帳戶的付費方式或加入 credits。ChatGPT Plus 與 OpenAI API 的 billing 是分開的；有 ChatGPT Plus 並不會自動附帶 API 額度。

在補充 API 額度前，網站仍可使用：

- `data.md` RAG
- 桃園觀光官方景點 Open Data
- 官方景點座標附近推薦
- 官方頁面／相簿頁照片抓取
- 後端對話主題記憶

但 **OpenAI 自然語言生成與 OpenAI Web Search 不會執行**。

## Render

`render.yaml` 已設定：

```text
uvicorn app:app --host 0.0.0.0 --port $PORT
```

Environment Variables：

```text
OPENAI_API_KEY=你的 API Key
OPENAI_MODEL=gpt-5.6
OPENAI_FALLBACK_MODEL=gpt-5.6-luna
WEB_SEARCH_ENABLED=true
CHAT_RATE_LIMIT=30
CHAT_RATE_WINDOW_SECONDS=60
```

## 測試

```bash
python test_rag.py
```

診斷：

```text
https://你的網站.onrender.com/diagnostics
```

## V9：官方照片抓取強化

如果使用者輸入「照片」而官方頁面沒有直接輸出可用圖片網址，V9 會：

1. 先讀桃園觀光景點頁。
2. 加入已知官方相簿頁。
3. 對部分大溪景點加入官方「山水之間遇見大龍門」頁作為第二官方來源。
4. 從 `img src`、lazy-load、`srcset`、CSS `background-image`、內嵌 JSON、一般 JPG/PNG/WebP URL 等位置抽取候選圖片。
5. 實際用 HTTP `Content-Type: image/*` 驗證後才傳給前端。
6. 若仍無法直接顯示，回答來源列至少會保留「桃園觀光官方相簿」可點擊連結。

新增安全診斷：

```text
/diagnostics/images?name=福仁宮
```

會回傳官方景點匹配、官方相簿 URL、驗證成功的圖片數量與最近一次圖片錯誤，不包含任何 API Key。

## V10：data.md 外部名詞搜尋

V10 保留既有 RAG、照片、附近景點、行程與對話記憶，新增「外部實體搜尋」。

搜尋順序：

1. `data.md` 直接主題命中。
2. 桃園觀光官方「景點 Open Data」。
3. 桃園觀光官方「消費／美食 Open Data」（店家、食品、伴手禮）。
4. 若官方 Open Data 仍找不到，使用公開網路搜尋；搜尋順序優先 `travel.tycg.gov.tw`、`tycg.gov.tw`、`taiwan.net.tw`，最後才補一般網路結果。
5. OpenAI API 有額度時，可再由 Responses API Web Search 補充；若 API 額度不足，前四層仍可獨立工作。

因此像「月光餅」即使沒有 `data.md` 的獨立章節，也可以命中桃園觀光的消費／美食官方資料；如果官方 Open Data 沒收錄其他新名詞，系統還會進一步搜尋公開網路，而不是直接拒答。

安全診斷：

```text
/diagnostics/search?name=月光餅
```

可以查看該名詞是否由 data.md、官方實體資料或公開網路結果命中，不會顯示 API Key。

## V11：data.md 外部名詞搜尋修正

V10 診斷若出現 `direct_kb_topic=false`、`official_entity=null`、`public_results=[]`，代表問題不是 RAG 沒看到關鍵詞，而是「官方消費資料端點沒有成功載入」且單一公開搜尋 provider 沒有回傳可解析結果。

V11 改成：

1. 桃園官方消費／美食資料不再只依賴舊版 `OpenData` URL，會同時嘗試新版 `/open-api`，並可解析 XML / JSON / CSV。
2. 若 Open Data 端點仍失效，會直接掃描桃園觀光官方「美食快搜」列表建立店家名稱索引，再讀取店家 Detail 頁。
3. 公開搜尋從單一 DuckDuckGo 改成「桃園觀光站內全文搜尋 → Bing HTML → DuckDuckGo HTML」多層備援，官方網域仍優先排序。
4. 如果外部搜尋全部暫時失效，而 data.md 只有在大章節內提到該詞，回答只顯示包含該詞的句子，不再把整個「伴手禮推薦／傳統甜品與小吃」章節塞回來。
5. `/diagnostics/search?name=...` 會額外顯示官方消費快取數、HTML 店家索引數，以及最近一次公開搜尋錯誤，方便定位 Render 網路層問題。

例如查詢 `月光餅`，預期會優先命中桃園觀光官方的「陳媽媽月光餅」；若官方資料源短暫不可用，才退回公開搜尋或 data.md 中直接包含「月光餅」的句子。
