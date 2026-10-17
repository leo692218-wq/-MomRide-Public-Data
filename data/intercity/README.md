# 媽媽要坐車｜國光＋統聯公開離線資料通道

本庫專供媽媽要坐車 App **開啟時自動檢查新版本**；媽媽不需要登入 GitHub、手動下載 ZIP、選檔或匯入 SQLite，也不需要 TDX API 金鑰。

- 版本入口：`data/intercity/latest.json`（僅幾百 bytes，含資料庫建立時間、版本與雙層 SHA-256）。
- 資料包：`data/intercity/releases/<版本>/intercity-snapshot.zip`，**普通 Git blob 公開靜態檔**，不是 GitHub Release 附件、Actions Artifact、Git LFS 或 Package。
- 每份 `latest.json` 指向**固定的 40 字 Git commit SHA** 對應原始 ZIP；Android 驗證 URL 所屬公開庫、長度與 ZIP SHA-256，解壓後再核對 SQLite SHA-256、表格完整性及兩家營運商資料量，全部成功才安全替換舊版，否則保留舊版。
- 使用者定期要求維護 GPT 查詢、校對官方資料並發布新版本；媽媽手機不需要額外操作。無須付費伺服器，也不執行 GitHub Actions。
- **安全限制：目前資料只有靜態週時刻與 TDX 停靠站序證據；未核實指定日期發車、營運日曆、站間售票及特殊公告。App 不得將它呈現為「當天一定有車／已證明可買票」。**
- 所有內容限於公開交通資訊之衍生資料；不包含 App 私有原始碼、個資、使用紀錄、GitHub Token、TDX 憑證或任何金鑰。

公開資料檔的下載不使用 Actions 分鐘或 Actions Artifact 儲存額度，但仍受 GitHub 服務規範及合理使用條件限制。
