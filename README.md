# Energy + Protein Deal Radar

Daily deal hunter for **RTD energy drinks, protein snacks and RTD protein shakes** (56 products: 29 gym/performance energy drinks, 18 protein bars/snacks, 9 shakes),
**cases first** (12/15/18/24-packs, boxes) with single-can promos included. No API credits: a
scheduled Claude session on the owner's existing Claude plan does the web research
(`docs/RESEARCH_PROTOCOL.md`), and Python in this repo does every check and every price.

- **App:** https://amethystpeptideslabs.github.io/energy-protein-radar/ (installable PWA, "Cases only" filter)
  - iPhone: Safari → Share → **Add to Home Screen**
  - Android/Chrome: menu → **Install app**
- **Phone alerts:** ntfy (subscribe to your private topic in the ntfy app, server `ntfy.sh`)
- **Obsidian:** a separate "Deal Radar" vault in Google Drive (My Drive › Deal Radar, synced to `G:\My Drive\Deal Radar`).
  Every scan adds a dated note to `Deal-Radar/Logs` (append-only). No PowerShell needed.

## Schedule (Pacific time)

| When | What |
|---|---|
| Daily 5:43 AM | Claude session: **calibrate** on the first run, **deep** Mon + Thu, **quick** other days |
| Thu + Fri 12:17 PM | quick, focused on Vitamin Shoppe / GNC weekend promos + Stack3d / Slickdeals |

The sessions are Claude scheduled tasks on your account (edit or pause them in Claude). Each one runs
`deal_hunter.py --plan`, researches with web search, writes a research JSON, then runs
`deal_hunter.py --ingest` and pushes; the push redeploys the app.

Optional paid engine: Actions → **API scan (optional, manual)** with an `ANTHROPIC_API_KEY` secret.

## How it works

1. **Research**: a Claude session searches the web and records every result URL plus raw offer numbers
   (`docs/RESEARCH_PROTOCOL.md`). The optional API engine does the same via `radar/research.py` + `radar/extract.py`.
2. **Ingest** (`deal_hunter.py --ingest`): fills defaults and hands the offers to validation.
3. **Validation** (`radar/validate.py`): drops offers whose URL wasn't in that run's search results,
   stale posts (>21 days unless the promo is still running), wrong sizes/excluded products, dead codes.
   Too-good prices without a second source are flagged ⚠️ UNVERIFIED (shown, never pushed).
4. **Pricing** (`radar/pricing.py`): builds the cheapest cart that triggers each promo
   (BOGO = 2 packs), stacks codes/coupons/subscribe %, shipping, CA CRV. Tiers in `radar/tiers.py`.
5. **Memory** (`data/memory.json`): refs, all-time lows, dead/active codes, alert dedupe, cost ledger.

Tiers — energy ($/can incl. CRV, 16 oz): 🚨 STEAL < $1.25 · 🔥 HOT ≤ $1.55 · ✅ SOLID ≤ $1.85 · ❌ SKIP.
12 oz cans use the same $/oz. Protein (vs usual price): STEAL ≤ 70% · HOT ≤ 80% · SOLID ≤ 90%.
🏆 = beat the stored all-time low.

## Change products or settings

Edit `config/products.yaml` (set `enabled: false` to drop one, e.g. Drumroll) or `config/settings.yaml`, then push.

## Secrets

- ntfy topic: lives in the scheduled task prompt and the `NTFY_TOPIC` Actions secret, never in files.
- `ANTHROPIC_API_KEY`: only for the optional paid engine. Not needed.

Never commit them. `.githooks/pre-commit` blocks staged API keys, ntfy topics and `.env`.

## Optional: Windows git mirror (not needed; the Drive vault replaces it)

```powershell
irm https://raw.githubusercontent.com/amethystpeptideslabs/energy-protein-radar/main/scripts/setup_windows.ps1 | iex
```

## Local dev

```
py -3.12 -m venv .venv && .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pytest -q
python deal_hunter.py --dry-run     # fixtures, no API calls, writes to .dryrun/
python -m http.server               # then open http://localhost:8000
```

### Source rules
- Costco prices come only from costco.com. Third-party Costco trackers (warehouserunner, costco97)
  are blocked (`validation.blocked_source_domains`, `official_source_only` on the Costco retailer), and
  any stored offer from a blocked source is purged automatically with its records and history.
- Energy is gym/performance brands only; Monster, Red Bull, Rockstar, NOS, Prime and other mainstream
  brands are never reported (`exclude_brands` in `config/products.yaml`).
- Snacks are real protein bars (15g+ protein) from gym brands; candy-brand protein bars (Snickers,
  Reese's, Hershey...) and grocery-aisle bars (Clif, Kind, Pure Protein, ONE, Kirkland...) are never reported.
- Vitamin Shoppe BOGO 50% is swept every run, and each deal's pick-up stock is checked at the
  Orange store (1300 N Tustin St, home store) and then Brea in the built-in browser when Reza's PC is
  on, one page at a time; a bot check stops the store check for that run (never solved). Store-specific
  deals and stock notes must be in Orange County; a deal ranks last and never alerts only when no
  checked store has it.
- Amazon is swept every scan (`amazon` job): deep runs check every tracked energy drink, quick runs a
  rotating third, midday Amazon's Today's Deals. Only Sold by Amazon.com or the brand's store counts
  (resellers dropped, unknown seller hidden); clip coupons ($ or %) and Subscribe & Save are priced in,
  and the same $/can tiers decide whether it's a deal.
- No expired sales: every scan re-checks each live sale and deal on its store page (`verify` job).
  A sale or deal no scan re-confirmed in 20 hours drops off, as do sales past their end date or not
  started yet; sale evidence older than 7 days is rejected. The app hides anything not confirmed in
  36 hours even if a scan fails, and each card shows when its price was last checked. Scans run at
  5:43 AM and 12:17 PM daily, so new sales show up the day they go live.
- New products get a one-time calibration job (2 searches each, up to 6 per run) until each is done.
