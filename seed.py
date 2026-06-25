"""
大量測試資料：
  - 5 ADMIN + 15 USER = 20 帳戶
  - ~1500 筆回報（2026-02-01 到今天，約 65% 已確認）
  - 10 種材料
  - ~50 筆材料申請
  - 對應的變動紀錄
"""
import random
from datetime import datetime, date, timedelta

from app import app
from models import db, User, Report, Material, MaterialRequest, AuditLog, SystemConfig
from werkzeug.security import generate_password_hash

# ── 帳戶清單 ─────────────────────────────────────────────────────────────────
ADMINS = [
    ('張總管',   'admin123', 'TRANSFER', 0),
    ('王主任',   'admin123', 'TRANSFER', 0),
    ('李副理',   'admin123', 'TRANSFER', 1200),
    ('陳組長',   'admin123', 'CASH',     800),
    ('林督導',   'admin123', 'TRANSFER', 0),
]

USERS = [
    ('陳小明',   'user123', 'TRANSFER', 1200),
    ('李小華',   'user123', 'CASH',     800),
    ('黃大勇',   'user123', 'TRANSFER', 1200),
    ('張美玲',   'user123', 'TRANSFER', 0),
    ('吳志偉',   'user123', 'CASH',     800),
    ('劉建國',   'user123', 'TRANSFER', 1200),
    ('蔡雅芳',   'user123', 'TRANSFER', 0),
    ('鄭俊彥',   'user123', 'CASH',     800),
    ('許淑惠',   'user123', 'TRANSFER', 1200),
    ('林冠宇',   'user123', 'TRANSFER', 0),
    ('洪文彬',   'user123', 'CASH',     800),
    ('謝佳穎',   'user123', 'TRANSFER', 1200),
    ('楊宗翰',   'user123', 'TRANSFER', 0),
    ('賴怡君',   'user123', 'CASH',     800),
    ('江明哲',   'user123', 'TRANSFER', 0),
]

# ── 材料清單 ─────────────────────────────────────────────────────────────────
MATERIALS = [
    ('水管接頭 3/4"',  '個',   300),
    ('PVC 管材 1"',    '公尺', 200),
    ('防水膠帶',        '捲',   120),
    ('螺絲包 M6',      '包',    80),
    ('填縫劑',          '條',    60),
    ('清潔劑',          '瓶',    50),
    ('閥門 DN25',      '個',    40),
    ('彎頭 90° 1"',   '個',   150),
    ('管夾',            '個',   200),
    ('止水帶',          '捲',    90),
]


def seed():
    with app.app_context():
        db.drop_all()
        db.create_all()

        # ── 系統設定 ──────────────────────────────────────────────────────────
        db.session.add(SystemConfig(key='retention_rate', value='20'))

        # ── 建立帳戶 ──────────────────────────────────────────────────────────
        admin_objs = []
        for name, pw, pay, ins in ADMINS:
            u = User(display_name=name,
                     password_hash=generate_password_hash(pw),
                     role='ADMIN', is_active=True,
                     payment_method=pay, insurance_deduction=ins)
            db.session.add(u)
            admin_objs.append(u)

        user_objs = []
        for name, pw, pay, ins in USERS:
            u = User(display_name=name,
                     password_hash=generate_password_hash(pw),
                     role='USER', is_active=True,
                     payment_method=pay, insurance_deduction=ins)
            db.session.add(u)
            user_objs.append(u)

        db.session.flush()

        # 主要 ADMIN（用於確認回報 / 審核申請）
        main_admin = admin_objs[0]

        def audit(uid, action, desc):
            db.session.add(AuditLog(user_id=uid, action_type=action, description=desc))

        for u in user_objs:
            audit(main_admin.id, 'ACCOUNT_CREATE', f'建立帳戶「{u.display_name}」（角色：USER）')
        for u in admin_objs[1:]:
            audit(main_admin.id, 'ACCOUNT_CREATE', f'建立帳戶「{u.display_name}」（角色：ADMIN）')

        # ── 建立回報（2026-02-01 ～ 今天）────────────────────────────────────
        today = date.today()
        start_date = date(2026, 2, 1)
        all_period_days = (today - start_date).days + 1
        all_workers = admin_objs + user_objs

        # 每位員工在每個「工作日」（週一到週六）有機率提交回報
        reports_created = []
        for worker in all_workers:
            d = start_date
            while d <= today:
                # 週日休息；其餘日有 75% 機率回報
                if d.weekday() < 6 and random.random() < 0.75:
                    confirmed = random.random() < 0.65
                    r = Report(
                        user_id=worker.id,
                        report_date=d,
                        direct_13=random.randint(0, 25),
                        direct_20=random.randint(0, 20),
                        direct_25=random.randint(0, 15),
                        direct_40=random.randint(0, 10),
                        indirect_13=random.randint(0, 15),
                        indirect_20=random.randint(0, 12),
                        indirect_25=random.randint(0, 10),
                        indirect_40=random.randint(0, 6),
                        original_change=random.randint(0, 6),
                        direct_switch_valve=random.randint(0, 5),
                        indirect_switch_valve=random.randint(0, 4),
                        switch_valve_13_25=random.randint(0, 4),
                        switch_valve_40=random.randint(0, 3),
                        direct_fixed_13_25=random.randint(0, 4),
                        direct_fixed_40=random.randint(0, 3),
                        indirect_fixed_13_25=random.randint(0, 3),
                        indirect_fixed_40=random.randint(0, 2),
                        pipe_repair=random.randint(0, 5),
                        mobilization=random.randint(0, 4),
                        recheck=random.randint(0, 6),
                        soil_clearing=random.randint(0, 10),
                        is_confirmed=confirmed,
                        confirmed_by=main_admin.id if confirmed else None,
                        confirmed_at=datetime.utcnow() if confirmed else None,
                    )
                    db.session.add(r)
                    reports_created.append((worker, r))
                d += timedelta(days=1)

        db.session.flush()

        for worker, r in reports_created:
            audit(worker.id, 'REPORT_CREATE',
                  f'新增 {r.report_date} 的回報（直總-13:{r.direct_13}, 間接-13:{r.indirect_13}）')
            if r.is_confirmed:
                audit(main_admin.id, 'REPORT_CONFIRM',
                      f'確認 {worker.display_name} 的回報 #{r.id}（{r.report_date}）')

        # ── 建立材料 ──────────────────────────────────────────────────────────
        mat_objs = []
        for name, unit, qty in MATERIALS:
            m = Material(name=name, unit=unit, remaining_quantity=qty)
            db.session.add(m)
            mat_objs.append(m)
            audit(main_admin.id, 'MATERIAL_ADD',
                  f'新增材料「{name}」（{unit}），初始數量：{qty}')
        db.session.flush()

        # ── 建立材料申請（共 50 筆）─────────────────────────────────────────
        status_pool = ['PENDING', 'PENDING', 'APPROVED', 'APPROVED', 'APPROVED', 'REJECTED']
        req_users = user_objs  # USER 申請

        for _ in range(50):
            ru = random.choice(req_users)
            m = random.choice(mat_objs)
            qty = random.randint(1, 15)
            st = random.choice(status_pool)

            mr = MaterialRequest(
                user_id=ru.id,
                material_id=m.id,
                requested_quantity=qty,
                status=st,
                reviewed_by=main_admin.id if st != 'PENDING' else None,
                reviewed_at=datetime.utcnow() if st != 'PENDING' else None,
            )
            db.session.add(mr)
            audit(ru.id, 'MATERIAL_REQUEST',
                  f'申請領取「{m.name}」{qty}{m.unit}')

            if st == 'APPROVED':
                old = m.remaining_quantity
                m.remaining_quantity = max(0, old - qty)
                audit(main_admin.id, 'MATERIAL_APPROVE',
                      f'核准 {ru.display_name} 申請的「{m.name}」{qty}{m.unit}，'
                      f'庫存 {old} → {m.remaining_quantity}')
            elif st == 'REJECTED':
                audit(main_admin.id, 'MATERIAL_REJECT',
                      f'駁回 {ru.display_name} 申請的「{m.name}」{qty}{m.unit}')

        db.session.commit()

        # ── Summary ──────────────────────────────────────────────────────────
        confirmed_cnt = Report.query.filter_by(is_confirmed=True).count()
        pending_cnt   = Report.query.filter_by(is_confirmed=False).count()
        mat_req_cnt   = MaterialRequest.query.count()
        audit_cnt     = AuditLog.query.count()

        print('=' * 60)
        print('✅  測試資料建立完成')
        print('=' * 60)
        print('  ADMIN 帳戶（密碼 admin123）：')
        for u in admin_objs:
            print(f'    {u.display_name:<8} | {u.payment_method} | 勞健保: {u.insurance_deduction}')
        print('  USER 帳戶（密碼 user123）：')
        for u in user_objs:
            print(f'    {u.display_name:<8} | {u.payment_method} | 勞健保: {u.insurance_deduction}')
        print(f'  回報紀錄   : {confirmed_cnt + pending_cnt} 筆'
              f'（已確認 {confirmed_cnt}，未確認 {pending_cnt}）')
        print(f'  材料種類   : {len(mat_objs)} 種')
        print(f'  材料申請   : {mat_req_cnt} 筆')
        print(f'  變動紀錄   : {audit_cnt} 筆')
        print('=' * 60)
        print('  啟動方式: python app.py')
        print('  網址    : http://127.0.0.1:5000')
        print('=' * 60)


if __name__ == '__main__':
    seed()
