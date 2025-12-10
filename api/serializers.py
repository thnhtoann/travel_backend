# api/serializers.py
from rest_framework import serializers
from .models import *

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'phone_number'] 
class UserLocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['latitude', 'longitude']
class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = ['id', 'name']

class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'name', 'image', 'quantity']

class ReviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = Review
        fields = ['id', 'name', 'rating', 'comment', 'image', 'date']

class ProductSerializer(serializers.ModelSerializer):
    categories = CategorySerializer(many=True, read_only=True)
    reviews = ReviewSerializer(many=True, read_only=True)
    tags = TagSerializer(many=True, read_only=True)

    class Meta:
        model = Product
        fields = [
            'id', 'name', 'weight', 'calories', 'price', 'rating', 'image',
            'images', 'sizes', 'colors', 'description', 'categories', 'tags',
            'is_bestseller', 'is_featured', 'is_out_of_stock', 'old_price',
            'quantity', 'reviews', 'is_new'
        ]

class BannerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Banner
        fields = '__all__'

class CarouselSlideSerializer(serializers.ModelSerializer):
    class Meta:
        model = CarouselSlide
        fields = '__all__'

class PlaceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Place
        fields = ['id', 'place_id', 'name', 'address', 'lat', 'lon', 'rating', 'reviews', 'price', 'image', 'working_hours', 'open_state']
        # Ánh xạ thêm trường is_recommended để Frontend dùng luôn
        extra_kwargs = {'id': {'read_only': True}}
    
    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['is_recommended'] = True # Mặc định là True cho logic hiển thị
        return data