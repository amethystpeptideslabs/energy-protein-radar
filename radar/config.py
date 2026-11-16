"""Loads config/products.yaml + config/settings.yaml + environment (.env)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
CATEGORIES = ("energy", "snack", "rtd")
CATEGORY_LABEL = {"energy": "Energy", "snack": "Protein Snacks", "rtd": "RTD Shakes"}


@dataclass
class Product:
    id: str
    category: str
    brand: str
    line: str
    display_name: str
    unit_label: str
    unit_size_oz: float
    protein_g: float
    search_terms: list[str]
    exclude_terms: list[str]
    retailers_priority: list[str]
    ref_unit_price: float | None
    crv_applies: bool
    plant_based: bool
    enabled: bool
    size_range_oz: tuple[float, float] | None = None
    needs_verification: bool = False
    crv_verify: bool = False
    protein_note: str = ""
    aliases: list[str] = field(default_factory=list)          # names the brand goes by (lowercase)
    exclude_brands: list[str] = field(default_factory=list)   # mainstream brands never tracked here

    @property
    def is_energy(self) -> bool:
        return self.category == "energy"

    @property
    def is_drink(self) -> bool:
        return self.category in ("energy", "rtd")

    def accepts_size(self, oz: float, tol: float) -> bool:
        """Strict size match for drinks. 0/None = size not stated -> accept (validated elsewhere)."""
        if not oz or not self.is_drink:
            return True
        lo, hi = self.size_range_oz or (self.unit_size_oz, self.unit_size_oz)
        return (lo - tol) <= oz <= (hi + tol)


@dataclass
class Config:
    settings: dict[str, Any]
    products: dict[str, Product]
    env: dict[str, str] = field(default_factory=dict)

    def enabled(self, category: str | None = None) -> list[Product]:
        return [p for p in self.products.values()
                if p.enabled and (category is None or p.category == category)]

    @property
    def api_key(self) -> str:
        return self.env.get("ANTHROPIC_API_KEY", "")

    @property
    def ntfy_topic(self) -> str:
        return self.env.get("NTFY_TOPIC", "")

    @property
    def monthly_budget(self) -> float:
        raw = self.env.get("MONTHLY_BUDGET_USD", "").strip()
        try:
            return float(raw) if raw else float(self.settings["budget"]["monthly_usd_default"])
        except ValueError:
            return float(self.settings["budget"]["monthly_usd_default"])

    def retailer_name(self, key: str) -> str:
        r = self.settings.get("retailers", {}).get(key)
        return r["name"] if r else key


def _load_dotenv(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def load_products(path: Path) -> dict[str, Product]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    defaults = raw.get("defaults", {})
    out: dict[str, Product] = {}
    for item in raw["products"]:
        cat = item["category"]
        if cat not in CATEGORIES:
            raise ValueError(f"{item['id']}: unknown category {cat}")
        d = dict(defaults.get(cat, {}))
        d.update({k: v for k, v in item.items() if k != "extra_exclude_terms"})
        allow = {a.lower() for a in item.get("allow_terms", [])}   # e.g. ON Amino Energy is sold as "sparkling hydration"
        excludes = [e for e in list(d.get("exclude_terms", [])) + list(item.get("extra_exclude_terms", []))
                    if e.lower() not in allow]
        aliases = [a.lower() for a in [d["brand"], d["line"], *d.get("aliases", [])] if a]
        sr = d.get("size_range_oz")
        pid = d["id"]
        if pid in out:
            raise ValueError(f"duplicate product id {pid}")
        out[pid] = Product(
            id=pid, category=cat, brand=d["brand"], line=d["line"],
            display_name=d.get("display_name", d["line"]),
            unit_label=d.get("unit_label", "unit"),
            unit_size_oz=float(d.get("unit_size_oz") or 0),
            protein_g=float(d.get("protein_g") or 0),
            search_terms=list(d.get("search_terms", [])),
            exclude_terms=[e.lower() for e in excludes],
            retailers_priority=list(d.get("retailers_priority", [])),
            ref_unit_price=(float(d["ref_unit_price"]) if d.get("ref_unit_price") is not None else None),
            crv_applies=bool(d.get("crv_applies", False)),
            plant_based=bool(d.get("plant_based", False)),
            enabled=bool(d.get("enabled", True)),
            size_range_oz=(float(sr[0]), float(sr[1])) if sr else None,
            needs_verification=bool(d.get("needs_verification", False)),
            crv_verify=bool(d.get("crv_verify", False)),
            protein_note=str(d.get("protein_note", "")),
            aliases=aliases,
            exclude_brands=[b.lower() for b in d.get("exclude_brands", [])],
        )
    return out


def load_config(root: Path = ROOT) -> Config:
    settings = yaml.safe_load((root / "config" / "settings.yaml").read_text(encoding="utf-8"))
    products = load_products(root / "config" / "products.yaml")
    env = _load_dotenv(root / ".env")
    for key in ("ANTHROPIC_API_KEY", "NTFY_TOPIC", "MONTHLY_BUDGET_USD"):
        if os.environ.get(key):
            env[key] = os.environ[key]
    return Config(settings=settings, products=products, env=env)
