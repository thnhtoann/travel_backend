# trips/serializers.py
from rest_framework import serializers
from .models import Trip

class TripSerializer(serializers.ModelSerializer):
    tripName = serializers.CharField(source='trip_name')
    startingPoint = serializers.CharField(source='starting_point')
    class Meta:
        model = Trip
        fields = ['id', 'tripName', 'startingPoint', 'destinations', 'date', 'created_at']
        read_only_fields = ['id', 'created_at']