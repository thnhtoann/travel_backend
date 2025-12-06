# authentication/views.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.contrib.auth import authenticate, get_user_model
from rest_framework.authtoken.models import Token
from rest_framework.permissions import AllowAny
from django.core.mail import send_mail
from rest_framework.permissions import IsAuthenticated
from api.serializers import UserLocationSerializer
from django.conf import settings # Để lấy EMAIL_HOST_USER
import random

# Import Serializers (Đảm bảo bạn đã tạo file serializers.py trong app authentication)
from .serializers import RegisterSerializer, LoginSerializer

User = get_user_model()

# Lưu tạm mã OTP trong bộ nhớ (Lưu ý: Sẽ mất khi restart server)
otp_storage = {}
class UpdateLocationView(APIView):
    permission_classes = [IsAuthenticated] # Bắt buộc phải đăng nhập

    def post(self, request):
        user = request.user
        serializer = UserLocationSerializer(user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({"message": "Đã cập nhật vị trí"}, status=200)
        return Response(serializer.errors, status=400)
class RegisterView(APIView):
    permission_classes = [AllowAny] # Cho phép ai cũng đăng ký được
    authentication_classes = []
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            token, _ = Token.objects.get_or_create(user=user)
            return Response({
                "user": serializer.data,
                "token": token.key
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class LoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    def post(self, request):
        # Logic hỗ trợ đăng nhập bằng cả Username HOẶC Email
        login_input = request.data.get("username")
        password = request.data.get("password")

        if not login_input or not password:
             return Response({"error": "Vui lòng nhập tài khoản và mật khẩu"}, status=status.HTTP_400_BAD_REQUEST)

        # Tìm user theo email trước
        actual_username = login_input
        try:
            user_obj = User.objects.get(email=login_input)
            actual_username = user_obj.username
        except User.DoesNotExist:
            pass

        user = authenticate(username=actual_username, password=password)
        
        if user:
            token, _ = Token.objects.get_or_create(user=user)
            return Response({
                "token": token.key,
                "user": { "id": user.id, "username": user.username, "email": user.email } 
            })
        return Response({"error": "Sai tài khoản hoặc mật khẩu"}, status=status.HTTP_400_BAD_REQUEST)

class RequestPasswordResetView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    def post(self, request):
        email = request.data.get('email')
        if not email:
            return Response({"error": "Vui lòng nhập email"}, status=400)
        
        try:
            user = User.objects.get(email=email)
            
            # 1. Tạo mã OTP
            otp = str(random.randint(100000, 999999))
            otp_storage[email] = otp
            
            print(f"===== OTP CHO {email}: {otp} =====")
            
            # 2. Gửi Email (Bỏ comment khi đã cấu hình SMTP)
            try:
                send_mail(
                    subject='[Travellous] Mã xác thực đặt lại mật khẩu',
                    message=f'Mã OTP của bạn là: {otp}',
                    from_email=settings.EMAIL_HOST_USER,
                    recipient_list=[email],
                    fail_silently=False,
                )
            except Exception as e:
                print(f"Lỗi gửi mail: {e}")
                # Vẫn trả về thành công để user nhập OTP (nếu bạn đang test bằng console log)

            return Response({"message": "Mã OTP đã được gửi đến email."}, status=200)
            
        except User.DoesNotExist:
            # Bảo mật: Không tiết lộ email chưa đăng ký
            return Response({"message": "Mã OTP đã được gửi đến email."}, status=200)

class VerifyOTPView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    """API chỉ để kiểm tra xem mã OTP có đúng không"""
    def post(self, request):
        email = request.data.get('email')
        otp = request.data.get('otp')
        
        if not email or not otp:
            return Response({"error": "Thiếu thông tin"}, status=400)
        
        stored_otp = otp_storage.get(email)
        
        if not stored_otp or stored_otp != otp:
            return Response({"error": "Mã OTP không chính xác hoặc đã hết hạn"}, status=400)
            
        return Response({"message": "OTP hợp lệ"}, status=200)

class ResetPasswordConfirmView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        email = request.data.get('email')
        otp = request.data.get('otp') # Vẫn nên check lại OTP lần cuối cho an toàn
        new_password = request.data.get('new_password')
        
        if not email or not otp or not new_password:
            return Response({"error": "Thiếu thông tin"}, status=400)
        
        stored_otp = otp_storage.get(email)
        if not stored_otp or stored_otp != otp:
            return Response({"error": "Phiên làm việc hết hạn, vui lòng thử lại"}, status=400)
        
        try:
            user = User.objects.get(email=email)
            user.set_password(new_password)
            user.save()
            
            # Xóa OTP
            del otp_storage[email]
            
            return Response({"message": "Đặt lại mật khẩu thành công"}, status=200)
        except User.DoesNotExist:
            return Response({"error": "Lỗi hệ thống"}, status=400)

