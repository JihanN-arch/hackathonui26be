# Launch Forecast Demo — Backend (Django + DRF)

Backend for the 24-hour Beauty SKU Launch Forecast MVP. Implements the 6
endpoints from the PRD, backed by SQLite, seeded from a precomputed
`demo_predictions.json` exported by the AI team's notebook.

This is a **demo backend**: no auth, no live model inference, no live
marketplace/POS integration — all out of scope per the PRD.

## 1. Setup

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install django djangorestframework django-cors-headers

cd launchdemo
python manage.py migrate
python manage.py createsuperuser   # optional, for /admin
```

## 2. Load data

Two options, per the PRD's "fallback demo data" requirement:

**A. Load the fallback/sample data (works immediately, no dependencies):**

```bash
python manage.py load_demo_data ../fixtures/demo_predictions.sample.json
```

This seeds 3 demo SKUs (A/B/C — one of each demand-shift status: above
expectation, high-interest-low-conversion, below expectation) plus their
analog products.

**B. Load the real export from the AI team** (the `beautypulse-v1` format —
`candidates[]`, each with `analogs[]`, `initial_forecast`, `early_metrics`,
`adaptive_forecast`, `alert`. Full shape documented in the docstring at the
top of `forecast/management/commands/load_demo_data.py`):

```bash
python manage.py load_demo_data /path/to/export.json --flush
```

Note: `retailer_action` / `manufacturer_action` are **not** part of the ML
export — the export only sends `alert.status_code`. The loader looks up the
action pair from `ACTION_MAP` in `forecast/models.py`, which is a fixed
business rule (see PRD's Action Center table), not an ML prediction. Change
that dict if the retailer/manufacturer playbook changes.

`--flush` wipes existing Product/Forecast/etc rows first, so you can re-run
this safely as the AI team's export improves throughout the day.

## 3. Run

```bash
python manage.py runserver 0.0.0.0:8000
```

- API base: `http://localhost:8000/api/`
- Admin (to eyeball/tweak loaded data without touching the frontend):
  `http://localhost:8000/admin/`
- Browsable API (DRF's built-in UI, useful for the frontend dev to poke
  around without Postman): open any endpoint URL directly in a browser.

CORS is wide open (`CORS_ALLOW_ALL_ORIGINS = True`) since this is a local
24-hour demo talking to a separate frontend dev server. Tighten before any
real deployment.

## 4. Endpoints

| Method | Endpoint | Body | Notes |
|---|---|---|---|
| `GET` | `/api/products/` | — | List eligible candidate SKUs (analogs never appear here). Filters: `?brand=`, `?category_cluster_id=`, `?observed_launch_month=YYYY-MM` |
| `GET` | `/api/products/filter-options/` | — | Distinct brand/category/month values that actually exist in the loaded data, so the frontend's dropdowns never hardcode values that may not match the real dataset |
| `GET` | `/api/products/{id}/` | — | Full metadata + analogs + early metrics + simulation input |
| `POST` | `/api/forecast/initial` | `{"product_id": 1}` | Analog baseline forecast (7d/14d) + up to 3 analogs |
| `POST` | `/api/forecast/adaptive` | `{"product_id": 1, "day_cutoff": 3}` | Updated forecast + % change vs initial + day-N metrics |
| `POST` | `/api/recommendation` | `{"product_id": 1, "day_cutoff": 3}` | Status + retailer/manufacturer action + simulation (unit-equivalent) layer |
| `GET`/`POST` | `/api/decisions/` | `{"recommendation": 1, "action": "approve", "reason": "...", "decided_by": "..."}` | Records approve/modify/reject. `action` is one of `approve`/`modify`/`reject`; include `modified_payload` (JSON) when `action="modify"` |

All responses are JSON. Errors use standard DRF shape:
`{"detail": "..."}` with a 4xx status.

## 5. Data model notes

- Every `Product` field is one of **Dataset** / **Derived** / **Simulation
  input** per the PRD's provenance rule. The `source_badges` field on the
  product serializer tells the frontend which badge to render — the
  frontend should never hardcode this.
- `ForecastResult.stage` is `"initial"` (pre-launch, analog baseline) or
  `"adaptive"` (post day 1–3, uses `day_cutoff_used`).
- `EarlyMetric` stores only raw counts; all rates (`view_to_cart_rate`,
  `purchase_velocity`, etc.) are computed properties, so the model and UI
  can never drift on the rate formula (PRD section 4, Halaman 3).
- `SimulationInput.event_to_unit_ratio` is the demo-only "1 purchase event
  ≈ 1 unit-equivalent" assumption. It's returned explicitly in the
  `/api/recommendation` response so the frontend can show it next to any
  unit-equivalent number, per the PRD's UI principle of never mixing
  actual/prediction/simulation without a visible label.
- No login/role model — `Decision.decided_by` is a free-text field.

## 6. If something breaks during the demo

- If the AI team's real forecast/analog output isn't ready, re-run step 2A
  to reload the fallback fixture — the frontend doesn't need to know the
  difference, since it's the same schema.
- If a specific endpoint 404s, it usually means that `ForecastResult` /
  `Recommendation` row wasn't in the JSON for that `day_cutoff` — check
  the loaded fixture, not the view code.
- SQLite db file is `launchdemo/db.sqlite3` — delete it and re-run
  `migrate` + `load_demo_data` for a clean slate.

## 7. File upload (accept-only, MVP scope)

`POST /api/datasets/upload` (multipart/form-data, field name `file`)
accepts a user's own `.xlsx`, `.xls`, or `.csv` file, stores it under
`media/uploaded_datasets/`, and records who uploaded it — **that's it**.
The file's contents are never read, parsed, or merged into
Product/ForecastResult/etc. `GET /api/datasets/upload` lists what's been
uploaded so far (useful for checking in `/admin` too, under "Uploaded
datasets").

If a later version of this project needs to actually turn an uploaded
Excel file into new candidate SKUs, that's a separate, bigger feature
(column mapping, validation, matching against the REES46 category/brand
values) — intentionally not built here.

