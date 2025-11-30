# accounts/utils.py

import random
from datetime import datetime, timedelta
from django.core.mail import send_mail
from django.conf import settings
from .models import User

def generate_otp():
    return str(random.randint(100000, 999999))

def send_otp_email(email):
    try:
        user = User.objects.get(email=email)
    except User.DoesNotExist:
        return False, "User not found"

    otp_code = generate_otp()
    user.otp = otp_code
    user.otp_created_at = datetime.now() + timedelta(minutes=5) 
    user.save()

    subject = 'Mã Xác Thực OTP của bạn'
    message = f'Mã OTP của bạn là: {otp_code}. Mã này sẽ hết hạn trong 5 phút.'
    email_from = settings.EMAIL_HOST_USER
    recipient_list = [email]

    try:
        send_mail(subject, message, email_from, recipient_list)
        return True, "OTP sent successfully"
    except Exception as e:
        return False, f"Failed to send email: {e}"