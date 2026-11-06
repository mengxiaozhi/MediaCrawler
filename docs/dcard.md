# Dcard 使用說明

此 fork 新增 `dcard` 平台，支援關鍵字搜尋、指定文章、公開作者資訊與文章列表，以及文章留言。CLI、API 與 WebUI 都可選擇 Dcard，資料可輸出為 JSON、JSONL、CSV 或 Excel。

擷取使用 Dcard 網站公開頁面使用的 `/service/api/v2` 端點。已以少量公開資料驗證搜尋、文章、留言及作者端點；這些端點並非有相容性保證的開發者 API，網站改版或存取限制仍可能影響使用。

## 快速開始

```bash
git clone https://github.com/mengxiaozhi/MediaCrawler.git
cd MediaCrawler
uv sync --frozen
```

公開內容使用 `--lt cookie`，Cookie 可以留空，**不會啟動瀏覽器**，也不需要修改 CDP 設定。

搜尋並取得完整文章：

```bash
uv run main.py --platform dcard --lt cookie --type search \
  --keywords "Python,台灣旅遊" --crawler_max_notes_count 10 \
  --get_comment true --max_comments_count_singlenotes 10 \
  --save_data_option jsonl
```

指定文章可以使用文章 ID 或完整網址：

```bash
uv run main.py --platform dcard --lt cookie --type detail \
  --specified_id "262405106" --save_data_option jsonl

uv run main.py --platform dcard --lt cookie --type detail \
  --specified_id "https://www.dcard.tw/f/FORUM_ALIAS/p/POST_ID" \
  --save_data_option excel
```

把範例中的看板、文章 ID 換成實際內容。多篇文章可用逗號或換行分隔，也支援附帶標題或追蹤參數的 Dcard 文章網址。

作者模式接受公開使用者名稱或個人頁網址：

```bash
uv run main.py --platform dcard --lt cookie --type creator \
  --creator_id "https://www.dcard.tw/@USERNAME" \
  --crawler_max_notes_count 10 --save_data_option jsonl
```

匿名文章與留言不一定提供公開帳號，不能用學校名稱查出匿名作者。匿名資料的 `user_id` 留空，僅保留平台公開顯示的名稱。

## 輸出欄位

- 文章：真實文章 ID、網址、標題、全文、看板名稱與代號、發文時間、平台提供的讚數／留言數／分享數，以及媒體網址。
- 留言：真實留言 ID、文章 ID、內容、樓層、時間及可見的作者資訊；沒有留言 ID 時，僅在存在真實樓層時使用文章 ID 與樓層的組合識別。
- 作者：公開帳號 ID、名稱、個人頁網址、簡介及頭像。
- 每筆資料包含平台、搜尋關鍵字、擷取時間。缺少的欄位留空；不從匿名資料推測個人帳號。

預設檔案存到 `data/dcard/{json|jsonl|csv}`；`--save_data_path` 可以替換 `data` 目錄。Excel 使用 `data/dcard/dcard_{mode}_{時間}.xlsx`，含文章、留言及作者工作表。

## 分頁與選項

`config/dcard_config.py`：

```python
DCARD_SPECIFIED_ID_LIST = []
DCARD_CREATOR_ID_LIST = []
DCARD_MAX_PAGES = 30
DCARD_PAGE_SIZE = 30  # 1–100
DCARD_PAGE_TIMEOUT_MS = 30000
```

`--start` 代表從第幾頁開始，搜尋使用 offset，作者文章使用 before 游標。搜尋／作者的文章數上限分別套用於每個關鍵字／作者；指定文章模式則套用於整份輸入清單。相同執行中的重複文章會略過，跨次執行沿用檔案追加行為。

留言依 API 回傳的真實樓層游標分頁，數量受 `--max_comments_count_singlenotes` 限制。已刪除、隱藏、審核中及屬於其他文章的留言會略過。`--get_sub_comment true` 只保留目前端點回傳且帶有父層關係的回覆，**不保證取得獨立巢狀回覆端點中的所有回覆**。

既有 `CRAWLER_MAX_SLEEP_SEC` 控制請求間隔，這個平台循序擷取文章，不隨 `MAX_CONCURRENCY_NUM` 提高並行請求數。遇到 429 會停止並回報限流，不會持續重試。

## 登入與 WebUI

WebUI 選擇 Dcard 後，預設採 Cookie 模式，留空即可嘗試公開內容。若網站要求登入，可在本地 `COOKIES` 設定或既有 `--cookies` 參數提供有效的 Dcard Cookie。

也可使用 `--lt manual --headless false` 在瀏覽器手動登入。此模式沿用原專案的 Playwright／CDP 設定；若沒有已啟用偵錯的 Chrome，可先安裝 Chromium，並在 `config/base_config.py` 設定 `ENABLE_CDP_MODE=False`：

```bash
uv run playwright install chromium
uv run main.py --platform dcard --lt manual --headless false \
  --type search --keywords "Python" --save_data_option jsonl
```

登入後請開啟帳號選單，讓「登出」按鈕可見，程式才會確認登入並匯入該瀏覽器的 Cookie。追蹤或驗證 Cookie 不會被當成登入成功。手動登入流程已做模擬測試，尚未使用真實帳號驗證。

API 範例：

```json
{
  "platform": "dcard",
  "login_type": "cookie",
  "crawler_type": "search",
  "keywords": "Python",
  "max_notes_count": 10,
  "max_comments_count": 10,
  "enable_comments": true,
  "save_option": "jsonl"
}
```

目前不支援 Dcard 的資料庫輸出與媒體檔案下載；選擇這些功能會在開始擷取前回報錯誤。媒體網址照常保存。

## 驗證

```bash
uv run pytest tests/test_dcard_adapter.py tests/test_dcard_client.py \
  tests/test_dcard_core.py tests/test_dcard_registration.py tests/test_dcard_store.py
cd webui
npm test
npm run build
```

自動測試使用合成資料與攔截的 HTTP 回應，不會對 Dcard 產生流量。公開內容的實站驗證另外執行；私人、登入限定內容及完整子回覆不在已驗證範圍內。沿用上游 [LICENSE](../LICENSE) 的非商業學習使用限制。
