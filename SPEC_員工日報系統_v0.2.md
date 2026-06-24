# 員工日報回報系統 — 系統規格書 (System Specification)

> **版本**: v0.2
> **日期**: 2026-06-24
> **狀態**: 待審核（依據 Q1–Q10 回覆及新增需求更新）

---

## 變更紀錄 (Changelog)

| 版本 | 日期 | 變更內容 |
|------|------|----------|
| v0.1 | 2026-06-24 | 初稿 |
| v0.2 | 2026-06-24 | 依據 Q1–Q10 回覆更新全文；新增「頁面 9：個人統計頁面」供 USER 試算薪資與查看工項總和；回報頁面開放 ADMIN；材料新增「單位」欄位；Salary 輸出增加 PDF/Excel 匯出；帳戶刪除改為 ADMIN 可選保留或連帶刪除；ADMIN 於歷史紀錄頁面可修改/刪除回報 |

---

## 1. 系統概述 (System Overview)

本系統為一 Web-based 員工日報回報管理系統，供員工（及管理者）每日回報各類工項數量，並由管理者進行確認、統計、薪資計算等管理作業。

---

## 2. 角色定義 (Roles)

| 角色 | 代碼 | 說明 |
|------|------|------|
| 管理者 | ADMIN | 可存取所有頁面（含 ADMIN 專屬頁面），亦可填寫回報 |
| 一般使用者 | USER | 填報每日工項數量、查看自身紀錄、申請材料領取、試算個人薪資 |

---

## 3. 頁面與功能規格 (Page Specifications)

### 3.1 登入頁面 (Login Page)

- **存取權限**: 所有未登入者
- **欄位**:
  - 帳號 (username)
  - 密碼 (password)
- **行為**:
  - 登入成功後依角色導向對應首頁（USER → 回報頁面；ADMIN → Summary 頁面）
  - 登入失敗顯示錯誤訊息
  - 系統需維持登入 Session

---

### 3.2 頁面 1：回報頁面 (Daily Report Page)

- **存取權限**: USER 及 ADMIN

#### 3.2.1 表單欄位

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
> 同一帳戶同一日期 **允許送出多筆回報**（不設 unique constraint on user_id + date）。

#### 3.2.2 送出前二次確認 (Confirmation Dialog)

點擊「送出」後彈出確認框，內容包含：

1. **逐欄顯示**：列出所有已輸入的欄位名稱與對應只數
2. **小計計算**：
   - **A** = 直總-13 + 直總-20 + 直總-25 + 直總-40
   - **B** = 間接-13 + 間接-20 + 間接-25 + 間接-40
   - **C** = 直總—整組、拆泥、換由令(含表)
   - **D** = 間接—拆泥、換由令(含表)
   - **合計** = A + B + C + D
3. 使用者可選擇「確認送出」或「返回修改」

#### 3.2.3 送出後行為

- 資料寫入資料庫，回報狀態預設為 **「尚未確認」**（待 ADMIN 於確認頁面手動確認）
- 產生一筆變動紀錄 (Audit Log)

---

### 3.3 頁面 2：歷史紀錄頁面 (History Page)

- **存取權限**: USER 及 ADMIN

#### USER 視角

- 僅顯示 **自己** 已送出的回報紀錄
- 篩選條件：日期範圍（起始日 ~ 結束日）
- 操作：
  - **修改**：可編輯任一筆自身回報的數值欄位
  - **刪除**：可刪除任一筆自身回報
- **修改/刪除後行為**：
  - 若該筆回報原本為「已確認」，修改後狀態自動重置為 **「尚未確認」**，需 ADMIN 重新確認
  - 產生變動紀錄，記錄修改前後的數值差異

#### ADMIN 視角

- 顯示 **所有帳戶**（USER 及 ADMIN）已送出的回報紀錄
- 篩選條件：
  - 帳戶（下拉選單或多選）
  - 日期範圍（起始日 ~ 結束日）
- 操作：
  - **修改**：可編輯任一筆回報的數值欄位（同 USER 修改規則：已確認的回報修改後重置為「尚未確認」）
  - **刪除**：可刪除任一筆回報
  - 所有操作皆產生變動紀錄

#### 顯示欄位

每筆紀錄至少顯示：帳戶名稱、日期、所有 16 個工項欄位的數值、確認狀態（尚未確認 / 已確認）

---

### 3.4 頁面 3：設定頁面 (Settings Page)

- **存取權限**: USER 及 ADMIN

#### USER 功能

- 修改自己的密碼（需輸入舊密碼 + 新密碼 + 確認新密碼）

#### ADMIN 功能

- 檢視所有帳戶列表（USER 及 ADMIN），顯示帳號、角色、建立時間
- **新增帳戶**：可建立 USER 或 ADMIN 帳戶（需填入帳號、密碼、角色）
- **刪除帳戶**：可刪除任意 USER 或 ADMIN 帳戶
  - 刪除時 ADMIN 可選擇：
    - **(a) 保留歷史資料**：僅停用帳戶登入功能，該帳戶的回報、申請、變動紀錄全部保留
    - **(b) 連帶刪除**：刪除帳戶的同時，一併刪除該帳戶的所有回報紀錄、材料申請紀錄
  - 無論選擇何者，變動紀錄 (Audit Log) 中的歷史操作紀錄永久保留不刪除
- **修改密碼**：可重設任意帳戶的密碼（ADMIN 直接設定新密碼，無需輸入舊密碼）
- 所有帳戶管理操作皆產生變動紀錄

---

### 3.5 頁面 4：剩餘材料頁面 (Remaining Materials Page)

- **存取權限**: USER 及 ADMIN

#### 資料模型：材料 (Material)

| 欄位 | 說明 |
|------|------|
| 材料名稱 | 由 ADMIN 建立 |
| 單位 | 由 ADMIN 於新增材料時手動填入（如「個」「箱」「包」「公斤」等） |
| 剩餘數量 | 目前剩餘數量 |

#### USER 功能

- **檢視**：看到所有材料的名稱、單位、剩餘數量
- **申請領取**：對任一材料提出領取申請，須填入「申請領取數量」
- **申請紀錄**：頁面底部顯示該 USER 自己已提出的所有申請紀錄，每筆包含：
  - 材料名稱
  - 申請數量（含單位）
  - 申請時間
  - 狀態：待審核 / 已核准 / 已駁回

#### ADMIN 功能

- **檢視**：看到所有材料的名稱、單位、剩餘數量
- **新增材料**：可建立新材料，填入名稱、單位、初始數量
- **調整數量**：可修改任一材料的剩餘數量
- 所有操作皆產生變動紀錄

---

### 3.6 頁面 5：Summary 頁面 (Summary Page)

- **存取權限**: 僅 ADMIN

#### 功能

在選定的日期區間內，統計所有回報紀錄的各欄位數量總和。

#### 篩選條件

- **日期範圍**：起始日 ~ 結束日（必填）
- **帳戶**：可選擇特定帳戶或「全部」（含 ADMIN 帳戶的回報）
- **工項欄位**：可選擇特定欄位或「全部」
- **確認狀態**：可選擇「僅已確認」/「僅未確認」/「全部」（由 ADMIN 自行決定）

#### 顯示方式

以表格呈現，至少支援以下兩種檢視：

1. **依帳戶分列**：每列為一個帳戶，各欄為各工項欄位在該日期區間的加總
2. **總合計列**：所有帳戶的合併加總（置於表格底部）

---

### 3.7 頁面 6：確認頁面 (Confirmation Page)

- **存取權限**: 僅 ADMIN

#### 功能一：回報確認

- 列出所有 **尚未確認** 的回報紀錄
- 每筆顯示：帳戶名稱、回報日期、16 個工項欄位數值
- ADMIN 可逐筆點擊「確認」按鈕，將狀態從「尚未確認」改為「已確認」
- 確認操作產生變動紀錄

#### 功能二：材料申請回覆

- 列出所有 **待審核** 的材料領取申請
- 每筆顯示：申請者、材料名稱、申請數量（含單位）、申請時間
- ADMIN 可選擇「核准」或「駁回」
- 核准後系統自動扣減該材料的剩餘數量
- 操作產生變動紀錄

---

### 3.8 頁面 7：變動頁面 (Audit Log Page)

- **存取權限**: USER 及 ADMIN

#### 記錄範圍

任何會改變資料庫的行為皆產生一筆變動紀錄，包含但不限於：

- 回報新增 / 修改 / 刪除
- 回報狀態確認 / 因修改重置為尚未確認
- 材料申請提出 / 核准 / 駁回
- 材料新增 / 數量調整
- 帳戶新增 / 刪除（含選擇保留或連帶刪除資料）/ 密碼修改

#### 每筆紀錄欄位

| 欄位 | 說明 |
|------|------|
| 時間戳記 | 操作發生的精確時間 |
| 操作者 | 執行操作的帳戶名稱 |
| 操作類型 | 例：REPORT_CREATE, REPORT_UPDATE, REPORT_DELETE, REPORT_CONFIRM, MATERIAL_REQUEST, MATERIAL_APPROVE, MATERIAL_REJECT, MATERIAL_ADD, MATERIAL_UPDATE, ACCOUNT_CREATE, ACCOUNT_DELETE, PASSWORD_CHANGE |
| 操作描述 | 具體描述變動內容（例：「將 直總-13 從 5 改為 10」、「刪除 2026-06-20 的回報」） |

#### USER 視角

- 僅顯示 **自己** 的變動紀錄

#### ADMIN 視角

- 顯示 **所有帳戶**（包括其他 ADMIN）的變動紀錄

#### 不可刪除性

變動紀錄為永久保存，任何人（含 ADMIN）皆不可刪除或修改變動紀錄。

---

### 3.9 頁面 8：Salary 頁面 (Salary Page)

- **存取權限**: 僅 ADMIN

#### 操作流程

1. **選定日期範圍**：起始日 ~ 結束日
2. **填入各工項的單位計薪 (NTD)**：

   與回報頁面相同的 16 個欄位，每個欄位填入對應的單價。

   | 欄位名稱 | 填入內容 | 類型 |
   |----------|----------|------|
   | 直總-13 單價 | 每只計薪金額 | Decimal(10,2) ≥ 0 |
   | 直總-20 單價 | 每只計薪金額 | Decimal(10,2) ≥ 0 |
   | 直總-25 單價 | 每只計薪金額 | Decimal(10,2) ≥ 0 |
   | 直總-40 單價 | 每只計薪金額 | Decimal(10,2) ≥ 0 |
   | 間接-13 單價 | 每只計薪金額 | Decimal(10,2) ≥ 0 |
   | 間接-20 單價 | 每只計薪金額 | Decimal(10,2) ≥ 0 |
   | 間接-25 單價 | 每只計薪金額 | Decimal(10,2) ≥ 0 |
   | 間接-40 單價 | 每只計薪金額 | Decimal(10,2) ≥ 0 |
   | 直總—整組、拆泥、換由令(含表) 單價 | 每只計薪金額 | Decimal(10,2) ≥ 0 |
   | 間接—拆泥、換由令(含表) 單價 | 每只計薪金額 | Decimal(10,2) ≥ 0 |
   | 大改小(不含表) 單價 | 每只計薪金額 | Decimal(10,2) ≥ 0 |
   | 原大改小(不含表) 單價 | 每只計薪金額 | Decimal(10,2) ≥ 0 |
   | 特殊 單價 | 每只計薪金額 | Decimal(10,2) ≥ 0 |
   | 動員 單價 | 每只計薪金額 | Decimal(10,2) ≥ 0 |
   | 複查案 單價 | 每只計薪金額 | Decimal(10,2) ≥ 0 |
   | 清土 單價 | 每只計薪金額 | Decimal(10,2) ≥ 0 |

   > 單價允許為 0（表示該項不計薪），允許最多 2 位小數，單位為新台幣 (NTD)。

3. **計算與輸出**：所有單位計薪皆填入後，按下「輸出薪資明細」按鈕

#### 計算邏輯

**僅計算 `is_confirmed = true`（已確認）的回報紀錄。**

對該日期範圍內的每一位帳戶（USER 及有回報的 ADMIN）：

```
帳戶薪資總額 = Σ_{field ∈ 16_fields} ( 該帳戶在日期範圍內該 field 的已確認回報只數總和 × 該 field 單價 )
```

#### 輸出內容

薪資明細包含：
- 日期範圍
- 各工項的單價設定
- 每位帳戶的：
  - 各工項在該日期區間的只數加總（僅已確認）
  - 各工項的單價
  - 各工項的小計（只數 × 單價），單位 NTD
  - 該帳戶的薪資總額，單位 NTD
- 所有帳戶的薪資總合計

#### 輸出格式

薪資明細同時支援以下三種呈現方式：
1. **頁面內表格顯示**：直接在頁面上以表格呈現
2. **匯出 PDF**：可下載 PDF 檔案
3. **匯出 Excel (.xlsx)**：可下載 Excel 檔案

---

### 3.10 頁面 9：個人統計頁面 (Personal Statistics Page) 🆕

- **存取權限**: 僅 USER

#### 功能說明

USER 可在此頁面查看自己在選定日期區間內的工項加總與薪資試算，無需依賴 ADMIN。

#### 功能一：工項總和查詢

- **篩選條件**：
  - 日期範圍：起始日 ~ 結束日（必填）
  - 確認狀態：可選擇「僅已確認」/「僅未確認」/「全部」
- **顯示**：該 USER 在選定日期區間內，各工項欄位的只數加總，以表格呈現

#### 功能二：薪資試算

- **操作流程**：
  1. 選定日期範圍
  2. 填入各工項的單位計薪（與 Salary 頁面相同的 16 個欄位，Decimal(10,2) ≥ 0，單位 NTD）
  3. 按下「試算薪資」按鈕
- **計算邏輯**：
  - 僅計算 **該 USER 自己的、已確認** 的回報紀錄
  - 計算公式同 Salary 頁面
- **顯示**：
  - 各工項只數加總、單價、小計
  - 薪資總額

> **注意**：此功能為 USER 自行試算用途，不具正式效力。正式薪資以 ADMIN 於 Salary 頁面計算的結果為準。頁面上需標註此聲明文字。

---

## 4. 側邊欄 / 導覽列 (Navigation)

登入後顯示側邊欄或頂部導覽列，依角色顯示對應頁面連結：

| 頁面 | USER | ADMIN |
|------|------|-------|
| 回報頁面 | ✅ | ✅ |
| 歷史紀錄 | ✅ | ✅ |
| 設定 | ✅ | ✅ |
| 剩餘材料 | ✅ | ✅ |
| 個人統計 | ✅ | ❌ |
| Summary | ❌ | ✅ |
| 確認 | ❌ | ✅ |
| 變動紀錄 | ✅ | ✅ |
| Salary | ❌ | ✅ |

右上角顯示當前登入帳戶名稱（含角色標示）及登出按鈕。

---

## 5. 資料模型 (Data Model)

### 5.1 Users 表

| 欄位 | 類型 | 說明 |
|------|------|------|
| id | PK, Auto Increment | 主鍵 |
| username | VARCHAR, UNIQUE, NOT NULL | 帳號 |
| password_hash | VARCHAR, NOT NULL | 密碼雜湊（bcrypt 或同等強度） |
| role | ENUM('ADMIN', 'USER'), NOT NULL | 角色 |
| is_active | BOOLEAN, DEFAULT true | 帳戶是否啟用（刪除時若選擇保留資料則設為 false） |
| created_at | TIMESTAMP | 建立時間 |
| updated_at | TIMESTAMP | 最後修改時間 |

### 5.2 Reports 表（回報紀錄）

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

### 5.3 Materials 表（材料）

| 欄位 | 類型 | 說明 |
|------|------|------|
| id | PK, Auto Increment | 主鍵 |
| name | VARCHAR, NOT NULL | 材料名稱 |
| unit | VARCHAR, NOT NULL | 單位（如「個」「箱」「包」「公斤」，由 ADMIN 新增時手動填入） |
| remaining_quantity | INTEGER, ≥ 0 | 剩餘數量 |
| created_at | TIMESTAMP | 建立時間 |
| updated_at | TIMESTAMP | 最後修改時間 |

### 5.4 MaterialRequests 表（材料申請）

| 欄位 | 類型 | 說明 |
|------|------|------|
| id | PK, Auto Increment | 主鍵 |
| user_id | FK → Users.id | 申請者 |
| material_id | FK → Materials.id | 申請的材料 |
| requested_quantity | INTEGER, > 0 | 申請數量 |
| status | ENUM('PENDING', 'APPROVED', 'REJECTED'), DEFAULT 'PENDING' | 狀態 |
| reviewed_by | FK → Users.id, NULLABLE | 審核者 |
| reviewed_at | TIMESTAMP, NULLABLE | 審核時間 |
| created_at | TIMESTAMP | 申請時間 |

### 5.5 AuditLogs 表（變動紀錄）

| 欄位 | 類型 | 說明 |
|------|------|------|
| id | PK, Auto Increment | 主鍵 |
| user_id | FK → Users.id | 操作者 |
| action_type | VARCHAR, NOT NULL | 操作類型（見下方列舉） |
| description | TEXT, NOT NULL | 操作描述（含具體數值變動） |
| created_at | TIMESTAMP | 操作時間（不可修改） |

**action_type 列舉值**：

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
| ACCOUNT_DELETE | 刪除帳戶（含記錄選擇保留或連帶刪除） |
| ACCOUNT_DEACTIVATE | 停用帳戶（保留資料的刪除方式） |
| PASSWORD_CHANGE | 修改密碼（不記錄密碼內容，僅記錄「誰改了誰的密碼」） |

> AuditLogs 表不可被任何人刪除或修改（系統層級保護）。

---

## 6. 業務規則摘要 (Business Rules Summary)

| 編號 | 規則 |
|------|------|
| BR-01 | 同一帳戶同一日期可送出多筆回報 |
| BR-02 | 所有回報新增後預設為「尚未確認」 |
| BR-03 | 已確認的回報被修改後，確認狀態自動重置為「尚未確認」，需 ADMIN 重新確認 |
| BR-04 | Salary 頁面計算僅納入 is_confirmed = true 的回報 |
| BR-05 | Summary 頁面的確認狀態篩選由 ADMIN 自行選擇 |
| BR-06 | 材料申請核准後，系統自動扣減該材料的剩餘數量 |
| BR-07 | 帳戶刪除時，ADMIN 可選擇保留歷史資料（停用帳戶）或連帶刪除回報與申請紀錄 |
| BR-08 | 變動紀錄不可被任何人刪除或修改 |
| BR-09 | 個人統計頁面的薪資試算僅為參考，正式薪資以 ADMIN Salary 頁面為準 |
| BR-10 | USER 個人統計頁面的薪資試算僅計算已確認的回報 |
| BR-11 | ADMIN 亦可填寫回報，其回報紀錄同樣納入 Salary 與 Summary 計算 |

---

## 7. 尚未定義事項 (Not Yet Specified)

以下事項本規格書刻意不指定，留待實作階段決定：

- 技術棧選擇（前後端框架、資料庫）
- UI/UX 設計細節（配色、排版、RWD）
- API 路由設計
- 部署環境與方式
- 效能需求（同時在線人數、回應時間）
- 資料備份策略

---

*— 文件結束 —*
