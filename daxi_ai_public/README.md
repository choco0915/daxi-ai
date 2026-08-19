# 光影大溪－AI 與智慧城市結合（公開部署版）

這是一套以 `data.md` 為主要事實來源的 FastAPI + OpenAI RAG 大溪智慧導覽系統。
此版本已調整為可部署到公開網路，不再只綁定 `127.0.0.1`。

## 專案結構

- `app.py`：FastAPI、RAG、OpenAI 回答與公開站安全設定
- `index.html`：聊天導覽前端
- `data.md`：主要知識庫
- `requirements.txt`：Python 套件
- `render.yaml`：Render 公開部署設定
- `Procfile`：其他支援 Procfile 的平台可使用
- `.env.example`：本機環境變數範例
- `test_rag.py`：RAG 基本測試

## 本機測試

Windows Git Bash：

```bash
python -m venv .venv
source .venv/Scripts/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

編輯 `.env`，填入新產生的 OpenAI API Key：

```env
OPENAI_API_KEY=你的新_API_Key
OPENAI_MODEL=gpt-5.6-luna
```

啟動：

```bash
uvicorn app:app --reload --host 127.0.0.1 --port 8000
```

本機瀏覽：`http://127.0.0.1:8000/`

## 公開部署：Render（推薦）

### 1. 上傳到 GitHub

請把這個資料夾內的檔案放到一個 GitHub repository。`.env` 不可上傳；`.gitignore` 已排除它。

如果已經在 Git repository：

```bash
git add .
git commit -m "prepare public deployment"
git push
```

### 2. 在 Render 建立 Blueprint

1. 登入 Render。
2. 選擇 `New` → `Blueprint`。
3. 連接存放本專案的 GitHub repository。
4. Render 會讀取專案根目錄的 `render.yaml`。
5. 在要求 `OPENAI_API_KEY` 時填入真正的 Key；不要寫進 GitHub。
6. 開始部署。

部署成功後，Render 會提供類似：

```text
https://daxi-ai-guide.onrender.com
```

這個網址就能直接分享給其他人使用，不需要你的電腦持續開機。

## Render 設定已包含

- Python Web Service
- Singapore region
- `pip install -r requirements.txt`
- `uvicorn app:app --host 0.0.0.0 --port $PORT`
- `/health` 健康檢查
- Git commit 自動重新部署
- `OPENAI_API_KEY` 使用雲端 Secret，而非寫在程式碼
- 公開 `/chat` API 每 IP 基本限流

## 為什麼不能只把 127.0.0.1 改掉？

`127.0.0.1` 只代表自己的電腦。改成 `0.0.0.0` 只是讓伺服器接受外部連線；要真正讓全世界透過 HTTPS 存取，仍需要把程式部署到 Render、Railway、Fly.io、VPS 等具有公開網域與伺服器的環境。

本專案的前端使用 `/chat`、`/init_topics` 等相對 URL，因此前後端部署在同一個 Render Web Service 時，不需要修改 API 網址，也不需要額外設定 CORS。

## 公開站安全提醒

公開網站的 `/chat` 會使用你的 OpenAI API 額度，因此不要把 `OPENAI_API_KEY` 放到 `index.html`、GitHub、README 或任何前端 JavaScript 中。本版 Key 僅從伺服器環境變數讀取，並加上基本每 IP 限流。

如果預期大量使用者，建議之後再加入登入、Cloudflare、Redis 集中式 rate limit、每日額度與伺服器監控。

## RAG 測試

```bash
python test_rag.py
```

## 健康檢查

本機：`http://127.0.0.1:8000/health`

公開部署後：`https://你的網域/health`
