# 員工日報回報系統 — 系統規格書 (System Specification)

> **版本**: v0.4
> **日期**: 2026-06-24
> **狀態**: 已實作（反映當前實際運作的系統狀態）

---

## 變更紀錄 (Changelog)

| 版本 | 日期 | 變更內容 |
|------|------|----------|
| v0.1 | 2026-06-24 | 初稿 |
| v0.2 | 2026-06-24 | 新增個人統計頁面；Salary 增加 PDF/Excel 匯出；帳戶刪除可選保留或連帶刪除；ADMIN 可修改/刪除回報 |
| v0.3 | 2026-06-24 | 移除 `username` 欄位改以 `display_name` 識別；登入改為下拉選單；全面防呆機制；補充技術架構 |
| v0.4 | 2026-06-24 | **回報欄位全面更新**：16 個舊欄位替換為 21 個新欄位並附預設單價；**保留金機制**：直總/間接 8 欄位每只抽取費率（ADMIN 可設定，預設 20 NTD），個人統計及 Salary 頁面均顯示；**薪資實領制**：薪資扣除保留金後才是實領金額；**發薪方式**：帳戶新增領現(CASH)/轉帳(TRANSFER)，Salary 頁面分拆並附提現面額配置；**系統設定模型**：新增 `SystemConfig` 表；**金額格式化**：所有金額加千位逗號；**匯出加強**：Excel/PDF 包含發薪方式、保留金明細、面額配置；**變動紀錄**：ADMIN 可依操作者篩選；**ADMIN 個人統計**：ADMIN 亦可使用個人統計頁面；**部署上線**：Supabase(PostgreSQL) + Railway；PDF 改用 reportlab 內建 CID 字型 |

---

## 1. 系統概述 (System Overview)

本系統為一 Web-based 員工日報回報管理系統，供員工（及管理者）每日回報各類工項數量，並由管理者進行確認、統計、薪資計算等管理作業。

---

## 2. 技術架構 (Technical Stack)

| 項目 | 技術 |
|------|------|
| 後端框架 | Python Flask |
| 模板引擎 | Jinja2 |
| ORM | Flask-SQLAlchemy |
| 資料庫 | PostgreSQL（Supabase，正式環境）/ SQLite（本地開發） |
| 認證 | Flask-Login（Session-based，remember=True） |
| 密碼雜湊 | Werkzeug（bcrypt 級別） |
| 前端 UI | Bootstrap 5.3（CDN） + Bootstrap Icons |
| Excel 匯出 | openpyxl |
| PDF 匯出 | reportlab（CID 字型 STSong-Light，正式環境無需安裝系統字型） |
| 正式部署 | Railway（gunicorn）+ Supabase（PostgreSQL） |
| 本地開發 | `python app.py`（Flask dev server，port 5000） |

### 環境變數

| 變數名稱 | 說明 | 預設值 |
|---------|------|--------|
| `SECRET_KEY` | Flask session 簽名金鑰 | 本地 fallback 值（正式環境請設定隨機字串） |
| `DATABASE_URL` | 資料庫連線字串（`postgresql://...` 或 `postgres://...`） | `sqlite:///daily_report.db` |

---

## 3. 角色定義 (Roles)

| 角色 | 代碼 | 說明 |
|------|------|------|
| 管理者 | ADMIN | 可存取所有頁面，亦可填寫回報 |
| 一般使用者 | USER | 填報每日工項、查看自身紀錄、申請材料、試算個人薪資 |

---

## 4. 頁面與功能規格 (Page Specifications)

### 4.1 登入頁面 (Login Page)

- **存取權限**: 所有未登入者
- **欄位**:
  - 姓名下拉選單（顯示所有 `is_active = true` 的帳戶 `display_name`，含中文）
  - 密碼輸入框（含顯示/隱藏切換）
- **行為**:
  - 選取姓名後自動聚焦至密碼欄位，頂部顯示對應姓名首字的頭像圓圈
  - 登入成功後依角色導向：USER → 回報頁面；ADMIN → Summary 頁面
  - 登入失敗顯示錯誤訊息
  - 系統維持登入 Session（`remember=True`）

---

### 4.2 頁面 1：回報頁面 (Daily Report Page)

- **存取權限**: USER 及 ADMIN

#### 4.2.1 表單欄位

所有數值欄位單位皆為「只」，預設值為 0，僅允許輸入非負整數。共 21 個數值欄位 + 1 個日期欄位。

| 欄位名稱 | 欄位 Key | 預設單價 (NTD) |
|---------|---------|--------------|
| 直總-13 | `direct_13` | 100 |
| 直總-20 | `direct_20` | 100 |
| 直總-25 | `direct_25` | 100 |
| 直總-40 | `direct_40` | 150 |
| 間接-13 | `indirect_13` | 55 |
| 間接-20 | `indirect_20` | 55 |
| 間接-25 | `indirect_25` | 55 |
| 間接-40 | `indirect_40` | 105 |
| 原改 | `original_change` | 45 |
| 直總-換由令(含表)-13~25 | `direct_switch_valve` | 200 |
| 間接-換由令(含表)-13~25 | `indirect_switch_valve` | 150 |
| 13~25換開關(含表) | `switch_valve_13_25` | 320 |
| 40換開關(含表) | `switch_valve_40` | 450 |
| 直總-13~25固拆(含表) | `direct_fixed_13_25` | 340 |
| 直總-40固拆(含表) | `direct_fixed_40` | 500 |
| 間接-13~25固拆(含表) | `indirect_fixed_13_25` | 230 |
| 間接-40固拆(含表) | `indirect_fixed_40` | 450 |
| 管修(提高) | `pipe_repair` | 150 |
| 動員 | `mobilization` | 1,200 |
| 複查案/9年表 | `recheck` | 60 |
| 清積土 | `soil_clearing` | 100 |

> 同一帳戶同一日期允許送出多筆回報（無 UNIQUE 限制）。

#### 4.2.2 送出前二次確認 (Confirmation Modal)

點擊「送出」後彈出確認框，列出所有已填寫（> 0）的工項名稱與只數，以及所有欄位只數合計。使用者可選擇「確認送出」或「返回修改」。

#### 4.2.3 送出後行為

- 資料寫入資料庫，回報狀態預設為「尚未確認」
- 產生一筆變動紀錄 (Audit Log)

---

### 4.3 頁面 2：歷史紀錄頁面 (History Page)

- **存取權限**: USER 及 ADMIN

| 功能 | USER | ADMIN |
|------|------|-------|
| 可見範圍 | 僅自己的回報 | 所有帳戶的回報 |
| 篩選條件 | 日期範圍 | 日期範圍 + 帳戶下拉 |
| 修改 | ✅（已確認的修改後重置為未確認） | ✅ |
| 刪除 | ✅ | ✅ |

所有修改與刪除操作均設有二次確認對話框，並產生變動紀錄。

---

### 4.4 頁面 3：設定頁面 (Settings Page)

- **存取權限**: USER 及 ADMIN

#### USER 功能

修改自己的密碼（需輸入舊密碼 + 新密碼 + 確認新密碼），送出前有二次確認。

#### ADMIN 額外功能

**帳戶管理**（帳戶列表顯示：名稱、角色、發薪方式、狀態、建立時間）：

| 操作 | 說明 |
|------|------|
| 新增帳戶 | 填入帳戶名稱、密碼、帳戶類型、發薪方式 |
| 修改顯示名稱 | 修改任一帳戶的 `display_name` |
| 修改發薪方式 | 切換帳戶的領現(CASH) / 轉帳(TRANSFER) |
| 重設密碼 | ADMIN 直接設定新密碼，無需舊密碼 |
| 刪除帳戶 | 可選(a)保留資料僅停用，或(b)連帶刪除所有回報與申請 |

**保留金費率設定**：

- ADMIN 可在設定頁面調整「保留金費率」（NTD/只），預設 20 NTD
- 費率儲存於 `SystemConfig` 表，即時生效，影響後續所有保留金計算

所有操作均有二次確認並產生變動紀錄。

---

### 4.5 頁面 4：剩餘材料頁面 (Remaining Materials Page)

- **存取權限**: USER 及 ADMIN

| 功能 | USER | ADMIN |
|------|------|-------|
| 查看材料列表 | ✅ | ✅ |
| 申請領取 | ✅ | — |
| 查看申請紀錄 | ✅（自己的） | ✅（全部） |
| 新增材料 | — | ✅ |
| 調整數量 | — | ✅ |

剩餘數量 ≤ 5 顯示紅色，≤ 20 顯示橘色。所有操作均有二次確認並產生變動紀錄。

---

### 4.6 頁面 5：Summary 頁面 (Summary Page)

- **存取權限**: 僅 ADMIN
- 篩選條件：日期範圍（必填）、帳戶（全部或特定）、確認狀態（全部/已確認/未確認）
- 以表格呈現每位帳戶各工項只數加總，最後一列為所有帳戶合計

---

### 4.7 頁面 6：確認頁面 (Confirmation Page)

- **存取權限**: 僅 ADMIN

**功能一：回報確認**：列出所有未確認回報，逐筆點擊「確認」（有二次確認）。

**功能二：材料申請審核**：列出待審核申請，可核准（自動扣庫存）或駁回（均有二次確認）。

所有操作產生變動紀錄。

---

### 4.8 頁面 7：變動紀錄頁面 (Audit Log Page)

- **存取權限**: USER 及 ADMIN

#### 篩選條件

| 條件 | USER | ADMIN |
|------|------|-------|
| 日期範圍 | ✅ | ✅ |
| 操作者 | — | ✅（下拉選單） |
| 操作類型 | ✅ | ✅ |

USER 只能查看自己的紀錄；ADMIN 可依操作者篩選查看任一帳戶或所有帳戶的紀錄。

#### action_type 列舉值

| 值 | 說明 |
|----|------|
| REPORT_CREATE | 新增回報 |
| REPORT_UPDATE | 修改回報 |
| REPORT_DELETE | 刪除回報 |
| REPORT_CONFIRM | ADMIN 確認回報 |
| REPORT_UNCONFIRM | 因修改導致確認狀態重置 |
| MATERIAL_ADD | 新增材料 |
| MATERIAL_UPDATE | 調整材料數量 |
| MATERIAL_REQUEST | 申請材料領取 |
| MATERIAL_APPROVE | 核准材料申請（含扣減數量） |
| MATERIAL_REJECT | 駁回材料申請 |
| ACCOUNT_CREATE | 新增帳戶 |
| ACCOUNT_UPDATE | 修改帳戶資訊 |
| ACCOUNT_DELETE | 連帶刪除帳戶 |
| ACCOUNT_DEACTIVATE | 停用帳戶 |
| PASSWORD_CHANGE | 修改密碼 |
| SYSTEM_CONFIG | 修改系統設定（如保留金費率） |

變動紀錄不可被任何人刪除或修改。

---

### 4.9 頁面 8：Salary 頁面 (Salary Page)

- **存取權限**: 僅 ADMIN

#### 操作流程

1. 選定計薪日期範圍
2. 填入各工項單價（NTD，預設帶入系統預設單價）
3. 點擊「計算薪資」
4. 查看薪資明細
5. 可匯出為 PDF 或 Excel

#### 計算邏輯（僅計算已確認回報）

```
計薪小計（稅前）= Σ 已確認只數 × 工項單價
本期保留金（扣除）= 直總/間接 8 欄位只數加總 × 保留金費率
本期實領金額 = 計薪小計 − 本期保留金
```

#### 保留金機制

- 適用欄位：`direct_13`, `direct_20`, `direct_25`, `direct_40`, `indirect_13`, `indirect_20`, `indirect_25`, `indirect_40`（8 欄位）
- 費率：預設 20 NTD/只，ADMIN 可在設定頁面修改
- 性質：類保證金，每年底結算歸零（YTD 保留金自當年 1/1 起累計）
- **保留金從薪資中扣除，實領金額 = 計薪小計 − 保留金**

#### 薪資發放方式

每位帳戶設有發薪方式（領現 CASH / 轉帳 TRANSFER），Salary 頁面計算完後顯示：

| 項目 | 說明 |
|------|------|
| 轉帳薪資總額 | 所有「轉帳」帳戶的實領金額加總 |
| 提現薪資總額 | 所有「領現」帳戶的實領金額加總 |
| 提現面額配置 | 最少張數拆解：1000/500/100/50/10/5/1 NTD |

#### 匯出內容

Excel 與 PDF 均包含：每位帳戶的姓名、發薪方式、工項明細、計薪小計、保留金扣除、實領金額；領現帳戶另附個人面額配置；末尾發放總覽含轉帳/提現分拆與合計面額配置。

---

### 4.10 頁面 9：個人統計頁面 (Personal Statistics Page)

- **存取權限**: USER 及 ADMIN

#### 功能一：工項總和查詢

- 篩選：日期範圍 + 確認狀態（全部/已確認/未確認）
- 顯示：各工項只數加總、本期保留金小計

#### 功能二：薪資試算（僅計算已確認回報）

- 填入各工項單價（預設帶入系統預設單價）
- 顯示：計薪小計、保留金扣除、**試算實領金額**

#### 今年度累積保留金

頁面頂端固定顯示當年（1/1 至今）已確認回報累積的保留金總額。

> 試算結果僅供個人參考，正式薪資以 ADMIN Salary 頁面計算為準。

---

## 5. 側邊欄 / 導覽列 (Navigation)

| 頁面 | USER | ADMIN |
|------|------|-------|
| 回報頁面 | ✅ | ✅ |
| 歷史紀錄 | ✅ | ✅ |
| 剩餘材料 | ✅ | ✅ |
| 變動紀錄 | ✅ | ✅ |
| 設定 | ✅ | ✅ |
| 個人統計 | ✅ | ✅ |
| Summary | ❌ | ✅ |
| 確認 | ❌ | ✅ |
| Salary | ❌ | ✅ |

---

## 6. 防呆機制 (Confirmation Guards)

所有會異動資料的操作均設有二次確認，防止誤操作。

| 頁面 | 操作 | 確認方式 |
|------|------|----------|
| 回報頁面 | 送出回報 | Bootstrap Modal（顯示工項列表與合計） |
| 歷史紀錄 | 儲存修改 | Modal 內 `onsubmit confirm()` |
| 歷史紀錄 | 刪除回報 | JS `confirm()` |
| 確認頁面 | 確認回報 / 核准 / 駁回 | `onsubmit confirm()` |
| 材料頁面 | 申請 / 新增 / 調整庫存 | Modal 內 `onsubmit confirm()` |
| 設定頁面 | 密碼 / 帳戶 / 費率 / 發薪方式 | `onsubmit confirm()` 或 Modal 內確認 |

---

## 7. 資料模型 (Data Model)

### 7.1 Users 表

| 欄位 | 類型 | 說明 |
|------|------|------|
| id | PK, Auto Increment | 主鍵 |
| display_name | VARCHAR(50), UNIQUE, NOT NULL | 唯一顯示名稱（允許中文） |
| password_hash | VARCHAR(256), NOT NULL | 密碼雜湊 |
| role | VARCHAR(10), NOT NULL | 'ADMIN' 或 'USER' |
| is_active | BOOLEAN, DEFAULT true | false 時不出現於登入下拉，資料保留 |
| payment_method | VARCHAR(10), NOT NULL, DEFAULT 'TRANSFER' | 發薪方式：'CASH' 或 'TRANSFER' |
| created_at | TIMESTAMP | 建立時間 |
| updated_at | TIMESTAMP | 最後修改時間 |

> `username` 不存入 DB，以 Python `@property` 返回 `f"uid_{self.id}"` 供程式碼相容。

### 7.2 Reports 表（回報紀錄）

共 21 個工項欄位（均為 INTEGER, DEFAULT 0, ≥ 0）：

`direct_13`, `direct_20`, `direct_25`, `direct_40`,
`indirect_13`, `indirect_20`, `indirect_25`, `indirect_40`,
`original_change`, `direct_switch_valve`, `indirect_switch_valve`,
`switch_valve_13_25`, `switch_valve_40`,
`direct_fixed_13_25`, `direct_fixed_40`,
`indirect_fixed_13_25`, `indirect_fixed_40`,
`pipe_repair`, `mobilization`, `recheck`, `soil_clearing`

其他欄位：`id`, `user_id (FK)`, `report_date`, `is_confirmed`, `confirmed_by (FK)`, `confirmed_at`, `created_at`, `updated_at`

### 7.3 Materials 表

`id`, `name`, `unit`, `remaining_quantity`, `created_at`, `updated_at`

### 7.4 MaterialRequests 表

`id`, `user_id (FK)`, `material_id (FK)`, `requested_quantity`, `status`（PENDING/APPROVED/REJECTED）, `reviewed_by (FK)`, `reviewed_at`, `created_at`

### 7.5 SystemConfig 表

| 欄位 | 類型 | 說明 |
|------|------|------|
| key | VARCHAR(50), PK | 設定鍵值 |
| value | VARCHAR(200), NOT NULL | 設定值（字串） |

目前使用的 key：`retention_rate`（保留金費率，預設 '20'）

### 7.6 AuditLogs 表

`id`, `user_id (FK)`, `action_type`, `description (TEXT)`, `created_at`（不可修改或刪除）

---

## 8. 業務規則摘要 (Business Rules)

| 編號 | 規則 |
|------|------|
| BR-01 | 同一帳戶同一日期可送出多筆回報 |
| BR-02 | 所有回報新增後預設為「尚未確認」 |
| BR-03 | 已確認的回報被修改後，確認狀態自動重置，需 ADMIN 重新確認 |
| BR-04 | Salary 頁面計算僅納入 `is_confirmed = true` 的回報 |
| BR-05 | Summary 頁面的確認狀態篩選由 ADMIN 自行選擇 |
| BR-06 | 材料申請核准後，系統自動扣減該材料的剩餘數量 |
| BR-07 | 帳戶刪除時，ADMIN 可選保留資料（停用）或連帶刪除 |
| BR-08 | 變動紀錄不可被任何人刪除或修改 |
| BR-09 | 個人統計薪資試算僅供參考，正式薪資以 ADMIN Salary 頁面為準 |
| BR-10 | 個人統計試算與 Salary 計算均只納入已確認的回報 |
| BR-11 | ADMIN 亦可填寫回報，其回報納入 Salary 與 Summary 計算 |
| BR-12 | 所有異動操作均設有二次確認防呆機制 |
| BR-13 | 帳戶識別以 `display_name` 為準（允許中文） |
| BR-14 | 停用帳戶不出現於登入下拉，歷史資料保留 |
| BR-15 | 保留金費率由 ADMIN 在設定頁面設定（預設 20 NTD/只），存於 SystemConfig |
| BR-16 | 保留金適用欄位：直總/間接 × 4 管徑 = 8 欄位，每只抽取費率金額 |
| BR-17 | YTD 保留金自當年 1/1 起累計，年底自然歸零（次年重新計算） |
| BR-18 | 實領金額 = 計薪小計 − 本期保留金；提現/轉帳分拆與面額配置均以實領金額為基準 |
| BR-19 | 發薪方式（領現/轉帳）為帳戶屬性，ADMIN 可在設定頁面修改 |
| BR-20 | Salary 計算後自動提示轉帳總額、提現總額及最少張數的面額配置 |

---

## 9. 測試資料 (Seed Data)

執行 `python seed.py` 建立初始測試資料（重複執行會清空並重建資料庫）：

| 帳戶名稱 | 密碼 | 角色 | 發薪方式 |
|---------|------|------|---------|
| 張管理員 | admin123 | ADMIN | 轉帳 |
| 陳小明 | user123 | USER | 轉帳 |
| 李小華 | user123 | USER | 領現 |

Seed 資料包含：30 筆回報（跨 3 帳戶、近 30 天，約 65% 已確認）、6 種材料、15 筆材料申請、SystemConfig 初始化（retention_rate = 20）。

---

## 10. 部署 (Deployment)

### 正式環境

| 項目 | 服務 |
|------|------|
| App Hosting | Railway（自動偵測 Python，讀取 Procfile） |
| Database | Supabase（PostgreSQL） |
| 啟動指令 | `gunicorn app:app`（Procfile） |
| 字型 | reportlab 內建 STSong-Light CID 字型（無需安裝系統字型） |

**Railway 環境變數設定：**

```
DATABASE_URL = postgresql://postgres:%40YourPassword%40@db.xxxx.supabase.co:6543/postgres?sslmode=require
SECRET_KEY   = (隨機字串，建議 openssl rand -hex 32)
```

> 注意：密碼中的 `@` 必須 URL encode 為 `%40`。Supabase 請使用 Connection Pooler（port 6543，Transaction mode），避免 IPv6 連線問題。

### 本地開發

```bash
python seed.py   # 建立測試資料（首次或重置時使用）
python app.py    # 啟動開發伺服器，port 5000
```

---

*— 文件結束 —*
