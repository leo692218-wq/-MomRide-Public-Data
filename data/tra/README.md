# 臺鐵精簡離線班表發佈通道

此資料夾由外部整理工具（不是手機）產出。

- `latest.tsv`：只在 7 天以上連續真實臺鐵官方資料全部驗證成功後建立，內容包含日期範圍、ZIP 文件名、大小、SHA-256、車次／停站筆數。
- `releases/tra-YYYYMMDD-YYYYMMDD.zip`：內含 `trips.tsv`、`stops.tsv`，不能存在虛構班次。
- `source-provenance.json`：政府每日 XML 各來源 SHA-256 與產物紀錄。

外部產製：`python tools/fetch_official_tra_xml.py --output-dir data/tra --days 60`。
資料發布目前採**每週一台灣時間 08:25** 或明確手動觸發的 `.github/workflows/compact-tra-publish-manual.yml`，**不在每次程式碼提交時執行**；單次工作限時 10 分鐘，且只有真實資料通過完整驗證才可更新發行。這是付費／有額度的 GitHub Actions，需持續注意使用量。手機仍僅在發行 SHA 改變時才下載資料包。

**首次真資料已發佈（2026-10-27）**：GitHub Actions Run 40362713025 真實執行成功；59份臺鐵官方每日XML整理為 2026-10-27 至 2026-12-24（59日）、53,769車次、1,242,866筆停靠、9,799,208位元組 ZIP。SHA-256 `410526c88c9b333c8daabf1e75c85f82130902688e36bafea6c119090a46c189`。仍須完成 Android 端真連線／SQLite匯入、使用者手機與完整API36驗收；不能把GitHub成功視為手機已驗收。

臺鐵官方班表來源：https://ods.railway.gov.tw/tra-ods-web/ods/download/dataResource/railway_schedule/XML/list。

此通道與既有國光／統聯公開靜態資料通道分開，不改動其舊版數據與授權說明。

## 2026-10-27｜可直接在手機查詢的 SQLite V2 實際發佈

- **已真發佈** `data/tra/latest-sqlite.tsv` 和 `data/tra/releases/tra-sqlite-20261027-20261224.zip`，使用**同一份**已核證 59 日官方來源 V1 ZIP（來源 SHA256 `410526c88c9b333c8daabf1e75c85f82130902688e36bafea6c119090a46c189`）在 GitHub 外部環境轉製，**沒有重抓官方59份XML或虛構班次**。
- **壓縮下載** 35,182,756 bytes（約33.6 MiB），SHA256 `78b16f485164ea147d404427a0bb7074a8970e3fbedcbf3f535d997b238e9305`；**展開SQLite** 168,779,776 bytes（約161 MiB），SHA256 `4865eb8c9edacd3001ca8a307ef795d41cf7e3c67769fbc90fd002c2787ae931`，具有實際 `train_trip`、`train_stop`、`feed_meta` 和兩個站名／站碼查詢索引。
- 59日、53,769車次、1,242,866筆停站資訊與V1相同。版本/大小/雙SHA由手機嚴格驗證；預建SQLite避免在手機逐筆建124萬筆索引，但**下載量由V1 9.80 MB增至V2 35.18 MB、手機常駐資料庫約161 MiB**，不可宣稱更省手機儲存或流量。安裝時暫存也需要額外空間；若空間不足應保留既有離線資料。
- 初次V2發布：GitHub Actions Run `40381166789` **SUCCESS**。此前四次有價上限/提交路徑驗證失敗（`40379285630`、`40379741682`、`40380142232`、`40380708011`），完整保留原因，不得把失敗回合冒稱通過。正式V2的ZIP及manifest均已讀回確認。
- 後續每週發布工作流程已同時產製V1/V2；僅在通過雙SHA、實際日期與資料筆數驗證後提交。**V2首次發布成功不等於Android API36完整編譯、手機實機下載速度、空間足夠或首次查詢效能已驗收**。

