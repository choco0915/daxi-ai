# 光影大溪－豆干弟 AI 智慧導覽 V7

這是一套以 `data.md` 為主要在地知識來源，搭配桃園觀光官方 Open Data、OpenAI Responses API 與官方網路搜尋的大溪智慧導覽系統。

## V7 這次修正的核心問題

### 1. 「那附近還有什麼？」會斷掉前文

舊版只在「詳細／照片」類追問強制沿用 `active_topics`，但「附近／周邊／那附近還有什麼」沒有完整走同一條狀態路徑，因此可能把問題重新當成一個沒有主詞的新問題。

V7 改成：

- `照片`
- `再詳細一點`
- `那附近還有什麼？`
- `它周邊呢？`
- `第二個詳細介紹`
- `把剛剛推薦的幾個排成半日遊`

都會優先使用目前對話保存的 `active_topics`、上一輪 `recommendations` 與最近對話。

「附近」不再只交給模型猜。若桃園觀光官方景點資料有座標，後端會直接用座標計算附近景點；即使 OpenAI 暫時不可用，也能延續原景點回答。

### 2. 官方相簿存在，但照片仍抓不到

桃園觀光的「景點資料」與「觀光相簿」是不同資料來源。舊版又只從景點頁找一般 `<img src>`，但官方網站部分圖片使用 lazy-load、`srcset`、內嵌 JSON 或 `/image/<id>/<size>` 格式，因此會漏掉。

V7 改成多層圖片來源：

1. 桃園觀光「觀光相簿」Open Data。
2. 官方景點頁中的 `og:image`、`src`、`data-src`、`srcset`、lazy-load 資料。
3. 官方相簿頁中的 `/image/<id>/<size>` 圖片。
4. 常用大溪景點加入「官方相簿頁 fallback」，例如福仁宮、大溪老街、大溪橋、武德殿。
5. OpenAI web search 可用時，再補官方網域 image results。
6. 回傳圖片後由 `/image-proxy` 代理，降低防盜連／Referrer 導致圖片不顯示的機率。

### 3. 一直顯示「本地 RAG」但看不到真正原因

V7 新增安全診斷端點：

```text
/diagnostics
```

例如正式網址為：

```text
https://你的網站.onrender.com/diagnostics
```

它只會顯示：

- App 版本
- OpenAI 是否有設定
- 主要模型、備援模型與最近成功使用的模型
- Web Search 是否啟用
- 最近一次 OpenAI 錯誤（已遮蔽 API Key）
- 最近一次桃園官方資料錯誤
- 最近一次圖片抓取錯誤
- 快取資料筆數

**不會顯示 `OPENAI_API_KEY`。**

如果聊天泡泡下面一直顯示「本地備援」，也可以直接點該標籤開啟診斷頁。

> 注意：先前文件曾把 `gpt-5.6-luna` 說成不能使用 Web Search，這個判斷不正確。現在不再用模型名稱猜錯誤原因；V7 直接記錄實際 OpenAI 例外到 `/diagnostics`。目前專案主要模型預設 `gpt-5.6`，並加入 `gpt-5.6-luna` 作為模型備援；兩者目前官方文件都支援 Responses API，Luna 也支援 Web Search。若兩個都失敗，`/diagnostics` 會顯示實際錯誤。

## 主要能力

- `data.md` Hybrid RAG：中文 2～4 字 n-gram TF-IDF、標題／意圖加權、主題焦點過濾。
- 防止岔題：問木藝不會因其他片段順帶提到武德殿，就把武德殿整段展開。
- 多輪對話狀態：`active_topics` + `last_recommendations` + 最近 10 輪 history。
- 官方附近景點：利用桃園觀光 Open Data 的 X/Y 座標計算附近景點。
- 行程延續：可把上一輪推薦景點排成路線；也支援「第二個跟第三個一起排」。
- 詳細介紹：data.md + 桃園觀光官方景點資料；OpenAI 可用時再用官方網路來源補充。
- 官方照片：官方相簿／官方景點頁／OpenAI 官方網域 Image Search。
- 回答來源標示、豆干弟角色、動態光影、RWD 手機版、Render 公開部署。

## 1. 安裝

Windows Git Bash：

```bash
python -m venv .venv
source .venv/Scripts/activate
python -m pip install -r requirements.txt
```

## 2. `.env`

```env
OPENAI_API_KEY=your_new_openai_api_key_here
OPENAI_MODEL=gpt-5.6
OPENAI_FALLBACK_MODEL=gpt-5.6-luna
WEB_SEARCH_ENABLED=true
CHAT_RATE_LIMIT=30
CHAT_RATE_WINDOW_SECONDS=60
```

不要把真正的 `.env` 或 API Key 上傳 GitHub。

## 3. 本機啟動

```bash
uvicorn app:app --reload --host 127.0.0.1 --port 8000
```

首頁：

```text
http://127.0.0.1:8000/
```

健康檢查：

```text
http://127.0.0.1:8000/health
```

診斷：

```text
http://127.0.0.1:8000/diagnostics
```

## 4. 建議測試流程

部署後開「新對話」，依序輸入：

```text
福仁宮
照片
再詳細一點
那附近還有什麼？
深入介紹第二個
把第二個跟第三個排成兩小時路線
```

預期：

- `照片` 會沿用福仁宮。
- `再詳細一點` 會沿用福仁宮。
- `那附近還有什麼？` 會以福仁宮為原點列出附近官方景點，而不是說不知道主詞。
- 下一句「第二個」會指向上一輪附近推薦的第二個景點。
- 若 OpenAI 不可用，上述「附近」與基本路線仍會由官方 Open Data + 本地邏輯完成。

## 5. 自動測試

```bash
python test_rag.py
```

V7 測試包含：RAG 焦點、木藝防岔題、active topic 延續、照片追問、詳細追問、附近景點、官方資料 fallback、相簿 HTML `/image/` 解析等。

## 6. Render

`render.yaml` 已設定：

```text
uvicorn app:app --host 0.0.0.0 --port $PORT
```

GitHub `main` branch Commit 後 Render 可自動重新部署。

如果新版部署後仍顯示「本地備援」，先不要再猜模型或 prompt，直接開：

```text
/diagnostics
```

看 `last_openai_error` 的實際內容，再針對 API Key、額度、模型權限或工具參數處理。
