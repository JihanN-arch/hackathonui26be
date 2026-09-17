"""
Load the ML team's export (beautypulse-vX) into the DB.

Expected top-level shape, matching the real export we received:

{
  "schema_version": "1.0",
  "model_version": "beautypulse-v1",
  "generated_at": "2026-09-18T08:00:00Z",
  "candidates": [
    {
      "sku_id": "5000001",
      "display_alias": "New Beauty SKU A",
      "brand": "runail",
      "category_cluster_id": "1487580005134238553",
      "category_label": null,
      "representative_price": 12.5,
      "observed_launch_date": "2019-11-03",
      "eligibility": "eligible",
      "analogs": [
        {
          "sku_id": "5000101",
          "display_alias": "Historical Beauty SKU A",
          "brand": "runail",
          "category_cluster_id": "1487580005134238553",
          "category_label": null,
          "representative_price": 12.9,
          "observed_launch_date": "2019-10-10",
          "eligibility": "eligible",
          "similarity_rank": 1,
          "similarity_score": 0.93,
          "similarity_reasons": ["Same category cluster", "Similar price band", "Same brand"],
          "actual_purchase_events_7d": 105,
          "actual_purchase_events_14d": 195
        }
      ],
      "initial_forecast": {
        "projected_total_day_7": 120, "projected_total_day_14": 210,
        "range_low_day_7": 90, "range_high_day_7": 150,
        "range_low_day_14": 170, "range_high_day_14": 260
      },
      "early_metrics": {
        "day_cutoff": 3,
        "views": 4200, "unique_viewers": 3300,
        "cart_events": 310, "unique_cart_users": 270,
        "remove_events": 35, "purchase_events": 58, "unique_purchasers": 52
      },
      "adaptive_forecast": {
        "projected_total_day_7": 165, "projected_total_day_14": 290,
        "change_day_7_percent": 37.5, "change_day_14_percent": 38.1,
        "range_low_day_7": 145, "range_high_day_7": 185,
        "range_low_day_14": 255, "range_high_day_14": 320
      },
      "alert": {
        "status_code": "ABOVE_EXPECTATION",
        "confidence": 0.78,
        "evidence": ["Adaptive 14-day forecast increased by 38.1%", "..."]
      }
    }
  ]
}

Note what this loader does NOT get from the ML export, and fills in itself:
  - retailer_action / manufacturer_action: looked up from ACTION_MAP in
    forecast/models.py, keyed on alert.status_code. This is a fixed business
    rule owned by the backend, not something the ML model predicts.
  - The adaptive ForecastResult's day_cutoff_used is taken from
    early_metrics.day_cutoff (the export doesn't repeat it inside
    adaptive_forecast itself).

Usage:
    python manage.py load_demo_data path/to/export.json
    python manage.py load_demo_data path/to/export.json --flush
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
    help = "Load an ML export (candidates/analogs/forecasts/alert) into the database."

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

        model_version = payload.get("model_version", "unknown")
        self.stdout.write(f"Loading export: schema_version={payload.get('schema_version')}, "
                           f"model_version={model_version}, generated_at={payload.get('generated_at')}")

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
                product = self._upsert_product(c, is_launch_candidate=True)
                counts["products"] += 1

                for a in c.get("analogs", []):
                    # is_launch_candidate=False here, but _upsert_product never
                    # downgrades an existing True back to False (see below) —
                    # so a SKU that's a real candidate elsewhere stays visible.
                    analog_product = self._upsert_product(a, is_launch_candidate=False)
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

                if init := c.get("initial_forecast"):
                    ForecastResult.objects.create(
                        product=product,
                        stage="initial",
                        day_cutoff_used=None,
                        forecast_7d=init["projected_total_day_7"],
                        forecast_14d=init["projected_total_day_14"],
                        range_low_7d=init.get("range_low_day_7"),
                        range_high_7d=init.get("range_high_day_7"),
                        range_low_14d=init.get("range_low_day_14"),
                        range_high_14d=init.get("range_high_day_14"),
                    )
                    counts["forecasts"] += 1

                day_cutoff = None
                if metrics := c.get("early_metrics"):
                    day_cutoff = metrics["day_cutoff"]
                    EarlyMetric.objects.update_or_create(
                        product=product,
                        day_cutoff=day_cutoff,
                        defaults={
                            "views": metrics.get("views", 0),
                            "unique_viewers": metrics.get("unique_viewers", 0),
                            "cart_events": metrics.get("cart_events", 0),
                            "unique_cart_users": metrics.get("unique_cart_users", 0),
                            "remove_events": metrics.get("remove_events", 0),
                            "purchase_events": metrics.get("purchase_events", 0),
                            "unique_purchasers": metrics.get("unique_purchasers", 0),
                        },
                    )
                    counts["metrics"] += 1

                if adaptive := c.get("adaptive_forecast"):
                    ForecastResult.objects.create(
                        product=product,
                        stage="adaptive",
                        day_cutoff_used=day_cutoff,
                        forecast_7d=adaptive["projected_total_day_7"],
                        forecast_14d=adaptive["projected_total_day_14"],
                        range_low_7d=adaptive.get("range_low_day_7"),
                        range_high_7d=adaptive.get("range_high_day_7"),
                        range_low_14d=adaptive.get("range_low_day_14"),
                        range_high_14d=adaptive.get("range_high_day_14"),
                        change_percent_7d=adaptive.get("change_day_7_percent"),
                        change_percent_14d=adaptive.get("change_day_14_percent"),
                    )
                    counts["forecasts"] += 1

                if alert := c.get("alert"):
                    status_code = alert["status_code"]
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
                        day_cutoff_used=day_cutoff,
                        status_code=status_code,
                        retailer_action=retailer_action,
                        manufacturer_action=manufacturer_action,
                        confidence=alert.get("confidence"),
                        evidence=alert.get("evidence", []),
                    )
                    counts["recommendations"] += 1

                # simulation_input never comes from the ML export (it's planner
                # input) — seed a sane default only if nothing exists yet, so a
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
    def _upsert_product(p, is_launch_candidate):
        defaults = {
            "display_alias": p.get("display_alias", ""),
            "brand": p.get("brand") or "Unknown Brand",
            "category_cluster_id": p["category_cluster_id"],
            "category_label": p.get("category_label"),
            "category_label_verified": bool(p.get("category_label")),
            "representative_price": p["representative_price"],
            "observed_launch_date": p["observed_launch_date"],
            "eligibility": p.get("eligibility", "eligible"),
        }
        existing = Product.objects.filter(sku_id=p["sku_id"]).first()
        # Never downgrade True -> False: a SKU that's a real candidate
        # elsewhere in this same export must stay visible even when it also
        # shows up as someone else's analog.
        defaults["is_launch_candidate"] = bool(
            is_launch_candidate or (existing and existing.is_launch_candidate)
        )
        product, _ = Product.objects.update_or_create(sku_id=p["sku_id"], defaults=defaults)
        return product
