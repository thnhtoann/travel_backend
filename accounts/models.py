from django.contrib.auth.models import AbstractUser
from django.db import models
#from django.contrib.auth.hashers import check_password
class User(AbstractUser):
    USERNAME_FIELD = 'username' 
    REQUIRED_FIELDS = ['email']
    # Thêm trường OTP
    otp = models.CharField(max_length=6, blank=True, null=True)
    otp_created_at = models.DateTimeField(null=True, blank=True)
    groups = models.ManyToManyField(
        'auth.Group',
        related_name='accounts_user_set', # Tên duy nhất 1
        blank=True,
        help_text=('The groups this user belongs to.'),
        related_query_name='user',
    )
    user_permissions = models.ManyToManyField(
        'auth.Permission',
        related_name='accounts_user_permissions_set', # Tên duy nhất 2
        blank=True,
        help_text=('Specific permissions for this user.'),
        related_query_name='user',
    )
    # Đảm bảo bạn dùng email cho trường username nếu muốn đăng nhập bằng email
    # AbstractUser đã bao gồm username, email, password.
    # def check_password(self, raw_password):
    #     # --- DÒNG DEBUG KHỞI TẠO ---
    #     print("\n--- DEBUG: Custom check_password called ---")
    #     print(f"DEBUG: Password sent: {raw_password}")
    #     print(f"DEBUG: Hashed password in DB: {self.password}")
        
    #     is_valid = check_password(raw_password, self.password)
    #     print(f"DEBUG: Password verification result: {is_valid}")
    #     return is_valid
    #     # --- KẾT THÚC DEBUG ---
    def __str__(self):
        return self.email