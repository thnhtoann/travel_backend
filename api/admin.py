# api/admin.py
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import *

# Đăng ký các model của bạn ở đây
admin.site.register(User, UserAdmin)
admin.site.register(Tag)
admin.site.register(Category)
admin.site.register(Product)
admin.site.register(Review)
admin.site.register(Banner)
admin.site.register(CarouselSlide)