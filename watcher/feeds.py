"""Ingest public deal feeds and surface the few posts worth waking you for.

A watchlist cannot catch price errors - errors land on SKUs nobody predicted.
The communities that catch them are relays, so this reads the public origins of
that relay traffic (Slickdeals, deal subreddits) rather than trying to guess
which product will break.

Deliberately NOT here: Discord scraping. Reading a server you do not administer
means automating a user account, which violates Discord's ToS and gets accounts
banned. A bot account works only in servers that allow bots and where you can
add one.
"""

import html
import re
import xml.etree.ElementTree as ET

from collections import namedtuple

Post = namedtuple("Post", "uid title url feed price")

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) deal-watcher/0.1"

ATOM = "{http://www.w3.org/2005/Atom}"

# "$1,299.99" / "$49" / "49.99" preceded by a $
PRICE_RE = re.compile(r"\$\s?([0-9][0-9,]*(?:\.[0-9]{2})?)")


def _text(node):
    return html.unescape((node.text or "").strip()) if node is not None else ""


def parse_feed(xml_text, feed_name):
    """Handle RSS 2.0 and Atom without pulling in a dependency."""
    root = ET.fromstring(xml_text)
    posts = []

    for item in root.iter("item"):                      # RSS 2.0
        title = _text(item.find("title"))
        link = _text(item.find("link"))
        uid = _text(item.find("guid")) or link or title
        posts.append(Post(uid, title, link, feed_name, extract_price(title)))

    for entry in root.iter(f"{ATOM}entry"):             # Atom (Reddit)
        title = _text(entry.find(f"{ATOM}title"))
        link_el = entry.find(f"{ATOM}link")
        link = link_el.get("href") if link_el is not None else ""
        uid = _text(entry.find(f"{ATOM}id")) or link or title
        posts.append(Post(uid, title, link, feed_name, extract_price(title)))

    return posts


def extract_price(title):
    m = PRICE_RE.search(title or "")
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def fetch(feed, cfg):
    import requests
    if feed.get("type") == "reddit":
        url = f"https://www.reddit.com/r/{feed['subreddit']}/new/.rss"
    else:
        url = feed["url"]
    r = requests.get(url, timeout=20, headers={"User-Agent": UA})
    r.raise_for_status()
    return parse_feed(r.text, feed.get("name") or url)


def match(post, rules):
    """Return (reason, urgency) when a post is worth alerting on, else None.

    Two independent ways to qualify:
      - it names something you actually want, or
      - the community flagged it as an error, whatever it is.

    The second matters most. A 90%-off anything is worth knowing about even if
    you would never have put it on a list, and those communities label errors
    explicitly, which makes it an unusually high-precision signal.
    """
    title = (post.title or "").lower()

    for bad in rules.get("exclude") or []:
        if bad.lower() in title:
            return None

    signals = [s.lower() for s in (rules.get("error_signals") or [])]
    hit_signal = next((s for s in signals if s in title), None)

    includes = [k.lower() for k in (rules.get("include") or [])]
    hit_include = next((k for k in includes if k in title), None)

    # Two different ceilings. max_price is taste - things above it don't
    # interest you. max_spend is capital - an alert you cannot fund is noise
    # however good the deal is, and unfundable alerts are the fastest way to
    # train someone to ignore the feed.
    for key in ("max_price", "max_spend"):
        cap = rules.get(key)
        if cap and post.price is not None and post.price > float(cap):
            return None

    if hit_signal:
        return f"flagged '{hit_signal}'", "high"
    if hit_include:
        return f"matches '{hit_include}'", "default"
    return None


URGENCY_RANK = {"high": 0, "default": 1}


def rank(matched):
    """Order (post, reason, urgency) so that when the noise budget binds, the
    error-flagged posts survive and the keyword matches are the ones dropped."""
    return sorted(matched, key=lambda m: (URGENCY_RANK.get(m[2], 9),
                                          m[0].price if m[0].price is not None else 1e9))
