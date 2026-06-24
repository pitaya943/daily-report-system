# 員工日報回報系統 — 系統規格書 (System Specification)

> **版本**: v0.3
> **日期**: 2026-06-24
> **狀態**: 已實作（反映當前實際運作的系統狀態）

---

## 變更紀錄 (Changelog)

| 版本 | 日期 | 變更內容 |
|------|------|----------|
| v0.1 | 2026-06-24 | 初稿 |
| v0.2 | 2026-06-24 | 依據 Q1–Q10 回覆更新全文；新增「頁面 9：個人統計頁面」；材料新增「單位」欄位；Salary 增加 PDF/Excel 匯出；帳戶刪除改為可選保留或連帶刪除；ADMIN 於歷史紀錄頁面可修改/刪除回報 |
| v0.3 | 2026-06-24 | **帳戶識別方式變更**：移除 `username` 欄位，改以 `display_name`（允許中文）作為唯一識別；**登入方式變更**：帳號改為下拉選單選取顯示名稱；**全面防呆機制**：所有異動操作加入二次確認對話框；**技術實作**：確定技術棧並補充系統架構；更新 Users 資料模型 |

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
| 資料庫 | SQLite（本地端檔案） |
| 認證 | Flask-Login（Session-based，remember=True） |
| 密碼雜湊 | Werkzeug（bcrypt 級別） |
| 前端 UI | Bootstrap 5.3（CDN） + Bootstrap Icons |
| Excel 匯出 | openpyxl |
| PDF 匯出 | reportlab（中文字型：Microsoft JhengHei / SimSun） |
| 執行環境 | Windows（本地端，port 5000） |

---

## 3. 角色定義 (Roles)

| 角色 | 代碼 | 說明 |
|------|------|------|
| 管理者 | ADMIN | 可存取所有頁面（含 ADMIN 專屬頁面），亦可填寫回報 |
| 一般使用者 | USER | 填報每日工項數量、查看自身紀錄、申請材料領取、試算個人薪資 |

---

## 4. 頁面與功能規格 (Page Specifications)

### 4.1 登入頁面 (Login Page)

- **存取權限**: 所有未登入者
- **欄位**:
  - **姓名下拉選單**（顯示所有 `is_active = true` 的帳戶 `display_name`，含中文）
  - 密碼輸入框（含顯示/隱藏切換）
- **行為**:
  - 選取姓名後自動聚焦至密碼欄位，並於頂部顯示對應姓名頭字母的頭像圓圈
  - 登入成功後依角色導向對應首頁（USER → 回報頁面；ADMIN → Summary 頁面）
  - 登入失敗顯示錯誤訊息
  - 系統維持登入 Session（`remember=True`）

> **v0.3 變更**：帳號欄位由文字輸入改為下拉選單，以 `display_name` 識別使用者。

---

### 4.2 頁面 1：回報頁面 (Daily Report Page)

- **存取權限**: USER 及 ADMIN

#### 4.2.1 表單欄位

所有數值欄位單位皆為 **「只」**，預設值為 **0**，僅允許輸入 **非負整數**。

| 欄位名稱 | 欄位 Key | 類型 | 預設值 |
|----------|----------|------|--------|
| 日期 | `date` | Date | 當天日期（可自行調整） |
| 直總-13 | `direct_13` | Integer ≥ 0 | 0 |
| 直總-20 | `direct_20` | Integer ≥ 0 | 0 |
| 直總-25 | `direct_25` | Integer ≥ 0 | 0 |
| 直總-40 | `direct_40` | Integer ≥ 0 | 0 |
| 間接-13 | `indirect_13` | Integer ≥ 0 | 0 |
| 間接-20 | `indirect_20` | Integer ≥ 0 | 0 |
| 間接-25 | `indirect_25` | Integer ≥ 0 | 0 |
| 間接-40 | `indirect_40` | Integer ≥ 0 | 0 |
| 直總—整組、拆泥、換由令(含表) | `direct_special_group` | Integer ≥ 0 | 0 |
| 間接—拆泥、換由令(含表) | `indirect_special_group` | Integer ≥ 0 | 0 |
| 大改小(不含表) | `downsize` | Integer ≥ 0 | 0 |
| 原大改小(不含表) | `original_downsize` | Integer ≥ 0 | 0 |
| 特殊 | `special` | Integer ≥ 0 | 0 |
| 動員 | `mobilization` | Integer ≥ 0 | 0 |
| 複查案 | `recheck` | Integer ≥ 0 | 0 |
| 清土 | `soil_clearing` | Integer ≥ 0 | 0 |

> 共 **16 個數值欄位 + 1 個日期欄位**。
> 同一帳戶同一日期 **允許送出多筆回報**（不設 UNIQUE constraint on user_id + date）。

#### 4.2.2 送出前二次確認 (Confirmation Dialog)

點擊「送出」後彈出確認框，內容包含：

1. **逐欄顯示**：列出所有已輸入的欄位名稱與對應只數
2. **小計計算**：
   - **A** = 直總-13 + 直總-20 + 直總-25 + 直總-40
   - **B** = 間接-13 + 間接-20 + 間接-25 + 間接-40
   - **C** = 直總—整組、拆泥、換由令(含表)
   - **D** = 間接—拆泥、換由令(含表)
   - **合計** = A + B + C + D
3. 使用者可選擇「確認送出」或「返回修改」

#### 4.2.3 送出後行為

- 資料寫入資料庫，回報狀態預設為 **「尚未確認」**（待 ADMIN 於確認頁面手動確認）
- 產生一筆變動紀錄 (Audit Log)

---

### 4.3 頁面 2：歷史紀錄頁面 (History Page)

- **存取權限**: USER 及 ADMIN

#### USER 視角

- 僅顯示 **自己** 已送出的回報紀錄
- 篩選條件：日期範圍（起始日 ~ 結束日）
- 操作：
  - **修改**：開啟 Modal 編輯各工項數值，儲存前有二次確認對話框
  - **刪除**：有二次確認對話框（顯示日期與回報編號）
- **修改/刪除後行為**：
  - 若該筆回報原本為「已確認」，修改後狀態自動重置為 **「尚未確認」**，需 ADMIN 重新確認
  - 產生變動紀錄

#### ADMIN 視角

- 顯示 **所有帳戶**（USER 及 ADMIN）已送出的回報紀錄
- 篩選條件：帳戶（下拉選單）、日期範圍
- 操作同 USER，且操作皆產生變動紀錄

#### 顯示欄位

帳戶名稱（`display_name`）、日期、16 個工項欄位數值、確認狀態

---

### 4.4 頁面 3：設定頁面 (Settings Page)

- **存取權限**: USER 及 ADMIN

#### USER 功能

- 修改自己的密碼（需輸入舊密碼 + 新密碼 + 確認新密碼）
- 送出前有二次確認對話框

#### ADMIN 功能

- 檢視所有帳戶列表（顯示帳戶名稱、角色、狀態、建立時間）
- **新增帳戶**：填入帳戶名稱（`display_name`）、密碼、帳戶類型（USER/ADMIN）；送出前有二次確認
- **修改顯示名稱**：修改任一帳戶的 `display_name`；送出前有二次確認
- **重設密碼**：ADMIN 直接設定新密碼，無需舊密碼；送出前有二次確認
- **刪除帳戶**：
  - 選項 (a) **保留歷史資料**：僅將帳戶設為 `is_active = false`，登入下拉選單不再顯示，資料保留
  - 選項 (b) **連帶刪除**：刪除帳戶及其所有回報、材料申請紀錄
  - 無論何者，Audit Log 中的歷史紀錄永久保留
  - 送出前有二次確認對話框（Modal 內再加 JS confirm）
- 所有帳戶管理操作皆產生變動紀錄

> **v0.3 變更**：帳戶無獨立 `username` 欄位，僅以 `display_name` 作為人類識別碼；系統內部以 `id` 為主鍵，`username` 作為唯讀 Python property（返回 `uid_{id}`）供程式碼相容使用。

---

### 4.5 頁面 4：剩餘材料頁面 (Remaining Materials Page)

- **存取權限**: USER 及 ADMIN

#### 資料模型：材料 (Material)

| 欄位 | 說明 |
|------|------|
| 材料名稱 | 由 ADMIN 建立 |
| 單位 | 由 ADMIN 於新增材料時手動填入（如「個」「箱」「包」「公斤」等） |
| 剩餘數量 | 目前剩餘數量；≤ 5 顯示紅色，≤ 20 顯示橘色 |

#### USER 功能

- 查看所有材料的名稱、單位、剩餘數量
- **申請領取**：點擊「申請」開啟 Modal，填入數量後送出；送出前有二次確認
- **申請紀錄**：頁面底部顯示自己所有申請紀錄（材料名稱、數量、時間、狀態）

#### ADMIN 功能

- 查看所有材料
- **新增材料**：填入名稱、單位、初始數量（Modal）；送出前有二次確認
- **調整數量**：修改任一材料的剩餘數量（Modal）；送出前有二次確認
- 所有操作皆產生變動紀錄

---

### 4.6 頁面 5：Summary 頁面 (Summary Page)

- **存取權限**: 僅 ADMIN

#### 篩選條件

| 條件 | 說明 |
|------|------|
| 日期範圍 | 起始日 ~ 結束日（必填） |
| 帳戶 | 特定帳戶或「全部」 |
| 確認狀態 | 全部 / 僅已確認 / 僅未確認 |

#### 顯示方式

表格呈現，每列為一位帳戶（顯示 `display_name`），各欄為工項總數；最後一列為所有帳戶的合計列（`table-success` 樣式）。

---

### 4.7 頁面 6：確認頁面 (Confirmation Page)

- **存取權限**: 僅 ADMIN

#### 功能一：回報確認

- 列出所有 **尚未確認** 的回報（帳戶名稱、日期、16 個工項數值）
- ADMIN 逐筆點擊「確認」，送出前有 JS 二次確認對話框（含回報日期與編號）
- 確認操作產生變動紀錄

#### 功能二：材料申請審核

- 列出所有 **待審核** 的材料申請（申請者、材料、數量、申請時間）
- 「核准」送出前有二次確認對話框（含申請編號與扣庫存提示）
- 「駁回」送出前有二次確認對話框（含申請編號）
- 核准後系統自動扣減該材料的剩餘數量
- 所有操作產生變動紀錄

---

### 4.8 頁面 7：變動紀錄頁面 (Audit Log Page)

- **存取權限**: USER 及 ADMIN

#### 每筆紀錄欄位

| 欄位 | 說明 |
|------|------|
| 時間戳記 | 操作發生的精確時間 |
| 操作者 | 執行操作的帳戶 `display_name` |
| 操作類型 | 見下方列舉 |
| 操作描述 | 具體描述變動內容 |

#### action_type 列舉值

| 值 | 說明 |
|----|------|
| REPORT_CREATE | 新增回報 |
| REPORT_UPDATE | 修改回報（含修改前後數值） |
| REPORT_DELETE | 刪除回報 |
| REPORT_CONFIRM | ADMIN 確認回報 |
| REPORT_UNCONFIRM | 因修改導致確認狀態重置 |
| MATERIAL_ADD | ADMIN 新增材料 |
| MATERIAL_UPDATE | ADMIN 調整材料數量 |
| MATERIAL_REQUEST | USER 提出材料申請 |
| MATERIAL_APPROVE | ADMIN 核准材料申請（含扣減數量） |
| MATERIAL_REJECT | ADMIN 駁回材料申請 |
| ACCOUNT_CREATE | 新增帳戶 |
| ACCOUNT_DELETE | 連帶刪除帳戶 |
| ACCOUNT_DEACTIVATE | 停用帳戶（保留資料的刪除方式） |
| PASSWORD_CHANGE | 修改密碼（僅記錄誰改了誰，不記錄密碼內容） |

#### 視角差異

- **USER**：僅顯示自己的變動紀錄
- **ADMIN**：顯示所有帳戶的完整變動紀錄

#### 不可刪除性

變動紀錄為永久保存，任何人（含 ADMIN）皆不可刪除或修改。

---

### 4.9 頁面 8：Salary 頁面 (Salary Page)

- **存取權限**: 僅 ADMIN

#### 操作流程

1. 選定計薪日期範圍（起始日 ~ 結束日）
2. 在各工項欄位填入每只的計薪單價（NTD，允許 0 與最多 2 位小數）
3. 點擊「計算薪資」
4. 頁面顯示薪資明細表格
5. 可選擇匯出 PDF 或 Excel (.xlsx)

#### 計算邏輯

**僅計算 `is_confirmed = true`（已確認）的回報紀錄。**

```
帳戶薪資總額 = Σ_{field ∈ 16_fields} ( 已確認回報只數加總 × 該 field 單價 )
```

#### 輸出內容

- 日期範圍與各工項單價設定
- 每位帳戶（顯示 `display_name`）：各工項只數加總、各工項小計（只數 × 單價）、薪資總額
- 所有帳戶薪資總合計

#### 匯出格式

| 格式 | 說明 |
|------|------|
| 頁面表格 | 直接在頁面上以 Bootstrap 表格呈現 |
| PDF | 使用 reportlab 產生，支援中文（Windows 字型） |
| Excel | 使用 openpyxl 產生 .xlsx 檔案 |

---

### 4.10 頁面 9：個人統計頁面 (Personal Statistics Page)

- **存取權限**: 僅 USER

#### 功能一：工項總和查詢

- 篩選條件：日期範圍 + 確認狀態（全部 / 僅已確認 / 僅未確認）
- 顯示：各工項欄位的只數加總表格

#### 功能二：薪資試算

- 操作：選定日期範圍，填入各工項單價，點擊「試算薪資」
- 計算邏輯：僅計算自己已確認的回報
- 顯示：各工項只數、單價、小計、薪資總額

> **免責聲明**：此頁面薪資試算結果僅供個人參考，正式薪資以 ADMIN 在 Salary 頁面計算的結果為準。頁面上需標註此聲明文字。

---

## 5. 側邊欄 / 導覽列 (Navigation)

登入後顯示固定側邊欄（左側，深藍色），右上角顯示當前 `display_name` 與角色標籤（ADMIN 紅色、USER 藍色）及登出按鈕。

| 頁面 | USER | ADMIN |
|------|------|-------|
| 回報頁面 | ✅ | ✅ |
| 歷史紀錄 | ✅ | ✅ |
| 剩餘材料 | ✅ | ✅ |
| 變動紀錄 | ✅ | ✅ |
| 設定 | ✅ | ✅ |
| 個人統計 | ✅ | ❌ |
| Summary | ❌ | ✅ |
| 確認 | ❌ | ✅ |
| Salary | ❌ | ✅ |

---

## 6. 防呆機制 (Confirmation Guards)

> **v0.3 新增**：所有會異動資料的操作均設有二次確認，防止誤操作。

| 頁面 | 操作 | 確認方式 |
|------|------|----------|
| 回報頁面 | 送出回報 | Bootstrap Modal（顯示各工項數值小計） |
| 歷史紀錄 | 儲存修改 | Modal 內 `onsubmit confirm()` |
| 歷史紀錄 | 刪除回報 | JS `confirm()`（含回報日期與編號） |
| 確認頁面 | 確認回報 | `onsubmit confirm()`（含回報日期與編號） |
| 確認頁面 | 核准申請 | `onsubmit confirm()`（含扣庫存提示） |
| 確認頁面 | 駁回申請 | `onsubmit confirm()` |
| 材料頁面 | 送出申請 | Modal 內 `onsubmit confirm()` |
| 材料頁面 | 新增材料 | Modal 內 `onsubmit confirm()` |
| 材料頁面 | 調整庫存 | Modal 內 `onsubmit confirm()` |
| 設定頁面 | 更新密碼 | `onsubmit confirm()` |
| 設定頁面 | 建立帳戶 | Modal 內 `onsubmit confirm()` |
| 設定頁面 | 修改名稱 | Modal 內 `onsubmit confirm()` |
| 設定頁面 | 重設密碼 | Modal 內 `onsubmit confirm()` |
| 設定頁面 | 刪除帳戶 | Modal 內再加 `onsubmit confirm()` |

---

## 7. 資料模型 (Data Model)

### 7.1 Users 表

| 欄位 | 類型 | 說明 |
|------|------|------|
| id | PK, Auto Increment | 主鍵，系統內部識別碼 |
| display_name | VARCHAR(50), UNIQUE, NOT NULL | 帳戶顯示名稱（允許中文，唯一，用於登入下拉與所有 UI 顯示） |
| password_hash | VARCHAR(256), NOT NULL | 密碼雜湊（Werkzeug，bcrypt 級別） |
| role | VARCHAR(10), NOT NULL | 'ADMIN' 或 'USER' |
| is_active | BOOLEAN, DEFAULT true | 帳戶是否啟用；false 時不出現於登入下拉，但歷史資料保留 |
| created_at | TIMESTAMP | 建立時間 |
| updated_at | TIMESTAMP | 最後修改時間 |

> **`username` 欄位說明（v0.3）**：資料庫中不儲存 `username`，改為 Python `@property`，返回 `f"uid_{self.id}"`（如 `uid_1`），供程式碼相容使用。所有 UI 顯示一律使用 `display_name`。

### 7.2 Reports 表（回報紀錄）

| 欄位 | 類型 | 說明 |
|------|------|------|
| id | PK, Auto Increment | 主鍵 |
| user_id | FK → Users.id | 回報者 |
| report_date | DATE, NOT NULL | 回報日期 |
| direct_13 | INTEGER, DEFAULT 0, ≥ 0 | 直總-13 |
| direct_20 | INTEGER, DEFAULT 0, ≥ 0 | 直總-20 |
| direct_25 | INTEGER, DEFAULT 0, ≥ 0 | 直總-25 |
| direct_40 | INTEGER, DEFAULT 0, ≥ 0 | 直總-40 |
| indirect_13 | INTEGER, DEFAULT 0, ≥ 0 | 間接-13 |
| indirect_20 | INTEGER, DEFAULT 0, ≥ 0 | 間接-20 |
| indirect_25 | INTEGER, DEFAULT 0, ≥ 0 | 間接-25 |
| indirect_40 | INTEGER, DEFAULT 0, ≥ 0 | 間接-40 |
| direct_special_group | INTEGER, DEFAULT 0, ≥ 0 | 直總—整組、拆泥、換由令(含表) |
| indirect_special_group | INTEGER, DEFAULT 0, ≥ 0 | 間接—拆泥、換由令(含表) |
| downsize | INTEGER, DEFAULT 0, ≥ 0 | 大改小(不含表) |
| original_downsize | INTEGER, DEFAULT 0, ≥ 0 | 原大改小(不含表) |
| special | INTEGER, DEFAULT 0, ≥ 0 | 特殊 |
| mobilization | INTEGER, DEFAULT 0, ≥ 0 | 動員 |
| recheck | INTEGER, DEFAULT 0, ≥ 0 | 複查案 |
| soil_clearing | INTEGER, DEFAULT 0, ≥ 0 | 清土 |
| is_confirmed | BOOLEAN, DEFAULT false | 是否已確認 |
| confirmed_by | FK → Users.id, NULLABLE | 確認者 |
| confirmed_at | TIMESTAMP, NULLABLE | 確認時間 |
| created_at | TIMESTAMP | 建立時間 |
| updated_at | TIMESTAMP | 最後修改時間 |

> **無 UNIQUE(user_id, report_date) 限制**：同一帳戶同一日期允許多筆回報。

### 7.3 Materials 表（材料）

| 欄位 | 類型 | 說明 |
|------|------|------|
| id | PK, Auto Increment | 主鍵 |
| name | VARCHAR(100), NOT NULL | 材料名稱 |
| unit | VARCHAR(20), NOT NULL | 單位（如「個」「箱」「公斤」，由 ADMIN 新增時手動填入） |
| remaining_quantity | INTEGER, ≥ 0 | 剩餘數量 |
| created_at | TIMESTAMP | 建立時間 |
| updated_at | TIMESTAMP | 最後修改時間 |

### 7.4 MaterialRequests 表（材料申請）

| 欄位 | 類型 | 說明 |
|------|------|------|
| id | PK, Auto Increment | 主鍵 |
| user_id | FK → Users.id | 申請者 |
| material_id | FK → Materials.id | 申請的材料 |
| requested_quantity | INTEGER, > 0 | 申請數量 |
| status | VARCHAR(10), DEFAULT 'PENDING' | PENDING / APPROVED / REJECTED |
| reviewed_by | FK → Users.id, NULLABLE | 審核者 |
| reviewed_at | TIMESTAMP, NULLABLE | 審核時間 |
| created_at | TIMESTAMP | 申請時間 |

### 7.5 AuditLogs 表（變動紀錄）

| 欄位 | 類型 | 說明 |
|------|------|------|
| id | PK, Auto Increment | 主鍵 |
| user_id | FK → Users.id | 操作者 |
| action_type | VARCHAR(50), NOT NULL | 操作類型（見 4.8 節） |
| description | TEXT, NOT NULL | 操作描述（含具體數值變動） |
| created_at | TIMESTAMP | 操作時間（不可修改） |

> AuditLogs 表不可被任何人刪除或修改（系統層級保護）。

---

## 8. 業務規則摘要 (Business Rules)

| 編號 | 規則 |
|------|------|
| BR-01 | 同一帳戶同一日期可送出多筆回報 |
| BR-02 | 所有回報新增後預設為「尚未確認」 |
| BR-03 | 已確認的回報被修改後，確認狀態自動重置為「尚未確認」，需 ADMIN 重新確認 |
| BR-04 | Salary 頁面計算僅納入 `is_confirmed = true` 的回報 |
| BR-05 | Summary 頁面的確認狀態篩選由 ADMIN 自行選擇 |
| BR-06 | 材料申請核准後，系統自動扣減該材料的剩餘數量 |
| BR-07 | 帳戶刪除時，ADMIN 可選擇保留歷史資料（停用帳戶）或連帶刪除回報與申請紀錄 |
| BR-08 | 變動紀錄不可被任何人刪除或修改 |
| BR-09 | 個人統計頁面的薪資試算僅為參考，正式薪資以 ADMIN Salary 頁面為準 |
| BR-10 | USER 個人統計頁面的薪資試算僅計算已確認的回報 |
| BR-11 | ADMIN 亦可填寫回報，其回報納入 Salary 與 Summary 計算 |
| BR-12 | 所有異動操作（新增、修改、刪除、確認、核准、駁回）均設有二次確認防呆機制 |
| BR-13 | 帳戶識別以 `display_name` 為準（允許中文），系統內部以 `id` 為主鍵 |
| BR-14 | 停用帳戶（`is_active = false`）不出現於登入下拉選單，但歷史資料與 Audit Log 保留 |

---

## 9. 測試資料 (Seed Data)

執行 `python seed.py` 建立初始測試資料：

| 帳戶名稱 | 密碼 | 角色 |
|---------|------|------|
| 張管理員 | admin123 | ADMIN |
| 陳小明 | user123 | USER |
| 李小華 | user123 | USER |

Seed 資料包含：30 筆回報（跨 3 帳戶、近 30 天，約 65% 已確認）、6 種材料、15 筆材料申請。

> **注意**：重複執行 `python seed.py` 會清空並重建資料庫。

---

*— 文件結束 —*
