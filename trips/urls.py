# trips/urls.py
from rest_framework.routers import DefaultRouter
from .views import TripViewSet

router = DefaultRouter()
router.register(r'', TripViewSet, basename='trips') # Đường dẫn gốc của app này

urlpatterns = router.urls