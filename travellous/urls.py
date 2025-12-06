# myproject/urls.py
from django.contrib import admin
from django.urls import path, include # Nhớ import 'include'
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('api.urls')), 
    path('api/trips/', include('trips.urls')),
    path('api/auth/', include('authentication.urls')),
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)