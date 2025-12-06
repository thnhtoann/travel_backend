# api/views.py
from rest_framework import viewsets, permissions
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import *
from .serializers import *
import google.generativeai as genai
import requests
import os
import math
import json
from dotenv import load_dotenv

load_dotenv()

# === CẤU HÌNH API ===
try:
    GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
    if GEMINI_API_KEY:
        genai.configure(api_key=GEMINI_API_KEY)
    
    WEATHER_API_KEY = os.environ.get('WEATHER_API_KEY')
    SERPAPI_API_KEY = os.environ.get('SERPAPI_API_KEY')
    GEOAPIFY_API_KEY = os.environ.get('GEOAPIFY_API_KEY')
except Exception as e:
    print(f"Lỗi cấu hình API Key: {e}")

# === HÀM HỖ TRỢ ===
def format_time(seconds):
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    if hours > 0: return f"{hours} giờ {minutes} phút"
    return f"{minutes} phút"

def format_distance(meters):
    return f"{round(meters / 1000, 1)} km"

# === PHẦN 1: CÁC VIEWSETS CƠ BẢN ===
class UserViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAdminUser] 

class TagViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Tag.objects.all()
    serializer_class = TagSerializer
class CarouselSlideViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = CarouselSlide.objects.all().order_by('id')
    serializer_class = CarouselSlideSerializer

class BannerViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Banner.objects.all()
    serializer_class = BannerSerializer
class NearbyPlacesView(APIView):
    """
    Tìm địa điểm quanh đây sử dụng SerpApi (Google Maps Engine)
    để lấy ẢNH THẬT và RATING THẬT.
    """
    def get(self, request):
        lat = request.query_params.get('lat')
        lon = request.query_params.get('lon')
        
        if not lat or not lon:
            return Response({"error": "Thiếu tọa độ lat/lon"}, status=400)
            
        if not SERPAPI_API_KEY:
             return Response({"error": "Chưa cấu hình SERPAPI_API_KEY"}, status=500)

        try:
            # Cấu hình tham số cho SerpApi
            # engine="google_maps": Tìm kiếm trên Google Maps
            # type="search": Tìm kiếm địa điểm
            # google_domain="google.com.vn": Ưu tiên kết quả Việt Nam
            # ll=f"@{lat},{lon},15z": Tọa độ tâm và mức zoom (15z là mức phố)
            params = {
                "engine": "google_maps",
                "q": "tourist attractions", # Hoặc "restaurants", "coffee"
                "ll": f"@{lat},{lon},15z",
                "type": "search",
                "google_domain": "google.com.vn",
                "hl": "vi", # Ngôn ngữ tiếng Việt
                "api_key": SERPAPI_API_KEY
            }
            
            # Gọi API (Dùng requests, không cần cài thư viện google-search-results nếu không muốn)
            res = requests.get("https://serpapi.com/search", params=params)
            data = res.json()
            
            places = []
            
            # Kết quả thường nằm trong 'local_results'
            if 'local_results' in data:
                for item in data['local_results']:
                    # Lấy ảnh: SerpApi thường trả về 'thumbnail'
                    image_url = item.get('thumbnail')
                    if not image_url:
                        # Fallback nếu không có ảnh
                        image_url = "https://via.placeholder.com/200x150.png?text=No+Image"

                    # Lấy tọa độ (nếu có)
                    gps = item.get('gps_coordinates', {})
                    
                    places.append({
                        "id": item.get('place_id') or item.get('data_id'),
                        "name": item.get('title'),
                        "address": item.get('address'),
                        "rating": item.get('rating', 0), # Rating thật từ Google!
                        "reviews": item.get('reviews', 0), # Số lượng review
                        "price": item.get('price'), # Mức giá (vd: ₫₫)
                        "lat": gps.get('latitude'),
                        "lon": gps.get('longitude'),
                        "image": image_url, # Ảnh thật từ Google!
                        "is_recommended": True
                    })
            
            return Response(places, status=200)

        except Exception as e:
            print("Lỗi SerpApi:", e)
            return Response({"error": str(e)}, status=500)
class ReviewViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Review.objects.all()
    serializer_class = ReviewSerializer

class ProductViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Product.objects.all().prefetch_related('categories', 'reviews', 'tags')
    serializer_class = ProductSerializer

class CategoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer

# === PHẦN 2: VIEW TRỢ LÝ AI (TRAVEL ADVICE) ===

class TravelAdviceView(APIView):
    def post(self, request, *args, **kwargs):
        if not GEMINI_API_KEY or not WEATHER_API_KEY or not GEOAPIFY_API_KEY:
            return Response({"error": "Chưa cấu hình đủ API Keys"}, status=500)

        data = request.data
        origin = data.get('origin')
        origin_name = data.get('originName')
        destinations = data.get('destinations')
        destination_names = data.get('destinationNames')

        if not origin or not destinations:
            return Response({"error": "Thiếu dữ liệu vị trí"}, status=400)

        try:
            # 1. LẤY THÔNG TIN THỜI TIẾT CHI TIẾT CHO TẤT CẢ ĐIỂM
            weather_details = []
            
            # A. Thời tiết điểm đi
            origin_weather = self.get_weather_data(origin['latitude'], origin['longitude'], origin_name)
            if origin_weather:
                weather_details.append(origin_weather)

            # B. Thời tiết các điểm đến
            # (Dùng loop để khớp tên với tọa độ)
            for i, dest in enumerate(destinations):
                name = destination_names[i] if destination_names and i < len(destination_names) else f"Điểm đến {i+1}"
                dest_weather = self.get_weather_data(dest['latitude'], dest['longitude'], name)
                if dest_weather:
                    weather_details.append(dest_weather)

            # 2. Lấy lộ trình (Demo lấy từ điểm đầu đến điểm cuối đầu tiên)
            route_list = self.get_all_routes(origin, destinations[0])

            # 3. Tạo chuỗi tóm tắt thời tiết để gửi cho AI (vì AI đọc text)
            weather_summary_str = "; ".join(
                [f"{w['name']}: {w['desc']}, {w['temp']}°C" for w in weather_details]
            )

            # 4. Tạo Prompt
            prompt = self.generate_gemini_prompt(
                origin_name, 
                destination_names, 
                weather_summary_str, # Gửi bản tóm tắt cho AI
                route_list
            )

            # 5. Gọi Gemini
            model = genai.GenerativeModel('gemini-2.0-flash-lite')
            response = model.generate_content(prompt)
            
            # 6. Parse JSON và trả về
            try:
                clean_text = response.text.replace('```json', '').replace('```', '').strip()
                advice_json = json.loads(clean_text)
                
                return Response({
                    "routes": route_list,
                    "advice": advice_json,
                    "weather_details": weather_details # <--- TRẢ VỀ LIST CHI TIẾT ĐỂ FRONTEND HIỂN THỊ CARD
                }, status=200)
            except json.JSONDecodeError:
                return Response({"error": "AI trả về định dạng không hợp lệ"}, status=500)

        except Exception as e:
            print(f"❌ LỖI SERVER CHI TIẾT: {str(e)}")
        import traceback
        traceback.print_exc() # In toàn bộ dấu vết lỗi
        # ===========================================

        return Response(
            {"error": f"Lỗi server: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    def get_weather_data(self, lat, lon, location_name):
        """Lấy thời tiết và trả về Object chi tiết"""
        try:
            url = f"http://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={WEATHER_API_KEY}&units=metric&lang=vi"
            res = requests.get(url).json()
            
            # Trả về Dictionary đầy đủ
            return {
                "name": location_name,
                "temp": round(res['main']['temp']),
                "desc": res['weather'][0]['description'].capitalize(),
                "icon": res['weather'][0]['icon'], # Mã icon (vd: 10d)
                "humidity": res['main']['humidity'],
                "wind_speed": res['wind']['speed']
            }
        except Exception as e:
            print(f"Lỗi weather cho {location_name}: {e}")
            return None

    def get_all_routes(self, origin, destination):
        routes = []
        modes = ['drive', 'motorcycle', 'bicycle', 'walk']
        waypoints = f"{origin['latitude']},{origin['longitude']}|{destination['latitude']},{destination['longitude']}"
        
        for mode in modes:
            try:
                geo_mode = mode
                url = f"https://api.geoapify.com/v1/routing?waypoints={waypoints}&mode={geo_mode}&apiKey={GEOAPIFY_API_KEY}"
                res = requests.get(url).json()
                if 'features' in res and res['features']:
                    props = res['features'][0]['properties']
                    routes.append({
                        "mode": mode,
                        "time": format_time(props.get('time', 0)),
                        "distance": format_distance(props.get('distance', 0))
                    })
            except:
                pass
        return routes

    def generate_gemini_prompt(self, origin_name, destination_names, weather_summary_str, route_list):
        dest_list_str = "\n".join([f"- {name}" for name in destination_names])
        route_info_str = "\n".join([f"- {r['mode']}: {r['distance']}, hết {r['time']}" for r in route_list])

        return f"""
        Bạn là trợ lý du lịch. Hãy phân tích chuyến đi sau:
        1. Xuất phát: {origin_name}
        2. Thời tiết chi tiết: {weather_summary_str}
        3. Điểm đến: {dest_list_str}
        4. Các tùy chọn di chuyển:
        {route_info_str}

        YÊU CẦU: Trả về JSON (không markdown) với 5 key:
        1. "weather_advice": Lời khuyên tổng quan về thời tiết cho cả chuyến đi.
        2. "traffic_alert": Cảnh báo giao thông.
        3. "other_tips": Mẹo vặt.
        4. "recommended_mode": Chọn 1 trong ['drive', 'motorcycle', 'bicycle', 'walk'].
        5. "route_advice": GIẢI THÍCH LÝ DO chọn phương tiện.
        """

# === PHẦN 3: OPTIMIZE ROUTE ===
class OptimizeRouteView(APIView):
    """
    Nhận điểm đi và danh sách điểm đến.
    Sắp xếp lại điểm đến để có tổng quãng đường ngắn nhất (Nearest Neighbor).
    """
    def post(self, request, *args, **kwargs):
        if not GEOAPIFY_API_KEY:
             return Response({"error": "API Key missing"}, status=500)

        data = request.data
        origin_data = data.get('origin') # Có thể là object {lat, lon} hoặc string tên
        destinations = data.get('destinations') # List [{id, name, ...}]

        if not origin_data or not destinations:
            return Response({"error": "Thiếu dữ liệu origin hoặc destinations"}, status=400)

        try:
            # === 1. XỬ LÝ ĐIỂM ĐI (SỬA LỖI Ở ĐÂY) ===
            start_coords = None
            
            # Trường hợp 1: Frontend gửi tọa độ (Dictionary)
            if isinstance(origin_data, dict) and 'latitude' in origin_data and 'longitude' in origin_data:
                # Geoapify dùng chuẩn [longitude, latitude]
                start_coords = [origin_data['longitude'], origin_data['latitude']]
            
            # Trường hợp 2: Frontend gửi tên địa điểm (String)
            elif isinstance(origin_data, str):
                start_coords = self.geocode(origin_data)

            if not start_coords:
                 return Response({"error": "Không xác định được tọa độ điểm đi"}, status=400)

            # === 2. XỬ LÝ CÁC ĐIỂM ĐẾN ===
            jobs = []
            for dest in destinations:
                # Kiểm tra xem điểm đến đã có tọa độ chưa
                if isinstance(dest, dict) and 'latitude' in dest and 'longitude' in dest:
                     coords = [dest['longitude'], dest['latitude']]
                else:
                     # Nếu chưa có tọa độ, gọi Geocode theo tên
                     coords = self.geocode(dest.get('name'))
                
                if coords:
                    jobs.append({
                        "location": coords, # [lon, lat]
                        "id": str(dest['id']) 
                    })
            
            if not jobs:
                return Response({"error": "Không tìm thấy tọa độ cho bất kỳ điểm đến nào"}, status=400)

            # === 3. THUẬT TOÁN SẮP XẾP (NEAREST NEIGHBOR) ===
            sorted_ids = self.solve_tsp(start_coords, jobs)
            
            # === 4. TẠO DANH SÁCH KẾT QUẢ ===
            final_result = []
            # Duyệt qua các ID đã sắp xếp để lấy lại object gốc
            for sorted_id in sorted_ids:
                for dest in destinations:
                    if str(dest['id']) == sorted_id:
                        final_result.append(dest)
                        break
            
            return Response({"optimized_destinations": final_result}, status=200)

        except Exception as e:
            # In lỗi ra terminal để dễ debug
            print(f"Lỗi Optimize: {str(e)}")
            return Response({"error": str(e)}, status=500)

    def geocode(self, address):
        """Hàm phụ trợ để lấy tọa độ [lon, lat] từ tên địa điểm"""
        try:
            if not address: return None
            # Encode URL để xử lý tiếng Việt và ký tự đặc biệt
            encoded_address = requests.utils.quote(address)
            url = f"https://api.geoapify.com/v1/geocode/search?text={encoded_address}&limit=1&apiKey={GEOAPIFY_API_KEY}"
            
            res = requests.get(url).json()
            if res.get('features'):
                props = res['features'][0]['properties']
                return [props['lon'], props['lat']]
        except Exception as e:
            print(f"Geocode error for {address}: {e}")
            return None
        return None

    def haversine(self, lat1, lon1, lat2, lon2):
        """
        Tính khoảng cách giữa 2 điểm GPS trên mặt cầu (đơn vị: mét)
        """
        R = 6371000  # Bán kính trái đất (mét)
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lon2 - lon1)

        a = math.sin(delta_phi / 2) ** 2 + \
            math.cos(phi1) * math.cos(phi2) * \
            math.sin(delta_lambda / 2) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        return R * c

    # === CẬP NHẬT THUẬT TOÁN TSP ===
    def solve_tsp(self, start, jobs):
        """
        Thuật toán tham lam (Nearest Neighbor) sử dụng công thức Haversine
        start: [lon, lat]
        jobs: [{location: [lon, lat], id: ...}]
        """
        # Lưu ý: Geoapify trả về [lon, lat], nhưng Haversine cần (lat, lon)
        current_coords = start # [lon, lat]
        unvisited = jobs.copy()
        path_ids = []

        while unvisited:
            # Tìm điểm gần nhất dựa trên khoảng cách thực tế (Haversine)
            nearest_job = min(unvisited, key=lambda x: self.haversine(
                current_coords[1], current_coords[0], # lat1, lon1
                x['location'][1], x['location'][0]    # lat2, lon2
            ))
            
            path_ids.append(nearest_job['id'])
            current_coords = nearest_job['location']
            unvisited.remove(nearest_job)
            
        return path_ids