# api/admin.py
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import *
class PlaceAdmin(admin.ModelAdmin):
    # 1. Các cột sẽ hiện ra trong danh sách
    list_display = ('id', 'name', 'rating', 'reviews', 'address', 'created_at')
    
    # 2. Cho phép bấm vào tên để xem chi tiết
    list_display_links = ('id', 'name')
    
    # 3. Thêm thanh tìm kiếm (Search box) theo tên hoặc địa chỉ
    search_fields = ('name', 'address')
    
    # 4. Bộ lọc bên tay phải (theo ngày tạo hoặc số sao)
    list_filter = ('created_at', 'rating')
    
    # 5. Sắp xếp mặc định (Mới nhất lên đầu)
    ordering = ('-created_at',)
class CustomUserAdmin(UserAdmin):
    # 1. Hiển thị cột latitude/longitude ngay ở danh sách user bên ngoài
    list_display = ('username', 'email', 'is_staff', 'latitude', 'longitude')
    
    # 2. Hiển thị ô nhập liệu trong trang chi tiết user
    fieldsets = UserAdmin.fieldsets + (
        ('Location Info', {'fields': ('latitude', 'longitude')}),
    )

# Hủy đăng ký cũ (nếu có) và đăng ký lại với class mới
# admin.site.unregister(User) # Bỏ comment dòng này nếu bạn gặp lỗi "AlreadyRegistered"
admin.site.register(Place, PlaceAdmin)
admin.site.register(User, CustomUserAdmin)
# Đăng ký các model của bạn ở đây
# admin.site.register(User, UserAdmin)
admin.site.register(Tag)
admin.site.register(Category)
admin.site.register(Product)
admin.site.register(Review)
admin.site.register(Banner)
admin.site.register(CarouselSlide)