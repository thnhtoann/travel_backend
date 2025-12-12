# trips/views.py
from rest_framework import viewsets, permissions
from .models import Trip
from .serializers import TripSerializer

class TripViewSet(viewsets.ModelViewSet):
    serializer_class = TripSerializer
    permission_classes = [permissions.IsAuthenticated] # Bắt buộc đăng nhập

    def get_queryset(self):
        # Chỉ lấy trip của người dùng hiện tại
        return Trip.objects.filter(user=self.request.user).order_by('-created_at')