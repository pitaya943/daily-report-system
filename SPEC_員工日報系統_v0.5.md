# 員工日報回報系統 — 系統規格書 (System Specification)

> **版本**: v0.5
> **日期**: 2026-06-25
> **狀態**: 已實作（反映當前實際運作的系統狀態）

---

## 變更紀錄 (Changelog)

| 版本 | 日期 | 變更內容 |
|------|------|----------|
| v0.1 | 2026-06-24 | 初稿 |
| v0.2 | 2026-06-24 | 新增個人統計頁面；Salary 增加 PDF/Excel 匯出；帳戶刪除可選保留或連帶刪除；ADMIN 可修改/刪除回報 |
| v0.3 | 2026-06-24 | 移除 `username` 欄位改以 `display_name` 識別；登入改為下拉選單；全面防呆機制；補充技術架構 |
| v0.4 | 2026-06-24 | 回報欄位全面更新（21 欄位）；保留金機制；發薪方式（CASH/TRANSFER）；SystemConfig；Excel/PDF 匯出加強；ADMIN 個人統計；部署上線（Supabase + Railway） |
| v0.5 | 2026-06-25 | **勞健保機制**：per-user 投保金額、計薪時 ADMIN 逐人勾選是否本次扣除；**稅務支出**：未投保帳戶依計薪小計扣 x%（預設 3%，四捨五入整數）；**快速計薪日期**：10號/25號發薪一鍵填入；**分頁**：歷史/確認/統計/變動紀錄頁面每頁 20 筆 + 上下分頁控制；**確認頁面排序**：待確認回報與待審核材料申請均改為由舊到新升冪排列；**材料管理**：刪除材料、ADMIN 手動排序（↑↓）；**材料申請**：USER 可取消待審核申請；**歷史刪除限制**：已確認回報 USER 不可刪除，僅 ADMIN 可刪；**累積保留金管理**：ADMIN 可重置為 0 或設定為任意值（retention_offset）；**停用帳戶重啟**；**種子資料更新**：20 帳戶（5 ADMIN + 15 USER）、約 1,800 筆回報 |

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
- **分頁**: 每頁 20 筆，表格上下方均顯示分頁控制列（含跳至第一頁/最後一頁按鈕）

| 功能 | USER | ADMIN |
|------|------|-------|
| 可見範圍 | 僅自己的回報 | 所有帳戶的回報 |
| 篩選條件 | 日期範圍 | 日期範圍 + 帳戶下拉 |
| 修改 | ✅（已確認的修改後自動重置為未確認） | ✅ |
| 刪除未確認回報 | ✅ | ✅ |
| 刪除已確認回報 | ❌（按鈕 disabled） | ✅ |

所有修改與刪除操作均設有二次確認對話框，並產生變動紀錄。

---

### 4.4 頁面 3：設定頁面 (Settings Page)

- **存取權限**: USER 及 ADMIN

#### USER 功能

修改自己的密碼（需輸入舊密碼 + 新密碼 + 確認新密碼），送出前有二次確認。

#### ADMIN 額外功能

**帳戶管理**（帳戶列表顯示欄位：#、名稱、角色、發薪方式、勞健保扣除額、今年累積保留金、狀態、建立時間、操作）：

| 操作 | 說明 |
|------|------|
| 新增帳戶 | 填入帳戶名稱、密碼、帳戶類型、發薪方式 |
| 修改顯示名稱 | 修改任一帳戶的 `display_name` |
| 修改發薪方式 | 切換帳戶的領現(CASH) / 轉帳(TRANSFER) |
| 設定勞健保扣除額 | 設定每期計薪的固定扣除金額（NTD）；0 代表未在公司投保 |
| 重設密碼 | ADMIN 直接設定新密碼，無需舊密碼 |
| 停用帳戶 | 可選(a)保留資料僅停用，或(b)連帶刪除所有回報與申請 |
| 重新啟用 | 將已停用帳戶重新設為啟用 |
| 累積保留金管理 | 重置今年度累積保留金為 0，或設定為指定金額 |

**費率設定：**

| 設定項目 | SystemConfig key | 說明 | 預設值 |
|---------|-----------------|------|--------|
| 保留金費率 | `retention_rate` | 直總/間接 8 欄位每只抽取的金額（NTD/只），即時生效 | 20 NTD |
| 稅務支出費率 | `tax_rate` | 未投保帳戶計薪時依計薪小計扣除的百分比，四捨五入整數 | 3% |

所有操作均有二次確認並產生變動紀錄。

---

### 4.5 頁面 4：剩餘材料頁面 (Remaining Materials Page)

- **存取權限**: USER 及 ADMIN
- 材料列表依 `sort_order` 升冪排列

| 功能 | USER | ADMIN |
|------|------|-------|
| 查看材料列表 | ✅ | ✅ |
| 申請領取 | ✅ | — |
| 取消待審核申請 | ✅ | — |
| 查看自己的申請紀錄 | ✅ | — |
| 新增材料 | — | ✅ |
| 調整庫存數量 | — | ✅ |
| 刪除材料 | — | ✅（連帶刪除所有申請紀錄） |
| 調整排序（↑↓） | — | ✅ |

剩餘數量 ≤ 5 顯示紅色，≤ 20 顯示橘色。所有操作均有二次確認並產生變動紀錄。

---

### 4.6 頁面 5：Summary 頁面 (Summary Page)

- **存取權限**: 僅 ADMIN
- **分頁**: 每頁 20 位帳戶，表格上下方均顯示分頁控制列
- 篩選條件：日期範圍（必填）、帳戶（全部或特定）、確認狀態（全部/已確認/未確認）
- 以表格呈現每位帳戶各工項只數加總
- `<tfoot>` 包含兩列：(1) 重複的欄位名稱標題列；(2) 所有帳戶合計列（計算全部資料，不受分頁影響）

---

### 4.7 頁面 6：確認頁面 (Confirmation Page)

- **存取權限**: 僅 ADMIN

**功能一：回報確認**
- 列出所有未確認回報，**依 report_date ASC, id ASC 排列**（最早的回報優先顯示）
- 每頁 20 筆，上下方均有分頁控制列
- 逐筆點擊「確認」（有二次確認）

**功能二：材料申請審核**
- 列出所有待審核申請，**依 created_at ASC 排列**（最早申請的優先顯示）
- 可核准（自動扣庫存）或駁回（均有二次確認）

所有操作產生變動紀錄。

---

### 4.8 頁面 7：變動紀錄頁面 (Audit Log Page)

- **存取權限**: USER 及 ADMIN
- **分頁**: 每頁 20 筆，表格上下方均顯示分頁控制列

#### 篩選條件

| 條件 | USER | ADMIN |
|------|------|-------|
| 日期範圍 | ✅ | ✅ |
| 操作者 | — | ✅（下拉選單） |
| 操作類型 | ✅ | ✅ |

USER 只能查看自己的紀錄；ADMIN 可依操作者篩選。

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
| MATERIAL_DELETE | 刪除材料（連帶刪除所有申請） |
| MATERIAL_REQUEST | 申請材料領取 |
| MATERIAL_CANCEL | USER 取消待審核申請 |
| MATERIAL_APPROVE | 核准材料申請（含扣減數量） |
| MATERIAL_REJECT | 駁回材料申請 |
| ACCOUNT_CREATE | 新增帳戶 |
| ACCOUNT_UPDATE | 修改帳戶資訊（名稱/發薪方式/密碼） |
| ACCOUNT_DELETE | 連帶刪除帳戶 |
| ACCOUNT_DEACTIVATE | 停用帳戶（保留資料） |
| ACCOUNT_REACTIVATE | 重新啟用停用帳戶 |
| PASSWORD_CHANGE | 使用者自行修改密碼 |
| SYSTEM_CONFIG | 修改系統設定（保留金費率 / 稅務支出費率） |
| RETENTION_RESET | ADMIN 重置帳戶累積保留金為 0 |
| RETENTION_SET | ADMIN 設定帳戶累積保留金為指定值 |

變動紀錄不可被任何人刪除或修改。

---

### 4.9 頁面 8：Salary 頁面 (Salary Page)

- **存取權限**: 僅 ADMIN
- 頁面佈局：左欄（條件輸入）可獨立捲動（CSS sticky + overflow-y:auto），右欄（計算結果）正常隨頁面捲動

#### 操作流程

1. 點擊快速日期按鈕（10號發薪 / 25號發薪），或手動填入自訂日期範圍
2. 點擊「**計算**」（位於快速日期按鈕下方、日期輸入上方）
3. 若已有計算結果，點擊「匯出 Excel」或「匯出 PDF」
4. 在「本次計薪扣除勞健保」表格中勾選本次要扣除勞健保的帳戶（支援「全選」按鈕）
5. 填入各工項計薪單價（預設帶入系統預設單價）

**快速日期規則：**

| 按鈕 | 起始日期 | 結束日期 |
|------|---------|---------|
| 10號發薪 | 上個月 21 日 | 本月 5 日 |
| 25號發薪 | 本月 6 日 | 本月 20 日 |

#### 計算邏輯（僅計算已確認回報）

```
計薪小計（稅前）   = Σ 已確認只數 × 工項單價
本期保留金（扣除） = 直總/間接 8 欄位只數合計 × 保留金費率
勞健保扣除        = 已投保（insurance_deduction > 0）且 ADMIN 本次勾選者，扣除其固定金額
稅務支出（扣除）  = 未投保（insurance_deduction == 0）者，= round(計薪小計 × tax_rate / 100)
本期實領金額      = 計薪小計 − 本期保留金 − 勞健保扣除 − 稅務支出
```

> 勞健保與稅務支出**互斥**：已投保者扣勞健保，未投保者扣稅務支出。

#### 保留金機制

- 適用欄位：`direct_13`, `direct_20`, `direct_25`, `direct_40`, `indirect_13`, `indirect_20`, `indirect_25`, `indirect_40`（8 欄位）
- 費率：儲存於 `SystemConfig(key='retention_rate')`，預設 20 NTD/只
- YTD 保留金 = 今年已確認回報累積計算值 + `User.retention_offset`（ADMIN 手動調整量），結果最小為 0

#### 稅務支出機制

- 條件：`User.insurance_deduction == 0`（未在公司投保）
- 計算：`round(計薪小計 × tax_rate / 100)`（整數，四捨五入）
- 費率：儲存於 `SystemConfig(key='tax_rate')`，預設 3%

#### 薪資發放方式

| 項目 | 說明 |
|------|------|
| 轉帳薪資總額 | 所有「轉帳」帳戶實領金額加總 |
| 提現薪資總額 | 所有「領現」帳戶實領金額加總 |
| 提現面額配置 | 最少張數拆解：1000/500/100/50/10/5/1 NTD |

#### 匯出內容

Excel 與 PDF 均包含：每位帳戶的姓名、發薪方式、工項明細、計薪小計、保留金扣除、勞健保扣除、稅務支出、實領金額；領現帳戶另附個人面額配置；末尾發放總覽含轉帳/提現分拆、勞健保合計、稅務支出合計、合計面額配置。

---

### 4.10 頁面 9：個人統計頁面 (Personal Statistics Page)

- **存取權限**: USER 及 ADMIN

#### 功能一：工項總和查詢

- 篩選：日期範圍 + 確認狀態（全部/已確認/未確認）
- 顯示：各工項只數加總、本期保留金小計

#### 功能二：薪資試算（僅計算已確認回報）

- 填入各工項單價（預設帶入系統預設單價）
- 可選擇是否本次扣除勞健保（若已投保）
- 顯示：計薪小計 → 保留金扣除 → 勞健保扣除（若已投保且勾選）→ 稅務支出（若未投保）→ **試算實領金額**

#### 今年度累積保留金

頁面頂端固定顯示當年（1/1 至今）已確認回報累積保留金（含 `retention_offset` 調整）。

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
| 材料頁面 | 申請 / 取消 / 新增 / 調整 / 刪除 | Modal 內或 `onsubmit confirm()` |
| 設定頁面 | 密碼 / 帳戶操作 / 費率 / 保留金 | `onsubmit confirm()` 或 Modal 內確認 |

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
| insurance_deduction | INTEGER, NOT NULL, DEFAULT 0 | 每期勞健保固定扣除額（NTD）；0 = 未投保 |
| retention_offset | INTEGER, NOT NULL, DEFAULT 0 | ADMIN 手動調整 YTD 保留金的偏移量（可為負值） |
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

| 欄位 | 類型 | 說明 |
|------|------|------|
| id | PK | 主鍵 |
| name | VARCHAR(100), NOT NULL | 材料名稱 |
| unit | VARCHAR(20), NOT NULL | 單位（個/箱/公尺等） |
| remaining_quantity | INTEGER, DEFAULT 0 | 剩餘數量 |
| sort_order | INTEGER, NOT NULL, DEFAULT 0 | 顯示排序（ADMIN 可手動調整） |
| created_at | TIMESTAMP | 建立時間 |
| updated_at | TIMESTAMP | 最後修改時間 |

### 7.4 MaterialRequests 表

| 欄位 | 類型 | 說明 |
|------|------|------|
| id | PK | 主鍵 |
| user_id | FK → users | 申請人 |
| material_id | FK → materials | 材料 |
| requested_quantity | INTEGER | 申請數量 |
| status | VARCHAR | PENDING / APPROVED / REJECTED |
| reviewed_by | FK → users, nullable | 審核者 |
| reviewed_at | TIMESTAMP, nullable | 審核時間 |
| created_at | TIMESTAMP | 申請時間 |

### 7.5 SystemConfig 表

| 欄位 | 類型 | 說明 |
|------|------|------|
| key | VARCHAR(50), PK | 設定鍵值 |
| value | VARCHAR(200), NOT NULL | 設定值（字串） |

目前使用的 key：

| key | 預設值 | 說明 |
|-----|--------|------|
| `retention_rate` | `'20'` | 保留金費率（NTD/只） |
| `tax_rate` | `'3'` | 稅務支出費率（%） |

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
| BR-17 | YTD 保留金 = 計算值 + retention_offset；顯示值最小為 0 |
| BR-18 | 實領金額 = 計薪小計 − 本期保留金 − 勞健保扣除 − 稅務支出 |
| BR-19 | 發薪方式（領現/轉帳）為帳戶屬性，ADMIN 可在設定頁面修改 |
| BR-20 | Salary 計算後自動提示轉帳總額、提現總額及最少張數的面額配置 |
| BR-21 | 已投保（insurance_deduction > 0）的帳戶：ADMIN 可在計薪時個別勾選是否本次扣除勞健保 |
| BR-22 | 未投保（insurance_deduction == 0）的帳戶：計薪時自動扣除稅務支出（tax_rate %），四捨五入整數 |
| BR-23 | 勞健保與稅務支出互斥：同一帳戶同一次計薪不會同時扣兩項 |
| BR-24 | USER 不能刪除已確認的回報；只有 ADMIN 可刪除已確認的回報 |
| BR-25 | USER 可取消自己「待審核（PENDING）」狀態的材料申請 |
| BR-26 | 確認頁面的待確認回報依 report_date ASC 排列；待審核申請依 created_at ASC 排列 |
| BR-27 | 材料的顯示順序由 sort_order 決定，ADMIN 可透過 ↑↓ 按鈕手動調整 |
| BR-28 | ADMIN 可對任一帳戶重置今年累積保留金為 0，或設定為任意值（透過 retention_offset 實現） |
| BR-29 | ADMIN 可重新啟用已停用的帳戶 |

---

## 9. 測試資料 (Seed Data)

執行 `python seed.py` 建立初始測試資料（重複執行會清空並重建資料庫）：

**帳戶（共 20 位）：**

| 角色 | 帳戶名稱 | 密碼 |
|------|---------|------|
| ADMIN × 5 | 張總管、王主任、李副理、陳組長、林督導 | admin123 |
| USER × 15 | 陳小明、李小華、黃大勇、張美玲、吳志偉 等 | user123 |

各帳戶依設定有不同的 `payment_method`（CASH/TRANSFER）與 `insurance_deduction`（0 或 800/1200）。

**其他種子資料：**

| 項目 | 數量 / 範圍 |
|------|------------|
| 回報紀錄 | 約 1,800 筆（2026-02-01 至今，週一～六，75% 機率，65% 已確認） |
| 材料種類 | 10 種（水管接頭、PVC管材、防水膠帶 等） |
| 材料申請 | 50 筆（PENDING/APPROVED/REJECTED 加權分布） |
| SystemConfig | `retention_rate='20'`、`tax_rate='3'` |

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
DATABASE_URL = postgresql://postgres:%40YourPassword%40@aws-1-ap-southeast-2.pooler.supabase.com:6543/postgres
SECRET_KEY   = (隨機字串，建議 openssl rand -hex 32)
```

> 注意：密碼中的 `@` 必須 URL encode 為 `%40`。Supabase 請使用 Connection Pooler（port **6543**，Transaction mode），避免 IPv6 連線問題。

### 本地開發

```bash
python seed.py   # 建立測試資料（首次或重置時使用）
python app.py    # 啟動開發伺服器，port 5000
```

### 資料庫自動遷移（_init_db）

啟動時 `_init_db()` 自動執行下列 idempotent 操作：
1. `db.create_all()`（建立所有未存在的表）
2. `ALTER TABLE users ADD COLUMN insurance_deduction ...`（若欄位不存在）
3. `ALTER TABLE users ADD COLUMN retention_offset ...`（若欄位不存在）
4. `ALTER TABLE materials ADD COLUMN sort_order ...`（若欄位不存在）
5. `UPDATE materials SET sort_order = id WHERE sort_order = 0`（初始化排序值）
6. 種入預設 `SystemConfig`（`retention_rate`、`tax_rate`）；若 `tax_rate` 仍為舊預設值 `'5'`，自動更新為 `'3'`

---

*— 文件結束 —*
