"""Price history + deal rules. SQLite, because the Mac mini is the only host."""

import os
import sqlite3
import statistics
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS observations (
    id INTEGER PRIMARY KEY,
    item_id TEXT NOT NULL,
    source TEXT NOT NULL,
    price REAL NOT NULL,
    available INTEGER NOT NULL DEFAULT 1,
    url TEXT,
    seen_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_obs_item ON observations(item_id, seen_at);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY,
    item_id TEXT NOT NULL,
    source TEXT NOT NULL,
    price REAL NOT NULL,
    rule TEXT NOT NULL,
    sent_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_alert_item ON alerts(item_id, sent_at);
"""


class Store:
    def __init__(self, path):
        first = not os.path.exists(path)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()
        self.fresh = first

    def record(self, item_id, source, price, available, url, when=None):
        self.db.execute(
            "INSERT INTO observations (item_id, source, price, available, url, seen_at)"
            " VALUES (?,?,?,?,?,?)",
            (item_id, source, price, int(available), url, when or int(time.time())),
        )
        self.db.commit()

    def prices(self, item_id, since_days=None):
        q = "SELECT price, seen_at FROM observations WHERE item_id=? AND available=1"
        args = [item_id]
        if since_days:
            q += " AND seen_at >= ?"
            args.append(int(time.time()) - since_days * 86400)
        return [(r["price"], r["seen_at"]) for r in self.db.execute(q + " ORDER BY seen_at", args)]

    def last_price(self, item_id, source):
        r = self.db.execute(
            "SELECT price FROM observations WHERE item_id=? AND source=?"
            " ORDER BY seen_at DESC LIMIT 1", (item_id, source)).fetchone()
        return r["price"] if r else None

    def recently_alerted(self, item_id, price, cooldown_hours):
        """True if we already alerted this item at this price or lower, recently.

        Keyed on price as well as time so a further drop still gets through -
        a cooldown that swallows a better price is worse than no cooldown."""
        cutoff = int(time.time()) - int(cooldown_hours * 3600)
        r = self.db.execute(
            "SELECT MIN(price) AS lowest FROM alerts WHERE item_id=? AND sent_at >= ?",
            (item_id, cutoff)).fetchone()
        return r["lowest"] is not None and price >= r["lowest"]

    def log_alert(self, item_id, source, price, rule):
        self.db.execute(
            "INSERT INTO alerts (item_id, source, price, rule, sent_at) VALUES (?,?,?,?,?)",
            (item_id, source, price, rule, int(time.time())))
        self.db.commit()


def evaluate(item, price, history, cfg):
    """Return (rule_name, note) if this price is worth an alert, else None.

    history is a list of past prices (floats). Statistical rules stay off until
    there are enough observations - on a cold start the only rule that can fire
    is an explicit target_price, which is the honest behaviour: with no history
    there is no way to know whether a price is good.
    """
    target = item.get("target_price")
    if target and price <= float(target):
        return "target_price", f"at or below your target of ${float(target):,.2f}"

    min_obs = cfg.get("min_observations", 20)
    if len(history) < min_obs:
        return None

    low = min(history)
    if price < low:
        return "all_time_low", f"lowest seen in {len(history)} observations (prev ${low:,.2f})"

    pct = cfg.get("pct_below_median")
    if pct:
        median = statistics.median(history)
        threshold = median * (1 - pct / 100.0)
        if price <= threshold:
            return ("pct_below_median",
                    f"{(1 - price / median) * 100:.0f}% below median of ${median:,.2f}")
    return None
