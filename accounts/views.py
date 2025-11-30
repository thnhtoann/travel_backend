# accounts/views.py
from datetime import  timedelta,datetime
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import authenticate
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated # <--- Cần import
from django.contrib.auth import update_session_auth_hash # <--- Cần import
from .models import User
from .serializers import RegisterSerializer, EmailSerializer, OTPVerificationSerializer,SetNewPasswordSerializer#, ChangePasswordSerializer
from .utils import send_otp_email
from django.conf import settings
# 1. Đăng ký (Trả về Token)
class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    permission_classes = (AllowAny,)
    serializer_class = RegisterSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save() # user được tạo với is_active=False
        
        # Gửi OTP ngay sau khi tạo user
        success, message = send_otp_email(user.email)
        if success:
            return Response({
                'detail': 'Registration successful. Please verify your email with the OTP.',
                'email': user.email
            }, status=status.HTTP_201_CREATED)
        else:
            # Xử lý nếu gửi email thất bại
            # Tùy chọn: bạn có thể xóa user vừa tạo nếu không gửi được email
            return Response({'detail': f'Registration failed: Could not send verification email: {message}'}, 
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# 2. Đăng nhập (Trả về Token)
class LoginView(generics.GenericAPIView):
    permission_classes = (AllowAny,)
    
    def post(self, request):
        email = request.data.get('email')
        password = request.data.get('password')

        # 1. Tìm kiếm User bằng email để lấy ra username
        try:
            user_obj = User.objects.get(email=email)
            actual_username = user_obj.username # Lấy username thực tế
        except User.DoesNotExist:
            # Nếu không tìm thấy email, trả về lỗi chung để tránh lộ thông tin user
            return Response({'detail': 'Invalid Credentials'}, status=status.HTTP_401_UNAUTHORIZED)
        
        # 2. Sử dụng username thực tế để authenticate
        # Hàm authenticate sẽ kiểm tra mật khẩu, is_active và trả về user
        user = authenticate(request, username=actual_username, password=password) 
        
        if user is not None:
            # Kiểm tra thêm is_active (thường authenticate đã làm, nhưng kiểm tra lại cho chắc)
            if not user.is_active:
                return Response({'detail': 'Account not active. Please verify your email.'}, status=status.HTTP_401_UNAUTHORIZED)
                
            refresh = RefreshToken.for_user(user)
            return Response({
                'refresh': str(refresh),
                'access': str(refresh.access_token),
            })
        else:
            # Lỗi ở đây chủ yếu là sai mật khẩu
            return Response({'detail': 'Invalid Credentials'}, status=status.HTTP_401_UNAUTHORIZED)

# 3. Yêu cầu Gửi OTP
class RequestOTPView(generics.GenericAPIView):
    permission_classes = (AllowAny,)
    serializer_class = EmailSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email']
        
        success, message = send_otp_email(email)
        
        if success:
            return Response({'detail': message}, status=status.HTTP_200_OK)
        else:
            return Response({'detail': message}, status=status.HTTP_400_BAD_REQUEST)

# 4. Xác nhận OTP
class VerifyOTPView(generics.GenericAPIView):
    permission_classes = (AllowAny,)
    serializer_class = OTPVerificationSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email']
        otp = serializer.validated_data['otp']
        
        try:
            # Chỉ tìm user chưa được kích hoạt
            user = User.objects.get(email=email, is_active=False) 
        except User.DoesNotExist:
            return Response({'detail': 'User not found or account is already active.'}, status=status.HTTP_404_NOT_FOUND)

        # 1. Kiểm tra OTP
        if user.otp != otp:
            return Response({'detail': 'Invalid OTP.'}, status=status.HTTP_400_BAD_REQUEST)

        # 2. Kiểm tra hết hạn
        if user.otp_created_at < timezone.now():
            return Response({'detail': 'OTP expired.'}, status=status.HTTP_400_BAD_REQUEST)

        # Nếu thành công: Kích hoạt tài khoản và dọn dẹp OTP
        user.otp = None
        user.otp_created_at = None
        user.is_active = True # <--- KÍCH HOẠT TÀI KHOẢN
        user.save()
        
        # Trả về token cho phép người dùng truy cập sau khi kích hoạt
        refresh = RefreshToken.for_user(user)
        return Response({
            'detail': 'Account verified and activated successfully. You are now logged in.',
            'refresh': str(refresh),
            'access': str(refresh.access_token),
        }, status=status.HTTP_200_OK)

class SetNewPasswordView(APIView):
    """
    Bước 2: Xác minh OTP và đặt lại mật khẩu mới.
    Endpoint: POST /accounts/set-new-password/
    Data: {email, otp, new_password, confirm_new_password}
    """
    serializer_class = SetNewPasswordSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        email = serializer.validated_data.get('email')
        otp_input = serializer.validated_data.get('otp')
        new_password = serializer.validated_data.get('new_password')

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response(
                {"detail": "Email không tồn tại."},
                status=status.HTTP_404_NOT_FOUND
            )

        # 1. Kiểm tra OTP
        current_time = timezone.now()
        otp_valid_until = user.otp_created_at + timedelta(minutes=settings.OTP_EXPIRATION_MINUTES)
        
        if user.otp != otp_input:
            return Response(
                {"otp": "Mã OTP không hợp lệ."}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        if current_time > otp_valid_until:
            return Response(
                {"otp": "Mã OTP đã hết hạn."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # 2. Đặt mật khẩu mới và xóa OTP đã dùng
        user.set_password(new_password)
        user.otp = None # Xóa OTP để không thể dùng lại
        user.otp_created_at = None
        user.save()

        return Response(
            {"detail": "Đặt lại mật khẩu thành công. Vui lòng đăng nhập lại."},
            status=status.HTTP_200_OK
        )

# # ====================================================================
# # B. LUỒNG THAY ĐỔI MẬT KHẨU (NGƯỜI DÙNG ĐÃ ĐĂNG NHẬP)
# # ====================================================================

# class ChangePasswordView(APIView):
#     """
#     Thay đổi mật khẩu cho người dùng đã đăng nhập.
#     Endpoint: POST /accounts/change-password/
#     Headers: Authorization: Bearer <token>
#     Data: {old_password, new_password, confirm_new_password}
#     """
#     permission_classes = [IsAuthenticated] # Bắt buộc phải đăng nhập
#     serializer_class = ChangePasswordSerializer

#     def post(self, request):
#         user = request.user
#         serializer = self.serializer_class(data=request.data, context={'request': request})
#         serializer.is_valid(raise_exception=True)

#         old_password = serializer.validated_data.get('old_password')
#         new_password = serializer.validated_data.get('new_password')
        
#         # 1. Kiểm tra mật khẩu cũ
#         if not user.check_password(old_password):
#             return Response(
#                 {"old_password": "Mật khẩu cũ không đúng."},
#                 status=status.HTTP_400_BAD_REQUEST
#             )

#         # 2. Đặt mật khẩu mới
#         user.set_password(new_password)
#         user.save()
        
#         return Response(
#             {"detail": "Thay đổi mật khẩu thành công."},
#             status=status.HTTP_200_OK
#         )