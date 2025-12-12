# api/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'tags', views.TagViewSet, basename='tags')
router.register(r'users', views.UserViewSet, basename='users')
router.register(r'slides', views.CarouselSlideViewSet, basename='slides')
router.register(r'banners', views.BannerViewSet, basename='banners')
router.register(r'reviews', views.ReviewViewSet, basename='reviews')
router.register(r'products', views.ProductViewSet, basename='products')
router.register(r'categories', views.CategoryViewSet, basename='categories')

urlpatterns = [
    
    path(
        'get-travel-advice/', 
        views.TravelAdviceView.as_view(), 
        name='get-travel-advice'
    ),
    path('optimize-route/', views.OptimizeRouteView.as_view(), name='optimize-route'),
    path('traffic/predict/', views.PredictTrafficView.as_view(), name='traffic-predict'),
    path('places/nearby/', views.NearbyPlacesView.as_view()),
    path('favorites/', views.FavoriteView.as_view(), name='favorites'),
    path('', include(router.urls)),
    path('plan-trip-smart/', views.PlanTripSmartView.as_view(), name='plan-trip-smart'),
    path('get-good-traffic-routes/', views.GoodTrafficRoutesView.as_view(), name='get-good-traffic-routes'),
    path('find-green-route/', views.FindGreenRouteView.as_view(), name='find-green-route'),
]