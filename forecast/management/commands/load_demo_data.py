"""
Load the ML team's real export (beautypulse-adaptive-vX, schema_version 1.1)
into the DB.

Real, confirmed top-level shape:

{
  "schema_version": "1.1",
  "model_version": "beautypulse-adaptive-v1",
  "generated_at": "2026-09-17T14:45:28.877217+00:00",
  "prediction_unit": "purchase_events",
  "candidates": [
    {
      "sku_id": "5917178",
      "display_alias": "New Beauty SKU A",
      "brand": "Unknown Brand",
      "category_cluster_id": "1487580013950664926",
      "category_code": null,
      "category_label": null,
      "category_label_verified": false,
      "representative_price": 16.35,
      "observed_launch_date": "2019-12-30",
      "eligibility": "eligible",
      "is_launch_candidate": true,
      "analogs": [
        {
          "sku_id": "5910474", "display_alias": "...", "brand": "dewal",
          "category_cluster_id": "1487580013950664926", "category_code": null,
          "category_label": null, "category_label_verified": false,
          "representative_price": 16.71, "observed_launch_date": "2019-12-03",
          "eligibility": "eligible", "is_launch_candidate": false,
          "similarity_rank": 1, "similarity_score": 0.59,
          "similarity_reasons": ["Same category cluster", "Similar price band"],
          "actual_purchase_events_7d": 1, "actual_purchase_events_14d": 2
        }
      ],
      "forecasts": [
        {
          "stage": "initial", "day_cutoff_used": null,
          "forecast_7d": 1, "forecast_14d": 2,
          "range_low_7d": 0, "range_high_7d": 5,
          "range_low_14d": 0, "range_high_14d": 6,
          "change_percent_7d": null, "change_percent_14d": null
        },
        {
          "stage": "adaptive", "day_cutoff_used": 3,
          "forecast_7d": 49.43, "forecast_14d": 136.53,
          "range_low_7d": 47.4, "range_high_7d": 51.45,
          "range_low_14d": 133.63, "range_high_14d": 139.44,
          "change_percent_7d": 4842.6, "change_percent_14d": 6726.7
        }
      ],
      "early_metrics": [
        {
          "day_cutoff": 3, "views": 217, "unique_viewers": 159,
          "cart_events": 57, "unique_cart_users": 54, "remove_events": 9,
          "purchase_events": 23, "unique_purchasers": 23
        }
      ],
      "recommendations": [
        {
          "day_cutoff_used": 3, "status_code": "ABOVE_EXPECTATION",
          "confidence": 0.568,
          "evidence": ["Adaptive 14-day forecast increased by 6726.7% versus initial", "..."]
        }
      ]
    }
  ]
}

Key points vs earlier draft schemas:
  - forecast field names now match our ForecastResult model 1:1
    (forecast_7d, range_low_7d, change_percent_7d, ...) - no renaming needed.
  - "forecasts", "early_metrics" and "recommendations" are all LISTS now
    (so a product can eventually carry day-1, day-2, day-3 metrics/recs, or
    multiple forecast stages) - loop over them, don't treat as a single dict.
  - "is_launch_candidate" is sent explicitly by the ML export for both
    candidates (true) and analogs (false) - we still apply a safety rule
    on top: never let it flip an existing True back to False, in case the
    same sku_id appears as a real candidate in one export and as someone
    else's analog in another.
  - retailer_action / manufacturer_action are still NOT in the export -
    looked up from ACTION_MAP in forecast/models.py, keyed on status_code.
  - confidence can be null (see SKU C in the sample) - the model field
    allows null, so this passes through fine.

Usage:
    python manage.py load_demo_data demo_predictions.json --flush
"""
import json

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from forecast.models import (
    ACTION_MAP,
    AnalogLink,
    EarlyMetric,
    ForecastResult,
    Product,
    Recommendation,
    SimulationInput,
)


class Command(BaseCommand):
    help = "Load the ML team's demo_predictions.json export into the database."

    def add_arguments(self, parser):
        parser.add_argument("json_path", type=str)
        parser.add_argument(
            "--flush",
            action="store_true",
            help="Delete all existing Product/Forecast/etc rows before loading.",
        )

    def handle(self, *args, **options):
        path = options["json_path"]
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except FileNotFoundError:
            raise CommandError(f"File not found: {path}")
        except json.JSONDecodeError as exc:
            raise CommandError(f"Invalid JSON in {path}: {exc}")

        candidates = payload.get("candidates", [])
        if not candidates:
            raise CommandError("No 'candidates' key found (or it is empty) in the JSON file.")

        self.stdout.write(
            f"Loading export: schema_version={payload.get('schema_version')}, "
            f"model_version={payload.get('model_version')}, "
            f"prediction_unit={payload.get('prediction_unit')}, "
            f"generated_at={payload.get('generated_at')}"
        )

        with transaction.atomic():
            if options["flush"]:
                self.stdout.write("Flushing existing demo data...")
                AnalogLink.objects.all().delete()
                ForecastResult.objects.all().delete()
                EarlyMetric.objects.all().delete()
                Recommendation.objects.all().delete()
                SimulationInput.objects.all().delete()
                Product.objects.all().delete()

            counts = {"products": 0, "analogs": 0, "forecasts": 0, "metrics": 0, "recommendations": 0}

            for c in candidates:
                product = self._upsert_product(c)
                counts["products"] += 1

                for a in c.get("analogs", []):
                    analog_product = self._upsert_product(a)  # analogs are full Product rows too
                    counts["products"] += 1
                    AnalogLink.objects.update_or_create(
                        target_product=product,
                        similarity_rank=a["similarity_rank"],
                        defaults={
                            "analog_product": analog_product,
                            "similarity_score": a["similarity_score"],
                            "similarity_reasons": a.get("similarity_reasons", []),
                            "actual_purchase_events_7d": a.get("actual_purchase_events_7d"),
                            "actual_purchase_events_14d": a.get("actual_purchase_events_14d"),
                        },
                    )
                    counts["analogs"] += 1

                for fc in c.get("forecasts", []):
                    ForecastResult.objects.create(
                        product=product,
                        stage=fc["stage"],
                        day_cutoff_used=fc.get("day_cutoff_used"),
                        forecast_7d=fc["forecast_7d"],
                        forecast_14d=fc["forecast_14d"],
                        range_low_7d=fc.get("range_low_7d"),
                        range_high_7d=fc.get("range_high_7d"),
                        range_low_14d=fc.get("range_low_14d"),
                        range_high_14d=fc.get("range_high_14d"),
                        change_percent_7d=fc.get("change_percent_7d"),
                        change_percent_14d=fc.get("change_percent_14d"),
                    )
                    counts["forecasts"] += 1

                for m in c.get("early_metrics", []):
                    EarlyMetric.objects.update_or_create(
                        product=product,
                        day_cutoff=m["day_cutoff"],
                        defaults={
                            "views": m.get("views", 0),
                            "unique_viewers": m.get("unique_viewers", 0),
                            "cart_events": m.get("cart_events", 0),
                            "unique_cart_users": m.get("unique_cart_users", 0),
                            "remove_events": m.get("remove_events", 0),
                            "purchase_events": m.get("purchase_events", 0),
                            "unique_purchasers": m.get("unique_purchasers", 0),
                        },
                    )
                    counts["metrics"] += 1

                for r in c.get("recommendations", []):
                    status_code = r["status_code"]
                    try:
                        retailer_action, manufacturer_action = ACTION_MAP[status_code]
                    except KeyError:
                        raise CommandError(
                            f"Unknown status_code '{status_code}' for sku_id {c['sku_id']}. "
                            f"Known codes: {list(ACTION_MAP)}. Update ACTION_MAP in models.py "
                            f"if the ML team introduced a new status."
                        )
                    Recommendation.objects.create(
                        product=product,
                        day_cutoff_used=r.get("day_cutoff_used"),
                        status_code=status_code,
                        retailer_action=retailer_action,
                        manufacturer_action=manufacturer_action,
                        confidence=r.get("confidence"),
                        evidence=r.get("evidence", []),
                    )
                    counts["recommendations"] += 1

                # simulation_input never comes from the ML export (it's planner
                # input) - seed a sane default only if nothing exists yet, so a
                # demo can proceed before the planner fills the Launch Setup form.
                SimulationInput.objects.get_or_create(
                    product=product,
                    defaults={
                        "initial_inventory": 100,
                        "reorder_lead_time_days": 7,
                        "production_capacity": 200,
                        "campaign_status": "Unknown",
                        "event_to_unit_ratio": 1.0,
                    },
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Loaded {counts['products']} products (candidates + analogs), "
                f"{counts['analogs']} analog links, {counts['forecasts']} forecast rows, "
                f"{counts['metrics']} early-metric rows, {counts['recommendations']} recommendations."
            )
        )

    @staticmethod
    def _upsert_product(p):
        defaults = {
            "display_alias": p.get("display_alias", ""),
            "brand": p.get("brand") or "Unknown Brand",
            "category_cluster_id": p["category_cluster_id"],
            "category_label": p.get("category_label"),
            "category_label_verified": bool(p.get("category_label_verified", False)),
            "representative_price": p["representative_price"],
            "observed_launch_date": p["observed_launch_date"],
            "eligibility": p.get("eligibility", "eligible"),
        }
        existing = Product.objects.filter(sku_id=p["sku_id"]).first()
        incoming_flag = bool(p.get("is_launch_candidate", False))
        # Never downgrade True -> False: a SKU that's a real candidate
        # elsewhere in this same export must stay visible even when it also
        # shows up as someone else's analog.
        defaults["is_launch_candidate"] = bool(
            incoming_flag or (existing and existing.is_launch_candidate)
        )
        product, _ = Product.objects.update_or_create(sku_id=p["sku_id"], defaults=defaults)
        return product
