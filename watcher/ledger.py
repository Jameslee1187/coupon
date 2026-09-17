"""Purchase ledger: cost basis in, disposition out, and honest P&L between.

Worth keeping whether or not resale ever becomes a thing. For personal buys it
answers "did that deal actually save me anything"; for resale it is the only
way to know whether predicted margins survive contact with fees, shipping and
holding time. Cost basis reconstructed a year later from bank statements is
miserable, so it is recorded at purchase time.
"""

import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS lots (
    id INTEGER PRIMARY KEY,
    what TEXT NOT NULL,
    retailer TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'error',
    intent TEXT NOT NULL DEFAULT 'undecided',
    qty INTEGER NOT NULL DEFAULT 1,
    unit_price REAL NOT NULL,
    tax REAL NOT NULL DEFAULT 0,
    purchase_ship REAL NOT NULL DEFAULT 0,
    normal_price REAL,
    expected_resale REAL,
    ordered_at INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    platform TEXT,
    listed_price REAL,
    listed_at INTEGER,
    sold_price REAL,
    sold_at INTEGER,
    fees REAL,
    ship_cost REAL,
    notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_lots_status ON lots(status);
"""

STATES = ["pending", "cancelled", "received", "listed", "sold", "kept", "returned"]
OPEN_STATES = {"pending", "received", "listed"}

# Rough platform take rates, used only when actual fees aren't supplied.
DEFAULT_FEE_RATES = {"ebay": 0.1325, "amazon": 0.15, "mercari": 0.10,
                     "facebook": 0.0, "local": 0.0, "other": 0.10}


def init(db):
    db.executescript(SCHEMA)
    db.commit()


def migrate_outcomes(db):
    """Fold the older `outcomes` table into `lots`, then drop it."""
    exists = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='outcomes'").fetchone()
    if not exists:
        return 0
    rows = list(db.execute("SELECT * FROM outcomes"))
    for r in rows:
        db.execute(
            "INSERT INTO lots (what, retailer, kind, unit_price, normal_price,"
            " ordered_at, status, notes) VALUES (?,?,?,?,?,?,?,?)",
            (r["what"], r["retailer"], r["kind"], r["paid"], r["normal_price"],
             r["ordered_at"],
             {"shipped": "received", "cancelled": "cancelled"}.get(r["outcome"], "pending"),
             r["notes"]))
    db.execute("DROP TABLE outcomes")
    db.commit()
    return len(rows)


def cost_basis(lot):
    return (lot["unit_price"] or 0) * (lot["qty"] or 1) + (lot["tax"] or 0) \
        + (lot["purchase_ship"] or 0)


def estimate_fees(platform, price, cfg):
    rates = {**DEFAULT_FEE_RATES, **(cfg.get("fee_rates") or {})}
    return price * rates.get((platform or "other").lower(), rates["other"])


def net(lot, cfg):
    """Realised profit on a sold lot, or None if it hasn't sold."""
    if lot["status"] != "sold" or lot["sold_price"] is None:
        return None
    fees = lot["fees"]
    if fees is None:
        fees = estimate_fees(lot["platform"], lot["sold_price"], cfg)
    return lot["sold_price"] - fees - (lot["ship_cost"] or 0) - cost_basis(lot)


def holding_days(lot):
    if not lot["sold_at"]:
        return None
    return max(0.0, (lot["sold_at"] - lot["ordered_at"]) / 86400.0)


MIN_DAYS_TO_ANNUALIZE = 7


def annualized(lot, cfg):
    """Return on capital per year. A thin margin that recycles fast beats a fat
    one that sits, and only this number shows that.

    Returns None for very short holds: annualizing a two-day flip produces a
    figure in the tens of thousands of percent that is arithmetically correct
    and completely useless, since you cannot repeat it 180 times a year.
    """
    n, days, basis = net(lot, cfg), holding_days(lot), cost_basis(lot)
    if n is None or not basis or days is None or days < MIN_DAYS_TO_ANNUALIZE:
        return None
    return (n / basis) / days * 365.0


def add(db, **kw):
    cols = ("what retailer kind intent qty unit_price tax purchase_ship "
            "normal_price expected_resale ordered_at notes").split()
    kw.setdefault("ordered_at", int(time.time()))
    vals = [kw.get(c) for c in cols]
    cur = db.execute(
        f"INSERT INTO lots ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", vals)
    db.commit()
    return cur.lastrowid


def get(db, lot_id):
    return db.execute("SELECT * FROM lots WHERE id=?", (lot_id,)).fetchone()


def all_lots(db):
    return list(db.execute("SELECT * FROM lots ORDER BY ordered_at DESC, id DESC"))


def set_status(db, lot_id, status):
    cur = db.execute("UPDATE lots SET status=? WHERE id=?", (status, lot_id))
    db.commit()
    return cur.rowcount


def mark_listed(db, lot_id, price, platform):
    cur = db.execute(
        "UPDATE lots SET status='listed', listed_price=?, platform=?, listed_at=? WHERE id=?",
        (price, platform, int(time.time()), lot_id))
    db.commit()
    return cur.rowcount


def mark_sold(db, lot_id, price, fees, ship_cost, platform):
    lot = get(db, lot_id)
    cur = db.execute(
        "UPDATE lots SET status='sold', sold_price=?, fees=?, ship_cost=?,"
        " platform=COALESCE(?, platform), sold_at=? WHERE id=?",
        (price, fees, ship_cost, platform, int(time.time()), lot_id))
    db.commit()
    return cur.rowcount
