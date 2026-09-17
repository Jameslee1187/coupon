# perk-finder

Finds eligibility-gated retail discounts you qualify for — clothes, electronics,
home goods. Employee purchase programs, identity-verified pricing, trade
programs. Not the Honey/Rakuten kind.

## Why this is a different problem

Honey's unit is a **code string** matched to a **domain**, from a crowdsourced
pool that rots in days. This indexes **programs**: published, eligibility-gated
offers that brands deliberately extend to a defined group.

That's a slower-decaying dataset. "Does Samsung still run an EPP, does SheerID
still back Nike's first-responder discount" are program questions, and programs
outlive codes by years. Final verification happens when *you* log in — so the
tool never holds a secret or guesses whether a code is still alive.

The output is therefore sometimes a path, not a string: *"look for gift cards
inside your perk platform, not on Target's site."* That's the honest shape of
this data.

## What retail actually looks like

Scoping to retail moves the center of gravity. Three channels, roughly in order
of how much they'll return:

**Identity beats employment.** Apparel and home goods brands mostly don't run
employee programs — they run *identity*-gated discounts through SheerID, ID.me,
and UNiDAYS. Military, first responder, healthcare, teacher, student. One
verification unlocks dozens of brands, which is why `offers/identity-providers.yaml`
sorts first in the report: do those, and every brand entry downstream becomes
one click instead of one signup.

**Electronics is the exception.** Dell, Samsung, Lenovo, HP still run real
employee purchase programs gated on a work email domain, and they work at
almost any employer. Samsung's covers appliances too, so one registration
spans electronics and home goods.

**Everything else arrives as gift cards.** Most big retailers offer nothing at
all. Inside a perk platform the discount shows up as a gift card a few percent
below face value. Small — but it reaches retailers with no program, and it
*stacks*, because you're changing how you pay rather than asking for a discount.
Worth it on a planned appliance purchase, not on socks.

Underused fourth channel: **trade and pro programs**. Wayfair Professional,
Williams-Sonoma trade, Patagonia Pro. Eligibility is consistently looser than
the name implies — contractors, nonprofit staff, part-time instructors, and
volunteer first responders qualify far more often than they assume.

## "Is a 10% discount even worth it?"

Percentage is the wrong axis. 40% off a $60 hoodie is $24; 15% off a $2,000
appliance is $300. So the tool scores in **dollars, against purchases you
already intend to make**:

```yaml
planned_purchases:
  - item: "washer/dryer"
    category: home
    est_price: 1800
    brands: [samsung, lowe, home depot]   # optional, and it matters
```

An offer that touches nothing on that list correctly scores zero. That is the
point — the coupon industry's actual business model is discounts on things you
weren't going to buy, and this is the line that keeps that from happening to you.

Two distinctions the scoring depends on:

- **Merchant vs payment layer.** Brand offers are *alternatives* — you buy one
  laptop from one vendor, so Dell MPP and Samsung EPP never add together. Only
  payment-layer offers (discounted gift cards, platform cashback) stack on top
  of whatever vendor you pick.
- **Setup friction.** `once` amortizes to nothing — verify with ID.me one
  afternoon and it's free forever after. `per_purchase` costs you every time,
  and `application` may not be approved at all.

If you want the high-percentage filter anyway, `--min-pct 40` exists, and it
reports how much estimated value it just discarded so the tradeoff is visible.
On a typical profile it hides roughly 28 offers to keep 2, and the ones it keeps
are pro/trade programs — which is a real finding: **nothing else in gated retail
clears 40%.**

### Blank fields fail closed

An unfilled profile field looks exactly like genuine ineligibility — you just
see fewer offers, with no indication why. So the report ends with a **locked**
section: per blank field, the extra best-case dollars filling it in would add,
on the purchases you already listed. Fill in what's true before concluding the
channel is thin for you.

Merchant offers are ranked by **ceiling**, since the figure reported is a best
case. Ranking by midpoint can select an offer with a lower top end, which is
both misleading and, when computing unlock deltas, produced inverted ranges.

### Known limitation

Categories are coarse. A Logitech discount is not a laptop discount, and without
a `brands:` list a washer/dryer gets scored against mattress companies. Adding
brands per purchase fixes it. A proper product would need brand-level taxonomy;
a POC shouldn't build one before knowing whether the corpus is worth anything.

## Eligibility is compositional

A profile is a bag of attributes — employer, work email domain, profession,
school, memberships. An offer is a predicate over them. The question flips from
*"is there a code for this cart?"* to **"what do I qualify for that I don't
know about?"**

## Use

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install pyyaml requests
cp profile.example.yaml profile.yaml
$EDITOR profile.yaml
```

`profile.yaml` is gitignored — your employer and work email domain stay local.
On macOS it's `python3 -m pip`, not `pip`; the venv also avoids the
`externally-managed-environment` error a Homebrew Python raises. `requests` is
only needed for `--probe`.

Then:

```bash
python3 find.py                  # what you qualify for, scored in dollars
python3 find.py --category home  # electronics | apparel | home | meta
python3 find.py --all            # plus what you're missing, and why
python3 find.py --probe          # guess your employer's hidden perk portal
python3 find.py --min-pct 40     # deep discounts only, and what that costs you
python3 find.py --min-save 25    # hide offers worth under $25 to you
```

Don't paste a trailing `# comment` onto a command in zsh — interactive zsh
doesn't treat `#` as a comment, so it becomes an argument.

Fill in `profession` generously — it's the single highest-leverage field, and
the eligibility lists behind it are wider than the labels suggest.

## Layout

| path | what it holds |
|---|---|
| `offers/identity-providers.yaml` | ID.me, SheerID, UNiDAYS, GOVX. Do these first; they unlock the rest. |
| `offers/electronics.yaml` | Work-email EPPs — the strongest employer channel in retail. |
| `offers/apparel.yaml` | Identity- and pro-program-gated. |
| `offers/home-goods.yaml` | Identity-gated plus trade programs. |
| `offers/gift-cards.yaml` | How retail reaches you through a perk platform. |
| `offers/memberships.yaml` | Alumni, Costco. |
| `offers/platforms.yaml` | Perk platforms, portal URL patterns, catalog contents. |
| `offers/archive/` | Auto, telecom, travel, fitness. Not loaded — subdirectories are skipped. |

## The seed corpus is unverified

Every entry ships as `status: unverified` with a `confidence` rating. These are
starting points assembled from general knowledge of how these programs work —
percentages, exclusions, and eligibility shift constantly and some may already
be dead. `find.py` marks them so nothing reads as confirmed fact.

As you check each one, set `last_verified` and flip `status` to `verified` or
`dead`. Keep the dead ones: knowing a program ended saves re-investigating it
next year (see the Microsoft HUP entry).

Exclusions are where retail discounts actually die. A verified 10% that excludes
sale items and new releases is often worth less than the public sale you'd have
gotten anyway — so record exclusions in `notes` as you verify, not just the
headline number.

## Scope

Indexes **programs**, never individual codes. Brand employee stores are in the
corpus marked `not_accessible` as a boundary marker: those passes are named,
logged, and revocable, and passing one around gets the employee fired. A
personal single-use code is out of scope for the same reason, and it'd be dead
within days regardless.
