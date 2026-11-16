# Deal Radar research protocol (Claude session engine)

A scheduled Claude session on the owner's existing Claude plan does the web research. No
Anthropic API key or credits are used. Python in this repo does every calculation, check and
output. Follow these steps exactly and in order.

## 1. Set up

```bash
pip install -q -r requirements.txt
pytest -q                       # must pass; if it fails, stop and report the failure
python deal_hunter.py --plan > /tmp/plan.json
```

Read `/tmp/plan.json`. It gives today's `mode` (`calibrate` on the first run, `deep` on Monday
and Thursday mornings, `quick` otherwise, `quick` with a weekend-promo focus on Thu/Fri
middays), the `jobs` to research, a `search_budget` per job, known `dead_codes` and current
`records`.

## 2. Research each job (WebSearch, then WebFetch only for URLs WebSearch returned)

- Use the job's `task` text as the brief. Stay within its `search_budget` searches (the plan's
  `total_search_budget` is the whole run). Keep your notes short: numbers, URL, verbatim price text
  (a few extra WebFetch reads of result pages are fine when a snippet lacks the price).
- **Local first.** The owner is in Orange County, CA (South OC first) and prefers local pickup. Prioritize
  in-store deals and buy-online-pick-up-in-store at OC stores (Target, Walmart, Vitamin Shoppe, GNC, Costco,
  Sam's Club, Ralphs, Vons, Sprouts, and Grocery Outlet's weekly ad for an OC store). In-store-only or
  store-specific promos count only if valid at an Orange County store; put the store in `local_store`
  (e.g. "Grocery Outlet Lake Forest") when the page names one. Set `pickup_available: true` when the page
  offers pickup. Ship-to-home deals are still welcome.
- **Store stock.** For the best in-store/club deals, if a retailer or deal page shows availability at
  specific Orange County stores, record it in `stock_note`. Don't spend extra searches hunting for it.
- **Cases first.** The owner buys by the case: look for 12-, 15-, 18-, 24-pack / box prices.
  Single-can or single-bottle promos (Vitamin Shoppe / GNC $1-can weekends) still count.
- Every offer needs a page URL that came back in a WebSearch result in THIS session (or a page
  you WebFetched from such a result). Never type a URL from memory, never guess a price, code or
  date. If you can't source it, skip it.
- Record every URL your searches returned (not just the ones you use) in the job's `urls`.
- Copy numbers exactly as the page shows them. Do NOT compute per-can prices, totals or
  discounts: `deal_hunter.py` does all math.
- Respect sizes (a 12 oz can never counts for a 16 oz product) and the exclusions in
  `config/products.yaml` (no powders, tubs, sticks, shots, hydration lines, gummies, and no
  plant-based/vegan protein except Drumroll).
- Codes: record who reported the code and when in `evidence_text`. Never claim you tested a
  code. If a source says a code is expired/invalid, add it to `dead_codes`.
- Calibrate mode: also capture the REGULAR (non-sale) price per pack at major retailers in
  `regular_pack_price`, and the label protein per unit / exact size in `label_protein_g` /
  `unit_size_oz` when a nutrition panel or spec sheet shows it.

## 3. Write the research file

Save progressively: after finishing each job, rewrite `/tmp/research.json` with every job done so
far, so a long session never loses work. Format:

```json
{
  "mode": "<mode from the plan>",
  "jobs": [
    {
      "label": "<job label from the plan>",
      "product_ids": ["<ids from the plan>"],
      "searches": 8,
      "urls": ["<every URL WebSearch returned for this job>"],
      "page_ages": {"<url>": "<page age/date shown in the result, if any>"},
      "offers": [
        {
          "product_id": "ghost-energy-16",
          "retailer": "The Vitamin Shoppe",
          "source_url": "<one of urls, copied exactly>",
          "evidence_text": "<verbatim price/promo text, under 200 chars>",
          "evidence_date": "YYYY-MM-DD or ''",
          "pack_count": 12,
          "pack_price": 29.99,
          "regular_pack_price": 0,
          "is_sale_price": false,
          "unit_size_oz": 16,
          "label_protein_g": 0,
          "promo_type": "none | pct_off | amount_off | bogo_50 | bogo_free | fixed_unit_price | multi_buy",
          "promo_value": 0,
          "min_qty": 1,
          "code": "",
          "code_pct_off": 0,
          "code_amount_off": 0,
          "code_stackable": false,
          "subscribe_save_pct": 0,
          "coupon_clip_value": 0,
          "shipping_cost": 0,
          "free_shipping_min": 0,
          "in_store_only": false,
          "limit_per_customer": 0,
          "membership_required": false,
          "pickup_available": false,
          "local_store": "",
          "stock_note": "",
          "starts": "",
          "ends": ""
        }
      ],
      "dead_codes": [{"code": "", "retailer": "", "source_url": "", "reason": "expired | invalid | reported-dead"}]
    }
  ]
}
```

Field rules (same as the API extractor in `radar/extract.py`):
- `pack_price` = price of ONE pack before promo, code, coupon or subscribe discount. If it's a
  sale/rollback price, set `is_sale_price: true` and put the was/list price in `regular_pack_price`.
- "BOGO 50%" → `bogo_50`; "buy one get one free" → `bogo_free`; "$1 cans" → `fixed_unit_price`,
  `promo_value: 1`, `pack_count: 1`; "3 for $10" → `multi_buy`, `min_qty: 3`, `promo_value: 10`;
  an automatic "15% off" → `pct_off`, `promo_value: 15`.
- Subscribe & Save / Auto-Delivery % → `subscribe_save_pct` (not a promo).
- Costco, Sam's Club, GNC Pro Access → `membership_required: true`.
- `stock_note`: only when a page explicitly shows store-level availability near Orange County, CA
  (e.g. "In stock at Target Mission Viejo, pickup today", "Limited stock at Costco Laguna Niguel").
  Copy what the page says. Never infer stock; leave `""` when the page doesn't say.
- Unknown numbers are `0`, unknown text is `""`, unknown flags are `false`.

## 4. Process, publish, alert

```bash
NTFY_TOPIC="<topic from your task prompt>" python deal_hunter.py --ingest /tmp/research.json
```

This validates (drops offers whose URL isn't in that job's `urls`, stale posts, wrong sizes,
excluded products, dead codes), prices every cart, ranks, detects records, writes `data/` and
`Obsidian-Vault/`, and sends the ntfy alerts/digest. Never write the topic to any file.

## 5. Commit and push

```bash
git add data Obsidian-Vault
git commit -m "radar: $(TZ=America/Los_Angeles date +%F) <mode> <status> (session)"
git pull --rebase && git push
```

The push redeploys the app (GitHub Pages workflow). Finish with one line: mode, status,
offers kept/dropped, products with offers, top deal per category.
