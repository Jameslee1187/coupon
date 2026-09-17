# watcher

Watches a short list of products and alerts you when one is *actually* cheap.

This is the opposite problem from [the perk finder](README.md). That one answers
"what discounts am I eligible for" — static, public, slow-moving, and no edge,
since anyone can google their way to the same list. This one answers "what is
mispriced right now," which is a sensor, not a reference book.

## What it can and can't catch

Deal accounts blur five different things together:

| Kind | Catchable here? |
|---|---|
| **Price errors** — decimal slips, bad feed imports | Yes, if you're watching that SKU. This is what all-time-low detection is for. |
| **Clearance / liquidation** | Yes. Slower-moving, so polling interval barely matters. |
| **Real flash sales** — Woot, Lightning, open-box | Yes, if polling is frequent enough and the SKU is on your list. |
| **Stacked deals** — gift card + portal + card offer | No. No monitoring involved; that's a calculation, and it's what the perk corpus feeds. |
| **Repackaged community finds** | No, and this won't beat a tipster network. See below. |

## The honest limit

You will not out-run the deal accounts on *generic* finds. They have tipster
networks, private Discords, and an affiliate incentive to post volume. A solo
poller loses that race.

The edge is different: **relevance beats speed when the list is narrow.** You
don't need to be first in the world, only first among people buying the twenty
things you actually want. A 60-second poll on a small watchlist gets you there,
and a broadcast feed can't, because you'll miss the one item you cared about in
the noise of four hundred you didn't.

Corollary: **keep the watchlist short.** A watchlist you'd genuinely act on
beats a firehose you learn to ignore within a week.

## Cold start

A fresh watchlist has no price history, so "is this cheap?" is unanswerable.
Handled two ways:

- `target_price` works on day one. You name a number you'd happily pay.
- Statistical rules (all-time-low, percent-below-median) stay **off** until
  `min_observations` accumulate. Below that they stay silent rather than
  guessing, because a confident alert from four data points is worse than none.
- Keepa backfills full Amazon history, so Amazon items skip the wait entirely.

This is also why "50% off" in a deal feed means little — it's usually measured
against an inflated list price. Your own history is the only honest baseline.

## Sources

| Source | Access | Notes |
|---|---|---|
| **Best Buy** | Official public API, free key at developer.bestbuy.com | Cleanest. Start here. |
| **Shopify DTC brands** | `/products/<handle>.js`, no auth | Most DTC brands are Shopify. Returns per-variant price and stock. Badly underrated. |
| **Target** | Unofficial RedSky endpoint | Key comes from browser devtools and rotates. Expect to re-grab it. |
| **Amazon** | Keepa API, paid | The only realistic path. PA-API requires qualifying affiliate sales first, and the storefront is aggressively bot-blocked. |

**Only the `fixture` adapter is verified.** The four network adapters were
written against documented and observed API shapes but have never been run
against the live services. Run `python3 watch.py check` on the Mac before
trusting a quiet alert stream to mean "no deals" — it may mean "every adapter is
broken."

## Setup

```bash
source .venv/bin/activate
cp watch-config.example.yaml watch-config.yaml
cp watchlist.example.yaml watchlist.yaml
```

Edit both, then:

```bash
python3 watch.py check        # do the adapters actually work?
python3 watch.py test-alert   # does the notification reach your phone?
python3 watch.py poll         # one pass
```

Run `check` and `test-alert` before installing. Both fail loudly, which is what
you want — a silent watcher is indistinguishable from a working one with
nothing to report.

### Always-on via launchd

```bash
python3 watch.py install --interval 120 > ~/Library/LaunchAgents/com.perkfinder.watch.plist
launchctl load ~/Library/LaunchAgents/com.perkfinder.watch.plist
```

`poll` is a short-lived process rather than a daemon, so launchd restarts it
after reboots and crashes for free. Logs go to `watch.log` and `watch.err`.

Sub-minute polling only helps if the source tolerates it — Best Buy rate-limits
and Keepa bills per token. **60–300s is the sane range** for a small watchlist.

### Alerts

`ntfy` pushes to your phone free with no account: pick an unguessable topic,
subscribe to it in the ntfy app. Anyone who knows the topic string can read your
alerts, so don't use your name. `macos` posts a local banner, useless when
you're away from the Mac. `console` is for testing.

Alerts have a cooldown, keyed on **price as well as time** — a further drop
still gets through, because a cooldown that swallows a better price is worse
than no cooldown at all.

## Files

| path | what |
|---|---|
| `watch.py` | CLI: poll, check, history, test-alert, install |
| `watcher/sources.py` | Per-retailer adapters |
| `watcher/store.py` | SQLite price history + the deal rules |
| `watcher/notify.py` | ntfy / macOS / console |
| `watchlist.yaml` | Your list. Gitignored. |
| `watch-config.yaml` | API keys. Gitignored. |
| `prices.db` | Accumulated history. Gitignored — and it's the asset; back it up. |
