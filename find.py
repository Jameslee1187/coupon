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

import yaml

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
    mil = profile.get("military") or {}
    loc = profile.get("location") or {}
    return {
        "employment_status": emp.get("status"),
        "employer": emp.get("employer"),
        "employer_slug": emp.get("employer_slug"),
        "work_email_domain": emp.get("work_email_domain"),
        "perk_platform": emp.get("perk_platform"),
        "has_work_email": bool(emp.get("work_email_domain")),
        "has_education": bool(edu),
        "memberships": profile.get("memberships") or [],
        "military_status": mil.get("status", "none"),
        "country": loc.get("country"),
        "state": loc.get("state"),
        "interests": profile.get("interests") or [],
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


def show(offer, attrs):
    print(f"\n  {BOLD}{offer['brand']}{RESET}  {confidence_marker(offer)}")
    print(f"    {offer.get('benefit', '')}")
    red = offer.get("redemption") or {}
    if red.get("method"):
        print(f"    {DIM}how:{RESET} {red['method']}")
    if red.get("url"):
        print(f"    {DIM}url:{RESET} {red['url']}")
    if offer.get("notes"):
        print(f"    {DIM}note:{RESET} {offer['notes']}")
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
    args = ap.parse_args()

    profile = load_profile()
    attrs = flatten(profile)
    offers = load_offers()
    platforms = load_platforms()

    eligible, blocked, dead = [], [], []
    for offer in offers:
        if offer.get("status") == "discontinued":
            dead.append(offer)
            continue
        ok, unmet = evaluate(offer.get("eligibility"), attrs)
        (eligible if ok else blocked).append((offer, unmet))

    interests = attrs["interests"]
    eligible.sort(key=lambda t: (
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
        print(f"\n{DIM}Known dead, don't chase: {', '.join(o['brand'] for o in dead)}{RESET}")

    unverified = sum(1 for o, _ in eligible if o.get("status") == "unverified")
    if unverified:
        print(f"\n{YELLOW}{unverified} of these are unverified seed data.{RESET} "
              f"As you check them, set last_verified and flip status to 'verified' or 'dead'.")

    if args.probe:
        probe_portals(attrs, platforms)
    print()


if __name__ == "__main__":
    main()
