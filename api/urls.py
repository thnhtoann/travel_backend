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
    path('', include(router.urls)),
    path(
        'get-travel-advice/', 
        views.TravelAdviceView.as_view(), 
        name='get-travel-advice'
    ),
    path('optimize-route/', views.OptimizeRouteView.as_view(), name='optimize-route'),
    path('traffic/predict/', views.PredictTrafficView.as_view(), name='traffic-predict'),
    path('places/nearby/', views.NearbyPlacesView.as_view())
]