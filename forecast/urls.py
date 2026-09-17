from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AdaptiveForecastView,
    DatasetUploadView,
    DecisionViewSet,
    InitialForecastView,
    ProductViewSet,
    RecommendationView,
)

router = DefaultRouter()
router.register("products", ProductViewSet, basename="product")
router.register("decisions", DecisionViewSet, basename="decision")

urlpatterns = [
    path("", include(router.urls)),
    path("forecast/initial", InitialForecastView.as_view(), name="forecast-initial"),
    path("forecast/adaptive", AdaptiveForecastView.as_view(), name="forecast-adaptive"),
    path("recommendation", RecommendationView.as_view(), name="recommendation"),
    path("datasets/upload", DatasetUploadView.as_view(), name="dataset-upload"),
]
