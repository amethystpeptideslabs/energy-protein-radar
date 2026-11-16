import copy
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DEAL_RADAR_NOW", "2026-11-16T07:17:00-08:00")

from radar.config import load_config  # noqa: E402

_CFG = load_config(ROOT)


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch):
    """Tests must not depend on the CI event, schedule slot or real secrets."""
    for k in ("GITHUB_EVENT_NAME", "DEAL_RADAR_SCHEDULE", "GITHUB_OUTPUT", "NTFY_TOPIC",
              "ANTHROPIC_API_KEY", "MONTHLY_BUDGET_USD"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("DEAL_RADAR_NOW", "2026-11-16T07:17:00-08:00")


@pytest.fixture
def cfg():
    c = copy.deepcopy(_CFG)
    c.env = {}
    return c


@pytest.fixture
def settings(cfg):
    return cfg.settings


def make_offer(**kw):
    base = dict(product_id="ghost-energy-16", retailer="Amazon", source_url="https://www.amazon.com/dp/X",
                evidence_text="", evidence_date="2026-11-14", pack_count=12, pack_price=29.99,
                regular_pack_price=0, is_sale_price=False, unit_size_oz=0, label_protein_g=0,
                promo_type="none", promo_value=0, min_qty=1, code="", code_pct_off=0, code_amount_off=0,
                code_stackable=False, subscribe_save_pct=0, coupon_clip_value=0, shipping_cost=0,
                free_shipping_min=0, in_store_only=False, limit_per_customer=0, membership_required=False,
                starts="", ends="")
    base.update(kw)
    return base
