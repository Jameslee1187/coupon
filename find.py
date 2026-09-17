#!/usr/bin/env python3
"""
Find employment- and affiliation-gated discounts you're actually eligible for.

This is a map, not a code pool. It won't hand you a code string for most
entries — it tells you which programs exist, whether you plausibly qualify,
and where to go verify. You do the last step; that's what keeps it accurate.

    python3 find.py                # what you qualify for
    python3 find.py --all          # also show what you're missing and why
    python3 find.py --probe        # guess your employer's hidden perk portal
"""

import argparse
import glob
import os
import sys


try:
    import yaml
except ImportError:
    sys.exit(
        "PyYAML isn't installed.\n\n"
        "  python3 -m venv .venv\n"
        "  source .venv/bin/activate\n"
        "  python3 -m pip install pyyaml requests\n\n"
        "On macOS use python3 -m pip, not pip. The venv also avoids the\n"
        "'externally-managed-environment' error from a Homebrew Python."
    )

HERE = os.path.dirname(os.path.abspath(__file__))
CONTROL_SLUG = "zzq7xkvn-not-a-real-company"

BOLD, DIM, RESET = "\033[1m", "\033[2m", "\033[0m"
GREEN, YELLOW, RED = "\033[32m", "\033[33m", "\033[31m"


def load_profile():
    path = os.path.join(HERE, "profile.yaml")
    if not os.path.exists(path):
        sys.exit(
            "No profile.yaml found.\n"
            "  cp profile.example.yaml profile.yaml   and fill it in.\n"
            "  (profile.yaml is gitignored — it stays on your machine.)"
        )
    with open(path) as f:
        return yaml.safe_load(f) or {}


def load_offers():
    offers = []
    for path in sorted(glob.glob(os.path.join(HERE, "offers", "*.yaml"))):
        if os.path.basename(path) == "platforms.yaml":
            continue
        with open(path) as f:
            data = yaml.safe_load(f) or []
        for offer in data:
            offer["_source"] = os.path.basename(path)
            offers.append(offer)
    return offers


def load_platforms():
    with open(os.path.join(HERE, "offers", "platforms.yaml")) as f:
        return (yaml.safe_load(f) or {}).get("platforms", [])


def flatten(profile):
    """Profile -> flat attribute dict the eligibility predicates read."""
    emp = profile.get("employment") or {}
    edu = profile.get("education") or []
    loc = profile.get("location") or {}
    is_student = (
        emp.get("status") == "student"
        or profile.get("profession") == "student"
        or any(e.get("status") == "current_student" for e in edu)
    )
    return {
        "employment_status": emp.get("status"),
        "profession": profile.get("profession", "none"),
        "is_student": is_student,
        "has_perk_platform": bool(emp.get("perk_platform")),
        "verified_identities": profile.get("verified_identities") or [],
        "employer": emp.get("employer"),
        "employer_slug": emp.get("employer_slug"),
        "work_email_domain": emp.get("work_email_domain"),
        "perk_platform": emp.get("perk_platform"),
        "has_work_email": bool(emp.get("work_email_domain")),
        "has_education": bool(edu),
        "memberships": profile.get("memberships") or [],
        "country": loc.get("country"),
        "state": loc.get("state"),
        "interests": profile.get("interests") or [],
        "planned_purchases": profile.get("planned_purchases") or [],
    }


def evaluate(eligibility, attrs):
    """Return (eligible: bool, unmet: list[str]). Empty predicate = matches all."""
    unmet = []
    for key, expected in (eligibility or {}).items():
        if key.endswith("_in"):
            field = key[:-3]
            ok = attrs.get(field) in expected
            want = f"{field} in {expected}"
        elif key.endswith("_include"):
            field = key[:-8]
            ok = expected in (attrs.get(field) or [])
            want = f"{field} includes '{expected}'"
        else:
            ok = attrs.get(key) == expected
            want = f"{key} = {expected}"
        if not ok:
            unmet.append(want)
    return (not unmet), unmet


def confidence_marker(offer):
    if offer.get("status") == "discontinued":
        return f"{RED}[discontinued]{RESET}"
    return {
        "high": f"{GREEN}[high]{RESET}",
        "medium": f"{YELLOW}[medium]{RESET}",
        "low": f"{RED}[low]{RESET}",
    }.get(offer.get("confidence"), "[?]")


def pct_range(offer):
    est = offer.get("typical_discount_estimate") or {}
    if est.get("min_pct") is None:
        return None
    return est["min_pct"], est["max_pct"]


def applies_to(offer, purchase):
    """Payment-layer offers apply to any purchase; merchant offers to their category.

    An optional `brands` list on the purchase narrows merchant offers to vendors
    you'd actually consider — category alone is coarse (a Logitech discount is
    not a laptop discount)."""
    if offer.get("enabler"):
        return False
    if offer.get("layer") == "payment":
        return True
    if offer.get("category") != purchase.get("category"):
        return False
    brands = [b.lower() for b in (purchase.get("brands") or [])]
    if brands:
        return any(b in offer["brand"].lower() for b in brands)
    return True


def best_case(scored):
    """Best merchant offer (alternatives, pick one) plus all payment-layer offers."""
    merchant = [s for s in scored if s[0].get("layer") != "payment"]
    payment = [s for s in scored if s[0].get("layer") == "payment"]
    lo = hi = 0.0
    if merchant:
        # Rank by ceiling: the figure reported is a best case, so the offer with
        # the highest top end is the right pick. Ranking by midpoint could select
        # an offer with a LOWER ceiling, which made deltas come out inverted.
        best = max(merchant, key=lambda s: (s[2], s[1]))
        lo, hi = best[1], best[2]
    for _, p_lo, p_hi in payment:
        lo, hi = lo + p_lo, hi + p_hi
    return lo, hi


def score_against(offers, purchase, min_save=0):
    price = float(purchase.get("est_price", 0))
    out = []
    for o in offers:
        if not applies_to(o, purchase):
            continue
        rng = pct_range(o)
        if not rng:
            continue
        lo, hi = price * rng[0] / 100, price * rng[1] / 100
        if hi < min_save:
            continue
        out.append((o, lo, hi))
    return out


FIELD_LABEL = {
    "profession": "profession",
    "has_perk_platform": "employment.perk_platform",
    "is_student": "student status",
    "memberships": "memberships",
    "has_education": "education",
    "employment_status": "employment.status",
}


def locked_value(blocked, purchases, current):
    """Per blocking profile attribute, the extra best-case dollars it would unlock.

    Computed as a true delta: re-run best_case with the locked offers merged in
    and subtract what you already have, so a locked offer that merely beats an
    alternative you can already use only counts for the difference.
    """
    by_field = {}
    for offer, unmet in blocked:
        if pct_range(offer) and unmet:
            by_field.setdefault(unmet[0].split()[0], []).append(offer)

    rows = []
    for field, offers in by_field.items():
        lo = hi = 0.0
        for p in purchases:
            extra = score_against(offers, p)
            if not extra:
                continue
            cur_lo, cur_hi = current[id(p)]
            new_lo, new_hi = best_case(current["raw"][id(p)] + extra)
            d_lo, d_hi = new_lo - cur_lo, new_hi - cur_hi
            if d_hi <= 0:
                continue  # unlocking this adds nothing to the ceiling
            lo += max(0.0, min(d_lo, d_hi))
            hi += d_hi
        if hi > 0:
            rows.append((FIELD_LABEL.get(field, field), len(offers), lo, hi))
    return sorted(rows, key=lambda r: -r[3])


def value_report(eligible, blocked, attrs, min_save):
    purchases = attrs["planned_purchases"]
    if not purchases:
        print(f"\n{DIM}No planned_purchases in profile.yaml — add some to see what any of{RESET}")
        print(f"{DIM}this is actually worth in dollars. A percentage on its own can't tell you.{RESET}")
        return

    offers = [o for o, _ in eligible]
    grand_lo = grand_hi = 0.0
    hidden = 0
    current_totals = {"raw": {}}

    total_planned = sum(float(p.get("est_price", 0)) for p in purchases)
    print(f"\n{BOLD}What this is worth on what you're actually buying{RESET}")
    print(f"{DIM}{len(purchases)} planned purchases, ${total_planned:,.0f} total{RESET}")

    for p in purchases:
        price = float(p.get("est_price", 0))
        scored = score_against(offers, p, min_save)
        hidden += len(score_against(offers, p)) - len(scored)
        current_totals["raw"][id(p)] = scored
        current_totals[id(p)] = best_case(scored)

        label = p.get('item', '(unnamed)')
        narrowed = f" · {', '.join(p['brands'])}" if p.get("brands") else ""
        print(f"\n  {BOLD}{label}{RESET}  {DIM}${price:,.0f} · {p.get('category','?')}{narrowed}{RESET}")
        if not scored:
            print(f"    {DIM}nothing eligible applies{RESET}")
            continue

        merchant = [s for s in scored if s[0].get("layer") != "payment"]
        payment = [s for s in scored if s[0].get("layer") == "payment"]
        merchant.sort(key=lambda s: -(s[1] + s[2]))

        sub_lo = sub_hi = 0.0
        if merchant:
            print(f"    {DIM}pick one vendor (ranked by ceiling):{RESET}")
            for i, (o, lo, hi) in enumerate(merchant[:4]):
                mark = "*" if i == 0 else " "
                fr = o.get("friction", "?")
                print(f"     {mark} {o['brand'][:36]:<36} ${lo:>6,.0f}-{hi:<6,.0f} {DIM}[{fr}]{RESET}")
                if i == 0 and o.get("exclusions"):
                    print(f"       {DIM}! {o['exclusions']}{RESET}")
            if len(merchant) > 4:
                print(f"       {DIM}+{len(merchant)-4} more{RESET}")
            sub_lo, sub_hi = merchant[0][1], merchant[0][2]
        if payment:
            print(f"    {DIM}on top, any vendor:{RESET}")
            for o, lo, hi in sorted(payment, key=lambda s: (-s[2], -s[1])):
                print(f"       {o['brand'][:36]:<36} ${lo:>6,.0f}-{hi:<6,.0f} {DIM}[{o.get('friction','?')}]{RESET}")
                sub_lo, sub_hi = sub_lo + lo, sub_hi + hi

        print(f"    {BOLD}-> ${sub_lo:,.0f}-{sub_hi:,.0f}{RESET} {DIM}best case{RESET}")
        grand_lo, grand_hi = grand_lo + sub_lo, grand_hi + sub_hi

    pct = (grand_hi / total_planned * 100) if total_planned else 0
    print(f"\n{BOLD}Best case: ${grand_lo:,.0f}-{grand_hi:,.0f}{RESET}"
          f"  {DIM}({pct:.0f}% of planned spend, top end){RESET}")
    print(f"{DIM}Assumes you buy from the best-scoring vendor for each item. Switching{RESET}")
    print(f"{DIM}brands to capture a discount is usually a worse deal than it looks -{RESET}")
    print(f"{DIM}add `brands:` to a purchase to score only vendors you'd really consider.{RESET}")

    rows = locked_value(blocked, purchases, current_totals)
    if rows:
        print(f"\n{BOLD}Locked by blank or unset profile fields{RESET}")
        print(f"{DIM}What filling each one in would add, on these same purchases:{RESET}")
        for label, n, lo, hi in rows:
            print(f"  {label:<26} {n:>2} offers   {GREEN}+${lo:,.0f}-{hi:,.0f}{RESET}")
        print(f"{DIM}Blank fields fail closed, so an unfilled profile looks identical to{RESET}")
        print(f"{DIM}genuine ineligibility. Fill in what's true before concluding the{RESET}")
        print(f"{DIM}channel is thin for you.{RESET}")
    if hidden:
        print(f"{DIM}{hidden} offer/purchase pairs below the ${min_save:,.0f} threshold, hidden.{RESET}")
    print(f"{DIM}Estimates use rough priors, not verified figures. Treat the ordering as{RESET}")
    print(f"{DIM}signal and the absolute numbers as provisional until you verify entries.{RESET}")


def show(offer, attrs):
    print(f"\n  {BOLD}{offer['brand']}{RESET}  {confidence_marker(offer)}")
    rng = pct_range(offer)
    if rng:
        span = f"{rng[0]:g}%" if rng[0] == rng[1] else f"{rng[0]:g}-{rng[1]:g}%"
        extra = " · stacks" if offer.get("stacks") else ""
        print(f"    {DIM}est. {span}{extra} · setup: {offer.get('friction','?')}{RESET}")
    elif offer.get("enabler"):
        print(f"    {DIM}enabler — no discount itself, unlocks the entries below{RESET}")
    print(f"    {offer.get('benefit', '')}")
    if offer.get("exclusions"):
        print(f"    {DIM}exclusions:{RESET} {offer['exclusions']}")
    red = offer.get("redemption") or {}
    if red.get("method"):
        print(f"    {DIM}how:{RESET} {red['method']}")
    if red.get("url"):
        print(f"    {DIM}url:{RESET} {red['url']}")
    if offer.get("notes"):
        print(f"    {DIM}note:{RESET} {' '.join(offer['notes'].split())}")
    if offer.get("status") == "unverified":
        print(f"    {DIM}status: unverified — confirm before relying on it{RESET}")


def probe_portals(attrs, platforms):
    try:
        import requests
    except ImportError:
        sys.exit("--probe needs requests:  pip install requests")

    slug = attrs.get("employer_slug")
    if not slug:
        sys.exit("Set employment.employer_slug in profile.yaml to probe.")

    headers = {"User-Agent": "Mozilla/5.0 (compatible; personal-perk-finder/0.1)"}

    def fetch(url):
        try:
            r = requests.get(url, timeout=8, headers=headers, allow_redirects=True)
            return r.status_code, r.url
        except Exception as exc:
            return None, str(exc)

    print(f"\n{BOLD}Probing perk portals for slug '{slug}'{RESET}")
    print(f"{DIM}A control slug is checked first — many of these hosts answer 200 for{RESET}")
    print(f"{DIM}anything, so a bare 200 on your slug proves nothing by itself.{RESET}")

    hits, errors, attempts = [], 0, 0
    for plat in platforms:
        for tmpl in plat.get("probe") or []:
            control_code, _ = fetch(tmpl.format(slug=CONTROL_SLUG))
            code, final = fetch(tmpl.format(slug=slug))
            url = tmpl.format(slug=slug)

            attempts += 1
            if code is None:
                errors += 1
                verdict = f"{DIM}no response ({final[:48]}){RESET}"
            elif code == control_code:
                verdict = f"{DIM}inconclusive (catch-all: control also {control_code}){RESET}"
            elif 200 <= code < 400:
                verdict = f"{GREEN}LIKELY HIT ({code}, control {control_code}){RESET}"
                hits.append((plat["name"], final))
            else:
                verdict = f"{DIM}no ({code}){RESET}"
            print(f"  {plat['name']:<24} {url:<52} {verdict}")

    print()
    if attempts and errors == attempts:
        print(f"{YELLOW}Every probe failed at the network layer, not at the host.{RESET}")
        print(f"{DIM}Outbound HTTPS looks blocked here (proxy/firewall/DNS) — this says{RESET}")
        print(f"{DIM}nothing about whether your employer has a portal. Rerun somewhere{RESET}")
        print(f"{DIM}with open egress.{RESET}")
        return
    if hits:
        print(f"{BOLD}{GREEN}Worth opening:{RESET}")
        for name, url in hits:
            print(f"  {name}: {url}")
    else:
        print(f"{DIM}No clear hit. That doesn't mean you have no portal — most are behind{RESET}")
        print(f"{DIM}SSO with no public subdomain. Better sources: your benefits enrollment{RESET}")
        print(f"{DIM}site, the HR intranet search box, or just asking HR what perks vendor{RESET}")
        print(f"{DIM}they use. One question to HR beats any amount of probing.{RESET}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="also show offers you don't qualify for")
    ap.add_argument("--probe", action="store_true", help="probe for your employer's perk portal")
    ap.add_argument("--category", help="filter: electronics | apparel | home | meta")
    ap.add_argument("--min-pct", type=float, default=0,
                    help="hide offers whose top-end discount is below this percent")
    ap.add_argument("--min-save", type=float, default=0,
                    help="in the value report, hide offers saving less than this many dollars")
    args = ap.parse_args()

    profile = load_profile()
    attrs = flatten(profile)
    offers = load_offers()
    platforms = load_platforms()
    if args.category:
        offers = [o for o in offers if o.get("category") == args.category]

    dropped_by_pct = []
    if args.min_pct:
        kept = []
        for o in offers:
            rng = pct_range(o)
            if rng and rng[1] < args.min_pct:
                dropped_by_pct.append(o)
            else:
                kept.append(o)
        offers = kept

    eligible, blocked, dead = [], [], []
    for offer in offers:
        if offer.get("status") in ("discontinued", "not_accessible"):
            dead.append(offer)
            continue
        ok, unmet = evaluate(offer.get("eligibility"), attrs)
        (eligible if ok else blocked).append((offer, unmet))

    interests = attrs["interests"]
    eligible.sort(key=lambda t: (
        0 if t[0].get("category") == "meta" else 1,
        interests.index(t[0].get("category")) if t[0].get("category") in interests else 99,
        {"high": 0, "medium": 1, "low": 2}.get(t[0].get("confidence"), 3),
    ))

    who = attrs.get("employer") or "you"
    print(f"\n{BOLD}Eligible offers for {who} — {len(eligible)} of {len(offers)}{RESET}")
    for offer, _ in eligible:
        show(offer, attrs)

    if attrs.get("perk_platform"):
        plat = next((p for p in platforms if p["id"] == attrs["perk_platform"]), None)
        if plat:
            print(f"\n{BOLD}Your perk platform: {plat['name']}{RESET}")
            print(f"    {plat['home']}")
            print(f"    {DIM}{plat.get('catalog_notes','')}{RESET}")

    if args.all and blocked:
        print(f"\n{BOLD}Not eligible — and what would change that{RESET}")
        for offer, unmet in blocked:
            print(f"\n  {offer['brand']}: needs {', '.join(unmet)}")

    if dead:
        print(f"\n{BOLD}Known dead or out of reach — don't chase{RESET}")
        for offer in dead:
            print(f"  {DIM}{offer['brand']}: {offer.get('notes', '')}{RESET}")

    unverified = sum(1 for o, _ in eligible if o.get("status") == "unverified")
    if unverified:
        print(f"\n{YELLOW}{unverified} of these are unverified seed data.{RESET} "
              f"As you check them, set last_verified and flip status to 'verified' or 'dead'.")

    value_report(eligible, blocked, attrs, args.min_save)

    if dropped_by_pct:
        lost_lo = lost_hi = 0.0
        for p in attrs["planned_purchases"]:
            price = float(p.get("est_price", 0))
            for o in dropped_by_pct:
                if applies_to(o, p) and pct_range(o):
                    lo, hi = pct_range(o)
                    lost_lo += price * lo / 100
                    lost_hi += price * hi / 100
        print(f"\n{YELLOW}--min-pct {args.min_pct:g} hid {len(dropped_by_pct)} offers.{RESET}")
        if lost_hi:
            print(f"{DIM}On your planned purchases those were worth ${lost_lo:,.0f}-{lost_hi:,.0f}.{RESET}")
            print(f"{DIM}Percentage is not value: a stacking 5% on an appliance beats a{RESET}")
            print(f"{DIM}headline 40% that excludes everything you'd buy.{RESET}")

    if args.probe:
        probe_portals(attrs, platforms)
    print()


if __name__ == "__main__":
    main()
