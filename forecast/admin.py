from django.contrib import admin

from .models import (
    AnalogLink,
    Decision,
    EarlyMetric,
    ForecastResult,
    Product,
    Recommendation,
    SimulationInput,
    UploadedDataset,
)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "sku_id",
        "display_alias",
        "brand",
        "category_cluster_id",
        "representative_price",
        "observed_launch_date",
        "eligibility",
        "is_launch_candidate",
    )
    list_filter = ("eligibility", "is_launch_candidate", "brand", "category_cluster_id")
    search_fields = ("sku_id", "display_alias", "brand")


@admin.register(AnalogLink)
class AnalogLinkAdmin(admin.ModelAdmin):
    list_display = ("target_product", "analog_product", "similarity_rank", "similarity_score")


@admin.register(ForecastResult)
class ForecastResultAdmin(admin.ModelAdmin):
    list_display = ("product", "stage", "day_cutoff_used", "forecast_7d", "forecast_14d", "generated_at")
    list_filter = ("stage", "day_cutoff_used")


@admin.register(EarlyMetric)
class EarlyMetricAdmin(admin.ModelAdmin):
    list_display = ("product", "day_cutoff", "views", "cart_events", "purchase_events")
    list_filter = ("day_cutoff",)


@admin.register(Recommendation)
class RecommendationAdmin(admin.ModelAdmin):
    list_display = (
        "product",
        "day_cutoff_used",
        "status_code",
        "retailer_action",
        "manufacturer_action",
        "confidence",
        "generated_at",
    )
    list_filter = ("status_code", "retailer_action", "manufacturer_action")


@admin.register(SimulationInput)
class SimulationInputAdmin(admin.ModelAdmin):
    list_display = ("product", "initial_inventory", "production_capacity", "campaign_status")


@admin.register(Decision)
class DecisionAdmin(admin.ModelAdmin):
    list_display = ("recommendation", "action", "decided_by", "created_at")
    list_filter = ("action",)


@admin.register(UploadedDataset)
class UploadedDatasetAdmin(admin.ModelAdmin):
    list_display = ("original_filename", "uploaded_by", "uploaded_at")
    readonly_fields = ("uploaded_at",)
