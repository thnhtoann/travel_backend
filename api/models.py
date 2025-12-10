# api/models.py
from django.db import models
from django.contrib.auth.models import AbstractUser

# User (Dựa trên UserType.tsx)
class User(AbstractUser):
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    latitude = models.FloatField(blank=True, null=True)
    longitude = models.FloatField(blank=True, null=True)
    def __str__(self):
        return self.username

# Category (Dựa trên CategoryType.tsx)
class Category(models.Model):
    name = models.CharField(max_length=255)
    image = models.ImageField(upload_to='categories/', blank=True, null=True)
    quantity = models.IntegerField(default=0, blank=True, null=True)
    def __str__(self):
        return self.name

# Tag (Từ endpoint 'api/tags')
class Tag(models.Model):
    name = models.CharField(max_length=100, unique=True)
    def __str__(self):
        return self.name

class Place(models.Model):
    place_id = models.CharField(max_length=255, unique=True) # ID từ Google Maps
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=500, blank=True, null=True)
    lat = models.FloatField()
    lon = models.FloatField()
    rating = models.FloatField(default=0.0)
    reviews = models.IntegerField(default=0)
    price = models.CharField(max_length=50, blank=True, null=True) # Ví dụ: ₫₫
    image = models.URLField(max_length=1000, blank=True, null=True)
    working_hours = models.JSONField(blank=True, null=True) 
    open_state = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name
class Product(models.Model):
    name = models.CharField(max_length=255)
    weight = models.FloatField(blank=True, null=True)
    calories = models.FloatField(blank=True, null=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    old_price = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    rating = models.FloatField(default=0.0)
    image = models.ImageField(upload_to='products/')
    images = models.TextField(blank=True, null=True) # Hoặc JSONField nếu dùng Postgres
    sizes = models.JSONField(default=list, blank=True)
    colors = models.JSONField(default=list, blank=True)
    description = models.TextField()
    categories = models.ManyToManyField(Category, related_name='products', blank=True)
    tags = models.ManyToManyField(Tag, related_name='products', blank=True)
    quantity = models.IntegerField(default=1)
    is_bestseller = models.BooleanField(default=False)
    is_featured = models.BooleanField(default=False)
    is_out_of_stock = models.BooleanField(default=False)
    is_new = models.BooleanField(default=False)

    def __str__(self):
        return self.name

# Review (Dựa trên ReviewType.tsx)
class Review(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='reviews')
    name = models.CharField(max_length=255)
    rating = models.FloatField()
    comment = models.TextField()
    image = models.ImageField(upload_to='reviews/', blank=True, null=True)
    date = models.DateTimeField(auto_now_add=True)
    def __str__(self):
        return f'Review for {self.product.name}'

# Banner (Dựa trên BannerType.tsx)
class Banner(models.Model):
    title = models.CharField(max_length=255)
    title1 = models.CharField(max_length=255, blank=True)
    title2 = models.CharField(max_length=255, blank=True)
    image = models.ImageField(upload_to='banners/')
    btnText = models.CharField(max_length=50)
    description1 = models.TextField(blank=True)
    description2 = models.TextField(blank=True)
    def __str__(self):
        return self.title

# CarouselSlide (Dựa trên CarouselType.tsx, endpoint 'api/slides')
class CarouselSlide(models.Model):
    title_line_1 = models.CharField(max_length=255)
    title_line_2 = models.CharField(max_length=255, blank=True)
    image = models.ImageField(upload_to='slides/')
    button_text = models.CharField(max_length=50)
    def __str__(self):
        return self.title_line_1