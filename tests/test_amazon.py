"""Amazon: scan every tracked energy drink, and only count real deals.

- Amazon URLs match by ASIN (provenance works whatever slug/ref the search returned).
- Seller must be Amazon.com or the brand's own store; third-party resellers are dropped,
  an unknown seller keeps the offer hidden (unverified) until a page shows the seller.
- Percent clip coupons are applied; Subscribe & Save stays a shown %, tiers decide "good deal".
- Every scan plans an Amazon job; deep runs cover every energy drink.
"""
from datetime import date

import pytest

from radar.util import normalize_url

AMZ = "https://www.amazon.com/Celsius-Essentials-Sparkling-Dragonberry/dp/B0C1234567/ref=sr_1_3?keywords=celsius"


def test_amazon_urls_canonical_by_asin():
    want = "https://amazon.com/dp/B0C1234567"
    assert normalize_url(AMZ) == want
    assert normalize_url("https://amazon.com/dp/B0C1234567?th=1&psc=1") == want
    assert normalize_url("https://www.amazon.com/gp/product/B0C1234567/") == want


def _amz(**kw):
    o = {"product_id": "celsius-essentials-16", "retailer": "Amazon", "source_url": AMZ, "pack_count": 12,
         "pack_price": 19.99, "unit_size_oz": 16,
         "evidence_text": "CELSIUS ESSENTIALS Sparkling Dragonberry, 16 Fl Oz (Pack of 12) $19.99"}
    o.update(kw)
    return o


def _validate(cfg, offers):
    from radar.validate import validate_offers
    urls = {normalize_url(AMZ): AMZ}
    return validate_offers(offers, cfg, urls, {}, [], date(2026, 11, 16))


@pytest.mark.parametrize("seller,kept", [
    ("Ships from Amazon.com, Sold by Amazon.com", True),
    ("Ships from Amazon, Sold by CELSIUS", True),            # brand's own store
    ("Ships from Amazon, Sold by Bev Deals Wholesale LLC", False),
])
def test_amazon_seller_rule(cfg, seller, kept):
    k, d = _validate(cfg, [_amz(seller=seller)])
    assert bool(k) is kept
    if not kept:
        assert d[0]["drop_reason"] == "third_party_seller"


def test_amazon_unknown_seller_stays_hidden(cfg):
    from radar.pipeline import _price_all
    from radar.validate import flag_unverified
    k, _ = _validate(cfg, [_amz(seller="")])
    priced = _price_all(k, cfg)
    flag_unverified(priced, cfg)
    assert priced[0]["unverified"] is True


def test_percent_clip_coupon_applied(cfg):
    from radar.pricing import price_offer
    p = cfg.products["celsius-essentials-16"]
    plain = price_offer(_amz(), p, p.ref_unit_price, cfg.settings)
    coupon = price_offer(_amz(coupon_clip_pct=20, subscribe_save_pct=5), p, p.ref_unit_price, cfg.settings)
    # $19.99 -> 20% clip $15.99 -> S&S 5% $15.19 ; + CRV 12 x $0.05
    assert coupon["effective_pack_total"] == pytest.approx(15.79, abs=0.01)
    assert coupon["unit_price"] < plain["unit_price"]


def test_every_scan_plans_an_amazon_job(cfg, tmp_path):
    from radar.memory import State
    from radar.pipeline import research_plan
    s = State.load(tmp_path, cfg)
    energy = {p.id for p in cfg.enabled("energy")}
    q = research_plan(cfg, s, "quick", "morning", "", None, date(2026, 11, 17))
    a = [j for j in q["jobs"] if j["label"] == "amazon"]
    assert len(a) == 1 and "Amazon" in a[0]["task"] and "Sold by" in a[0]["task"]
    assert energy <= set(a[0]["product_ids"])                       # anything seen can be reported
    dp = research_plan(cfg, s, "deep", "morning", "", None, date(2026, 11, 19))
    ad = [j for j in dp["jobs"] if j["label"] == "amazon"][0]
    assert all(p.display_name in ad["task"] for p in cfg.enabled("energy"))   # deep: every energy drink
    m = research_plan(cfg, s, "quick", "midday", "", None, date(2026, 11, 19))
    assert any(j["label"] == "amazon" for j in m["jobs"])
