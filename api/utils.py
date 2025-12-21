# api/utils.py
import requests
import datetime
import numpy as np
from dotenv import load_dotenv
import os
from .models import Place
from .image_search_service import ImageSearchService
load_dotenv()

OPENWEATHER_API_KEY = os.environ.get('WEATHER_API_KEY')
SERPAPI_KEY = os.environ.get('SERPAPI_API_KEY')
def get_weather_realtime(lat, lon):
    try:
        url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={OPENWEATHER_API_KEY}&units=metric&lang=vi"
        response = requests.get(url, timeout=5)
        data = response.json()
        
        if response.status_code == 200:
            desc = data['weather'][0]['description'] # "mây cụm", "mưa nhẹ"
            temp = data['main']['temp']
            return f"{desc.capitalize()}, nhiệt độ {temp}°C"
        else:
            return "Không lấy được dữ liệu thời tiết"
    except Exception as e:
        print(f"Lỗi Weather API: {e}")
        return "Thời tiết không xác định"

def predict_traffic_with_model(lat, lon, hour, day_of_week):
    try:
        status = "Thông thoáng"
        if 7 <= hour <= 9 or 17 <= hour <= 19:
            status = "Tắc nghẽn (Cao điểm)"
        elif 10 <= hour <= 16:
            status = "Bình thường"
            
        return status
    except Exception as e:
        print(f"Lỗi Traffic Model: {e}")
        return "Không xác định"

def get_external_context(lat, lon, time_str):
    # 1. Parse thời gian
    try:
        dt = datetime.datetime.strptime(time_str, "%H:%M")
        hour = dt.hour
        day_of_week = datetime.datetime.now().weekday()
    except:
        hour = datetime.datetime.now().hour
        day_of_week = 0
    weather_info = get_weather_realtime(lat, lon)
    traffic_info = predict_traffic_with_model(lat, lon, hour, day_of_week)

    return weather_info, traffic_info

def find_and_save_place_info(query_name):

    print(f" Đang tìm kiếm online cho: {query_name}...")

    place_info = {}
    try:
        params = {
            "engine": "google_maps",
            "q": query_name + " Vietnam",
            "type": "search",
            "api_key": SERPAPI_KEY,
            "hl": "en"
        }
        
        response = requests.get("https://serpapi.com/search", params=params, timeout=10)
        data = response.json()
        
        result = None
        if "local_results" in data and len(data["local_results"]) > 0:
            result = data["local_results"][0]
        elif "place_results" in data:
            result = data["place_results"]
            
        if result:
            description = result.get('description')
        if not description:
            snippet_raw = result.get('snippet')

            if isinstance(snippet_raw, dict):

                description = snippet_raw.get('snippet')
            elif isinstance(snippet_raw, str):

                description = snippet_raw
        

        if not description and result.get('extensions'):
            description = ", ".join([str(ext) for ext in result.get('extensions', [])])

        if not description:
            description = ""
        else:
            description = str(description) 

            gps = result.get('gps_coordinates', {})
            lat = gps.get('latitude', 0)
            lon = gps.get('longitude', 0)

            place_info = {
                "title": result.get("title", query_name),
                "address": result.get("address", ""),
                "rating": result.get("rating", 0),
                "reviews": result.get("reviews", 0),
                "type": result.get("type", ""),
                "description": description,
                "lat": lat,
                "lon": lon
            }
    except Exception as e:
        print(f"❌ Lỗi SerpApi: {e}")

    image_url = "https://via.placeholder.com/400x200?text=No+Image"
    try:
        search_service = ImageSearchService()
        images = search_service.find_images_for_destination(query_name, "Vietnam", 1)
        if images and len(images) > 0:
            image_url = images[0].get('image', image_url)
    except Exception as e:
        print(f"❌ Lỗi Image Service: {e}")

    final_name = place_info.get('title', query_name)
    
    final_description = place_info.get('description')
    
    if not final_description:
        parts = []
        if place_info.get('rating'):
            parts.append(f"⭐ {place_info['rating']} ({place_info['reviews']})")
        
        p_type = place_info.get('type')
        if p_type:
            if isinstance(p_type, list): parts.append(", ".join(p_type))
            else: parts.append(str(p_type))

        p_addr = place_info.get('address')
        if p_addr:
            if isinstance(p_addr, list): parts.append(", ".join(p_addr))
            else: parts.append(str(p_addr))
        
        final_description = " • ".join(parts)

    if not final_description: 
        final_description = "Địa điểm tham quan thú vị."
    try:
        safe_id = f"auto_{final_name.strip().replace(' ', '_').lower()}"[:50]

        place, created = Place.objects.update_or_create(
            name=final_name,
            defaults={
                'place_id': safe_id,
                'image': image_url,
                'description': final_description,
                'address': place_info.get('address', ''),
                'rating': place_info.get('rating', 0),
                'reviews': place_info.get('reviews', 0),
                'lat': place_info.get('lat', 0),  
                'lon': place_info.get('lon', 0)       
            }
        )
        return place
    except Exception as e:
        print(f"❌ Lỗi lưu DB: {e}")
        return {
            "name": final_name,
            "image": image_url,
            "description": final_description,
            "address": place_info.get('address', ''),
            "rating": place_info.get('rating', 0),
            "reviews": place_info.get('reviews', 0),
            "lat": place_info.get('lat', 0),
            "lon": place_info.get('lon', 0)
        }