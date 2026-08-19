# 光影大溪－豆干弟 AI 智慧導覽

這是一套以 `data.md` 為主要知識來源、搭配 OpenAI Responses API 與官方網站 `web_search` 的大溪智慧導覽系統。

## 主要能力

- `data.md` Hybrid RAG：中文 2～4 字 n-gram TF-IDF、標題／意圖加權、主題焦點過濾。
- 防止「前面答對、後面岔題」：單一主題只保留高相關章節；例如問「大溪木藝」不會再把「武德殿」當獨立主題一起展開。
- 多輪對話記憶：支援「剛剛第二個」「深入介紹它」「把剛剛推薦的幾個景點排成半日行程」。
- 官方網路補充：需要最新、深入、營業／開放、活動或行程資訊時，可使用 OpenAI `web_search`。
- 官方來源優先：預設限制在桃園市政府體系、交通部觀光署與指定 ArcGIS StoryMap。
- 回答來源標示：`data.md` 來源與網路來源分開呈現；網路來源可直接點開。
- 豆干弟角色、指定人物頭像、動態光影背景、景點卡片與 RWD 手機版。
- 公開部署：支援 Render。

## 1. 建立環境

Windows Git Bash：

```bash
python -m venv .venv
source .venv/Scripts/activate
python -m pip install -r requirements.txt
```

macOS / Linux：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## 2. 設定環境變數

把 `.env.example` 複製成 `.env`：

```env
OPENAI_API_KEY=your_new_openai_api_key_here
OPENAI_MODEL=gpt-5.6
WEB_SEARCH_ENABLED=true
CHAT_RATE_LIMIT=30
CHAT_RATE_WINDOW_SECONDS=60
```

`OPENAI_API_KEY` 只放在本機 `.env` 或 Render Environment Variables，不要上傳到 GitHub。

## 3. 啟動

```bash
uvicorn app:app --reload --host 127.0.0.1 --port 8000
```

瀏覽器：

```text
http://127.0.0.1:8000/
```

健康檢查：

```text
http://127.0.0.1:8000/health
```

## 4. 對話脈絡怎麼運作

前端會把最近 10 輪對話一起送到 `/chat`，並保留上一輪：

- 回答所使用的 `data.md` 章節
- 豆干弟推薦的景點

因此可以接著問：

```text
深入介紹第二個
剛剛第三個景點有什麼特色？
把剛剛推薦的幾個景點排成半日行程
它附近還能安排什麼？
```

後端會先把這類代名詞／序號解析成具體景點，再做 RAG，避免把前文所有景點一起塞進回答。

## 5. 官方網路搜尋

系統不是每一題都上網，避免不必要的延遲與 API 成本。以下情況會優先啟用官方網路補充：

- 使用者明確說要查網路／官網
- 問最新、目前、營業、開放、休館、票價、活動、交通等可能變動資訊
- 要求「深入／詳細／更多」
- 要安排行程或路線
- `data.md` RAG 信心不足

預設官方網域：

```text
tycg.gov.tw        桃園市政府與子網域
 taiwan.net.tw       交通部觀光署
 storymaps.arcgis.com 指定故事地圖
```

> `tycg.gov.tw` 的子網域包含桃園觀光導覽網、大溪木藝生態博物館、大溪大禧等官方服務。

如不想使用 web search，可設定：

```env
WEB_SEARCH_ENABLED=false
```

## 6. RAG 測試

不需要 OpenAI API Key：

```bash
python test_rag.py
```

目前測試包含：巴洛克、美食、六二四、停車、鳳飛飛、雨天、半日遊、未知問題、木藝防岔題、第二個景點延續、前文推薦行程等。

## 7. Render 部署

專案根目錄保留 `render.yaml`，Push 到 GitHub 後 Render 可自動重新部署。

確認 Environment Variables 至少有：

```text
OPENAI_API_KEY
OPENAI_MODEL
WEB_SEARCH_ENABLED
CHAT_RATE_LIMIT
CHAT_RATE_WINDOW_SECONDS
```

Render 啟動指令：

```text
uvicorn app:app --host 0.0.0.0 --port $PORT
```


## V5：詳細介紹與官方照片

- 當使用者輸入「詳細介紹／深入介紹」時，系統會優先讀取桃園觀光導覽網官方 Open Data 補充同一景點的詳細資料。
- 當使用者輸入「照片／圖片」時，會優先從官方 Open Data 取得景點圖片；若 OpenAI web search 可用，也會使用官方網域的 image search 結果。
- 官方 Open Data 路徑不依賴 OpenAI，因此即使 OpenAI 暫時失敗，只要 Render 可連上桃園觀光官方資料，仍可顯示較完整的景點介紹與官方圖片。
- 中央聊天區背景已改成透明，讓動態光影背景直接顯示；聊天頭像也稍微放大。

## V6：修正「照片不顯示」與話題斷線

這版修正兩個根因：

1. `OPENAI_MODEL` 改為官方目前可用於 Responses API + `web_search` 的 `gpt-5.6`。如果 Render 仍保留舊的 `gpt-5.6-luna`，請手動改成 `gpt-5.6`，否則 OpenAI 會失敗並退回本地 RAG。
2. 桃園市景點 Open Data 本身沒有照片欄位；V6 改成三層照片來源：
   - 桃園觀光「觀光相簿」Open Data
   - 桃園觀光官方景點頁的 `og:image` / `img`
   - OpenAI `web_search` 的官方網域 image results

前端顯示圖片時會優先走 `/image-proxy`，由 FastAPI 代理本輪已驗證的官方圖片，降低來源站防盜連或 referrer 政策造成圖片空白的機率。

多輪對話則新增 `active_topics` 顯式狀態。每一輪後端會把目前正在談的景點回傳前端並保存，下一輪會再送回後端，所以現在可直接接著說：

```text
福仁宮
照片
再詳細一點
那附近還有什麼？
把剛剛推薦的三個排成半日遊
```

即使句子裡沒有再次寫「福仁宮」，系統也會優先沿用上一輪主題。
