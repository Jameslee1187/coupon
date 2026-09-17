"""Price source adapters.

Each adapter takes the `source` dict from watchlist.yaml plus the global config
and returns a Quote, or None when the product can't be read.

IMPORTANT: only `fixture` is verified. The network adapters below were written
against documented/observed API shapes but have NOT been exercised against the
live services from this machine. Run `python3 watch.py check` on the Mac mini to
validate each one before trusting an empty alert stream to mean "no deals".
"""

import json
import urllib.parse
from collections import namedtuple

Quote = namedtuple("Quote", "price available url title")

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 " \
     "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"


def _get(url, headers=None, timeout=15):
    import requests
    r = requests.get(url, timeout=timeout, headers={"User-Agent": UA, **(headers or {})})
    r.raise_for_status()
    return r


# --------------------------------------------------------------------------
# fixture: offline, for testing the pipeline without touching a network
# --------------------------------------------------------------------------
def fixture(src, cfg):
    return Quote(float(src["price"]), bool(src.get("available", True)),
                 src.get("url", "https://example.invalid/item"), src.get("title", "Fixture item"))


# --------------------------------------------------------------------------
# Best Buy: official public API. Free key at developer.bestbuy.com
# --------------------------------------------------------------------------
def bestbuy(src, cfg):
    key = cfg.get("bestbuy_api_key")
    if not key:
        raise RuntimeError("bestbuy_api_key missing from watch-config.yaml")
    sku = src["sku"]
    url = (f"https://api.bestbuy.com/v1/products(sku={sku})"
           f"?apiKey={key}&format=json"
           f"&show=sku,name,salePrice,regularPrice,onlineAvailability,url")
    data = _get(url).json()
    items = data.get("products") or []
    if not items:
        return None
    p = items[0]
    return Quote(float(p["salePrice"]), bool(p.get("onlineAvailability", True)),
                 p.get("url"), p.get("name"))


# --------------------------------------------------------------------------
# Shopify: most DTC brands. /products/<handle>.js needs no auth and returns
# per-variant price (in cents) and availability.
# --------------------------------------------------------------------------
def shopify(src, cfg):
    base = src["base"].rstrip("/")
    handle = src["handle"]
    data = _get(f"{base}/products/{handle}.js").json()
    variants = data.get("variants") or []
    if not variants:
        return None
    want = src.get("variant")
    chosen = None
    if want:
        for v in variants:
            if want.lower() in (v.get("title") or "").lower() or str(v.get("id")) == str(want):
                chosen = v
                break
        if chosen is None:
            return None
    else:
        available = [v for v in variants if v.get("available")]
        chosen = min(available or variants, key=lambda v: v["price"])
    return Quote(chosen["price"] / 100.0, bool(chosen.get("available")),
                 f"{base}/products/{handle}", data.get("title"))


# --------------------------------------------------------------------------
# Target: unofficial RedSky endpoint. The api_key is the public web key, read
# from a network request in browser devtools on target.com. It rotates, so
# expect this adapter to need re-keying periodically.
# --------------------------------------------------------------------------
def target(src, cfg):
    key = cfg.get("target_api_key")
    if not key:
        raise RuntimeError("target_api_key missing (grab it from target.com devtools)")
    tcin = src["tcin"]
    params = urllib.parse.urlencode({
        "key": key, "tcin": tcin,
        "store_id": src.get("store_id", cfg.get("target_store_id", "1771")),
        "pricing_store_id": src.get("store_id", cfg.get("target_store_id", "1771")),
        "has_pricing_store_id": "true",
    })
    data = _get(f"https://redsky.target.com/redsky_aggregations/v1/web/pdp_client_v1?{params}").json()
    product = (data.get("data") or {}).get("product") or {}
    price = (product.get("price") or {}).get("current_retail")
    if price is None:
        return None
    title = ((product.get("item") or {}).get("product_description") or {}).get("title")
    return Quote(float(price), True, f"https://www.target.com/p/-/A-{tcin}", title)


# --------------------------------------------------------------------------
# Amazon via Keepa. Paid, but it returns full historical pricing, which solves
# the cold-start problem outright. Direct Amazon scraping is not a realistic
# option: PA-API needs qualifying affiliate sales first, and the storefront is
# aggressively bot-blocked.
# --------------------------------------------------------------------------
def keepa(src, cfg):
    key = cfg.get("keepa_api_key")
    if not key:
        raise RuntimeError("keepa_api_key missing from watch-config.yaml")
    asin = src["asin"]
    domain = src.get("domain", 1)  # 1 = amazon.com
    data = _get(f"https://api.keepa.com/product?key={key}&domain={domain}&asin={asin}&stats=1").json()
    products = data.get("products") or []
    if not products:
        return None
    p = products[0]
    stats = p.get("stats") or {}
    current = stats.get("current") or []
    # Keepa index 0 = Amazon, 1 = marketplace new. Prices are in cents; -1 = no offer.
    candidates = [c for c in current[:2] if isinstance(c, int) and c > 0]
    if not candidates:
        return Quote(0.0, False, f"https://www.amazon.com/dp/{asin}", p.get("title"))
    return Quote(min(candidates) / 100.0, True,
                 f"https://www.amazon.com/dp/{asin}", p.get("title"))


ADAPTERS = {
    "fixture": fixture,
    "bestbuy": bestbuy,
    "shopify": shopify,
    "target": target,
    "keepa": keepa,
}


def fetch(src, cfg):
    kind = src.get("type")
    fn = ADAPTERS.get(kind)
    if not fn:
        raise RuntimeError(f"unknown source type: {kind!r} (have: {', '.join(ADAPTERS)})")
    return fn(src, cfg)
