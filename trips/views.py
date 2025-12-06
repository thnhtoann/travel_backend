# trips/views.py
from rest_framework import viewsets, permissions
from .models import Trip
from .serializers import TripSerializer

class TripViewSet(viewsets.ModelViewSet):
    serializer_class = TripSerializer
    # Bắt buộc phải có Token đăng nhập mới được gọi API này
    permission_classes = [permissions.IsAuthenticated] 

    def get_queryset(self):
        # Chỉ trả về những chuyến đi của người đang đăng nhập
        return Trip.objects.filter(user=self.request.user).order_by('-date')

    def perform_create(self, serializer):
        # Tự động gán người tạo là người đang đăng nhập
        serializer.save(user=self.request.user)