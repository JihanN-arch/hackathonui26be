from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    AnalogLink,
    Decision,
    EarlyMetric,
    ForecastResult,
    Product,
    Recommendation,
    SimulationInput,
)
from .serializers import (
    AnalogLinkSerializer,
    DecisionSerializer,
    EarlyMetricSerializer,
    ForecastResultSerializer,
    ProductSerializer,
    RecommendationSerializer,
    SimulationInputSerializer,
)


class ProductViewSet(viewsets.ReadOnlyModelViewSet):
    """GET /api/products, GET /api/products/{id}

    Supports the Launch Setup filters from the PRD via query params, e.g.
    /api/products/?brand=Bene&category_cluster_id=12&eligibility=eligible
    """

    queryset = Product.objects.filter(
        eligibility="eligible", is_launch_candidate=True
    ).order_by("observed_launch_date")
    serializer_class = ProductSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params
        if brand := params.get("brand"):
            qs = qs.filter(brand__iexact=brand)
        if category_cluster_id := params.get("category_cluster_id"):
            qs = qs.filter(category_cluster_id=category_cluster_id)
        if month := params.get("observed_launch_month"):  # format YYYY-MM
            year, mon = month.split("-")
            qs = qs.filter(observed_launch_date__year=year, observed_launch_date__month=mon)
        return qs

    def retrieve(self, request, *args, **kwargs):
        product = self.get_object()
        data = self.get_serializer(product).data
        data["analogs"] = AnalogLinkSerializer(
            product.analogs.select_related("analog_product"), many=True
        ).data
        data["early_metrics"] = EarlyMetricSerializer(product.early_metrics.all(), many=True).data
        if hasattr(product, "simulation_input"):
            data["simulation_input"] = SimulationInputSerializer(product.simulation_input).data
        return Response(data)

    @action(detail=False, methods=["get"], url_path="filter-options")
    def filter_options(self, request):
        """GET /api/products/filter-options/

        Returns the brand/category/launch-month values that ACTUALLY exist
        in the currently loaded data — never hardcoded. The frontend should
        build its Launch Setup dropdowns from this instead of guessing what
        the dataset contains (brand spellings, category IDs, etc. vary by
        whatever the AI team's export happens to have).
        """
        qs = Product.objects.filter(eligibility="eligible", is_launch_candidate=True)
        brands = sorted(qs.exclude(brand="").values_list("brand", flat=True).distinct())
        categories = sorted(qs.values_list("category_cluster_id", flat=True).distinct())
        months = sorted(
            {d.strftime("%Y-%m") for d in qs.values_list("observed_launch_date", flat=True) if d}
        )
        prices = list(qs.values_list("representative_price", flat=True))
        price_range = {"min": min(prices), "max": max(prices)} if prices else {"min": None, "max": None}

        return Response(
            {
                "brands": brands,
                "category_cluster_ids": categories,
                "observed_launch_months": months,
                "representative_price_range": price_range,
            }
        )


class InitialForecastView(APIView):
    """POST /api/forecast/initial
    body: {"product_id": <int>}
    Returns the pre-launch analog baseline forecast + the analog list.
    """

    def post(self, request):
        product_id = request.data.get("product_id")
        if not product_id:
            return Response({"detail": "product_id is required"}, status=status.HTTP_400_BAD_REQUEST)
        product = get_object_or_404(Product, pk=product_id)

        forecast = ForecastResult.objects.filter(product=product, stage="initial").first()
        if not forecast:
            return Response(
                {"detail": "No initial forecast has been generated for this product yet."},
                status=status.HTTP_404_NOT_FOUND,
            )

        analogs = AnalogLink.objects.filter(target_product=product).select_related("analog_product")

        return Response(
            {
                "product": ProductSerializer(product).data,
                "forecast": ForecastResultSerializer(forecast).data,
                "analogs": AnalogLinkSerializer(analogs, many=True).data,
                "demand_proxy_label": "Purchase-event demand proxy",
            }
        )


class AdaptiveForecastView(APIView):
    """POST /api/forecast/adaptive
    body: {"product_id": <int>, "day_cutoff": 1|2|3}
    Returns the updated forecast plus the day 1-3 signals it was built from.
    """

    def post(self, request):
        product_id = request.data.get("product_id")
        day_cutoff = request.data.get("day_cutoff", 3)
        if not product_id:
            return Response({"detail": "product_id is required"}, status=status.HTTP_400_BAD_REQUEST)
        product = get_object_or_404(Product, pk=product_id)

        adaptive = (
            ForecastResult.objects.filter(product=product, stage="adaptive", day_cutoff_used=day_cutoff)
            .first()
        )
        initial = ForecastResult.objects.filter(product=product, stage="initial").first()
        metric = EarlyMetric.objects.filter(product=product, day_cutoff=day_cutoff).first()

        if not adaptive:
            return Response(
                {"detail": f"No adaptive forecast for day_cutoff={day_cutoff} yet."},
                status=status.HTTP_404_NOT_FOUND,
            )

        percent_change_7d = None
        percent_change_14d = None
        if initial and initial.forecast_7d:
            percent_change_7d = round((adaptive.forecast_7d - initial.forecast_7d) / initial.forecast_7d * 100, 2)
        if initial and initial.forecast_14d:
            percent_change_14d = round(
                (adaptive.forecast_14d - initial.forecast_14d) / initial.forecast_14d * 100, 2
            )

        return Response(
            {
                "product_id": product.id,
                "day_cutoff": day_cutoff,
                "original_forecast": ForecastResultSerializer(initial).data if initial else None,
                "adaptive_forecast": ForecastResultSerializer(adaptive).data,
                "percent_change_7d": percent_change_7d,
                "percent_change_14d": percent_change_14d,
                "early_metric": EarlyMetricSerializer(metric).data if metric else None,
            }
        )


class RecommendationView(APIView):
    """POST /api/recommendation
    body: {"product_id": <int>, "day_cutoff": 1|2|3 (optional)}
    Returns the latest status + retailer/manufacturer action, plus the
    simulation layer (unit-equivalent) computed from SimulationInput.
    """

    def post(self, request):
        product_id = request.data.get("product_id")
        day_cutoff = request.data.get("day_cutoff")
        if not product_id:
            return Response({"detail": "product_id is required"}, status=status.HTTP_400_BAD_REQUEST)
        product = get_object_or_404(Product, pk=product_id)

        qs = Recommendation.objects.filter(product=product)
        if day_cutoff is not None:
            qs = qs.filter(day_cutoff_used=day_cutoff)
        recommendation = qs.first()
        if not recommendation:
            return Response(
                {"detail": "No recommendation available for this product/day_cutoff."},
                status=status.HTTP_404_NOT_FOUND,
            )

        simulation = {}
        adaptive = ForecastResult.objects.filter(
            product=product, stage="adaptive", day_cutoff_used=recommendation.day_cutoff_used
        ).first()
        initial = ForecastResult.objects.filter(product=product, stage="initial").first()

        if hasattr(product, "simulation_input") and adaptive:
            sim_input = product.simulation_input
            unit_equiv_7d = round(adaptive.forecast_7d * sim_input.event_to_unit_ratio, 2)
            unit_equiv_14d = round(adaptive.forecast_14d * sim_input.event_to_unit_ratio, 2)
            initial_unit_equiv_14d = (
                round(initial.forecast_14d * sim_input.event_to_unit_ratio, 2) if initial else unit_equiv_14d
            )

            simulation = {
                "event_to_unit_ratio": sim_input.event_to_unit_ratio,
                "unit_equivalent_forecast_7d": unit_equiv_7d,
                "unit_equivalent_forecast_14d": unit_equiv_14d,
                "current_inventory": sim_input.initial_inventory,
                "production_capacity": sim_input.production_capacity,
            }

            # --- Retailer-side quantity: how many units to replenish ---
            if recommendation.retailer_action == "REPLENISH":
                simulation["suggested_replenishment_units"] = max(
                    round(unit_equiv_14d - sim_input.initial_inventory, 2), 0
                )
            else:
                simulation["suggested_replenishment_units"] = 0

            # --- Manufacturer-side quantity: what the next production batch should be ---
            change_ratio = (
                (unit_equiv_14d - initial_unit_equiv_14d) / initial_unit_equiv_14d
                if initial_unit_equiv_14d
                else 0
            )
            if recommendation.manufacturer_action == "SCALE_PRODUCTION":
                # Scale capacity up proportionally to how much demand grew.
                suggested_batch = round(sim_input.production_capacity * (1 + max(change_ratio, 0)), 2)
            elif recommendation.manufacturer_action == "REDUCE_NEXT_BATCH":
                # Scale capacity down proportionally to how much demand fell.
                suggested_batch = round(sim_input.production_capacity * max(1 + min(change_ratio, 0), 0), 2)
            else:  # MAINTAIN_PRODUCTION / WAIT_FOR_CONFIRMATION
                suggested_batch = sim_input.production_capacity

            simulation["suggested_next_batch_units"] = suggested_batch
            simulation["production_change_units"] = round(suggested_batch - sim_input.production_capacity, 2)

        return Response(
            {
                "data_backed_result": RecommendationSerializer(recommendation).data,
                "simulation": simulation,
                "disclaimer": (
                    "Simulation values assume 1 purchase event \u2248 1 unit-equivalent and are "
                    "for demo purposes only; they are not validated against real inventory."
                ),
            }
        )


class DecisionViewSet(viewsets.ModelViewSet):
    """POST /api/decisions (approve/modify/reject), also lists past decisions.

    No auth/role management in this MVP (out of scope per PRD); decided_by is
    a free-text field.
    """

    queryset = Decision.objects.all()
    serializer_class = DecisionSerializer
    http_method_names = ["get", "post", "head"]
