"""
seed_test_data.py

本地執行（SQLite）:
  python seed_test_data.py

連接生產 PostgreSQL（Supabase）:
  $env:DATABASE_URL="postgresql://user:pass@host:5432/db"  # PowerShell
  python seed_test_data.py

透過 Railway CLI（在生產環境執行）:
  railway run python seed_test_data.py

⚠️  執行前確認：此腳本會刪除目標資料庫的所有資料！
"""
import random
import sys
import os
from datetime import date, datetime, timedelta
from werkzeug.security import generate_password_hash

# ── 確保可以 import app ──────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 允許在 import app 前覆蓋 DATABASE_URL
if os.environ.get('DATABASE_URL'):
    _db_url = os.environ['DATABASE_URL'].replace('postgres://', 'postgresql://', 1)
    print(f"📡 連接至 PostgreSQL: {_db_url[:40]}...")
else:
    print("💾 使用本地 SQLite")

from app import app, db
from models import (
    User, Report, Material, MaterialRequest,
    AuditLog, SystemConfig, UserRetentionRate
)

random.seed(42)

# ── 所有工項欄位 ─────────────────────────────────────────────────────────
REPORT_FIELDS = [
    'direct_13', 'direct_20', 'direct_25', 'direct_40',
    'indirect_13', 'indirect_20', 'indirect_25', 'indirect_40',
    'original_change', 'direct_switch_valve', 'indirect_switch_valve',
    'switch_valve_13_25', 'switch_valve_40',
    'direct_fixed_13_25', 'direct_fixed_40',
    'indirect_fixed_13_25', 'indirect_fixed_40',
    'pipe_repair', 'mobilization', 'recheck', 'soil_clearing',
]

# 各欄位每日合理數量上限（模擬真實工作量分布）
FIELD_MAX = {
    'direct_13': 6, 'direct_20': 5, 'direct_25': 4, 'direct_40': 3,
    'indirect_13': 8, 'indirect_20': 6, 'indirect_25': 5, 'indirect_40': 3,
    'original_change': 3, 'direct_switch_valve': 2, 'indirect_switch_valve': 2,
    'switch_valve_13_25': 2, 'switch_valve_40': 1,
    'direct_fixed_13_25': 2, 'direct_fixed_40': 1,
    'indirect_fixed_13_25': 2, 'indirect_fixed_40': 1,
    'pipe_repair': 2, 'mobilization': 1, 'recheck': 4, 'soil_clearing': 2,
}

# 欄位填入機率（稀有工項機率低）
FIELD_PROB = {
    'direct_13': 0.70, 'direct_20': 0.60, 'direct_25': 0.55, 'direct_40': 0.40,
    'indirect_13': 0.65, 'indirect_20': 0.55, 'indirect_25': 0.50, 'indirect_40': 0.35,
    'original_change': 0.30, 'direct_switch_valve': 0.25, 'indirect_switch_valve': 0.20,
    'switch_valve_13_25': 0.15, 'switch_valve_40': 0.10,
    'direct_fixed_13_25': 0.20, 'direct_fixed_40': 0.10,
    'indirect_fixed_13_25': 0.15, 'indirect_fixed_40': 0.08,
    'pipe_repair': 0.20, 'mobilization': 0.10, 'recheck': 0.25, 'soil_clearing': 0.15,
}

def rand_report_fields():
    vals = {}
    for f in REPORT_FIELDS:
        if random.random() < FIELD_PROB[f]:
            vals[f] = random.randint(1, FIELD_MAX[f])
        else:
            vals[f] = 0
    # 確保至少有一個欄位有值
    if all(v == 0 for v in vals.values()):
        f = random.choice(['direct_13', 'direct_20', 'indirect_13', 'indirect_20'])
        vals[f] = random.randint(1, 4)
    return vals

def random_dates(start: date, end: date, n: int):
    days = (end - start).days + 1
    chosen = random.sample(range(days), min(n, days))
    return sorted([start + timedelta(d) for d in chosen])

def fmt_bank(i: int) -> str:
    """生成假的 14 碼銀行帳號"""
    branch = str(random.choice([103, 132, 156, 205, 212])).zfill(3)
    acct   = str(1000000000 + i * 73917 + random.randint(0, 9999)).zfill(11)
    return branch + acct

with app.app_context():
    print("▶ 清空所有資料表…")
    is_pg = 'postgresql' in str(db.engine.url)
    if is_pg:
        # PostgreSQL: TRUNCATE ... CASCADE 最快且正確處理 FK
        db.session.execute(db.text(
            "TRUNCATE TABLE audit_logs, material_requests, reports, "
            "user_retention_rates, materials, system_config, users RESTART IDENTITY CASCADE"
        ))
    else:
        # SQLite: 逐表刪除（不支援 TRUNCATE）
        db.session.execute(db.text("PRAGMA foreign_keys = OFF"))
        for Model in [AuditLog, MaterialRequest, Report,
                      UserRetentionRate, Material, SystemConfig, User]:
            db.session.query(Model).delete()
        db.session.execute(db.text("PRAGMA foreign_keys = ON"))
    db.session.commit()

    # ── SystemConfig ─────────────────────────────────────────────────────
    print("▶ 初始化 SystemConfig…")
    db.session.add(SystemConfig(key='retention_rate', value='20'))
    db.session.add(SystemConfig(key='tax_rate',       value='3'))
    db.session.add(SystemConfig(key='price_direct_13',              value='120'))
    db.session.add(SystemConfig(key='price_direct_20',              value='120'))
    db.session.add(SystemConfig(key='price_direct_25',              value='120'))
    db.session.add(SystemConfig(key='price_direct_40',              value='170'))
    db.session.add(SystemConfig(key='price_indirect_13',            value='75'))
    db.session.add(SystemConfig(key='price_indirect_20',            value='75'))
    db.session.add(SystemConfig(key='price_indirect_25',            value='75'))
    db.session.add(SystemConfig(key='price_indirect_40',            value='125'))
    db.session.add(SystemConfig(key='price_original_change',        value='45'))
    db.session.add(SystemConfig(key='price_direct_switch_valve',    value='200'))
    db.session.add(SystemConfig(key='price_indirect_switch_valve',  value='150'))
    db.session.add(SystemConfig(key='price_switch_valve_13_25',     value='320'))
    db.session.add(SystemConfig(key='price_switch_valve_40',        value='450'))
    db.session.add(SystemConfig(key='price_direct_fixed_13_25',     value='340'))
    db.session.add(SystemConfig(key='price_direct_fixed_40',        value='500'))
    db.session.add(SystemConfig(key='price_indirect_fixed_13_25',   value='230'))
    db.session.add(SystemConfig(key='price_indirect_fixed_40',      value='450'))
    db.session.add(SystemConfig(key='price_pipe_repair',            value='150'))
    db.session.add(SystemConfig(key='price_mobilization',           value='1200'))
    db.session.add(SystemConfig(key='price_recheck',                value='60'))
    db.session.add(SystemConfig(key='price_soil_clearing',          value='80'))
    db.session.commit()

    # ── ADMIN ─────────────────────────────────────────────────────────────
    print("▶ 建立 ADMIN Root…")
    root = User(
        display_name='Root',
        password_hash=generate_password_hash('admin123'),
        role='ADMIN',
        is_active=True,
        payment_method='TRANSFER',
        insurance_deduction=0,
        tax_exempt=True,
        fixed_salary=0,
        bank_account='10299999999999',
        retention_offset=0,
        created_at=datetime(2025, 1, 1),
        updated_at=datetime(2025, 1, 1),
    )
    db.session.add(root)
    db.session.flush()
    root_id = root.id

    # ── 20 位 USER ────────────────────────────────────────────────────────
    print("▶ 建立 20 位 USER…")

    # 設定多樣的帳戶屬性
    user_configs = [
        # (insurance_deduction, tax_exempt, payment_method, has_bank, fixed_salary, is_active, retention_offset)
        (1500, False, 'TRANSFER', True,  0,     True,  0),     # 測試用戶1  — 投保+轉帳
        (1200, False, 'TRANSFER', True,  0,     True,  0),     # 測試用戶2  — 投保+轉帳
        (2000, False, 'TRANSFER', True,  20000, True,  0),     # 測試用戶3  — 投保+轉帳+固定薪
        (800,  False, 'TRANSFER', True,  15000, True,  0),     # 測試用戶4  — 投保+轉帳+固定薪
        (1800, False, 'CASH',     False, 0,     True,  0),     # 測試用戶5  — 投保+現金
        (0,    False, 'CASH',     False, 0,     True,  0),     # 測試用戶6  — 未投保扣稅+現金
        (0,    False, 'CASH',     False, 0,     True,  0),     # 測試用戶7  — 未投保扣稅+現金
        (0,    True,  'TRANSFER', True,  30000, True,  0),     # 測試用戶8  — 未投保免稅+固定薪+轉帳
        (0,    True,  'TRANSFER', True,  25000, True,  0),     # 測試用戶9  — 未投保免稅+固定薪+轉帳
        (0,    True,  'CASH',     False, 0,     True,  0),     # 測試用戶10 — 未投保免稅+現金
        (1600, False, 'TRANSFER', True,  0,     True,  500),   # 測試用戶11 — 投保+保留金調整
        (1400, False, 'TRANSFER', True,  18000, True,  -200),  # 測試用戶12 — 投保+固定薪+負調整
        (0,    False, 'TRANSFER', True,  0,     True,  0),     # 測試用戶13 — 未投保扣稅+轉帳
        (0,    False, 'CASH',     False, 0,     True,  0),     # 測試用戶14 — 未投保扣稅+現金
        (900,  False, 'CASH',     False, 0,     True,  0),     # 測試用戶15 — 投保+現金
        (0,    True,  'CASH',     False, 12000, True,  0),     # 測試用戶16 — 未投保免稅+固定薪+現金
        (1100, False, 'TRANSFER', True,  0,     False, 0),     # 測試用戶17 — 停用帳戶
        (0,    False, 'CASH',     False, 0,     False, 0),     # 測試用戶18 — 停用帳戶
        (2200, False, 'TRANSFER', True,  50000, True,  0),     # 測試用戶19 — 高薪+投保+固定薪
        (0,    True,  'TRANSFER', True,  40000, True,  0),     # 測試用戶20 — 未投保免稅+高固定薪
    ]

    users = []
    for i, (ins, tex, pm, has_bank, fixed, active, offset) in enumerate(user_configs, start=1):
        bank = fmt_bank(i) if has_bank else None
        created = datetime(2025, random.randint(1, 3), random.randint(1, 28))
        u = User(
            display_name=f'測試用戶{i}',
            password_hash=generate_password_hash(f'user{i:02d}pass'),
            role='USER',
            is_active=active,
            payment_method=pm,
            insurance_deduction=ins,
            tax_exempt=tex,
            fixed_salary=fixed,
            bank_account=bank,
            retention_offset=offset,
            created_at=created,
            updated_at=created,
        )
        db.session.add(u)
        users.append(u)
    db.session.flush()

    # ── Materials ─────────────────────────────────────────────────────────
    print("▶ 建立材料清單…")
    material_defs = [
        ('瓦斯管 13mm', '支', 500),
        ('瓦斯管 20mm', '支', 300),
        ('瓦斯管 25mm', '支', 200),
        ('瓦斯管 40mm', '支', 100),
        ('開關閥 13-25mm', '個', 150),
        ('開關閥 40mm',    '個', 80),
        ('接頭 T型 13mm',  '個', 600),
        ('接頭 T型 20mm',  '個', 400),
        ('防爆軟管',       '條', 200),
        ('橡皮圈',         '包', 1000),
    ]
    materials = []
    for idx, (name, unit, qty) in enumerate(material_defs, start=1):
        m = Material(name=name, unit=unit, remaining_quantity=qty, sort_order=idx)
        db.session.add(m)
        materials.append(m)
    db.session.flush()

    # ── Reports（40 筆/人，分散 5/1~6/30）─────────────────────────────────
    print("▶ 建立回報紀錄（40 筆 × 20 人 = 800 筆）…")
    start_d = date(2025, 5, 1)
    end_d   = date(2025, 6, 30)

    # root 也有一些回報
    root_dates = random_dates(start_d, end_d, 15)
    for rd in root_dates:
        vals = rand_report_fields()
        confirmed = random.random() < 0.8
        r = Report(
            user_id=root_id,
            report_date=rd,
            is_confirmed=confirmed,
            confirmed_by=root_id if confirmed else None,
            confirmed_at=datetime(rd.year, rd.month, rd.day, 18) if confirmed else None,
            **{f: vals.get(f, 0) for f in REPORT_FIELDS}
        )
        db.session.add(r)

    for u in users:
        if not u.is_active:
            # 停用帳戶也有一些舊回報
            dates = random_dates(start_d, date(2025, 5, 31), 10)
        else:
            dates = random_dates(start_d, end_d, 40)

        for rd in dates:
            vals = rand_report_fields()
            # 按日期決定確認狀態
            roll = random.random()
            if rd < date(2025, 6, 10):
                confirmed  = roll < 0.85
                rejected   = (not confirmed) and roll > 0.95
            else:
                confirmed  = roll < 0.50
                rejected   = (not confirmed) and roll > 0.90

            r = Report(
                user_id=u.id,
                report_date=rd,
                is_confirmed=confirmed,
                is_rejected=rejected,
                confirmed_by=root_id if confirmed or rejected else None,
                confirmed_at=datetime(rd.year, rd.month, rd.day, 17, 30) if (confirmed or rejected) else None,
                **{f: vals.get(f, 0) for f in REPORT_FIELDS}
            )
            db.session.add(r)
    db.session.flush()

    # ── Material Requests（5 筆/人）────────────────────────────────────────
    print("▶ 建立材料申請（5 筆 × 20 人 = 100 筆）…")
    statuses = ['PENDING', 'APPROVED', 'APPROVED', 'REJECTED', 'PENDING']
    for u in users:
        for j, status in enumerate(statuses):
            mat = materials[random.randint(0, len(materials)-1)]
            qty = random.randint(1, 10)
            created = datetime(2025, random.randint(5, 6), random.randint(1, 28))
            mr = MaterialRequest(
                user_id=u.id,
                material_id=mat.id,
                requested_quantity=qty,
                status=status,
                reviewed_by=root_id if status != 'PENDING' else None,
                reviewed_at=created + timedelta(hours=random.randint(1, 48)) if status != 'PENDING' else None,
                created_at=created,
            )
            db.session.add(mr)
    db.session.flush()

    # ── Audit Logs ────────────────────────────────────────────────────────
    print("▶ 建立變動紀錄（數十筆）…")
    audit_entries = [
        # 系統初始化
        (root_id, 'SYSTEM_CONFIG', '初始化系統：設定稅務費率 3%'),
        (root_id, 'SYSTEM_CONFIG', '初始化系統：設定保留金費率 20%'),
        (root_id, 'SYSTEM_CONFIG', '更新稅務支出費率：5% → 3%'),
        (root_id, 'SYSTEM_CONFIG', '更新保留金費率（direct_13）：18% → 20%'),
        # 帳戶管理
        (root_id, 'ACCOUNT_CREATE', '建立帳戶「測試用戶1」(USER)'),
        (root_id, 'ACCOUNT_CREATE', '建立帳戶「測試用戶2」(USER)'),
        (root_id, 'ACCOUNT_CREATE', '建立帳戶「測試用戶3」(USER)'),
        (root_id, 'ACCOUNT_UPDATE', '更新「測試用戶3」固定薪資：0 → 20000 NTD'),
        (root_id, 'ACCOUNT_UPDATE', '更新「測試用戶8」固定薪資：0 → 30000 NTD'),
        (root_id, 'ACCOUNT_UPDATE', '更新「測試用戶19」固定薪資：0 → 50000 NTD'),
        (root_id, 'ACCOUNT_UPDATE', '更新「測試用戶11」保留金調整：0 → +500'),
        (root_id, 'ACCOUNT_UPDATE', '更新「測試用戶12」保留金調整：0 → -200'),
        (root_id, 'ACCOUNT_UPDATE', '更新「測試用戶1」發薪方式：CASH → TRANSFER'),
        (root_id, 'ACCOUNT_UPDATE', '更新「測試用戶5」投保狀態：未投保 → 1800 NTD'),
        (root_id, 'ACCOUNT_UPDATE', '更新「測試用戶15」投保狀態：未投保 → 900 NTD'),
        (root_id, 'ACCOUNT_DEACTIVATE', '停用帳戶「測試用戶17」'),
        (root_id, 'ACCOUNT_DEACTIVATE', '停用帳戶「測試用戶18」'),
        (root_id, 'PASSWORD_CHANGE', '重設「測試用戶6」密碼'),
        (root_id, 'PASSWORD_CHANGE', '重設「測試用戶14」密碼'),
        # 回報確認
        (root_id, 'REPORT_CONFIRM', '確認「測試用戶1」2025-05-03 的回報 #15'),
        (root_id, 'REPORT_CONFIRM', '確認「測試用戶2」2025-05-07 的回報 #28'),
        (root_id, 'REPORT_CONFIRM', '批次確認 2025-05 共 45 筆回報'),
        (root_id, 'REPORT_REJECT',  '駁回「測試用戶6」2025-05-12 的回報（數量異常）'),
        (root_id, 'REPORT_REJECT',  '駁回「測試用戶9」2025-06-03 的回報（重複回報）'),
        (root_id, 'REPORT_UNCONFIRM', '取消確認「測試用戶3」2025-05-20 的回報 #67'),
        # 材料
        (root_id, 'MATERIAL_ADD', '新增材料「瓦斯管 13mm」'),
        (root_id, 'MATERIAL_ADD', '新增材料「開關閥 13-25mm」'),
        (root_id, 'MATERIAL_UPDATE', '更新材料「瓦斯管 20mm」數量：250 → 300'),
        (root_id, 'MATERIAL_APPROVE', '核准「測試用戶1」申請瓦斯管 13mm × 3'),
        (root_id, 'MATERIAL_APPROVE', '核准「測試用戶7」申請開關閥 40mm × 2'),
        (root_id, 'MATERIAL_REJECT', '拒絕「測試用戶13」申請防爆軟管 × 10（庫存不足）'),
        (root_id, 'MATERIAL_REQUEST', '「測試用戶4」申請橡皮圈 × 5'),
        (root_id, 'MATERIAL_CANCEL', '「測試用戶9」取消申請接頭 T型 13mm × 2'),
        # 薪資相關
        (root_id, 'SYSTEM_CONFIG', '更新工項單價 直總-13：110 → 120'),
        (root_id, 'SYSTEM_CONFIG', '更新工項單價 動員：1000 → 1200'),
        (root_id, 'RETENTION_RESET', '重設「測試用戶11」保留金（新年度）'),
        (root_id, 'RETENTION_SET', '設定「測試用戶12」保留金補償：-200'),
        # 用戶自己的操作
        (users[0].id, 'REPORT_CREATE', '「測試用戶1」新增 2025-06-01 回報'),
        (users[1].id, 'REPORT_CREATE', '「測試用戶2」新增 2025-06-02 回報'),
        (users[2].id, 'REPORT_UPDATE', '「測試用戶3」修改 2025-05-15 回報'),
        (users[5].id, 'REPORT_DELETE', '「測試用戶6」刪除 2025-05-10 回報（確認前）'),
        (users[0].id, 'PASSWORD_CHANGE', '「測試用戶1」修改自身密碼'),
        (users[3].id, 'MATERIAL_REQUEST', '「測試用戶4」申請瓦斯管 25mm × 6'),
        (users[9].id, 'MATERIAL_REQUEST', '「測試用戶10」申請接頭 T型 20mm × 4'),
        (users[12].id, 'MATERIAL_CANCEL', '「測試用戶13」取消申請橡皮圈 × 8'),
    ]

    # 在 5/1~6/30 隨機分配時間
    base_dt = datetime(2025, 5, 1)
    for i, (uid, atype, desc) in enumerate(audit_entries):
        dt = base_dt + timedelta(
            days=random.randint(0, 60),
            hours=random.randint(8, 20),
            minutes=random.randint(0, 59)
        )
        db.session.add(AuditLog(
            user_id=uid,
            action_type=atype,
            description=desc,
            created_at=dt,
        ))

    # ── UserRetentionRate 客製費率 ─────────────────────────────────────────
    print("▶ 設定客製保留金費率…")
    # 測試用戶3: direct_13 費率 25%
    db.session.add(UserRetentionRate(user_id=users[2].id, field='direct_13', rate=25))
    db.session.add(UserRetentionRate(user_id=users[2].id, field='direct_20', rate=25))
    # 測試用戶11: 整體費率 15%（主要工項）
    db.session.add(UserRetentionRate(user_id=users[10].id, field='direct_13',  rate=15))
    db.session.add(UserRetentionRate(user_id=users[10].id, field='indirect_13', rate=15))

    db.session.commit()

    # ── 統計摘要 ─────────────────────────────────────────────────────────
    print("\n✅ 資料填入完成！")
    print(f"   User 數量  : {db.session.query(User).count()}")
    print(f"   Report 數量: {db.session.query(Report).count()}")
    print(f"   Material 數: {db.session.query(Material).count()}")
    print(f"   MatlReq 數 : {db.session.query(MaterialRequest).count()}")
    print(f"   AuditLog 數: {db.session.query(AuditLog).count()}")
    print("\n帳戶清單：")
    print(f"   {'ADMIN':<8} Root          密碼: admin123")
    for i, u in enumerate(users, 1):
        status = '🔴停用' if not u.is_active else '🟢在職'
        print(f"   {status} 測試用戶{i:<3}  密碼: user{i:02d}pass")
