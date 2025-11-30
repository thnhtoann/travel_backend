# accounts/urls.py

from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView 
from .views import RegisterView, LoginView, RequestOTPView, VerifyOTPView, SetNewPasswordView#, ChangePasswordView

urlpatterns = [
    path('register/', RegisterView.as_view(), name='register'),
    path('login/', LoginView.as_view(), name='login'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'), 
    path('request-otp/', RequestOTPView.as_view(), name='request_otp'),
    path('verify-otp/', VerifyOTPView.as_view(), name='verify_otp'),
    # Luồng Quên Mật khẩu (Forgot Password)
    path('request-otp/', RequestOTPView.as_view(), name='request-otp'), # Tái sử dụng
    path('set-new-password/', SetNewPasswordView.as_view(), name='set-new-password'), # Bước đặt lại

    # Luồng Thay đổi Mật khẩu (Change Password)
    #path('change-password/', ChangePasswordView.as_view(), name='change-password'),
]