# Energy + Protein Deal Radar

Daily deal hunter for **RTD energy drinks, protein snacks and RTD protein shakes** (25 products).
A GitHub Actions job searches the web with Claude every morning, Python does all the price math,
and results land in:

- **App:** https://amethystpeptideslabs.github.io/energy-protein-radar/ (installable PWA)
  - iPhone: Safari → Share → **Add to Home Screen**
  - Android/Chrome: menu → **Install app**
- **Phone alerts:** ntfy (subscribe to your private topic in the ntfy app, server `ntfy.sh`)
- **Obsidian:** `Obsidian-Vault/` here, mirrored to `<your vault>/Deal-Radar/` by a Windows scheduled task

## Schedule (Pacific time)

| When | What |
|---|---|
| Daily 7:17 AM | auto: **deep** on Mon + Thu (one search per product), **quick** other days; first ever run = **calibrate** |
| Thu + Fri 12:17 PM | quick, focused on Vitamin Shoppe / GNC weekend promos + Stack3d / Slickdeals |
| Daily 6:17 PM | no-op (zero API calls) unless inside a `deal_season` window in `config/settings.yaml` |
| Daily 8:05 AM (your PC) | `DealRadarSync` pulls the repo and copies notes into your vault |

Manual run: Actions → **Daily deal scan** → Run workflow → pick a mode
(or `gh workflow run daily_scan.yml -f mode=deep`). `check` mode = tiny API + web search + ntfy test.

## How it works

1. **Research** (`radar/research.py`): Claude + `web_search_20260209` (dynamic filtering) writes an evidence
   dossier. Every URL returned in `web_search_tool_result` blocks is recorded.
2. **Extraction** (`radar/extract.py`): a cheap model converts the dossier to strict JSON via
   `output_config.format`. Raw numbers only.
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

## Secrets (GitHub → Settings → Secrets and variables → Actions)

- `ANTHROPIC_API_KEY` — required for scans
- `NTFY_TOPIC` — your private ntfy topic (topics are public by name: keep it long and random)
- `MONTHLY_BUDGET_USD` — optional, default 40 (above 80% deep runs become quick; at 100% research pauses)

Never commit them. `.githooks/pre-commit` blocks staged API keys, ntfy topics and `.env`.

## Windows setup (Obsidian sync)

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
