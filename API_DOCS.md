# Launch Forecast API — Dokumentasi untuk FE

Base URL (local dev): `http://localhost:8000/api/`

Semua response `JSON`. Semua request body juga `JSON`, kecuali upload file
(pakai `multipart/form-data`, dijelaskan di bagian 7).

**Nggak ada auth/login.** Semua endpoint bisa diakses langsung tanpa token
apa pun (sesuai scope MVP).

---

## Daftar isi

1. [GET /products](#1-get-apiproducts) — daftar kandidat SKU
2. [GET /products/{id}](#2-get-apiproductsid) — detail 1 SKU
3. [GET /products/filter-options](#3-get-apiproductsfilter-options) — isi dropdown filter
4. [POST /forecast/initial](#4-post-apiforecastinitial) — forecast awal + analog
5. [POST /forecast/adaptive](#5-post-apiforecastadaptive) — forecast setelah day 1-3
6. [POST /recommendation](#6-post-apirecommendation) — status + rekomendasi aksi
7. [POST/GET /datasets/upload](#7-postget-apidatasetsupload) — upload file Excel/CSV
8. [GET/POST /decisions](#8-getpost-apidecisions) — approve/modify/reject
9. [Kode status & referensi enum](#9-kode-status--referensi-enum)
10. [Format error](#10-format-error)

---

## 1. `GET /api/products`

Daftar SKU kandidat yang bisa dipilih planner di halaman **Launch Setup**.
Analog (produk pembanding historis) **tidak pernah** muncul di sini — cuma
SKU yang benar-benar kandidat.

### Query params (semua opsional, bisa digabung)

| Param | Contoh | Keterangan |
|---|---|---|
| `brand` | `?brand=runail` | Exact match, case-insensitive |
| `category_cluster_id` | `?category_cluster_id=1487580005134238553` | Exact match |
| `observed_launch_month` | `?observed_launch_month=2019-11` | Format `YYYY-MM` |

Bisa digabung: `?brand=runail&observed_launch_month=2019-11`

### Contoh response `200`

```json
[
  {
    "id": 1,
    "sku_id": "5917178",
    "display_alias": "New Beauty SKU A",
    "brand": "Unknown Brand",
    "category_cluster_id": "1487580013950664926",
    "category_code": null,
    "category_label": null,
    "category_label_verified": false,
    "representative_price": "16.35",
    "observed_launch_date": "2019-12-30",
    "eligibility": "eligible",
    "source_badges": {
      "sku_id": "Dataset",
      "brand": "Dataset",
      "category_cluster_id": "Dataset",
      "category_code": "Dataset",
      "category_label": "Unverified",
      "representative_price": "Dataset",
      "observed_launch_date": "Derived (Proxy)",
      "display_alias": "Presentation only"
    }
  }
]
```

**`source_badges`** — ini yang dipakai buat nunjukin badge "Dataset" /
"Derived" / "Simulation input" di UI (lihat PRD bagian provenance field).
Jangan hardcode badge ini di FE, selalu pakai apa yang dikirim di sini.

---

## 2. `GET /api/products/{id}`

Detail lengkap 1 SKU: metadata + analog + early metrics + simulation input
sekaligus (nggak perlu request terpisah-pisah).

### Contoh response `200`

```json
{
  "id": 1,
  "sku_id": "5917178",
  "display_alias": "New Beauty SKU A",
  "brand": "Unknown Brand",
  "category_cluster_id": "1487580013950664926",
  "representative_price": "16.35",
  "observed_launch_date": "2019-12-30",
  "eligibility": "eligible",
  "source_badges": { "...": "sama seperti di atas" },
  "analogs": [
    {
      "similarity_rank": 1,
      "similarity_score": 0.59,
      "similarity_reasons": ["Same category cluster", "Similar price band"],
      "actual_purchase_events_7d": 1.0,
      "actual_purchase_events_14d": 2.0,
      "analog": {
        "id": 4,
        "sku_id": "5910474",
        "display_alias": "Historical Beauty SKU A1",
        "brand": "dewal",
        "...": "field Product lainnya sama seperti bagian 1"
      }
    }
  ],
  "early_metrics": [
    {
      "day_cutoff": 3,
      "views": 217,
      "unique_viewers": 159,
      "cart_events": 57,
      "unique_cart_users": 54,
      "remove_events": 9,
      "purchase_events": 23,
      "unique_purchasers": 23,
      "view_to_cart_rate": 0.3396,
      "view_to_purchase_rate": 0.1447,
      "cart_to_purchase_rate": 0.4259,
      "purchase_velocity": 7.6667,
      "removal_pressure": 0.1579
    }
  ],
  "simulation_input": {
    "initial_inventory": 100.0,
    "reorder_lead_time_days": 7,
    "safety_stock_days": null,
    "production_capacity": 200.0,
    "campaign_status": "Unknown",
    "event_to_unit_ratio": 1.0
  }
}
```

Catatan:
- `analogs` maksimal 3 item, sudah terurut dari `similarity_rank` 1 (paling mirip).
- `early_metrics` semua rate (`view_to_cart_rate`, dst) sudah dihitung backend — FE tidak perlu hitung ulang, dan harus pakai angka ini biar konsisten dengan definisi di PRD.
- `simulation_input` bisa **nggak ada** di response kalau planner belum pernah isi form Launch Setup untuk SKU itu — cek dulu keberadaan key-nya di FE.

---

## 3. `GET /api/products/filter-options`

Isi pilihan buat dropdown filter di Launch Setup — nilainya diambil
langsung dari data yang lagi ke-load, jadi **jangan hardcode** pilihan
brand/kategori di FE.

### Contoh response `200`

```json
{
  "brands": ["Unknown Brand", "f.o.x"],
  "category_cluster_ids": [
    "1487580005008409427",
    "1487580006317032337",
    "1487580013950664926"
  ],
  "observed_launch_months": ["2019-12", "2020-01"],
  "representative_price_range": { "min": 4.52, "max": 28.57 }
}
```

Kalau belum ada data sama sekali (`load_demo_data` belum dijalankan),
semua array kosong dan `representative_price_range` isinya `{"min": null, "max": null}`.

---

## 4. `POST /api/forecast/initial`

Forecast pre-launch (analog baseline) + daftar analog. Dipanggil pas
planner klik **"Analyze Launch"** di Launch Setup.

### Request body

```json
{ "product_id": 1 }
```

### Contoh response `200`

```json
{
  "product": { "...": "sama seperti bagian 1" },
  "forecast": {
    "stage": "initial",
    "day_cutoff_used": null,
    "forecast_7d": 1.0,
    "forecast_14d": 2.0,
    "range_low_7d": 0.0,
    "range_high_7d": 5.0,
    "range_low_14d": 0.0,
    "range_high_14d": 6.0,
    "change_percent_7d": null,
    "change_percent_14d": null,
    "generated_at": "2026-09-17T15:24:51.669802Z"
  },
  "analogs": [ "...": "sama seperti analogs di bagian 2" ],
  "demand_proxy_label": "Purchase-event demand proxy"
}
```

- `change_percent_7d` / `change_percent_14d` selalu `null` di stage `initial` (belum ada pembanding).
- `demand_proxy_label` — string tetap, tampilkan sebagai badge di UI (sesuai requirement PRD "Purchase-event demand proxy").

### Response `404`

Kalau `product_id` valid tapi belum ada forecast initial-nya (data belum di-load / belum diproses ML):

```json
{ "detail": "No initial forecast has been generated for this product yet." }
```

---

## 5. `POST /api/forecast/adaptive`

Forecast setelah ada sinyal hari 1-3. Dipanggil pas planner geser toggle
Day 1/2/3 di halaman **Early Demand Monitor**.

### Request body

```json
{ "product_id": 1, "day_cutoff": 3 }
```

`day_cutoff` opsional, default `3` kalau tidak dikirim.

### Contoh response `200`

```json
{
  "product_id": 1,
  "day_cutoff": 3,
  "original_forecast": {
    "stage": "initial",
    "forecast_7d": 1.0,
    "forecast_14d": 2.0,
    "...": "field ForecastResult lainnya"
  },
  "adaptive_forecast": {
    "stage": "adaptive",
    "day_cutoff_used": 3,
    "forecast_7d": 49.43,
    "forecast_14d": 136.53,
    "range_low_7d": 47.4,
    "range_high_7d": 51.45,
    "range_low_14d": 133.63,
    "range_high_14d": 139.44,
    "change_percent_7d": 4842.6,
    "change_percent_14d": 6726.7,
    "generated_at": "2026-09-17T15:24:51.669802Z"
  },
  "percent_change_7d": 4842.0,
  "percent_change_14d": 6726.5,
  "early_metric": {
    "day_cutoff": 3,
    "views": 217,
    "unique_viewers": 159,
    "purchase_events": 23,
    "...": "sama seperti early_metrics di bagian 2"
  }
}
```

Catatan penting: ada **dua** sumber angka persen di sini —
`adaptive_forecast.change_percent_7d/14d` (dikirim langsung oleh model ML)
dan `percent_change_7d/14d` di level atas (dihitung ulang oleh backend dari
`original_forecast` vs `adaptive_forecast`, sebagai cross-check). Keduanya
biasanya mirip, dipilih salah satu aja buat ditampilkan — biasanya pakai
yang dari `adaptive_forecast` karena itu langsung dari model.

### Response `404`

```json
{ "detail": "No adaptive forecast for day_cutoff=3 yet." }
```

---

## 6. `POST /api/recommendation`

Status demand-shift + aksi buat retailer/manufacturer + simulasi
unit-equivalent. Dipanggil di halaman **Action Center**.

### Request body

```json
{ "product_id": 1, "day_cutoff": 3 }
```

`day_cutoff` opsional — kalau tidak dikirim, ambil recommendation terbaru
apa pun day_cutoff-nya.

### Contoh response `200`

```json
{
  "data_backed_result": {
    "id": 3,
    "day_cutoff_used": 3,
    "status_code": "HIGH_INTEREST_LOW_CONVERSION",
    "retailer_action": "REVIEW_CAMPAIGN",
    "manufacturer_action": "WAIT_FOR_CONFIRMATION",
    "confidence": null,
    "evidence": [
      "Early traffic is high relative to the training distribution",
      "View-to-purchase conversion is low relative to the training distribution"
    ],
    "generated_at": "2026-09-17T15:24:51.669802Z"
  },
  "simulation": {
    "event_to_unit_ratio": 1.0,
    "unit_equivalent_forecast_7d": 2.01,
    "unit_equivalent_forecast_14d": 5.94,
    "current_inventory": 100.0,
    "production_capacity": 200.0,
    "suggested_replenishment_units": 0,
    "suggested_next_batch_units": 200.0,
    "production_change_units": 0.0
  },
  "disclaimer": "Simulation values assume 1 purchase event ≈ 1 unit-equivalent and are for demo purposes only; they are not validated against real inventory."
}
```

### Field penting di `simulation`

| Field | Arti |
|---|---|
| `suggested_replenishment_units` | Saran retailer nambah stok berapa unit. `0` kalau `retailer_action` bukan `REPLENISH`. |
| `suggested_next_batch_units` | Saran total produksi batch berikutnya buat manufacturer. |
| `production_change_units` | Selisih `suggested_next_batch_units` dari `production_capacity` sekarang — bisa negatif (artinya turun). |

`simulation` bisa jadi **object kosong `{}`** kalau planner belum isi
`SimulationInput` untuk SKU itu — tampilkan pesan "isi dulu asumsi
inventory di Launch Setup" kalau ini terjadi.

**Selalu tampilkan `disclaimer`** di dekat angka simulasi — ini requirement
UX dari PRD (jangan campur data aktual/prediksi/simulasi tanpa label jelas).

### Response `404`

```json
{ "detail": "No recommendation available for this product/day_cutoff." }
```

---

## 7. `POST`/`GET` `/api/datasets/upload`

Upload file Excel/CSV milik user sendiri. **PENTING: isi filenya TIDAK
diparse/dibaca oleh backend** — cuma disimpan dan dicatat. Ini sesuai
scope MVP, bukan bug.

### POST — upload file

Kirim sebagai `multipart/form-data`, bukan JSON biasa.

| Field form | Wajib? | Keterangan |
|---|---|---|
| `file` | Ya | File `.xlsx`, `.xls`, atau `.csv`, maks 20MB |
| `uploaded_by` | Tidak | Nama planner (free text) |
| `note` | Tidak | Catatan bebas |

Contoh pakai `fetch` di FE:

```js
const formData = new FormData();
formData.append("file", fileInput.files[0]);
formData.append("uploaded_by", "Planner Demo");

const res = await fetch("http://localhost:8000/api/datasets/upload", {
  method: "POST",
  body: formData, // JANGAN set Content-Type manual, biar browser yang atur boundary-nya
});
```

### Contoh response `201`

```json
{
  "id": 1,
  "file": "http://localhost:8000/media/uploaded_datasets/2026/09/17/data.xlsx",
  "original_filename": "data.xlsx",
  "uploaded_by": "Planner Demo",
  "note": "",
  "uploaded_at": "2026-09-17T15:50:55.751453Z",
  "detail": "File received and stored. Its contents have not been parsed or loaded into the app's data (not in MVP scope)."
}
```

`file` adalah URL langsung ke file yang bisa di-download / dibuka.

### Response `400` — ekstensi salah

```json
{ "detail": "Unsupported file type. Allowed: .xlsx, .xls, .csv" }
```

### Response `400` — kebesaran

```json
{ "detail": "File too large. Max size is 20 MB." }
```

### GET — lihat riwayat upload

Tidak butuh param apa-apa, balikin array semua file yang pernah di-upload
(format sama seperti response `201` di atas, minus field `detail`).

---

## 8. `GET`/`POST` `/api/decisions`

Approve / modify / reject rekomendasi di Action Center.

### POST — kirim keputusan

```json
{
  "recommendation": 3,
  "action": "approve",
  "reason": "Sesuai campaign yang sedang jalan",
  "decided_by": "Planner Demo"
}
```

| Field | Wajib? | Keterangan |
|---|---|---|
| `recommendation` | Ya | `id` dari `data_backed_result.id` di response `/api/recommendation` |
| `action` | Ya | `"approve"`, `"modify"`, atau `"reject"` |
| `reason` | Tidak | Free text |
| `decided_by` | Tidak | Nama planner, free text — **tidak ada login/validasi identitas** |
| `modified_payload` | Tidak | JSON bebas, isi kalau `action == "modify"` (misal angka replenishment yang diubah manual) |

### Contoh response `201`

```json
{
  "id": 1,
  "recommendation": 3,
  "action": "approve",
  "reason": "Sesuai campaign yang sedang jalan",
  "modified_payload": null,
  "decided_by": "Planner Demo",
  "created_at": "2026-09-17T08:08:42.051515Z"
}
```

### GET — riwayat semua keputusan

Balikin array semua `Decision`, terbaru duluan. Tidak ada filter per-produk
saat ini — kalau FE butuh filter per SKU, kabari saya, gampang ditambah.

---

## 9. Kode status & referensi enum

### `status_code` (demand-shift status)

| Kode | Arti |
|---|---|
| `ABOVE_EXPECTATION` | Demand di atas rencana |
| `ON_TRACK` | Sesuai rencana |
| `HIGH_INTEREST_LOW_CONVERSION` | Traffic tinggi, konversi rendah |
| `BELOW_EXPECTATION` | Demand di bawah rencana |

### `retailer_action` × `manufacturer_action` (auto dari `status_code`, fixed rule)

| `status_code` | `retailer_action` | `manufacturer_action` |
|---|---|---|
| `ABOVE_EXPECTATION` | `REPLENISH` | `SCALE_PRODUCTION` |
| `ON_TRACK` | `MAINTAIN` | `MAINTAIN_PRODUCTION` |
| `HIGH_INTEREST_LOW_CONVERSION` | `REVIEW_CAMPAIGN` | `WAIT_FOR_CONFIRMATION` |
| `BELOW_EXPECTATION` | `HOLD` | `REDUCE_NEXT_BATCH` |

### `eligibility` (Product)

`"eligible"` | `"insufficient_history"` | `"insufficient_future_window"`
— FE cuma akan pernah nerima `"eligible"` karena endpoint `/products`
sudah difilter, disebut di sini buat referensi aja.

### `action` (Decision)

`"approve"` | `"modify"` | `"reject"`

---

## 10. Format error

Semua error pakai bentuk yang sama:

```json
{ "detail": "pesan error di sini" }
```

| Status | Kapan terjadi |
|---|---|
| `400` | Body/param request tidak valid atau ada field wajib yang kosong |
| `404` | `product_id` / `recommendation` id tidak ditemukan, atau data forecast/recommendation-nya belum ada |
| `500` | Bug di backend — laporkan ke tim BE kalau ini muncul |

---

## Catatan umum buat FE

- Semua angka forecast/metric bisa berupa **float**, bukan cuma integer (misal `forecast_7d: 49.43`) — jangan asumsikan selalu bulat.
- `confidence` di `Recommendation` **bisa `null`** — handle kasus ini di UI (misal sembunyikan badge confidence kalau null).
- Field yang formatnya `Decimal` di Django (contoh: `representative_price`) dikirim sebagai **string** oleh DRF (`"16.35"`, bukan `16.35`), jadi perlu `parseFloat()` di FE kalau mau dipakai buat hitung-hitungan.
- Tanggal (`observed_launch_date`) format `YYYY-MM-DD`, timestamp (`generated_at`, `created_at`) format ISO 8601 UTC.
- Belum ada pagination di endpoint list manapun — untuk MVP jumlah datanya kecil (3-5 SKU), jadi semua langsung dibalikin sekaligus.
