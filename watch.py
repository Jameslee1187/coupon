#!/usr/bin/env python3
"""Watch a short list of products and alert when one is genuinely cheap.

Built for an always-on Mac: launchd runs `poll` on an interval, each run is a
short-lived process, and state lives in SQLite.

    python3 watch.py poll          one pass over the watchlist
    python3 watch.py feeds         read deal feeds, alert on price errors
    python3 watch.py buy ...       log a purchase into the ledger
    python3 watch.py ledger        positions, P&L, honor rates
    python3 watch.py calibrate     were your resale estimates any good?
    python3 watch.py check         verify each source adapter actually works
    python3 watch.py history <id>  price history for one item
    python3 watch.py test-alert    prove the notification path end to end
    python3 watch.py install       print the launchd plist for this checkout
"""

import argparse
import os
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

try:
    import yaml
except ImportError:
    sys.exit("PyYAML isn't installed.\n\n"
             "  python3 -m venv .venv\n"
             "  source .venv/bin/activate\n"
             "  python3 -m pip install pyyaml requests\n")

from watcher import feeds as feedmod, ledger, notify, sources
from watcher.store import Store, evaluate

BOLD, DIM, RESET = "\033[1m", "\033[2m", "\033[0m"
GREEN, YELLOW, RED = "\033[32m", "\033[33m", "\033[31m"


def load(name, example):
    path = os.path.join(HERE, name)
    if not os.path.exists(path):
        sys.exit(f"No {name}.\n  cp {example} {name}\nthen edit it.")
    with open(path) as f:
        return yaml.safe_load(f) or {}


def load_all():
    cfg = load("watch-config.yaml", "watch-config.example.yaml")
    items = load("watchlist.yaml", "watchlist.example.yaml")
    store = Store(os.path.join(HERE, cfg.get("database", "prices.db")))
    return cfg, items, store


def cmd_poll(args):
    cfg, items, store = load_all()
    rules = cfg.get("rules") or {}
    channels = cfg.get("notify") or ["console"]
    quiet = args.quiet

    for item in items:
        item_id = item["id"]
        for src in item.get("sources") or []:
            label = f"{item_id}/{src.get('type')}"
            try:
                quote = sources.fetch(src, cfg)
            except Exception as exc:
                print(f"{RED}!{RESET} {label}: {exc}")
                continue
            if quote is None:
                if not quiet:
                    print(f"{DIM}-{RESET} {label}: not found")
                continue

            store.record(item_id, src["type"], quote.price, quote.available, quote.url)
            if not quote.available:
                if not quiet:
                    print(f"{DIM}-{RESET} {label}: ${quote.price:,.2f} (out of stock)")
                continue

            history = [p for p, _ in store.prices(item_id)]
            hit = evaluate(item, quote.price, history[:-1], rules)
            if not hit:
                if not quiet:
                    print(f"{DIM}·{RESET} {label}: ${quote.price:,.2f}")
                continue

            rule, why = hit
            if store.recently_alerted(item_id, quote.price, rules.get("cooldown_hours", 12)):
                if not quiet:
                    print(f"{DIM}·{RESET} {label}: ${quote.price:,.2f} ({rule}, in cooldown)")
                continue

            title = f"{item.get('name', item_id)} — ${quote.price:,.2f}"
            body = f"{why}\n{src['type']}"
            print(f"{GREEN}${RESET} {BOLD}{title}{RESET} — {why}")
            notify.send(channels, title, body, quote.url, cfg)
            store.log_alert(item_id, src["type"], quote.price, rule)


def cmd_feeds(args):
    """Read public deal feeds, alert on unseen posts that qualify."""
    cfg = load("watch-config.yaml", "watch-config.example.yaml")
    fcfg = load("feeds.yaml", "feeds.example.yaml")
    store = Store(os.path.join(HERE, cfg.get("database", "prices.db")))
    rules = fcfg.get("rules") or {}
    channels = cfg.get("notify") or ["console"]

    total = matched = fresh = 0
    for feed in fcfg.get("feeds") or []:
        name = feed.get("name") or feed.get("subreddit") or feed.get("url")
        try:
            posts = feedmod.fetch(feed, cfg)
        except Exception as exc:
            print(f"{RED}!{RESET} {name}: {exc}")
            continue
        total += len(posts)
        for post in posts:
            hit = feedmod.match(post, rules)
            if not hit:
                continue
            matched += 1
            # Dedupe AFTER matching so the log reflects what qualified, and
            # record even non-alerting matches so a relay storm stays quiet.
            if not store.is_new(post.uid, post.feed, post.title):
                continue
            fresh += 1
            reason, urgency = hit
            flag = f"{RED}!!{RESET}" if urgency == "high" else f"{GREEN}${RESET}"
            print(f"{flag} {BOLD}{post.title}{RESET}\n   {DIM}{reason} · {post.feed}{RESET}")
            notify.send(channels, post.title, f"{reason} · {post.feed}", post.url, cfg)
        if not args.quiet:
            print(f"{DIM}  {name}: {len(posts)} posts{RESET}")

    if not args.quiet:
        print(f"{DIM}{total} posts, {matched} matched rules, {fresh} new{RESET}")


def cmd_buy(args):
    cfg, _, store = load_all()
    lot_id = ledger.add(store.db, what=args.what, retailer=args.retailer, kind=args.kind,
                        intent=args.intent, qty=args.qty, unit_price=args.paid,
                        tax=args.tax, purchase_ship=args.ship, normal_price=args.normal,
                        expected_resale=args.expect, notes=args.notes)
    lot = ledger.get(store.db, lot_id)
    basis = ledger.cost_basis(lot)
    print(f"#{lot_id} {args.what} x{args.qty} from {args.retailer}")
    print(f"   cost basis ${basis:,.2f}{DIM} (incl tax and inbound shipping){RESET}")
    if args.expect:
        fees = ledger.estimate_fees(args.platform, args.expect, cfg)
        proj = args.expect - fees - basis
        colour = GREEN if proj > 0 else RED
        print(f"   if it resells at ${args.expect:,.2f}: {colour}${proj:,.2f}{RESET} before outbound"
              f" shipping{DIM} (est. ${fees:,.2f} fees){RESET}")
    print(f"{DIM}   next: watch.py status {lot_id} received|cancelled{RESET}")


def cmd_status(args):
    cfg, _, store = load_all()
    if not ledger.set_status(store.db, args.lot_id, args.status):
        sys.exit(f"No lot #{args.lot_id}")
    print(f"#{args.lot_id} -> {args.status}")


def cmd_listed(args):
    cfg, _, store = load_all()
    if not ledger.mark_listed(store.db, args.lot_id, args.price, args.platform):
        sys.exit(f"No lot #{args.lot_id}")
    print(f"#{args.lot_id} listed at ${args.price:,.2f} on {args.platform}")


def cmd_sold(args):
    cfg, _, store = load_all()
    if not ledger.mark_sold(store.db, args.lot_id, args.price, args.fees,
                            args.ship, args.platform):
        sys.exit(f"No lot #{args.lot_id}")
    lot = ledger.get(store.db, args.lot_id)
    n, ann = ledger.net(lot, cfg), ledger.annualized(lot, cfg)
    days = ledger.holding_days(lot)
    colour = GREEN if n and n > 0 else RED
    est = "" if lot["fees"] is not None else f"{DIM} (fees estimated){RESET}"
    print(f"#{args.lot_id} sold ${args.price:,.2f} -> net {colour}${n:,.2f}{RESET}{est}")
    if ann is not None:
        print(f"   held {days:.0f} days, {ann * 100:,.0f}% annualized on ${ledger.cost_basis(lot):,.2f}")
    elif days is not None:
        print(f"   held {days:.0f} days {DIM}(too short to annualize meaningfully){RESET}")
    if lot["expected_resale"]:
        delta = args.price - lot["expected_resale"]
        mark = GREEN if delta >= 0 else YELLOW
        print(f"   expected ${lot['expected_resale']:,.2f}, got {mark}${delta:+,.2f}{RESET}")


def cmd_ledger(args):
    cfg, _, store = load_all()
    lots = ledger.all_lots(store.db)
    if not lots:
        sys.exit("Nothing logged yet.  watch.py buy \"Thing\" --retailer X --paid N")

    colours = {"sold": GREEN, "cancelled": RED, "returned": RED,
               "listed": YELLOW, "pending": YELLOW}
    print(f"{BOLD}Lots{RESET}")
    for r in lots:
        when = time.strftime("%Y-%m-%d", time.localtime(r["ordered_at"]))
        c = colours.get(r["status"], "")
        n = ledger.net(r, cfg)
        tail = f"net {GREEN if n > 0 else RED}${n:,.2f}{RESET}" if n is not None else ""
        print(f"  #{r['id']:<3} {when}  {r['retailer'][:12]:<12} {r['what'][:24]:<24} "
              f"${ledger.cost_basis(r):>8,.2f}  {c}{r['status']:<9}{RESET} {tail}")

    open_lots = [r for r in lots if r["status"] in ledger.OPEN_STATES]
    sold = [r for r in lots if r["status"] == "sold"]
    cancelled = [r for r in lots if r["status"] == "cancelled"]

    tied = sum(ledger.cost_basis(r) for r in open_lots)
    print(f"\n{BOLD}Position{RESET}")
    print(f"  open        {len(open_lots):>3} lots   ${tied:,.2f} tied up")
    if sold:
        nets = [ledger.net(r, cfg) for r in sold]
        anns = [a for a in (ledger.annualized(r, cfg) for r in sold) if a is not None]
        days = [d for d in (ledger.holding_days(r) for r in sold) if d is not None]
        total = sum(nets)
        c = GREEN if total > 0 else RED
        print(f"  sold        {len(sold):>3} lots   {c}${total:,.2f} net{RESET}"
              f"   {sum(1 for n in nets if n < 0)} at a loss")
        if days:
            line = f"  median hold {statistics.median(days):>3.0f} days"
            if anns:
                line += f"   median annualized {statistics.median(anns) * 100:,.0f}%"
            print(line)
    if cancelled:
        resolved = len(sold) + len([r for r in lots if r["status"] in ("received", "kept")]) \
            + len(cancelled)
        print(f"  cancelled   {len(cancelled):>3} lots   "
              f"{DIM}{len(cancelled) / resolved * 100:.0f}% of resolved orders{RESET}")

    by = {}
    for r in lots:
        if r["status"] == "pending":
            continue
        k = (r["retailer"], r["kind"])
        honored, total_n = by.get(k, (0, 0))
        by[k] = (honored + (0 if r["status"] == "cancelled" else 1), total_n + 1)
    if by:
        print(f"\n{BOLD}Honor rate{RESET}  {DIM}(the discount rate on your whole pipeline){RESET}")
        for (retailer, kind), (h, n) in sorted(by.items()):
            print(f"  {retailer[:16]:<16} {kind:<11} {h}/{n}  ({h / n * 100:.0f}%)")


def cmd_calibrate(args):
    """Predicted resale vs realised. The report that says whether you're good at this."""
    cfg, _, store = load_all()
    lots = [r for r in ledger.all_lots(store.db)
            if r["status"] == "sold" and r["expected_resale"]]
    if not lots:
        sys.exit("No sold lots with an --expect figure yet.\n"
                 "Pass --expect when you buy; this report is the point of it.")

    print(f"{BOLD}Predicted vs realised{RESET}")
    errs = []
    for r in lots:
        exp, got = r["expected_resale"], r["sold_price"]
        err = (got - exp) / exp * 100
        errs.append(err)
        c = GREEN if err >= 0 else YELLOW
        print(f"  #{r['id']:<3} {r['what'][:26]:<26} expected ${exp:>8,.2f}  got ${got:>8,.2f}"
              f"  {c}{err:+.0f}%{RESET}")

    med = statistics.median(errs)
    print(f"\n  median error {med:+.0f}% over {len(errs)} sales")
    if med < -10:
        print(f"  {YELLOW}You are systematically optimistic about resale prices.{RESET}")
        print(f"  {DIM}Discount future estimates by roughly {abs(med):.0f}% before deciding.{RESET}")
    elif med > 10:
        print(f"  {DIM}You are systematically pessimistic - you may be passing on good buys.{RESET}")
    else:
        print(f"  {DIM}Well calibrated. Your estimates can be trusted as inputs.{RESET}")

    by_kind = {}
    for r in lots:
        n = ledger.net(r, cfg)
        s, tot = by_kind.get(r["kind"], (0, 0.0))
        by_kind[r["kind"]] = (s + 1, tot + (n or 0))
    print(f"\n{BOLD}Net by kind{RESET}")
    for kind, (n, tot) in sorted(by_kind.items(), key=lambda kv: -kv[1][1]):
        print(f"  {kind:<12} {n:>3} sold   {GREEN if tot > 0 else RED}${tot:,.2f}{RESET}")


def cmd_check(args):
    """Hit every configured source once and report what came back."""
    cfg, items, _ = load_all()
    seen = {}
    for item in items:
        for src in item.get("sources") or []:
            seen.setdefault(src.get("type"), (item, src))

    print(f"{BOLD}Source adapter check{RESET}")
    for kind, (item, src) in sorted(seen.items()):
        try:
            q = sources.fetch(src, cfg)
        except Exception as exc:
            print(f"  {RED}FAIL{RESET} {kind:<10} {exc}")
            continue
        if q is None:
            print(f"  {YELLOW}EMPTY{RESET} {kind:<10} reachable, but no product returned")
        else:
            print(f"  {GREEN}OK{RESET}   {kind:<10} ${q.price:,.2f}  {(q.title or '')[:44]}")
    missing = set(sources.ADAPTERS) - set(seen) - {"fixture"}
    if missing:
        print(f"{DIM}Not exercised (nothing in watchlist uses them): {', '.join(sorted(missing))}{RESET}")


def cmd_history(args):
    cfg, items, store = load_all()
    rows = store.prices(args.item_id)
    if not rows:
        sys.exit(f"No observations for {args.item_id!r} yet.")
    prices = [p for p, _ in rows]
    print(f"{BOLD}{args.item_id}{RESET}  {len(rows)} observations")
    print(f"  low ${min(prices):,.2f}   high ${max(prices):,.2f}   latest ${prices[-1]:,.2f}")
    for price, seen in rows[-args.limit:]:
        print(f"  {time.strftime('%Y-%m-%d %H:%M', time.localtime(seen))}  ${price:,.2f}")


def cmd_test_alert(args):
    cfg, _, _ = load_all()
    channels = cfg.get("notify") or ["console"]
    ok = notify.send(channels, "Watcher test alert",
                     "If you can read this, the notification path works.",
                     "https://example.com", cfg)
    print(f"delivered via: {', '.join(ok) if ok else RED + 'nothing' + RESET}")


PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.perkfinder.watch</string>
  <key>ProgramArguments</key>
  <array>
    <string>{python}</string>
    <string>{script}</string>
    <string>poll</string>
    <string>--quiet</string>
  </array>
  <key>WorkingDirectory</key><string>{here}</string>
  <key>StartInterval</key><integer>{interval}</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>{here}/watch.log</string>
  <key>StandardErrorPath</key><string>{here}/watch.err</string>
</dict>
</plist>
"""


def cmd_install(args):
    plist = PLIST.format(python=sys.executable, script=os.path.join(HERE, "watch.py"),
                         here=HERE, interval=args.interval)
    dest = os.path.expanduser("~/Library/LaunchAgents/com.perkfinder.watch.plist")
    print(plist)
    print(f"{BOLD}To install:{RESET}")
    print(f"  python3 watch.py install --interval {args.interval} > {dest}")
    print(f"  launchctl unload {dest} 2>/dev/null; launchctl load {dest}")
    print(f"\n{DIM}Runs every {args.interval}s. launchd restarts it after reboot and after")
    print(f"crashes, which is why poll is a short-lived process rather than a daemon.")
    print(f"Logs land in {HERE}/watch.log and watch.err.{RESET}")
    print(f"\n{YELLOW}Note:{RESET} sub-minute polling only helps if the source allows it.")
    print(f"{DIM}Best Buy's API has rate limits; Keepa bills per token. 60-300s is the{RESET}")
    print(f"{DIM}sane range for a small watchlist.{RESET}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("poll", help="one pass over the watchlist")
    p.add_argument("--quiet", action="store_true", help="only print alerts (for launchd)")
    p.set_defaults(func=cmd_poll)

    p = sub.add_parser("feeds", help="read public deal feeds and alert on price errors")
    p.add_argument("--quiet", action="store_true")
    p.set_defaults(func=cmd_feeds)

    p = sub.add_parser("buy", help="log a purchase")
    p.add_argument("what")
    p.add_argument("--retailer", required=True)
    p.add_argument("--paid", type=float, required=True, help="unit price")
    p.add_argument("--qty", type=int, default=1)
    p.add_argument("--tax", type=float, default=0)
    p.add_argument("--ship", type=float, default=0, help="inbound shipping")
    p.add_argument("--normal", type=float, help="normal price, for reference")
    p.add_argument("--expect", type=float, help="what you think it resells for")
    p.add_argument("--platform", help="where you'd resell, for the fee estimate")
    p.add_argument("--kind", default="error", help="error | sale | clearance | eligibility")
    p.add_argument("--intent", default="undecided", choices=["keep", "resell", "undecided"])
    p.add_argument("--notes", default="")
    p.set_defaults(func=cmd_buy)

    p = sub.add_parser("status", help="move a lot to a new state")
    p.add_argument("lot_id", type=int)
    p.add_argument("status", choices=ledger.STATES)
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("listed", help="mark a lot listed for sale")
    p.add_argument("lot_id", type=int)
    p.add_argument("--price", type=float, required=True)
    p.add_argument("--platform", default="ebay")
    p.set_defaults(func=cmd_listed)

    p = sub.add_parser("sold", help="mark a lot sold")
    p.add_argument("lot_id", type=int)
    p.add_argument("--price", type=float, required=True)
    p.add_argument("--fees", type=float, help="actual fees; estimated if omitted")
    p.add_argument("--ship", type=float, default=0, help="outbound shipping")
    p.add_argument("--platform")
    p.set_defaults(func=cmd_sold)

    sub.add_parser("ledger", help="positions, P&L and honor rates").set_defaults(func=cmd_ledger)
    sub.add_parser("calibrate", help="predicted vs realised resale").set_defaults(func=cmd_calibrate)

    sub.add_parser("check", help="verify each source adapter").set_defaults(func=cmd_check)

    p = sub.add_parser("history", help="price history for one item")
    p.add_argument("item_id")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_history)

    sub.add_parser("test-alert", help="prove the notification path").set_defaults(func=cmd_test_alert)

    p = sub.add_parser("install", help="print the launchd plist")
    p.add_argument("--interval", type=int, default=120, help="seconds between polls")
    p.set_defaults(func=cmd_install)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
