# 臺鐵精簡離線班表發佈通道

此資料夾由外部整理工具（不是手機）產出。

- `latest.tsv`：只在 7 天以上連續真實臺鐵官方資料全部驗證成功後建立，內容包含日期範圍、ZIP 文件名、大小、SHA-256、車次／停站筆數。
- `releases/tra-YYYYMMDD-YYYYMMDD.zip`：內含 `trips.tsv`、`stops.tsv`，不能存在虛構班次。
- `source-provenance.json`：政府每日 XML 各來源 SHA-256 與產物紀錄。

外部產製：`python tools/fetch_official_tra_xml.py --output-dir data/tra --days 60`。
僅限資料維護時使用，並可透過手動觸發的 `.github/workflows/compact-tra-publish-manual.yml` 運行；**未安排週期性 GitHub Actions，避免浪費額度**。

**注意：現在尚未發佈任何真實臺鐵班表 ZIP 或 latest.tsv。** 首次連線手機不會退回下載 60 份大型 XML，也不會使用測試用的虛構班次；首次使用的臺鐵查詢仍須待真實精簡包成功發佈。

臺鐵官方班表來源：https://ods.railway.gov.tw/tra-ods-web/ods/download/dataResource/railway_schedule/XML/list。

此通道與既有國光／統聯公開靜態資料通道分開，不改動其舊版數據與授權說明。