#!/usr/bin/env python3
"""Watch a short list of products and alert when one is genuinely cheap.

Built for an always-on Mac: launchd runs `poll` on an interval, each run is a
short-lived process, and state lives in SQLite.

    python3 watch.py poll          one pass over the watchlist
    python3 watch.py check         verify each source adapter actually works
    python3 watch.py history <id>  price history for one item
    python3 watch.py test-alert    prove the notification path end to end
    python3 watch.py install       print the launchd plist for this checkout
"""

import argparse
import os
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

from watcher import notify, sources
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
