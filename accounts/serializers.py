# accounts/serializers.py

from rest_framework import serializers
from .models import User
from django.contrib.auth.password_validation import validate_password
# Serializer cho Đăng ký (Có confirm password)
class RegisterSerializer(serializers.ModelSerializer):
    password2 = serializers.CharField(style={'input_type': 'password'}, write_only=True)

    class Meta:
        model = User
        fields = ['username', 'email', 'password', 'password2']
        extra_kwargs = {'password': {'write_only': True}}

    def validate(self, data):
        if data['password'] != data.pop('password2'):
            raise serializers.ValidationError({"password": "Password fields didn't match."})
        if User.objects.filter(username=data['username']).exists():
            raise serializers.ValidationError({"username": "Username already exists."})
        if User.objects.filter(email=data['email']).exists():
            raise serializers.ValidationError({"email": "Email already exists."})
        return data

    def create(self, validated_data):
        # THAY ĐỔI: Thêm is_active=False
        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data['email'],
            password=validated_data['password'],
            is_active=False 
        )
        return user

# Serializer cho Yêu cầu OTP
class EmailSerializer(serializers.Serializer):
    email = serializers.EmailField()

# Serializer cho Xác nhận OTP
class OTPVerificationSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp = serializers.CharField(max_length=6)

# --- Serializer cho ĐỔI MẬT KHẨU (Yêu cầu đăng nhập) ---
# class ChangePasswordSerializer(serializers.Serializer):
#     old_password = serializers.CharField(required=True)
#     new_password = serializers.CharField(required=True)
#     confirm_password = serializers.CharField(required=True)
#     def validate_new_password(self, value):
#         # Đảm bảo mật khẩu mới đủ mạnh
#         validate_password(value)
#         return value
#     def validate(self, data):
#         # Kiểm tra mật khẩu mới và xác nhận mật khẩu có khớp
#         if data['new_password'] != data['confirm_password']:
#             raise serializers.ValidationError({"new_password": "New passwords must match."})
#         return data

# --- Serializer cho QUÊN MẬT KHẨU (Xác nhận và đặt mật khẩu mới) ---
class SetNewPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    otp = serializers.CharField(max_length=6, required=True)
    new_password = serializers.CharField(required=True)
    confirm_password = serializers.CharField(required=True)
    def validate_new_password(self, value):
        # Đảm bảo mật khẩu mới đủ mạnh
        validate_password(value)
        return value
    def validate(self, data):
        # Kiểm tra mật khẩu mới và xác nhận mật khẩu có khớp
        if data['new_password'] != data['confirm_password']:
            raise serializers.ValidationError({"new_password": "New passwords must match."})
        return data