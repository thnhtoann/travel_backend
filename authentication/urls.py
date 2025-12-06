# authentication/urls.py
from django.urls import path
from .views import LoginView, RegisterView, RequestPasswordResetView, ResetPasswordConfirmView, VerifyOTPView, UpdateLocationView
urlpatterns = [
    path('login/', LoginView.as_view(), name='login'),
    path('user/create/', RegisterView.as_view(), name='register'),
    path('password/reset/', RequestPasswordResetView.as_view(), name='request-reset'),
    path('password/reset/verify-otp/', VerifyOTPView.as_view(), name='verify-otp'),
    path('password/reset/confirm/', ResetPasswordConfirmView.as_view(), name='reset-confirm'),
    path('user/update-location/', UpdateLocationView.as_view(), name='update-location'),
]