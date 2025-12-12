# trips/serializers.py
from rest_framework import serializers
from .models import Trip, PlanItem

class PlanItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlanItem
        fields = ['id', 'location_name', 'arrival_time', 'duration', 'highlight', 'image', 'travel_info', 'order']

class TripSerializer(serializers.ModelSerializer):
    # Mapping tên biến Frontend (camelCase) -> Backend (snake_case)
    tripName = serializers.CharField(source='trip_name')
    startingPoint = serializers.CharField(source='starting_point')
    
    # Nested Serializer: Nhận danh sách địa điểm ngay khi tạo Trip
    plans = PlanItemSerializer(many=True)

    class Meta:
        model = Trip
        fields = ['id', 'tripName', 'startingPoint', 'date', 'created_at', 'plans']
        read_only_fields = ['id', 'created_at']

    def create(self, validated_data):
        # 1. Tách dữ liệu plans ra riêng
        plans_data = validated_data.pop('plans')
        user = self.context['request'].user
        
        # 2. Tạo Trip trước
        trip = Trip.objects.create(user=user, **validated_data)
        
        # 3. Tạo từng PlanItem gắn vào Trip vừa tạo
        for index, item_data in enumerate(plans_data):
            # 👇 THÊM DÒNG NÀY: Xóa 'order' trong data nếu có để tránh trùng lặp
            item_data.pop('order', None) 
            
            PlanItem.objects.create(trip=trip, order=index, **item_data)
            
        return trip
    def update(self, instance, validated_data):
        # 1. Tách dữ liệu plans ra (nếu có)
        plans_data = validated_data.pop('plans', None)
        
        # 2. Cập nhật các trường thông tin chính của Trip
        instance.trip_name = validated_data.get('trip_name', instance.trip_name)
        instance.starting_point = validated_data.get('starting_point', instance.starting_point)
        instance.date = validated_data.get('date', instance.date)
        instance.save()

        # 3. Xử lý danh sách Plans (Chiến lược: Xóa cũ -> Tạo mới)
        if plans_data is not None:
            # Xóa toàn bộ plan cũ của trip này
            instance.plans.all().delete()
            
            # Tạo lại plan mới theo danh sách gửi lên
            for index, item_data in enumerate(plans_data):
                item_data.pop('order', None) # Xóa order thừa nếu có
                PlanItem.objects.create(trip=instance, order=index, **item_data)

        return instance