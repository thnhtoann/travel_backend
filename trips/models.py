# trips/models.py
from django.db import models
from django.conf import settings # Cách chuẩn để lấy User model

class Trip(models.Model):
    # Liên kết với User (người tạo trip)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='trips'
    )
    trip_name = models.CharField(max_length=255)
    starting_point = models.CharField(max_length=255)
    
    # Lưu danh sách điểm đến (Mảng JSON)
    # Ví dụ: [{"name": "Hồ Gươm", "lat": 21..., "long": 105...}, ...]
    destinations = models.JSONField(default=list) 
    
    date = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.trip_name} - {self.user.username}"