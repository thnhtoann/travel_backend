from django.contrib import admin
# Import các lớp Admin cần thiết để tùy chỉnh giao diện User
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User

# 1. Tạo lớp tùy chỉnh cho User Admin
class CustomUserAdmin(BaseUserAdmin):
    # Thêm trường is_active vào danh sách hiển thị
    list_display = BaseUserAdmin.list_display + ('is_active',)

    # Thêm các trường OTP vào phần chi tiết người dùng
    fieldsets = BaseUserAdmin.fieldsets + (
        ('OTP Verification', {'fields': ('otp', 'otp_created_at',)}),
    )

    # Thêm trường is_active vào bộ lọc
    list_filter = BaseUserAdmin.list_filter + ('is_active',)

# 2. Đăng ký mô hình User với lớp Admin tùy chỉnh
admin.site.register(User, CustomUserAdmin)