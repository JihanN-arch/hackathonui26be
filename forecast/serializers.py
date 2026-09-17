from rest_framework import serializers

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


class ProductSerializer(serializers.ModelSerializer):
    """Product card for Launch Setup. Includes explicit source badges so the
    frontend never has to guess whether a field is Dataset/Derived/Simulation."""

    source_badges = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "id",
            "sku_id",
            "display_alias",
            "brand",
            "category_cluster_id",
            "category_code",
            "category_label",
            "category_label_verified",
            "representative_price",
            "observed_launch_date",
            "eligibility",
            "source_badges",
        ]

    def get_source_badges(self, obj):
        return {
            "sku_id": "Dataset",
            "brand": "Dataset",
            "category_cluster_id": "Dataset",
            "category_code": "Dataset",
            "category_label": "Dataset" if obj.category_label_verified else "Unverified",
            "representative_price": "Dataset",
            "observed_launch_date": "Derived (Proxy)",
            "display_alias": "Presentation only",
        }


class AnalogLinkSerializer(serializers.ModelSerializer):
    analog = ProductSerializer(source="analog_product", read_only=True)

    class Meta:
        model = AnalogLink
        fields = [
            "similarity_rank",
            "similarity_score",
            "similarity_reasons",
            "actual_purchase_events_7d",
            "actual_purchase_events_14d",
            "analog",
        ]


class ForecastResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = ForecastResult
        fields = [
            "stage",
            "day_cutoff_used",
            "forecast_7d",
            "forecast_14d",
            "range_low_7d",
            "range_high_7d",
            "range_low_14d",
            "range_high_14d",
            "change_percent_7d",
            "change_percent_14d",
            "generated_at",
        ]


class EarlyMetricSerializer(serializers.ModelSerializer):
    view_to_cart_rate = serializers.ReadOnlyField()
    view_to_purchase_rate = serializers.ReadOnlyField()
    cart_to_purchase_rate = serializers.ReadOnlyField()
    purchase_velocity = serializers.ReadOnlyField()
    removal_pressure = serializers.ReadOnlyField()

    class Meta:
        model = EarlyMetric
        fields = [
            "day_cutoff",
            "views",
            "unique_viewers",
            "cart_events",
            "unique_cart_users",
            "remove_events",
            "purchase_events",
            "unique_purchasers",
            "view_to_cart_rate",
            "view_to_purchase_rate",
            "cart_to_purchase_rate",
            "purchase_velocity",
            "removal_pressure",
        ]


class SimulationInputSerializer(serializers.ModelSerializer):
    class Meta:
        model = SimulationInput
        fields = [
            "initial_inventory",
            "reorder_lead_time_days",
            "safety_stock_days",
            "production_capacity",
            "campaign_status",
            "event_to_unit_ratio",
        ]


class RecommendationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Recommendation
        fields = [
            "id",
            "day_cutoff_used",
            "status_code",
            "retailer_action",
            "manufacturer_action",
            "confidence",
            "evidence",
            "generated_at",
        ]


class DecisionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Decision
        fields = [
            "id",
            "recommendation",
            "action",
            "reason",
            "modified_payload",
            "decided_by",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class UploadedDatasetSerializer(serializers.ModelSerializer):
    class Meta:
        model = UploadedDataset
        fields = ["id", "file", "original_filename", "uploaded_by", "note", "uploaded_at"]
        read_only_fields = ["id", "original_filename", "uploaded_at"]
