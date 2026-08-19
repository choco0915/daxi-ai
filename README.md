# 光影大溪－豆干弟 AI 智慧導覽（正式作品展示版）

這是一套以 `data.md` 為主要知識來源的 FastAPI + OpenAI RAG 大溪智慧導覽網站，並針對公開展示加入豆干弟角色、動態光影背景、景點卡片、地圖導航、ArcGIS StoryMap 連結、回答來源標示、手機版介面與多輪對話記憶。

## 主要功能

- `data.md` Hybrid RAG：中文 2～4 字 n-gram TF-IDF、標題加權、口語查詢擴充。
- 豆干弟導覽角色：回答直接進入內容，不使用「我在 data.md 找到資料」等機械式前言。
- 多輪對話脈絡：前端會把最近數輪對話帶回後端，讓「那它呢？」「再幫我排一下」等追問更自然。
- 回答來源標示：顯示本次命中的 `data.md` 分類與章節。
- ArcGIS StoryMap：整合 `數位風華的光影刻痕`，並嘗試從 StoryMap 公開 item data 自動辨識「豆干弟」圖片作為頭像；若無法解析則使用本地備援頭像。
- 動態光影背景：保留原始 blob 光影概念，增加紫、粉、藍、青、橙、黃、綠等色彩層次。
- 景點卡片、Google Maps 導航與推薦行程卡片。
- 響應式手機版 UI。
- 公開網站基本保護：GZip、安全標頭、每 IP 聊天頻率限制。

## 本地執行

### Windows Git Bash

```bash
python -m venv .venv
source .venv/Scripts/activate
python -m pip install -r requirements.txt
cp .env.example .env
uvicorn app:app --reload --host 127.0.0.1 --port 8000
```

瀏覽器開啟：

```text
http://127.0.0.1:8000/
```

## OpenAI 環境變數

`.env`：

```env
OPENAI_API_KEY=你的新_API_Key
OPENAI_MODEL=gpt-5.6-luna
CHAT_RATE_LIMIT=30
CHAT_RATE_WINDOW_SECONDS=60
```

不要把 `.env` 或真正的 API Key 上傳 GitHub。

## Render 公開部署

專案根目錄已包含 `render.yaml`，GitHub 更新後 Render 可自動重新部署。

主要設定：

```text
Build Command: pip install -r requirements.txt
Start Command: uvicorn app:app --host 0.0.0.0 --port $PORT
Health Check: /health
```

Render 的 Environment 中需要設定：

```text
OPENAI_API_KEY
OPENAI_MODEL
CHAT_RATE_LIMIT
CHAT_RATE_WINDOW_SECONDS
```

## 豆干弟 StoryMap 頭像

前端會嘗試讀取：

```text
https://www.arcgis.com/sharing/rest/content/items/b704c98b362041c1be364ad2c8ca3d27/data?f=json
```

並在公開 StoryMap 的圖片節點/資源中尋找含「豆干弟」相關標示的圖片。成功時網站上的主角頭像與 AI 對話頭像會自動換成 StoryMap 圖片。

若 StoryMap 後續更換圖片 metadata、資源結構或限制跨網域讀取，網站會自動退回：

```text
static/dougan-di-fallback.svg
```

若希望 100% 固定使用某一張 StoryMap 豆干弟原圖，也可以把原圖另存成專案內的 `static/dougan-di.png`，再將 `index.html` 的 fallback 路徑改成該檔案。

## 測試

```bash
python test_rag.py
python check_public_ready.py
```
