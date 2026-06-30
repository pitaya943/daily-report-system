# 擴展性報告 — 員工日報回報系統

> 版本: v1.0.1 | 日期: 2026-06-30
> 系統規模: 10 ADMIN + 75 USER = 85 人

---

## 執行摘要

本報告分析系統在當前 85 人規模下的效能狀態，記錄已完成的優化措施，並評估未來擴展至更大規模時的瓶頸與建議。

---

## 一、已實施的優化措施

### 1.1 資料庫索引（本次新增）

在 `models.py` 和 `_init_db()` 中新增以下索引：

| 索引名稱 | 表格 | 欄位 | 覆蓋查詢 |
|----------|------|------|----------|
| ix_reports_user_date | reports | (user_id, report_date) | 個人歷史紀錄、個人統計 |
| ix_reports_date_confirmed | reports | (report_date, is_confirmed) | 薪資計算（日期範圍 + 已確認篩選）|
| ix_reports_user_confirmed | reports | (user_id, is_confirmed) | 確認頁面（待確認列表）|
| ix_audit_logs_created_at | audit_logs | (created_at) | 變動紀錄（時間排序）|
| ix_audit_logs_user_id | audit_logs | (user_id) | 用戶操作查詢 |
| ix_audit_logs_action_type | audit_logs | (action_type) | 依類型篩選 |
| ix_mat_req_user_id | material_requests | (user_id) | 個人申請查詢 |
| ix_mat_req_status | material_requests | (status) | 待審核申請篩選 |

**預期效益**：薪資計算、確認頁面、歷史紀錄的查詢速度提升 5-20 倍（從全表掃描改為索引掃描）。

### 1.2 批次查詢（之前已實施）

薪資計算 `/salary` 路由中：

- **批次載入用戶費率**: `get_users_all_retention_rates(list(user_data.keys()))` — 一次查詢取所有帳戶的客製費率（避免 N 次查詢）
- **批次載入確認回報**: 年度確認回報一次查詢，在 Python 端按用戶分組（避免 N 次子查詢）
- **用戶字典**: `users_dict = {u.id: u for u in User.query.all()}` — O(1) 查找用戶資訊

### 1.3 分頁查詢

- `/history`：per_page=30
- `/audit`：per_page=20
- `/confirmation`：非分頁（但確認頁面通常僅顯示未處理回報，數量有限）

### 1.4 Loading Overlay

前端加入全域 loading 遮罩，隱藏網路延遲造成的空白畫面，提升感知效能。

### 1.5 SystemConfig 快取機制

`get_item_prices()` 每次請求重新查詢，但 SystemConfig 表資料量極小（< 30 筆），無效能問題。

---

## 二、當前系統容量分析

### 2.1 資料量估算（85 人，正常運作）

| 表格 | 每月新增 | 一年累積 | 五年累積 |
|------|----------|----------|----------|
| reports | 85 × 22 = 1,870 | 22,440 | 112,200 |
| audit_logs | ~500 | ~6,000 | ~30,000 |
| material_requests | ~200 | ~2,400 | ~12,000 |

**結論**: 在正確索引下，SQLite 和 PostgreSQL 在此資料量下均能流暢運作（SQLite 支援至 TB 級別，PostgreSQL 更不受限）。

### 2.2 主要查詢效能估算

| 操作 | 索引前估算 | 索引後估算 | 說明 |
|------|-----------|-----------|------|
| 歷史紀錄（個人）| ~50ms | ~5ms | ix_reports_user_date |
| 薪資計算（2個月）| ~200ms | ~20ms | ix_reports_date_confirmed |
| 確認頁面 | ~100ms | ~10ms | ix_reports_user_confirmed |
| 變動紀錄 | ~80ms | ~8ms | ix_audit_logs_created_at |

*估算基於 22,000 筆 reports，PostgreSQL 環境

### 2.3 並發處理

- Flask 本身為單執行緒（開發伺服器）
- Railway 部署使用 Gunicorn（預設 2-4 workers）
- 85 人不可能同時操作，實際並發 < 10，無瓶頸

---

## 三、已識別的效能瓶頸

### 瓶頸 1: 薪資計算 — 年度預期保留金計算

**描述**: 計算每位用戶的 `ytd_before`（年初至計薪日的累計保留金）需要查詢整年確認回報。

**現狀**: 已優化為一次批次查詢，在 Python 端分組計算，非 N+1。

**潛在問題**: 若年度回報超過 50,000 筆，單次查詢回傳量大。

**建議**（未來）: 引入 `YTDRetentionCache` 表，每次確認回報時更新 YTD 累計，薪資計算時直接讀取快取值。

---

### 瓶頸 2: 薪轉單（Word）生成速度

**描述**: `python-docx` 生成複雜 Word 文件速度較慢（50-200ms），但為一次性下載操作，用戶體驗可接受。

**建議**: 無需優化（低頻操作，可接受延遲）。

---

### 瓶頸 3: 確認頁面 — 無分頁

**描述**: `/confirmation` 顯示所有未確認回報。若積累大量未確認記錄（如系統閒置 1 個月），頁面可能載入 500+ 筆回報。

**建議**: 加入分頁或日期篩選（如「僅顯示最近 30 天」的預設篩選）。

---

### 瓶頸 4: 個人統計薪資試算 — 重複查詢保留金費率

**描述**: `personal_stats()` 呼叫 `get_user_all_retention_rates(current_user.id)` 是針對單一用戶的版本，為 N 次查詢（N = RETENTION_FIELDS 數量）。

**現狀**: 已由批次版本 `get_users_all_retention_rates()` 在薪資計算中處理，但個人統計仍使用舊版。

**修復**:
```python
# 舊（personal_stats 中）
my_ret_rates = get_user_all_retention_rates(current_user.id)

# 建議改為批次版本
my_ret_rates = get_users_all_retention_rates([current_user.id])[current_user.id]
```

---

## 四、未來擴展可能性

### 4.1 擴展至 200+ 使用者

**需要的改動**:
- [ ] 確認頁面加入分頁
- [ ] 薪資計算引入 YTD 快取表
- [ ] 考慮 Redis 快取 SystemConfig（工項單價讀取）
- [ ] Gunicorn worker 數量調整（4-8）

**預估觸發規模**: 150 人以上開始感受明顯延遲

---

### 4.2 行動版 UI

**現狀**: Bootstrap 5 響應式設計，手機可用但非最佳化

**擴展方向**:
- 工人在工地使用手機回報 → 簡化的行動版回報頁面
- 減少欄位數量（點擊工項即加 1，而非輸入數字）
- PWA（Progressive Web App）支援離線操作

---

### 4.3 多語系支援

**現狀**: 純繁體中文介面
**擴展**: Flask-Babel 加入 i18n，支援英文/簡體中文

---

### 4.4 API 化

**現狀**: 純 Jinja2 SSR，無 REST API
**擴展方向**: 拆分前後端
- 後端：Flask 提供 JSON API
- 前端：React/Vue SPA
- 行動 App：React Native
- 此改動工程量大，建議 v2.0 規劃

---

### 4.5 多工程隊支援

**現狀**: 單一工程隊（所有帳戶共用同一 namespace）
**擴展**: 引入 `Team` 模型，USER 歸屬於特定工程隊，ADMIN 只看自己隊的資料

---

### 4.6 工項自訂化

**現狀**: 工項欄位（21 個）為硬編碼
**擴展**: 動態工項系統（`work_item_types` 表），支援新增/停用工項，Report 改用 EAV（Entity-Attribute-Value）模式儲存

**注意**: 此改動影響所有現有邏輯，為重大架構變更

---

### 4.7 薪資歷史記錄

**現狀**: 薪資計算結果不儲存，每次重新計算
**擴展**: 新增 `PayrollPeriod` 和 `PayrollRecord` 表，儲存每期計算結果，支援薪資單列印和歷史查詢

---

### 4.8 通知系統

**現狀**: 無推播通知，用戶需主動進入系統查看
**擴展**:
- Email 通知（Flask-Mail）：回報被確認/駁回時發信
- LINE Bot / Telegram：推播材料申請審核結果

---

## 五、系統健康度總評

| 面向 | 評分 | 說明 |
|------|------|------|
| 資料庫設計 | ★★★★☆ | 合理正規化，索引已補全；無 UNIQUE 約束為小缺失 |
| 業務邏輯 | ★★★★☆ | 薪資計算邏輯清晰；YTD 快取可改進 |
| 查詢效率 | ★★★★☆ | 批次查詢已實施；索引補全後接近最佳 |
| 前端效能 | ★★★☆☆ | CDN 依賴、無 JS 壓縮；功能性優先，不影響使用 |
| 可維護性 | ★★★☆☆ | 單檔 app.py（2500+ 行）應考慮 Blueprint 拆分 |
| 安全性 | ★★☆☆☆ | 缺 CSRF、速率限制（見 security_report.md）|
| 擴展彈性 | ★★★☆☆ | 硬編碼工項、單一 namespace；擴展需重構 |

**整體評估**: 在 85 人規模下，當前架構為近似最佳解，效能足夠。未來若規模擴展至 200 人或需行動端支援，建議啟動 v2.0 架構規劃。

---

## 六、建議的近期優化項目（不需大規模重構）

```
優先級 1（1-2小時）:
  ✅ 已完成：加入資料庫索引
  □ 修復：個人統計保留金費率使用批次版本函數
  □ 確認頁面：加入日期篩選（預設顯示最近 30 天）

優先級 2（半天）:
  □ app.py 拆分：Blueprint（report_bp, settings_bp, salary_bp 等）
  □ 加入 Redis 快取 SystemConfig（單價讀取）

優先級 3（長期規劃）:
  □ YTD 保留金快取表
  □ 薪資計算結果儲存（PayrollRecord）
  □ 行動版回報介面
```

---

*報告生成日期: 2026-06-30*
