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
    """
    Hàm này chạy Model AI của bạn để dự đoán giao thông.
    Thay thế logic giả lập bên dưới bằng code gọi model thực tế của bạn.
    """
    try:
        # --- VÍ DỤ TÍCH HỢP MODEL CỦA BẠN ---
        # input_data = np.array([[lat, lon, hour, day_of_week]])
        # prediction = traffic_model.predict(input_data)
        # traffic_level = np.argmax(prediction) 
        
        # --- LOGIC GIẢ LẬP (Placeholder) ---
        # 0: Thông thoáng, 1: Bình thường, 2: Đông đúc, 3: Tắc nghẽn
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
    """Hàm tổng hợp ngữ cảnh gọi từ View"""
    # 1. Parse thời gian
    try:
        dt = datetime.datetime.strptime(time_str, "%H:%M")
        hour = dt.hour
        # Giả sử ngày hiện tại để lấy thứ (0=Mon, 6=Sun)
        day_of_week = datetime.datetime.now().weekday()
    except:
        hour = datetime.datetime.now().hour
        day_of_week = 0

    # 2. Lấy dữ liệu song song (hoặc tuần tự nếu nhanh)
    weather_info = get_weather_realtime(lat, lon)
    traffic_info = predict_traffic_with_model(lat, lon, hour, day_of_week)

    return weather_info, traffic_info

def find_and_save_place_info(query_name):

    print(f"🌍 Đang tìm kiếm online cho: {query_name}...")

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
        
        # Nếu không có description, lấy snippet
        if not description:
            snippet_raw = result.get('snippet')
            
            # KIỂM TRA KỸ KIỂU DỮ LIỆU CỦA SNIPPET
            if isinstance(snippet_raw, dict):
                # Nếu snippet là object { "snippet": "...", ... }
                description = snippet_raw.get('snippet')
            elif isinstance(snippet_raw, str):
                # Nếu snippet là chuỗi bình thường
                description = snippet_raw
        
        # Nếu vẫn không có, thử ghép từ extensions
        if not description and result.get('extensions'):
            # Ép kiểu str() cho chắc chắn
            description = ", ".join([str(ext) for ext in result.get('extensions', [])])

        # Đảm bảo description luôn là string (không bao giờ là None hoặc Object)
        if not description:
            description = ""
        else:
            description = str(description) # Ép kiểu lần cuối cho an toàn tuyệt đối

            # 2. Lấy tọa độ
            gps = result.get('gps_coordinates', {})
            lat = gps.get('latitude', 0)
            lon = gps.get('longitude', 0)

            place_info = {
                "title": result.get("title", query_name),
                "address": result.get("address", ""),
                "rating": result.get("rating", 0),
                "reviews": result.get("reviews", 0),
                "type": result.get("type", ""),
                "description": description, # Có thể None
                "lat": lat,
                "lon": lon
            }
    except Exception as e:
        print(f"❌ Lỗi SerpApi: {e}")

    # --- BƯỚC 2: LẤY ẢNH TỪ IMAGE SERVICE ---
    image_url = "https://via.placeholder.com/400x200?text=No+Image"
    try:
        search_service = ImageSearchService()
        images = search_service.find_images_for_destination(query_name, "Vietnam", 1)
        if images and len(images) > 0:
            image_url = images[0].get('image', image_url)
    except Exception as e:
        print(f"❌ Lỗi Image Service: {e}")

    # --- BƯỚC 3: TỔNG HỢP DỮ LIỆU ---
    final_name = place_info.get('title', query_name)
    
    # Xử lý Description: Nếu SerpApi không có, mới dùng logic ghép chuỗi cũ
    final_description = place_info.get('description')
    
    if not final_description:
        # Logic Fallback (Ghép chuỗi)
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

    # --- BƯỚC 4: LƯU VÀO DATABASE ---
    try:
        # Tạo ID an toàn
        safe_id = f"auto_{final_name.strip().replace(' ', '_').lower()}"[:50]
        
        # Lưu đầy đủ các trường mới
        place, created = Place.objects.update_or_create(
            name=final_name,
            defaults={
                'place_id': safe_id,
                'image': image_url,
                'description': final_description,
                'address': place_info.get('address', ''), # Lưu address
                'rating': place_info.get('rating', 0),    # Lưu rating
                'reviews': place_info.get('reviews', 0),  # Lưu reviews
                'lat': place_info.get('lat', 0),          # Lưu lat
                'lon': place_info.get('lon', 0)           # Lưu lon
            }
        )
        return place
    except Exception as e:
        print(f"❌ Lỗi lưu DB: {e}")
        # Trả về dict tạm nếu lỗi DB
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