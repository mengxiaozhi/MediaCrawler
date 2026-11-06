# Threads / Facebook 使用說明

此 fork 新增 `threads` 與 `facebook` 平台，沿用 MediaCrawler 的命令列、API、WebUI 與檔案輸出流程。這是**實驗性的瀏覽器頁面擷取支援**：讀取已載入的頁面，不依賴未公開 API 的固定簽名或 GraphQL 文件 ID。

已使用本機 Chromium 的 HTML 測試頁驗證解析，並驗證命令列、API、儲存及瀏覽器生命週期；尚未以真實登入帳號完成兩個平台的實站端到端驗證。平台改版、地區、介面語言及帳號權限都可能影響結果。

## 功能範圍

| 功能 | Threads | Facebook |
| --- | --- | --- |
| 關鍵字搜尋 | `/search` 頁面 | `/search/posts` 頁面 |
| 指定貼文 | 貼文網址、`/t/` 分享網址、shortcode | 貼文、story/permalink、影片、reel、photo 網址、`ownerID_postID` |
| 作者頁 | 使用者名稱、個人頁網址 | 使用者名稱、數字 ID、個人頁或粉絲專頁網址 |
| 留言 | 可識別回覆區域或明確回覆關係中的可見回覆 | 帶真實 `comment_id` 的可見留言及回覆 |
| 資料輸出 | JSON、JSONL、CSV、Excel | JSON、JSONL、CSV、Excel |
| 登入 | 手動登入、Cookie、既有瀏覽器登入態 | 手動登入、Cookie、既有瀏覽器登入態 |

只會取得公開或目前帳號可見的內容。無法辨識的欄位留空，不會補造讚數、時間或留言 ID。Facebook 的互動計數目前留空；媒體僅保存頁面提供的網址，不下載檔案。資料庫輸出與媒體下載選項會明確回報不支援。

## 安裝與瀏覽器設定

在專案根目錄執行：

```bash
uv sync --frozen
uv run playwright install chromium
```

第一次使用，建議在 `config/base_config.py` 設定：

```python
ENABLE_CDP_MODE = False
HEADLESS = False
SAVE_LOGIN_STATE = True
```

這會啟動 Playwright Chromium，並將登入狀態分別存到 `browser_data/threads_user_data_dir` 與 `browser_data/facebook_user_data_dir`。瀏覽器中如需同意 Cookie 或登入，請手動完成。不要將登入資料提交到 Git。

也可以使用上游的 CDP 模式，連接已啟用遠端偵錯的 Chrome。`ENABLE_CDP_MODE=True`、`CDP_CONNECT_EXISTING=True` 時，本次新增的爬蟲只關閉自己開啟的分頁，保留原有分頁與瀏覽器。CDP 連線失敗會直接回報錯誤，請檢查上游的 CDP 設定。

## 執行範例

搜尋 Threads，首次手動登入：

```bash
uv run main.py --platform threads --lt manual --type search \
  --keywords "Python" --headless false \
  --crawler_max_notes_count 10 --save_data_option jsonl
```

Facebook 搜尋：

```bash
uv run main.py --platform facebook --lt manual --type search \
  --keywords "台灣旅遊" --headless false \
  --crawler_max_notes_count 10 --save_data_option jsonl
```

取得指定貼文（把示例網址換成實際網址）：

```bash
uv run main.py --platform threads --lt cookie --type detail \
  --specified_id "https://www.threads.com/@username/post/POST_CODE" \
  --save_data_option jsonl

uv run main.py --platform facebook --lt cookie --type detail \
  --specified_id "https://www.facebook.com/page.name/posts/POST_ID" \
  --get_comment true --save_data_option excel
```

取得作者資訊與貼文：

```bash
uv run main.py --platform threads --lt cookie --type creator \
  --creator_id "@username" --save_data_option jsonl

uv run main.py --platform facebook --lt cookie --type creator \
  --creator_id "https://www.facebook.com/page.name" --save_data_option jsonl
```

`--lt cookie` 會使用已保存或 CDP 瀏覽器的登入態；`COOKIES` 留空時也能嘗試不需登入的公開頁面。若需提供 Cookie，可在本地 `config/base_config.py` 設定 `COOKIES`，或使用既有的 `--cookies` 參數。舊的 `threads.net` 網址會轉為 `threads.com`，手動提供的 Threads Cookie 也應來自目前的 `threads.com` 登入頁。

多個貼文或作者可用逗號或換行分隔，也可以設定：

```python
# config/threads_config.py
THREADS_SPECIFIED_ID_LIST = []
THREADS_CREATOR_ID_LIST = []

# config/facebook_config.py
FACEBOOK_SPECIFIED_ID_LIST = []
FACEBOOK_CREATOR_ID_LIST = []
```

## WebUI 與 API

使用上游的 WebUI 啟動方式，選擇 Threads 或 Facebook。介面會提供「手動瀏覽器登入」與 Cookie 登入，並只顯示支援的儲存格式。手動登入時，瀏覽器會開在執行後端的電腦上。

API 範例：

```json
{
  "platform": "threads",
  "login_type": "manual",
  "crawler_type": "search",
  "keywords": "Python",
  "headless": false,
  "max_notes_count": 10,
  "save_option": "jsonl",
  "enable_comments": true
}
```

## 輸出與擷取限制

- 預設輸出為 `data/{platform}/{format}/{type}_{contents|comments|creators}_{日期}.{format}`；`--save_data_path` 可以替換 `data` 目錄。Excel 沿用上游工作簿命名與分頁。
- 每筆資料帶有 `platform`、`source_keyword`、擷取時間與真實內容 ID。同一次執行去重；再次執行仍沿用上游檔案的追加行為，不是跨執行的資料庫 upsert。
- 搜尋與作者頁採無限捲動，`--start` 代表從第幾個**捲動批次**開始收集，並非平台提供的頁碼。貼文數上限套用於每個關鍵字或作者；指定貼文模式套用於整份輸入清單。
- 先保存搜尋／作者頁貼文，再逐篇開啟詳情取得留言；此流程循序執行，避免多個工作同時操作同一分頁。`MAX_CONCURRENCY_NUM` 不會提高這兩個平台的並行度。
- 留言上限目前包含已擷取的第一層與子回覆總數。`--get_sub_comment true` 只納入能辨識父層 ID 的巢狀回覆；不保證取得所有留言。未載入、被摺疊、篩選掉或沒有可識別 ID 的留言可能被略過。
- Threads 若沒有可辨識的回覆區域或回覆關係，會保守地回傳空留言，避免把推薦貼文誤當回覆。圖片貼文、reel、watch 或相片頁是否能解析仍取決於其是否提供可識別的貼文 DOM；支援網址格式不代表每種頁面版型都能取得資料。
- 搜尋無結果會記錄警告；指定貼文找不到目標、遇到登入牆或驗證頁會回報錯誤，不會把推薦內容當成指定貼文保存。

`config/meta_config.py` 可調整登入等待、頁面逾時、捲動上限及空批次停止條件。預設最多捲動 30 次，連續 3 次沒有新內容即停止；既有 `CRAWLER_MAX_SLEEP_SEC` 同樣用於限速。

維持上游 [LICENSE](../LICENSE) 的非商業學習使用限制。

## 驗證

```bash
uv run pytest tests/test_threads_adapter.py tests/test_facebook_adapter.py \
  tests/test_meta_core.py tests/test_meta_e2e.py tests/test_meta_registration.py tests/test_meta_store.py
cd webui
npm ci
npm test
npm run build
```

DOM 測試使用本機 Chromium 與合成 HTML，無須真實帳號或連線到 Meta；這些測試驗證程式流程，不代表已通過平台實站驗證。
