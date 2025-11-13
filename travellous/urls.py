# myproject/urls.py
from django.contrib import admin
from django.urls import path, include # Nhớ import 'include'
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # === THÊM DÒNG NÀY ===
    # Trỏ tất cả 'api/' sang file api/urls.py
    path('api/', include('api.urls')), 
]

# === THÊM KHỐI NÀY ===
# Để phục vụ file ảnh (media) khi đang phát triển
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)