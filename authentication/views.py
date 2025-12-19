from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.contrib.auth import authenticate, get_user_model
from rest_framework.authtoken.models import Token
from rest_framework.permissions import AllowAny, IsAuthenticated
from django.core.mail import send_mail
from api.serializers import UserLocationSerializer
from django.conf import settings
import random

# Import Serializers (Ensure serializers.py exists in the authentication app)
from .serializers import RegisterSerializer, LoginSerializer

User = get_user_model()

# Temporary OTP storage in memory (Note: This will be cleared if the server restarts)
otp_storage = {}

class UpdateLocationView(APIView):
    permission_classes = [IsAuthenticated]  # Authentication required

    def post(self, request):
        user = request.user
        serializer = UserLocationSerializer(user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({"message": "Location updated successfully"}, status=200)
        return Response(serializer.errors, status=400)

class RegisterView(APIView):
    permission_classes = [AllowAny]  # Publicly accessible
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
        # Support login using either Username OR Email
        login_input = request.data.get("username")
        password = request.data.get("password")

        if not login_input or not password:
            return Response({"error": "Please enter both username/email and password"}, status=status.HTTP_400_BAD_REQUEST)

        # Attempt to find user by email first
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
        return Response({"error": "Invalid username or password"}, status=status.HTTP_400_BAD_REQUEST)

class RequestPasswordResetView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        email = request.data.get('email')
        if not email:
            return Response({"error": "Please provide an email address"}, status=400)
        
        try:
            user = User.objects.get(email=email)
            
            # 1. Generate OTP
            otp = str(random.randint(100000, 999999))
            otp_storage[email] = otp
            
            print(f"===== OTP FOR {email}: {otp} =====")
            
            # 2. Send Email
            try:
                send_mail(
                    subject='[NavEase] Password Reset Verification Code',
                    message=f'Your OTP: {otp}',
                    from_email=settings.EMAIL_HOST_USER,
                    recipient_list=[email],
                    fail_silently=False,
                )
            except Exception as e:
                print(f"Mail delivery error: {e}")
                # Still returning success so user can use OTP from console during testing

            return Response({"message": "OTP code has been sent to your email."}, status=200)
            
        except User.DoesNotExist:
            # Security: Do not reveal if an email is not registered
            return Response({"message": "OTP code has been sent to your email."}, status=200)

class VerifyOTPView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    """API to verify if the OTP code is correct"""
    def post(self, request):
        email = request.data.get('email')
        otp = request.data.get('otp')
        
        if not email or not otp:
            return Response({"error": "Missing information"}, status=400)
        
        stored_otp = otp_storage.get(email)
        
        if not stored_otp or stored_otp != otp:
            return Response({"error": "Invalid or expired OTP code"}, status=400)
            
        return Response({"message": "OTP is valid"}, status=200)

class ResetPasswordConfirmView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        email = request.data.get('email')
        otp = request.data.get('otp') # Final OTP verification for security
        new_password = request.data.get('new_password')
        
        if not email or not otp or not new_password:
            return Response({"error": "Missing information"}, status=400)
        
        stored_otp = otp_storage.get(email)
        if not stored_otp or stored_otp != otp:
            return Response({"error": "Session expired, please try again"}, status=400)
        
        try:
            user = User.objects.get(email=email)
            user.set_password(new_password)
            user.save()
            
            # Clear OTP from memory after successful reset
            if email in otp_storage:
                del otp_storage[email]
            
            return Response({"message": "Password has been reset successfully"}, status=200)
        except User.DoesNotExist:
            return Response({"error": "System error occurred"}, status=400)