# trips/models.py
from django.db import models
from django.conf import settings # Cách chuẩn để lấy User model

class Trip(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='trips')
    trip_name = models.CharField(max_length=255)
    starting_point = models.CharField(max_length=255)
    date = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.trip_name} ({self.user})"

class PlanItem(models.Model):
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name='plans')
    
    # Thông tin chi tiết địa điểm
    location_name = models.CharField(max_length=255)
    arrival_time = models.CharField(max_length=50) # VD: 08:30
    duration = models.CharField(max_length=50)     # VD: 60 phút
    highlight = models.TextField(blank=True, null=True)
    image = models.URLField(max_length=500, blank=True, null=True)
    
    # Lưu thông tin di chuyển (Time/Distance) dưới dạng JSON nhỏ
    travel_info = models.JSONField(default=dict, blank=True, null=True)
    
    order = models.IntegerField(default=0) # Thứ tự sắp xếp

    class Meta:
        ordering = ['order']