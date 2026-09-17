# perk-finder

Finds employment- and affiliation-gated discounts you're eligible for — employee
purchase programs, corporate rate codes, employer perk platforms. Not the
Honey/Rakuten kind.

## Why this is a different problem

Honey's unit is a **code string** matched to a **domain**, from a crowdsourced
pool that rots in days. This indexes **programs**: published, eligibility-gated
offers that brands deliberately extend to a defined group.

That's a slower-decaying dataset. "Does Acme still use PerkSpot, and does
PerkSpot still carry Dell?" are contract questions, and contracts last years.
The final verification is done by you, logging in — so the tool never has to
hold a secret or guess whether a code is still alive.

The output is therefore sometimes a path, not a string: *"log into your perks
portal and search Dell."* That's the honest shape of this data.

## Eligibility is compositional

A profile is a bag of attributes — employer, work email domain, school,
memberships, military status, location. An offer is a predicate over them. The
question flips from *"is there a code for this cart?"* to **"what do I qualify
for that I don't know about?"**

## Use

```bash
cp profile.example.yaml profile.yaml    # gitignored; stays local
$EDITOR profile.yaml
python3 find.py                         # what you qualify for
python3 find.py --all                   # plus what you're missing and why
python3 find.py --probe                 # guess your employer's hidden portal
```

Needs `pyyaml`, plus `requests` for `--probe`.

## Layout

| path | what it holds |
|---|---|
| `offers/work-email-verified.yaml` | Gated on proof of employment, not a specific employer. Works for almost anyone with a real work email — this is the cold-start engine. |
| `offers/platforms.yaml` | The perk platforms, their portal URL patterns, and what their catalogs typically contain. |
| `offers/affiliation.yaml` | Alumni, credit union, membership, military. |
| `profile.yaml` | You. Gitignored. |

## The seed corpus is unverified

Every entry ships as `status: unverified` with a `confidence` rating. These are
starting points assembled from general knowledge of how these programs work —
terms, percentages, and eligibility shift constantly, and some may already be
dead. `find.py` marks them so nothing here reads as confirmed fact.

As you check each one, set `last_verified` and flip `status` to `verified` or
`dead`. A `dead` entry is worth keeping: knowing a program ended saves you
re-investigating it next year (see the Microsoft HUP entry).

## Two things worth knowing about `--probe`

It checks whether `{your-employer}.perksatwork.com` and friends resolve. It
probes a deliberately fake control slug first, because several of these hosts
answer `200` for anything — a bare `200` on your slug proves nothing without
the control to compare against.

It's also low-yield by design: most real portals sit behind SSO with no public
subdomain. Asking HR which perks vendor they use beats any amount of probing.

## Scope

Indexes **programs**, never individual codes. Someone's personal single-use
employee code isn't in scope — it's account-bound, it gets that employee in
trouble, and it's dead within days anyway. Corporate rate codes belong to your
employer; use your own.
