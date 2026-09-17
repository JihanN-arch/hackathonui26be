from django.db import models


class Product(models.Model):
    """A candidate 'new launch' SKU exported from the preprocessing notebook.

    Field-level provenance (per PRD section 4):
      - Dataset: sku_id, brand, category_cluster_id, category_code, representative_price
      - Derived: observed_launch_date, eligibility
      - Presentation-only (not a model feature): display_alias, category_label
    """

    ELIGIBILITY_CHOICES = [
        ("eligible", "eligible"),
        ("insufficient_history", "insufficient_history"),
        ("insufficient_future_window", "insufficient_future_window"),
    ]

    sku_id = models.CharField(max_length=64, unique=True)  # dataset product_id
    display_alias = models.CharField(max_length=64, blank=True)  # e.g. "New Beauty SKU A"
    brand = models.CharField(max_length=128, blank=True, default="Unknown Brand")
    category_cluster_id = models.CharField(max_length=64)  # dataset category_id
    category_code = models.CharField(max_length=128, blank=True, null=True)
    category_label = models.CharField(max_length=128, blank=True, null=True)  # only if verified
    category_label_verified = models.BooleanField(default=False)
    representative_price = models.DecimalField(max_digits=10, decimal_places=2)
    observed_launch_date = models.DateField()  # derived: min(event_time); always "Proxy" in UI
    eligibility = models.CharField(max_length=32, choices=ELIGIBILITY_CHOICES, default="eligible")
    # True only for SKUs a planner can pick in Launch Setup. Analog products
    # are also stored as full Product rows (so AnalogLink can FK to them),
    # but they must never show up in the candidate list/filters — this flag
    # is what keeps them out.
    is_launch_candidate = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.sku_id} ({self.display_alias or 'no alias'})"


class AnalogLink(models.Model):
    """Up to three analog products used as the baseline for a candidate.

    analog_product is a full Product row (the ML export gives analogs the
    same shape as candidates), so it's loaded into the Product table too and
    linked here just like any other FK.
    """

    target_product = models.ForeignKey(Product, related_name="analogs", on_delete=models.CASCADE)
    analog_product = models.ForeignKey(Product, related_name="+", on_delete=models.CASCADE)
    similarity_rank = models.PositiveSmallIntegerField()  # 1..3
    similarity_score = models.FloatField()
    similarity_reasons = models.JSONField(default=list)  # list[str], e.g. ["Same category cluster", ...]
    # What the analog actually did historically — shown alongside its curve in the UI.
    actual_purchase_events_7d = models.FloatField(null=True, blank=True)
    actual_purchase_events_14d = models.FloatField(null=True, blank=True)

    class Meta:
        ordering = ["similarity_rank"]
        unique_together = ("target_product", "similarity_rank")


class ForecastResult(models.Model):
    """Initial (pre-launch) or adaptive (post day 1-3) purchase-event forecast."""

    STAGE_CHOICES = [("initial", "initial"), ("adaptive", "adaptive")]

    product = models.ForeignKey(Product, related_name="forecasts", on_delete=models.CASCADE)
    stage = models.CharField(max_length=16, choices=STAGE_CHOICES)
    day_cutoff_used = models.PositiveSmallIntegerField(null=True, blank=True)  # 1/2/3, only for adaptive
    forecast_7d = models.FloatField()
    forecast_14d = models.FloatField()
    range_low_7d = models.FloatField(null=True, blank=True)
    range_high_7d = models.FloatField(null=True, blank=True)
    range_low_14d = models.FloatField(null=True, blank=True)
    range_high_14d = models.FloatField(null=True, blank=True)
    # Only populated for stage="adaptive": % change vs the initial forecast, as sent by the ML export.
    change_percent_7d = models.FloatField(null=True, blank=True)
    change_percent_14d = models.FloatField(null=True, blank=True)
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-generated_at"]


class EarlyMetric(models.Model):
    """Derived Day 1-3 funnel metrics, computed straight from raw events."""

    product = models.ForeignKey(Product, related_name="early_metrics", on_delete=models.CASCADE)
    day_cutoff = models.PositiveSmallIntegerField()  # 1, 2, or 3

    views = models.PositiveIntegerField(default=0)
    unique_viewers = models.PositiveIntegerField(default=0)
    cart_events = models.PositiveIntegerField(default=0)
    unique_cart_users = models.PositiveIntegerField(default=0)
    remove_events = models.PositiveIntegerField(default=0)
    purchase_events = models.PositiveIntegerField(default=0)
    unique_purchasers = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ("product", "day_cutoff")
        ordering = ["day_cutoff"]

    # Rates are computed, not stored, to avoid drift between model and UI (PRD 4, Halaman 3).
    @property
    def view_to_cart_rate(self):
        return self._safe_div(self.unique_cart_users, self.unique_viewers)

    @property
    def view_to_purchase_rate(self):
        return self._safe_div(self.unique_purchasers, self.unique_viewers)

    @property
    def cart_to_purchase_rate(self):
        return self._safe_div(self.unique_purchasers, self.unique_cart_users)

    @property
    def purchase_velocity(self):
        return self._safe_div(self.purchase_events, max(self.day_cutoff, 1))

    @property
    def removal_pressure(self):
        return self._safe_div(self.remove_events, max(self.cart_events, 1))

    @staticmethod
    def _safe_div(numerator, denominator):
        if not denominator:
            return 0.0
        return round(numerator / denominator, 4)


# Business-rule lookup: which (retailer_action, manufacturer_action) each
# demand-shift status maps to. This is a fixed rule from the PRD, decided by
# the backend — NOT something the ML export sends. Keeping it here (not in
# views.py) so both the API view and the data loader can share one source
# of truth.
ACTION_MAP = {
    "ABOVE_EXPECTATION": ("REPLENISH", "SCALE_PRODUCTION"),
    "ON_TRACK": ("MAINTAIN", "MAINTAIN_PRODUCTION"),
    "HIGH_INTEREST_LOW_CONVERSION": ("REVIEW_CAMPAIGN", "WAIT_FOR_CONFIRMATION"),
    "BELOW_EXPECTATION": ("HOLD", "REDUCE_NEXT_BATCH"),
}


class Recommendation(models.Model):
    STATUS_CHOICES = [
        ("ABOVE_EXPECTATION", "ABOVE_EXPECTATION"),
        ("ON_TRACK", "ON_TRACK"),
        ("HIGH_INTEREST_LOW_CONVERSION", "HIGH_INTEREST_LOW_CONVERSION"),
        ("BELOW_EXPECTATION", "BELOW_EXPECTATION"),
    ]
    RETAILER_ACTIONS = [
        ("REPLENISH", "REPLENISH"),
        ("MAINTAIN", "MAINTAIN"),
        ("REVIEW_CAMPAIGN", "REVIEW_CAMPAIGN"),
        ("HOLD", "HOLD"),
    ]
    MANUFACTURER_ACTIONS = [
        ("SCALE_PRODUCTION", "SCALE_PRODUCTION"),
        ("MAINTAIN_PRODUCTION", "MAINTAIN_PRODUCTION"),
        ("WAIT_FOR_CONFIRMATION", "WAIT_FOR_CONFIRMATION"),
        ("REDUCE_NEXT_BATCH", "REDUCE_NEXT_BATCH"),
    ]

    product = models.ForeignKey(Product, related_name="recommendations", on_delete=models.CASCADE)
    day_cutoff_used = models.PositiveSmallIntegerField(null=True, blank=True)
    status_code = models.CharField(max_length=32, choices=STATUS_CHOICES)
    retailer_action = models.CharField(max_length=32, choices=RETAILER_ACTIONS)
    manufacturer_action = models.CharField(max_length=32, choices=MANUFACTURER_ACTIONS)
    confidence = models.FloatField(null=True, blank=True)
    evidence = models.JSONField(default=list)  # list[str], 2-3 short reasons
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-generated_at"]


class SimulationInput(models.Model):
    """User-entered what-if assumptions. Never used as a model feature."""

    CAMPAIGN_CHOICES = [("Yes", "Yes"), ("No", "No"), ("Unknown", "Unknown")]

    product = models.OneToOneField(Product, related_name="simulation_input", on_delete=models.CASCADE)
    initial_inventory = models.FloatField()
    reorder_lead_time_days = models.PositiveIntegerField()
    safety_stock_days = models.PositiveIntegerField(null=True, blank=True)
    production_capacity = models.FloatField()
    campaign_status = models.CharField(max_length=16, choices=CAMPAIGN_CHOICES, default="Unknown")
    event_to_unit_ratio = models.FloatField(default=1.0)  # the "1 purchase event ≈ 1 unit" assumption
    updated_at = models.DateTimeField(auto_now=True)


class Decision(models.Model):
    ACTION_CHOICES = [("approve", "approve"), ("modify", "modify"), ("reject", "reject")]

    recommendation = models.ForeignKey(Recommendation, related_name="decisions", on_delete=models.CASCADE)
    action = models.CharField(max_length=16, choices=ACTION_CHOICES)
    reason = models.TextField(blank=True)
    modified_payload = models.JSONField(null=True, blank=True)  # only used when action == "modify"
    decided_by = models.CharField(max_length=128, blank=True)  # free text, no auth in MVP
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
