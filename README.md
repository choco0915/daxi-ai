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
