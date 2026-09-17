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

## Two layers, because a watchlist can't catch an error

A watchlist structurally cannot catch price errors: errors land on SKUs nobody
predicted. If you'd listed the item in advance you'd be watching a product, not
hunting a glitch. So there are two commands doing different jobs:

- **`poll`** — watchlist monitoring. Catches real lows on things you want.
- **`feeds`** — reads public deal feeds and alerts on posts flagged as errors,
  plus anything matching your keywords. This is the one that catches glitches.

Run both on separate launchd intervals; `feeds` can be slower (2–5 min) since
you're reading a relay rather than racing to detect.

### Why not Discord and X

Reading a Discord server you don't administer means automating a user account —
a "self-bot" — which violates Discord's ToS and gets accounts banned. A bot
account only works in servers that permit bots and where you can add one. X's
API is now $100+/month for a tier that would do this, and Nitter is dead.

A large share of what gets relayed to X and Discord **originates on Slickdeals
and a handful of subreddits**, both of which publish RSS with no auth and no ToS
problem. You trade a minute or two of latency for not risking an account.

### Keeping it quiet enough to keep reading

A feed you mute is worth nothing, so precision beats recall here. Three controls:

- **`max_spend`** — capital, not taste. An alert you can't fund is noise however
  good the deal is, and unfundable alerts are the fastest way to train yourself
  to ignore the feed.
- **`max_alerts_per_day`** — a noise budget. When it binds, error-flagged posts
  survive and ordinary keyword matches are the ones dropped.
- **`watch.py mute <term>`** — tune without hand-editing YAML. `--remove` to undo,
  and `watch.py recent --suppressed` shows what the budget ate so you can catch
  a false negative.

### The error-label signal

Those communities tag errors explicitly — "price error", "glitch", "mispriced".
Matching on those labels is unusually high precision, and it fires regardless of
your keyword list, because a 90%-off *anything* is worth knowing about even if
you'd never have thought to watch it.

## The ledger

Every purchase gets logged with its cost basis at purchase time, because
reconstructing basis a year later from bank statements is miserable — and if
resale ever becomes regular, that's Schedule C and the platforms will issue you
a 1099-K.

```bash
python3 watch.py buy "Sony XM5" --retailer bestbuy --paid 27.99 --tax 2.40 \
    --expect 250 --platform ebay --intent resell
python3 watch.py status 1 received        # or cancelled
python3 watch.py listed 1 --price 260
python3 watch.py sold 1 --price 240 --ship 18.50
python3 watch.py ledger
python3 watch.py calibrate
```

`buy` projects the margin immediately, so you find out at order time rather than
at sale time that fees eat the deal:

```
#1 Sony XM5 x1 from bestbuy
   cost basis $30.39 (incl tax and inbound shipping)
   if it resells at $250.00: $186.49 before outbound shipping (est. $33.12 fees)
```

### Three numbers the deal accounts never show you

**Honor rate.** Price errors get cancelled — terms of sale generally reserve the
right, since a listing is an invitation to treat rather than a binding offer. So
the expected value of an error is the discount *times* the honor rate, and that
varies a lot by retailer. `ledger` accumulates yours. A cancelled order is
invisible in a deal account's engagement numbers, which is exactly why this has
to be measured rather than read.

**Annualized return.** A $200 margin on something that sits eight months is
worse than $40 on something that moves in a week, because the second recycles
your capital ten times. Margin alone hides this. Holds under a week aren't
annualized at all — a two-day flip annualizes to tens of thousands of percent,
which is arithmetically correct and completely useless, since you can't repeat
it 180 times a year.

**Calibration.** `calibrate` compares what you *expected* an item to resell for
against what it actually fetched, and tells you your median error:

```
  median error -19% over 11 sales
  You are systematically optimistic about resale prices.
  Discount future estimates by roughly 19% before deciding.
```

This is the report worth building the rest for. Almost nobody measures it, and
it's what separates people who make money from people who believe they do.

## Cold start## Cold start

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

`telegram` is the best option if you already run a bot: real links, and the
alerts persist in a chat you can scroll back through. Create one with
@BotFather, message it once, then read your chat id from
`https://api.telegram.org/bot<TOKEN>/getUpdates`.

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
