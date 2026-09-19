import aiosqlite
import time

DB_PATH = "saldonesia.db"


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            saldo INTEGER DEFAULT 0,
            is_banned INTEGER DEFAULT 0,
            created_at INTEGER,
            referrer_id INTEGER DEFAULT 0,
            referral_earned INTEGER DEFAULT 0,
            total_orders INTEGER DEFAULT 0,
            total_spent INTEGER DEFAULT 0,
            first_topup_done INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            provider_order_id TEXT,
            service_id TEXT,
            service_name TEXT,
            link TEXT,
            quantity INTEGER,
            price_sell INTEGER,
            price_cost INTEGER,
            status TEXT,
            created_at INTEGER,
            notified INTEGER DEFAULT 0,
            refunded INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS topups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount INTEGER,
            method TEXT,
            proof TEXT,
            status TEXT DEFAULT 'pending',
            created_at INTEGER,
            approved_at INTEGER,
            approved_by INTEGER
        );
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER,
            referred_id INTEGER,
            amount INTEGER,
            source TEXT,
            created_at INTEGER
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        """)

        # ===== MIGRATIONS (untuk DB lama) =====
        migrations = [
            ("users", "referrer_id", "INTEGER DEFAULT 0"),
            ("users", "referral_earned", "INTEGER DEFAULT 0"),
            ("users", "total_orders", "INTEGER DEFAULT 0"),
            ("users", "total_spent", "INTEGER DEFAULT 0"),
            ("users", "first_topup_done", "INTEGER DEFAULT 0"),
            ("orders", "notified", "INTEGER DEFAULT 0"),
            ("orders", "refunded", "INTEGER DEFAULT 0"),
        ]
        for tbl, col, definition in migrations:
            try:
                await db.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} {definition}")
            except Exception:
                pass  # sudah ada

        await db.commit()


# ============ USER ============
async def get_user(tid: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE telegram_id=?", (tid,)) as c:
            row = await c.fetchone()
            return dict(row) if row else None


async def create_user(tid: int, username: str, full_name: str, referrer_id: int = 0):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (telegram_id, username, full_name, saldo, referrer_id, created_at) "
            "VALUES (?, ?, ?, 0, ?, ?)",
            (tid, username, full_name, referrer_id, int(time.time()))
        )
        await db.commit()


async def update_user_info(tid: int, username: str, full_name: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET username=?, full_name=? WHERE telegram_id=?",
            (username, full_name, tid)
        )
        await db.commit()


async def set_referrer(tid: int, referrer_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET referrer_id=? WHERE telegram_id=? AND (referrer_id IS NULL OR referrer_id=0)",
            (referrer_id, tid)
        )
        await db.commit()


async def get_saldo(tid: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT saldo FROM users WHERE telegram_id=?", (tid,)) as c:
            row = await c.fetchone()
            return row[0] if row else 0


async def add_saldo(tid: int, amount: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET saldo = saldo + ? WHERE telegram_id=?", (amount, tid))
        await db.commit()


async def deduct_saldo(tid: int, amount: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT saldo FROM users WHERE telegram_id=?", (tid,)) as c:
            row = await c.fetchone()
            if not row or row[0] < amount:
                return False
        await db.execute("UPDATE users SET saldo = saldo - ? WHERE telegram_id=?", (amount, tid))
        await db.commit()
        return True


async def set_ban(tid: int, banned: bool):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET is_banned=? WHERE telegram_id=?", (1 if banned else 0, tid))
        await db.commit()


async def count_users() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as c:
            return (await c.fetchone())[0]


async def get_all_user_ids():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT telegram_id FROM users WHERE is_banned=0") as c:
            return [r[0] for r in await c.fetchall()]


async def inc_total_orders(tid: int, spent: int = 0):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET total_orders = total_orders + 1, total_spent = total_spent + ? WHERE telegram_id=?",
            (spent, tid)
        )
        await db.commit()


async def set_first_topup_done(tid: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET first_topup_done=1 WHERE telegram_id=?", (tid,))
        await db.commit()


# ============ REFERRAL ============
async def add_referral_earning(referrer_id: int, amount: int, referred_id: int, source: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET saldo = saldo + ? WHERE telegram_id=?", (amount, referrer_id))
        await db.execute("UPDATE users SET referral_earned = referral_earned + ? WHERE telegram_id=?", (amount, referrer_id))
        await db.execute(
            "INSERT INTO referrals (referrer_id, referred_id, amount, source, created_at) VALUES (?, ?, ?, ?, ?)",
            (referrer_id, referred_id, amount, source, int(time.time()))
        )
        await db.commit()


async def get_referral_stats(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(DISTINCT referred_id), COALESCE(SUM(amount),0) FROM referrals WHERE referrer_id=?",
            (user_id,)
        ) as c:
            row = await c.fetchone()
        async with db.execute(
            "SELECT COUNT(*) FROM users WHERE referrer_id=?", (user_id,)
        ) as c:
            total_joined = (await c.fetchone())[0]
        return {
            "total_active": row[0] if row else 0,
            "earned": row[1] if row else 0,
            "total_joined": total_joined,
        }


async def get_referral_list(referrer_id: int, limit=10):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM referrals WHERE referrer_id=? ORDER BY created_at DESC LIMIT ?",
            (referrer_id, limit)
        ) as c:
            return [dict(r) for r in await c.fetchall()]


# ============ ORDER ============
async def create_order(user_id, provider_order_id, service_id, service_name,
                       link, quantity, price_sell, price_cost):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO orders (user_id, provider_order_id, service_id, service_name, link, "
            "quantity, price_sell, price_cost, status, created_at, notified, refunded) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Pending', ?, 0, 0)",
            (user_id, provider_order_id, service_id, service_name, link,
             quantity, price_sell, price_cost, int(time.time()))
        )
        await db.commit()
        return cur.lastrowid


async def update_order_status(order_id: int, status: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE orders SET status=? WHERE id=?", (status, order_id))
        await db.commit()


async def mark_order_notified(order_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE orders SET notified=1 WHERE id=?", (order_id,))
        await db.commit()


async def mark_order_refunded(order_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE orders SET refunded=1 WHERE id=?", (order_id,))
        await db.commit()


async def get_pending_orders(limit=15):
    """Ambil order yang belum final & belum di-refund."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM orders 
               WHERE LOWER(status) NOT IN ('completed', 'canceled', 'cancelled', 'error', 'fail', 'failed', 'refunded')
               ORDER BY created_at DESC LIMIT ?""",
            (limit,)
        ) as c:
            return [dict(r) for r in await c.fetchall()]


async def get_order(order_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM orders WHERE id=?", (order_id,)) as c:
            row = await c.fetchone()
            return dict(row) if row else None


async def get_user_orders(user_id: int, limit=10):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM orders WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit)
        ) as c:
            return [dict(r) for r in await c.fetchall()]


async def count_orders() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM orders") as c:
            return (await c.fetchone())[0]


async def get_total_revenue():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COALESCE(SUM(price_sell),0), COALESCE(SUM(price_cost),0) FROM orders WHERE refunded=0"
        ) as c:
            row = await c.fetchone()
            return row[0], row[1]


async def count_refunds():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*), COALESCE(SUM(price_sell),0) FROM orders WHERE refunded=1"
        ) as c:
            row = await c.fetchone()
            return row[0], row[1]


# ============ TOPUP ============
async def create_topup(user_id: int, amount: int, method: str, proof: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO topups (user_id, amount, method, proof, status, created_at) "
            "VALUES (?, ?, ?, ?, 'pending', ?)",
            (user_id, amount, method, proof, int(time.time()))
        )
        await db.commit()
        return cur.lastrowid


async def get_topup(topup_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM topups WHERE id=?", (topup_id,)) as c:
            row = await c.fetchone()
            return dict(row) if row else None


async def update_topup(topup_id: int, status: str, admin_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE topups SET status=?, approved_at=?, approved_by=? WHERE id=?",
            (status, int(time.time()), admin_id, topup_id)
        )
        await db.commit()


# ============ SETTINGS ============
async def get_setting(key: str, default=None):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM settings WHERE key=?", (key,)) as c:
            row = await c.fetchone()
            return row[0] if row else default


async def set_setting(key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value))
        )
        await db.commit()