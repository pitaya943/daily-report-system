"""
隨機生成測試資料：
  - 1 ADMIN  (admin / admin123)
  - 2 USER   (user1 / user123, user2 / user123)
  - 30 筆回報（跨 3 個帳戶、近 30 天、60% 已確認）
  - 6 種材料
  - 15 筆材料申請（PENDING / APPROVED / REJECTED）
  - 對應的變動紀錄
"""
import random
from datetime import datetime, date, timedelta

from app import app
from models import db, User, Report, Material, MaterialRequest, AuditLog
from werkzeug.security import generate_password_hash


def seed():
    with app.app_context():
        db.drop_all()
        db.create_all()

        # ── Users ──────────────────────────────────────────────
        admin = User(display_name='張管理員',
                     password_hash=generate_password_hash('admin123'),
                     role='ADMIN', is_active=True)
        user1 = User(display_name='陳小明',
                     password_hash=generate_password_hash('user123'),
                     role='USER', is_active=True)
        user2 = User(display_name='李小華',
                     password_hash=generate_password_hash('user123'),
                     role='USER', is_active=True)
        db.session.add_all([admin, user1, user2])
        db.session.flush()

        def audit(uid, action, desc):
            db.session.add(AuditLog(user_id=uid, action_type=action, description=desc))

        audit(admin.id, 'ACCOUNT_CREATE', f'建立帳戶「陳小明」（角色：USER）')
        audit(admin.id, 'ACCOUNT_CREATE', f'建立帳戶「李小華」（角色：USER）')

        # ── Reports ────────────────────────────────────────────
        today = date.today()
        all_users = [admin, user1, user2]

        reports_created = []
        for i in range(30):
            u = random.choice(all_users)
            rdate = today - timedelta(days=random.randint(0, 29))
            confirmed = random.random() < 0.65  # ~65% confirmed

            r = Report(
                user_id=u.id,
                report_date=rdate,
                direct_13=random.randint(0, 20),
                direct_20=random.randint(0, 15),
                direct_25=random.randint(0, 10),
                direct_40=random.randint(0, 8),
                indirect_13=random.randint(0, 12),
                indirect_20=random.randint(0, 10),
                indirect_25=random.randint(0, 8),
                indirect_40=random.randint(0, 5),
                direct_special_group=random.randint(0, 6),
                indirect_special_group=random.randint(0, 4),
                downsize=random.randint(0, 5),
                original_downsize=random.randint(0, 3),
                special=random.randint(0, 4),
                mobilization=random.randint(0, 8),
                recheck=random.randint(0, 5),
                soil_clearing=random.randint(0, 10),
                is_confirmed=confirmed,
                confirmed_by=admin.id if confirmed else None,
                confirmed_at=datetime.utcnow() if confirmed else None,
            )
            db.session.add(r)
            reports_created.append((u, r))

        db.session.flush()

        for u, r in reports_created:
            audit(u.id, 'REPORT_CREATE',
                  f'新增 {r.report_date} 的回報（直總-13:{r.direct_13}, 間接-13:{r.indirect_13}）')
            if r.is_confirmed:
                audit(admin.id, 'REPORT_CONFIRM',
                      f'確認 {u.display_name} 的回報 #{r.id}（{r.report_date}）')

        # ── Materials ──────────────────────────────────────────
        materials_data = [
            ('水管接頭',  '個',   200),
            ('PVC管材',   '公尺', 150),
            ('防水膠帶',  '捲',    80),
            ('螺絲包',    '包',    50),
            ('填縫劑',    '條',    30),
            ('清潔劑',    '瓶',    40),
        ]
        materials = []
        for name, unit, qty in materials_data:
            m = Material(name=name, unit=unit, remaining_quantity=qty)
            db.session.add(m)
            materials.append(m)
            audit(admin.id, 'MATERIAL_ADD',
                  f'新增材料「{name}」（{unit}），初始數量：{qty}')
        db.session.flush()

        # ── MaterialRequests ───────────────────────────────────
        status_pool = ['PENDING', 'PENDING', 'APPROVED', 'APPROVED', 'APPROVED', 'REJECTED']
        req_users = [user1, user2]

        for _ in range(15):
            ru = random.choice(req_users)
            m = random.choice(materials)
            qty = random.randint(1, 10)
            st = random.choice(status_pool)

            mr = MaterialRequest(
                user_id=ru.id,
                material_id=m.id,
                requested_quantity=qty,
                status=st,
                reviewed_by=admin.id if st != 'PENDING' else None,
                reviewed_at=datetime.utcnow() if st != 'PENDING' else None,
            )
            db.session.add(mr)
            audit(ru.id, 'MATERIAL_REQUEST',
                  f'申請領取「{m.name}」{qty}{m.unit}')

            if st == 'APPROVED':
                old = m.remaining_quantity
                m.remaining_quantity = max(0, old - qty)
                audit(admin.id, 'MATERIAL_APPROVE',
                      f'核准 {ru.display_name} 申請的「{m.name}」{qty}{m.unit}，庫存 {old} → {m.remaining_quantity}')
            elif st == 'REJECTED':
                audit(admin.id, 'MATERIAL_REJECT',
                      f'駁回 {ru.display_name} 申請的「{m.name}」{qty}{m.unit}')

        db.session.commit()

        # ── Summary ────────────────────────────────────────────
        confirmed_cnt = Report.query.filter_by(is_confirmed=True).count()
        pending_cnt = Report.query.filter_by(is_confirmed=False).count()
        mat_req_cnt = MaterialRequest.query.count()
        audit_cnt = AuditLog.query.count()

        print('=' * 50)
        print('✅  測試資料建立完成')
        print('=' * 50)
        print(f'  張管理員 (admin)  : admin123')
        print(f'  陳小明   (user1)  : user123')
        print(f'  李小華   (user2)  : user123')
        print(f'  回報紀錄   : {confirmed_cnt + pending_cnt} 筆'
              f'（已確認 {confirmed_cnt}，未確認 {pending_cnt}）')
        print(f'  材料種類   : {len(materials)} 種')
        print(f'  材料申請   : {mat_req_cnt} 筆')
        print(f'  變動紀錄   : {audit_cnt} 筆')
        print('=' * 50)
        print('  啟動方式: python app.py')
        print('  網址    : http://127.0.0.1:5000')
        print('=' * 50)


if __name__ == '__main__':
    seed()
