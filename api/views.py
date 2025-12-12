# api/views.py
from rest_framework import viewsets, permissions
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import *
from rest_framework.permissions import IsAuthenticated
from .serializers import *
import google.generativeai as genai
from scipy.spatial import cKDTree
import requests
import re
import traceback
from datetime import datetime
from thefuzz import process, fuzz
import os
import joblib
import pandas as pd
from .image_search_service import ImageSearchService
import concurrent.futures
import math
import json
from django.conf import settings
from dotenv import load_dotenv
from .utils import get_external_context, find_and_save_place_info
load_dotenv()

BASE_DIR = settings.BASE_DIR
ML_DIR = os.path.join(BASE_DIR, 'ml_models')

# 1. Load Model AI
print("⏳ Đang khởi tạo hệ thống AI & Bản đồ số...")
try:
    traffic_model = joblib.load(os.path.join(ML_DIR, 'traffic_model.pkl'))
    street_encoder = joblib.load(os.path.join(ML_DIR, 'street_encoder.pkl'))
    known_streets = set(street_encoder.classes_) 
    print("✅ Model AI đã tải xong.")
except Exception as e:
    traffic_model = None
    print(f"❌ Lỗi tải Model AI: {e}")

# 2. Load Dữ liệu Không gian (Nodes & Streets)
spatial_tree = None
node_street_map = {} 
spatial_nodes_ids = []

try:
    print("⏳ Đang tải dữ liệu bản đồ (Nodes/Streets)...")
    df_nodes = pd.read_csv(os.path.join(ML_DIR, 'nodes.csv'))
    df_segments = pd.read_csv(os.path.join(ML_DIR, 'segments.csv'))
    df_streets = pd.read_csv(os.path.join(ML_DIR, 'streets.csv'))

    # === SỬA LỖI Ở ĐÂY (Dựa trên tên cột bạn cung cấp) ===
    
    # 1. Merge Segment với Street
    # Segments dùng 'street_id', Streets dùng '_id'
    merged = pd.merge(df_segments, df_streets, left_on='street_id', right_on='_id', how='inner')
    
    # 2. Tạo Map: Node -> Tên đường
    # Segments dùng 's_node_id' để nối với Node
    # Streets dùng cột 'name' để lưu tên đường
    # (Lưu ý: dùng .strip() để xóa khoảng trắng thừa nếu có)
    temp_map = dict(zip(merged['s_node_id'], merged['name'].astype(str).str.strip())) 
    node_street_map = temp_map

    # 3. Lọc Node và tạo KDTree
    # Nodes dùng cột '_id'
    NODE_ID_COL = '_id' 
    
    # Chỉ lấy những node nào có nằm trên một con đường
    valid_nodes = df_nodes[df_nodes[NODE_ID_COL].isin(node_street_map.keys())]
    
    # Lấy tọa độ lat/long (trong file của bạn là 'lat' và 'long')
    node_coords = valid_nodes[['lat', 'long']].values 
    node_ids = valid_nodes[NODE_ID_COL].values 
    
    spatial_tree = cKDTree(node_coords)
    spatial_nodes_ids = node_ids
    
    print(f"✅ Bản đồ số đã tải xong ({len(valid_nodes)} điểm nút).")

except Exception as e:
    print(f"⚠️ Không thể tải dữ liệu bản đồ (Spatial): {e}")
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
def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371  # Bán kính trái đất (km)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) * math.sin(dlat / 2) + \
        math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * \
        math.sin(dlon / 2) * math.sin(dlon / 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c
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
    def get(self, request):
        lat = request.query_params.get('lat')
        lon = request.query_params.get('lon')
        request_type = request.query_params.get('type', 'sights') 
        
        if not lat or not lon:
            return Response({"error": "Thiếu tọa độ lat/lon"}, status=400)

        try:
            user_lat = float(lat)
            user_lon = float(lon)
        except ValueError:
            return Response({"error": "Tọa độ không hợp lệ"}, status=400)

        # 1. CHECK CACHE (Giữ nguyên)
        radius = 0.045 
        places_in_db = Place.objects.filter(
            lat__range=(user_lat - radius, user_lat + radius),
            lon__range=(user_lon - radius, user_lon + radius),
            category=request_type
        )
        
        if places_in_db.exists():
            print(f"CACHE HIT: {places_in_db.count()} items.")
            serializer = PlaceSerializer(places_in_db, many=True)
            return Response(serializer.data, status=200)

        # 2. GỌI API (Giữ nguyên)
        print(f"⚠️ CACHE MISS: Calling Google Maps...")
        
        keyword_map = {
            'sights': 'top sights', 'coffee': 'coffee shops', 'food': 'restaurants',
            'park': 'parks', 'shopping': 'shopping malls', 'hotel': 'hotels',
            'entertainment': 'entertainment'
        }
        search_query = keyword_map.get(request_type, 'tourist attractions')

        try:
            if not SERPAPI_API_KEY: return Response({"error": "No API Key"}, 500)
            
            params = {
                "engine": "google_maps", "q": search_query, "ll": f"@{lat},{lon},15z",
                "type": "search", "google_domain": "google.com.vn", "hl": "en",
                "api_key": SERPAPI_API_KEY
            }
            res = requests.get("https://serpapi.com/search", params=params)
            local_results = res.json().get('local_results', [])

            if not local_results: return Response([], status=200)

            # === SỬA ĐỔI QUAN TRỌNG Ở ĐÂY ===

            # Hàm này CHỈ XỬ LÝ DỮ LIỆU, KHÔNG GỌI DB
            def prepare_data(item):
                try:
                    # Lấy thông tin đầu vào
                    title = item.get('title', '')
                    place_type = item.get('type', '')
                    category = item.get('category', '') # Một số kết quả có thêm field này
                    description = item.get('description')
                    if not description:
                        description = item.get('snippet')
                    
                    # Nếu vẫn không có, thử lấy từ extensions (thường chứa thông tin phụ)
                    if not description and item.get('extensions'):
                        # extensions thường là list, nối lại thành chuỗi
                        description = ", ".join([str(ext) for ext in item.get('extensions', [])])
                    title_lower = title.lower()
                    type_lower = place_type.lower()
                    cat_lower = category.lower()

                    # === BỘ LỌC NÂNG CAO (AGGRESSIVE FILTER) ===
                    
                    # 1. DANH SÁCH ĐEN CHO LOẠI HÌNH (TYPE)
                    # Loại bỏ các văn phòng, bến xe, công ty
                    type_blacklist = [
                        'travel agency', 'tour operator', 'tour agency', 
                        'corporate office', 'bus station', 'transit station',
                        'establishment', 'point of interest', # Quá chung chung thường là rác
                        'công ty', 'đại lý', 'văn phòng', 'nhà xe'
                    ]
                    
                    # 2. DANH SÁCH ĐEN CHO TÊN ĐỊA ĐIỂM (TITLE) - QUAN TRỌNG
                    # Nếu tên có chữ "Tour", "Travel", "Vé"... thì loại ngay
                    title_blacklist = [
                        'travel', 'tour', 'ticket', 'booking', 'transport', 'limousine', 
                        'visa', 'service', 'office',
                        'du lịch', 'lữ hành', 'vé máy bay', 'vé tàu', 'vận tải', 'xe khách'
                    ]

                    # --- THỰC HIỆN LỌC ---
                    
                    # Check 1: Lọc theo Type (Loại hình)
                    if any(bad in type_lower for bad in type_blacklist): 
                        return None
                    
                    # Check 2: Lọc theo Category (Danh mục phụ)
                    if any(bad in cat_lower for bad in type_blacklist): 
                        return None

                    # Check 3: Lọc theo Tên (Title)
                    # Chỉ áp dụng lọc tên gắt gao khi tìm địa điểm tham quan ('sights')
                    # Vì nếu tìm 'food' mà quán tên "Travel Coffee" thì không nên xóa.
                    if request_type == 'sights':
                        if any(bad in title_lower for bad in title_blacklist): 
                            return None

                    # ---------------------

                    place_id = item.get('place_id') or item.get('data_id')
                    if not place_id or not title: return None

                    # Tìm ảnh (Tốn thời gian -> Chạy trong thread OK)
                    image_url = item.get('thumbnail', "https://via.placeholder.com/200x150.png?text=No+Image")
                    try:
                        search_service = ImageSearchService()
                        images = search_service.find_images_for_destination(title, "Vietnam", 1)
                        if images: image_url = images[0]['image']
                    except: pass

                    # TRẢ VỀ DICT DỮ LIỆU
                    return {
                        'place_id': place_id,
                        'name': title,
                        'category': request_type,
                        'description': description,
                        'address': item.get('address'),
                        'lat': item.get('gps_coordinates', {}).get('latitude'),
                        'lon': item.get('gps_coordinates', {}).get('longitude'),
                        'rating': item.get('rating', 0),
                        'reviews': item.get('reviews', 0),
                        'price': item.get('price'),
                        'image': image_url,
                        'working_hours': item.get('operating_hours', {}),
                        'open_state': item.get('open_state', '')
                    }
                except Exception as e: 
                    # print(f"Lỗi xử lý item con: {e}") # Bỏ comment nếu muốn debug
                    return None
            # BƯỚC 3: CHẠY SONG SONG ĐỂ LẤY DỮ LIỆU (Không động vào DB)
            data_to_save = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                results = executor.map(prepare_data, local_results)
                for res in results:
                    if res: data_to_save.append(res)

            # BƯỚC 4: LƯU VÀO DB (CHẠY TUẦN TỰ - MAIN THREAD)
            # SQLite an toàn tuyệt đối khi chạy ở đây
            saved_places = []
            print(f"Đang lưu {len(data_to_save)} địa điểm vào DB...")
            
            for item_data in data_to_save:
                try:
                    place_obj, created = Place.objects.update_or_create(
                        place_id=item_data['place_id'],
                        defaults=item_data # Dict data đã chuẩn bị ở trên
                    )
                    saved_places.append(place_obj)
                except Exception as db_err:
                    print(f"Lỗi lưu DB item {item_data['name']}: {db_err}")

            serializer = PlaceSerializer(saved_places, many=True)
            return Response(serializer.data, status=200)

        except Exception as e:
            print("Lỗi Server:", e)
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
        # ... (Phần kiểm tra API Key giữ nguyên) ...
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
            # 1. THỜI TIẾT (Giữ nguyên)
            weather_details = []
            origin_weather = self.get_weather_data(origin['latitude'], origin['longitude'], origin_name)
            if origin_weather: weather_details.append(origin_weather)

            for i, dest in enumerate(destinations):
                name = destination_names[i] if destination_names and i < len(destination_names) else f"Điểm đến {i+1}"
                dest_weather = self.get_weather_data(dest['latitude'], dest['longitude'], name)
                if dest_weather: weather_details.append(dest_weather)

            # 2. LỘ TRÌNH (Giữ nguyên)
            route_list = self.get_all_routes(origin, destinations[0])

            # === 3. (MỚI) DỰ BÁO GIAO THÔNG ===
            traffic_reports = []
            # Dự báo cho điểm xuất phát
            traffic_reports.append(self.get_traffic_forecast(origin['latitude'], origin['longitude'], origin_name))
            
            # Dự báo cho các điểm đến
            for i, dest in enumerate(destinations):
                name = destination_names[i] if destination_names and i < len(destination_names) else f"Dest {i}"
                traffic_reports.append(self.get_traffic_forecast(dest['latitude'], dest['longitude'], name))
            
            # Lọc bỏ các kết quả rỗng và nối thành chuỗi
            traffic_summary_str = "\n".join([t for t in traffic_reports if t])
            # ==================================

            # 4. CHUẨN BỊ DATA CHO PROMPT
            weather_summary_str = "; ".join([f"{w['name']}: {w['desc']}, {w['temp']}°C" for w in weather_details])

            # 5. TẠO PROMPT (Có thêm thông tin giao thông)
            prompt = self.generate_gemini_prompt(
                origin_name, 
                destination_names, 
                weather_summary_str, 
                traffic_summary_str, # <--- Truyền vào đây
                route_list
            )

            # 6. GỌI GEMINI (Giữ nguyên)
            model = genai.GenerativeModel('gemini-2.0-flash-lite')
            response = model.generate_content(prompt)
            
            try:
                clean_text = response.text.replace('```json', '').replace('```', '').strip()
                advice_json = json.loads(clean_text)
                
                return Response({
                    "routes": route_list,
                    "advice": advice_json,
                    "weather_details": weather_details
                }, status=200)
            except json.JSONDecodeError:
                return Response({"error": "AI trả về định dạng không hợp lệ"}, status=500)

        except Exception as e:
            print(f"❌ Lỗi: {e}")
            return Response({"error": str(e)}, status=500)

    # --- HÀM PHỤ TRỢ ---

    def get_weather_data(self, lat, lon, name):
        # ... (Giữ nguyên code cũ của bạn) ...
        try:
            url = f"http://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={WEATHER_API_KEY}&units=metric&lang=vi"
            res = requests.get(url).json()
            return {
                "name": name,
                "temp": round(res['main']['temp']),
                "desc": res['weather'][0]['description'].capitalize(),
                "icon": res['weather'][0]['icon'],
                "humidity": res['main']['humidity'],
                "wind_speed": res['wind']['speed']
            }
        except:
            return None

    def get_all_routes(self, origin, destination):
        # ... (Giữ nguyên code cũ của bạn) ...
        routes = []
        modes = ['drive', 'motorcycle', 'bicycle', 'walk']
        waypoints = f"{origin['latitude']},{origin['longitude']}|{destination['latitude']},{destination['longitude']}"
        for mode in modes:
            try:
                url = f"https://api.geoapify.com/v1/routing?waypoints={waypoints}&mode={mode}&apiKey={GEOAPIFY_API_KEY}"
                res = requests.get(url).json()
                if 'features' in res and res['features']:
                    props = res['features'][0]['properties']
                    routes.append({
                        "mode": mode,
                        "time": self.format_time(props.get('time', 0)), # Nhớ thêm hàm format_time hoặc import
                        "distance": self.format_distance(props.get('distance', 0))
                    })
            except: pass
        return routes

    # === HÀM MỚI: DỰ BÁO GIAO THÔNG ===
    def get_traffic_forecast(self, lat, lon, name):
        if not traffic_model or not spatial_tree:
            return None
            
        try:
            # 1. Tìm đường gần nhất (Spatial Search)
            radius_deg = 0.2 / 111.0 
            distances, indices = spatial_tree.query([float(lat), float(lon)], k=1)
            
            target_street = None
            if indices < len(spatial_nodes_ids):
                real_node_id = spatial_nodes_ids[indices]
                s_name = node_street_map.get(real_node_id)
                if s_name and str(s_name).strip() in known_streets:
                    target_street = str(s_name).strip()
            
            if not target_street:
                return f"- Tại {name}: Không có dữ liệu lịch sử giao thông."

            # 2. Dự báo
            now = datetime.now()
            hour = now.hour
            weekday = now.weekday()
            
            street_code = street_encoder.transform([target_street])[0]
            input_data = pd.DataFrame([[hour, weekday, street_code]], columns=['hour', 'weekday', 'street_encoded'])
            pred_los = traffic_model.predict(input_data)[0]
            
            status = "Bình thường"
            if pred_los in ['E', 'F']: status = "TẮC NGHẼN CAO (LOS E/F)"
            elif pred_los in ['C', 'D']: status = "Đông xe (LOS C/D)"
            elif pred_los in ['A', 'B']: status = "Thông thoáng (LOS A/B)"
            
            return f"- Tại {name} (Khu vực {target_street}): Dự báo {status}."
            
        except Exception as e:
            print(f"Lỗi Traffic Forecast: {e}")
            return None

    # === CẬP NHẬT PROMPT ===
    def generate_gemini_prompt(self, origin_name, destination_names, weather_str, traffic_str, route_list):
        dest_list_str = "\n".join([f"- {name}" for name in destination_names])
        route_info_str = "\n".join([f"- {r['mode']}: {r['distance']}, hết {r['time']}" for r in route_list])

        return f"""
        Bạn là trợ lý du lịch thông minh. Hãy phân tích dữ liệu chuyến đi sau:

        1. HÀNH TRÌNH:
           - Điểm đi: {origin_name}
           - Điểm đến: {dest_list_str}

        2. ĐIỀU KIỆN THỰC TẾ:
           - Thời tiết: {weather_str}
           - Dự báo Giao thông (từ mô hình AI): 
             {traffic_str}

        3. TÙY CHỌN DI CHUYỂN (Geoapify):
           {route_info_str}

        YÊU CẦU PHẢN HỒI JSON (Tuyệt đối không dùng Markdown, chỉ trả về JSON thuần):
        {{
            "weather_advice": "Lời khuyên ngắn gọn về thời tiết (vd: mưa thì nên mang áo mưa)",
            "traffic_alert": "Phân tích kỹ dữ liệu giao thông ở trên. Nếu có 'TẮC NGHẼN CAO', hãy cảnh báo mạnh và khuyên đi sớm hoặc đổi phương tiện.",
            "recommended_mode": "Chọn 1 phương tiện tối ưu nhất (drive/motorcycle/bicycle/walk) dựa trên cả thời tiết và giao thông.",
            "route_advice": "Giải thích lý do chọn phương tiện trên (Ví dụ: Tuy trời đẹp nhưng đường tắc, nên đi xe máy cho linh hoạt...)",
            "other_tips": "Một mẹo nhỏ thú vị cho chuyến đi."
        }}
        """

    # Helper format (nếu chưa có)
    def format_time(self, seconds):
        minutes = round(seconds / 60)
        if minutes < 60: return f"{minutes} phút"
        return f"{minutes // 60} giờ {minutes % 60} phút"

    def format_distance(self, meters):
        if meters < 1000: return f"{meters} m"
        return f"{round(meters / 1000, 1)} km"
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

class PredictTrafficView(APIView):
    def post(self, request):
        """
        Input ưu tiên: { "lat": 10.78, "lon": 106.70 }
        Input phụ: { "street_name": "Nguyen Hue" }
        """
        now = datetime.now()
        current_hour = now.hour
        current_weekday = now.weekday()

        lat = request.data.get('lat')
        lon = request.data.get('lon')
        street_name_input = request.data.get('street_name') # Tên địa điểm người dùng nhập
        
        target_streets = [] 
        detected_street_name = "" # Tên đường thực tế tìm thấy trong Data

        # === CHIẾN THUẬT 1: TÌM THEO TỌA ĐỘ (CHÍNH XÁC NHẤT) ===
        if lat and lon and spatial_tree:
            try:
                # 1. Tìm điểm nút gần nhất trong bán kính 200m (0.2km)
                # Lưu ý: Bán kính nhỏ để đảm bảo chính xác, không bắt nhầm đường song song
                radius_deg = 0.2 / 111.0 
                
                # query_ball_point trả về danh sách index, ta lấy cái gần nhất
                distances, indices = spatial_tree.query([float(lat), float(lon)], k=1) # k=1: Lấy 1 điểm gần nhất
                
                # Nếu tìm thấy
                if indices < len(spatial_nodes_ids):
                    real_node_id = spatial_nodes_ids[indices]
                    s_name = node_street_map.get(real_node_id)
                    
                    if s_name:
                        clean_name = str(s_name).strip()
                        if clean_name in known_streets:
                            target_streets = [clean_name]
                            detected_street_name = clean_name
                            print(f"📍 Mapping: Tọa độ ({lat},{lon}) -> Đường '{clean_name}'")
            except Exception as e:
                print(f"Lỗi Spatial Search: {e}")
        
        # === CHIẾN THUẬT 2: TÌM THEO TÊN (NẾU KHÔNG CÓ TỌA ĐỘ) ===
        # Chỉ chạy nếu chiến thuật 1 thất bại
        if not target_streets and street_name_input:
             # ... (Giữ nguyên logic Fuzzy Matching cũ của bạn ở đây) ...
             # Nhưng lưu ý: street_name_input lúc này là "Trường ĐH...", rất khó khớp
             pass

        # === KIỂM TRA KẾT QUẢ TÌM KIẾM ===
        if not target_streets:
             return Response({
                 "street": street_name_input,
                 "status": "No Data",
                 "message": "Không tìm thấy dữ liệu đường tại vị trí này",
                 "timeline": []
             })

        # === 2. DỰ BÁO (GIỮ NGUYÊN LOGIC CŨ) ===
        timeline_result = []
        
        for i in range(3):
            target_hour = (current_hour + i) % 24
            target_weekday = current_weekday
            if current_hour + i >= 24: target_weekday = (current_weekday + 1) % 7
            
            # --- Chạy Model ---
            # Vì target_streets giờ chỉ chứa 1 tên đường chính xác nhất từ tọa độ
            # Nên vòng lặp này sẽ chạy rất nhanh và chuẩn
            st = target_streets[0] 
            
            try:
                street_code = street_encoder.transform([st])[0]
                input_data = pd.DataFrame([[target_hour, target_weekday, street_code]], 
                                          columns=['hour', 'weekday', 'street_encoded'])
                pred_los = traffic_model.predict(input_data)[0]
                
                # Map LOS sang màu sắc/trạng thái
                status_map = {
                    'A': ("Thông thoáng", "#28A745"), 'B': ("Thông thoáng", "#28A745"),
                    'C': ("Đông xe", "#FFC107"), 'D': ("Đông xe", "#FFC107"),
                    'E': ("Tắc đường", "#DC3545"), 'F': ("Kẹt cứng", "#8B0000")
                }
                status_text, color_hex = status_map.get(pred_los, ("Không rõ", "#9E9E9E"))

                timeline_result.append({
                    "time_display": f"{target_hour}:00",
                    "status": status_text,
                    "color": color_hex,
                    "los": pred_los
                })
            except:
                continue

        # === 3. TRẢ KẾT QUẢ ===
        current = timeline_result[0] if timeline_result else {}

        return Response({
            # Trả về cả tên địa điểm gốc VÀ tên đường AI tìm thấy
            "input_name": street_name_input, 
            "street": detected_street_name, # Đây là tên đường AI dùng (Ví dụ: "Đinh Tiên Hoàng")
            
            "current_status": current.get('status', 'N/A'),
            "current_color": current.get('color', '#9E9E9E'),
            "current_los": current.get('los', 'N/A'),
            "timeline": timeline_result
        })
    
class FavoriteView(APIView):
    permission_classes = [IsAuthenticated] # Bắt buộc phải đăng nhập

    def get(self, request):
        """Lấy danh sách yêu thích của User"""
        favorites = Favorite.objects.filter(user=request.user).order_by('-created_at')
        # Chúng ta chỉ muốn lấy thông tin Place ra thành list
        places = [fav.place for fav in favorites]
        serializer = PlaceSerializer(places, many=True)
        return Response(serializer.data, status=200)

    def post(self, request):
        print("="*30)
        print("🚀 DEBUG FAVORITE VIEW POST")
        print(f"👤 User: {request.user}")
        print(f"🔗 Path: {request.path}")
        print(f"📦 Body Data: {request.data}")
        print("="*30)
        """Toggle Like/Unlike: Gửi { "place_id": "..." }"""
        place_id_str = request.data.get('place_id')
        
        if not place_id_str:
            return Response({"error": "Thiếu place_id"}, status=400)

        try:
            # Dữ liệu gửi lên: 49 (int) hoặc "ChIJ..." (str)
            input_id = request.data.get('place_id')
            
            # Logic tìm kiếm thông minh:
            # Nếu là số -> Tìm theo ID (Primary Key)
            # Nếu là chuỗi dài -> Tìm theo place_id (Google ID)
            if str(input_id).isdigit():
                place = Place.objects.get(id=int(input_id))
            else:
                place = Place.objects.get(place_id=input_id)

            # ... Phần logic Like/Unlike bên dưới giữ nguyên ...
            favorite_item = Favorite.objects.filter(user=request.user, place=place).first()

            if favorite_item:
                favorite_item.delete()
                print("✅ Unliked thành công")
                return Response({"status": "unliked", "place_id": input_id}, status=200)
            else:
                Favorite.objects.create(user=request.user, place=place)
                print("✅ Liked thành công")
                return Response({"status": "liked", "place_id": input_id}, status=201)

        except Place.DoesNotExist:
            print(f"❌ Không tìm thấy địa điểm có ID: {input_id}")
            return Response({"error": "Địa điểm không tồn tại"}, status=404)
        except Exception as e:
            print(f"❌ Lỗi server: {e}")
            return Response({"error": str(e)}, status=500)
        
class PlanTripSmartView(APIView):
    def post(self, request):
        data = request.data
        origin = data.get('origin', 'TP.HCM')
        destinations = data.get('destinations', [])
        departure_time_str = data.get('departure_time', '08:00')
        force_plan = data.get('force', False)
        client_weather = data.get('weather_context')
        client_traffic = data.get('traffic_context')
        
        current_lat = data.get('lat', 10.7769)
        current_lon = data.get('lon', 106.7009)
        if not force_plan:
            if client_weather and client_traffic:
                weather_desc = client_weather
                traffic_desc = client_traffic
            else:
                weather_desc, traffic_desc = get_external_context(current_lat, current_lon, departure_time_str)

            check_prompt = f"""
            Bạn là trợ lý giao thông. Người dùng khởi hành lúc: {departure_time_str}.
            Ngữ cảnh: Thời tiết {weather_desc}, Giao thông {traffic_desc}.
            Đánh giá xem giờ này có HỢP LÝ để đi du lịch không?
            TRẢ VỀ JSON (bằng tiếng anh): {{ "is_reasonable": boolean, "reason": "...", "suggested_time": "HH:mm" }}
            """
            
            try:
                model = genai.GenerativeModel('gemini-2.0-flash-lite')
                response = model.generate_content(check_prompt)
                res_json = json.loads(response.text.replace("```json", "").replace("```", "").strip())
                
                if not res_json.get("is_reasonable", True):
                    return Response({
                        "status": "warning",
                        "message": res_json.get('reason'),
                        "suggested_time": res_json.get('suggested_time', departure_time_str)
                    })
            except: pass
        destinations_formatted = "\n".join([f"- {dest}" for dest in destinations])
        
        plan_prompt = f"""
        Tôi đang ở '{origin}'.
        Tôi muốn lên lịch trình đi qua {len(destinations)} địa điểm sau (theo thứ tự hợp lý nhất):
        
        {destinations_formatted}  <-- DÙNG BIẾN NÀY THAY VÌ .JOIN(',')
        
        Giờ khởi hành: {departure_time_str}.
        
        YÊU CẦU QUAN TRỌNG:
        1. Chỉ trả về đúng {len(destinations)} địa điểm trong danh sách JSON (không thêm điểm xuất phát). 
        2. TUYỆT ĐỐI KHÔNG TỰ Ý TÁCH ĐỊA ĐIỂM DỰA TRÊN DẤU PHẨY (Ví dụ: "Chợ Bến Thành, Quận 1" là 1 địa điểm, không phải 2).
        3. Trả lời bằng Tiếng Anh
        4. TRẢ VỀ JSON ARRAY (Không markdown):
        [
            {{
                "location_name": "Tên địa điểm chính xác",
                "arrival_time": "HH:mm",
                "duration": "Ví dụ: 60 - 90 phút",
                "travel_to_next": {{ "time": "...", "distance": "..." }} (hoặc null nếu là điểm cuối)
            }}
        ]
        """

        schedule_list = []
        try:
            model = genai.GenerativeModel('gemini-2.0-flash-lite')
            response = model.generate_content(plan_prompt)
            schedule_list = json.loads(response.text.replace("```json", "").replace("```", "").strip())
        except Exception as e:
            return Response({"status": "error", "message": str(e)})

        # ==================================================================
        # GIAI ĐOẠN 3: LÀM GIÀU DỮ LIỆU (SERPAPI + DB CACHE)
        # ==================================================================
        
        def clean_place_name(name):
            return re.sub(r'^[\d\.\-\*\s]+', '', name).strip()

        def enrich_location_data(item):
            raw_name = item.get('location_name', '')
            clean_name = clean_place_name(raw_name)
            place = None
            place = Place.objects.filter(name__iexact=clean_name).first()
            if not place:
                all_places = list(Place.objects.values('id', 'name'))

                choices = {p['name']: p['id'] for p in all_places}
                
                if choices:
                    # Tìm tên trong DB giống với 'clean_name' nhất
                    # limit=1: Chỉ lấy 1 kết quả tốt nhất
                    best_match = process.extractOne(clean_name, choices.keys(), scorer=fuzz.token_set_ratio)
                    
                    # best_match dạng: ('Tên Trong DB', Score)
                    if best_match:
                        match_name, score = best_match
                        
                        # NGƯỠNG CHẤP NHẬN: 85/100 (Bạn có thể chỉnh số này)
                        if score >= 85: 
                            print(f"✨ Fuzzy Match: '{clean_name}' ≈ '{match_name}' (Score: {score})")
                            place_id = choices[match_name]
                            place = Place.objects.get(id=place_id)

            # ---------------------------------------------------------
            # 🚦 KẾT QUẢ
            # ---------------------------------------------------------
            if place:
                # ✅ CACHE HIT
                print(f"🎯 Cache Hit: {clean_name} -> ID: {place.id}")
                item['image'] = place.image
                item['highlight'] = place.description
                # Cập nhật lại tên chuẩn từ DB để hiển thị đẹp hơn
                item['location_name'] = place.name 
            else:
                # ⚠️ CACHE MISS -> Gọi API
                print(f"🔍 Cache Miss: {clean_name} (Không tìm thấy tên giống > 85%)")
                
                result = find_and_save_place_info(clean_name)
                
                if hasattr(result, 'image'): 
                    item['image'] = result.image
                    item['highlight'] = result.description
                elif isinstance(result, dict):
                    item['image'] = result.get('image')
                    item['highlight'] = result.get('description')
                else:
                    item['image'] = "https://via.placeholder.com/400x200"
                    item['highlight'] = "Địa điểm tham quan thú vị."

            return item
        # 2. CHẠY SONG SONG
        # Dù logic đã gọn, nhưng việc gọi find_and_save_place_info vẫn tốn thời gian mạng
        # nên vẫn cần ThreadPoolExecutor.
        enriched_schedule = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            results = executor.map(enrich_location_data, schedule_list)
            for res in results:
                enriched_schedule.append(res)

        return Response({
            "status": "success",
            "data": enriched_schedule
        })
    
class GoodTrafficRoutesView(APIView):
    def post(self, request):
        try:
            # 1. Kiểm tra Model đã load chưa
            if traffic_model is None or street_encoder is None:
                return Response({"status": "error", "message": "Model AI chưa sẵn sàng"}, status=503)

            # 2. Lấy Input
            user_lat = request.data.get('lat')
            user_lon = request.data.get('lon')
            radius_km = request.data.get('radius', 5) # Mặc định tìm trong 5km

            if user_lat is None or user_lon is None:
                return Response({"status": "error", "message": "Thiếu tọa độ lat/lon"}, status=400)

            # Ép kiểu an toàn
            user_lat = float(user_lat)
            user_lon = float(user_lon)
            radius_km = float(radius_km)

            # 3. Lọc thô từ Database (Bounding Box)
            # 1 độ vĩ độ ~ 111km. 
            lat_min = user_lat - (radius_km / 111)
            lat_max = user_lat + (radius_km / 111)
            lon_min = user_lon - (radius_km / 111)
            lon_max = user_lon + (radius_km / 111)

            # Lấy các segment trong khu vực
            nearby_segments = TrafficSegment.objects.filter(
                lat_snode__range=(lat_min, lat_max),
                long_snode__range=(lon_min, lon_max)
            )
            
            count = nearby_segments.count()
            print(f"🔍 Tìm thấy {count} đoạn đường trong bán kính {radius_km}km.")
            
            if count == 0:
                return Response({"status": "success", "good_routes": [], "message": "Không có đường nào gần đây"})

            # 4. Chuẩn bị dữ liệu để dự đoán
            now = datetime.now()
            current_hour = now.hour
            current_weekday = now.weekday()
            
            good_roads = []

            # 5. Duyệt và Dự đoán
            for seg in nearby_segments:
                try:
                    # Kiểm tra xem tên đường có trong tập huấn luyện không
                    # (Dùng set để tra cứu nhanh hơn, ở đây dùng tạm classes_)
                    if seg.street_name in street_encoder.classes_:
                        # Mã hóa tên đường
                        street_code = street_encoder.transform([seg.street_name])[0]
                        
                        # Dự đoán: [hour, weekday, street_code]
                        # Input cho model phải là mảng 2 chiều [[...]]
                        # pred_los = traffic_model.predict([[current_hour, current_weekday, street_code]])[0]
                        input_df = pd.DataFrame(
                            [[current_hour, current_weekday, street_code]], 
                            columns=['hour', 'weekday', 'street_encoded']
                        )
                        
                        pred_los = traffic_model.predict(input_df)[0]
                        
                        # CHỈ LẤY NẾU LOS TỐT (A hoặc B)
                        if pred_los in ['A', 'B']:
                            good_roads.append({
                                "id": seg.id,
                                "street_name": seg.street_name,
                                "los": pred_los,
                                "coords": [
                                    {"latitude": seg.lat_snode, "longitude": seg.long_snode},
                                    {"latitude": seg.lat_enode, "longitude": seg.long_enode}
                                ]
                            })
                except Exception as inner_e:
                    # Lỗi ở 1 segment không nên làm chết cả API
                    # print(f"⚠️ Lỗi dự đoán seg {seg.id}: {inner_e}")
                    continue 

            print(f"✨ Đã lọc được {len(good_roads)} đoạn đường tốt (LOS A/B).")
            
            return Response({"status": "success", "good_routes": good_roads})

        except Exception as e:
            print("❌ Lỗi Server 500:")
            traceback.print_exc() # In chi tiết lỗi ra terminal
            return Response({"status": "error", "message": str(e)}, status=500)
        
def calculate_bearing(lat1, lon1, lat2, lon2):
    """
    Trả về góc (0-360 độ) từ điểm 1 hướng tới điểm 2.
    0: Bắc, 90: Đông, 180: Nam, 270: Tây
    """
    dLon = math.radians(lon2 - lon1)
    lat1 = math.radians(lat1)
    lat2 = math.radians(lat2)

    y = math.sin(dLon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - \
        math.sin(lat1) * math.cos(lat2) * math.cos(dLon)
    
    bearing = math.atan2(y, x)
    bearing = math.degrees(bearing)
    
    # Chuẩn hóa về 0-360
    return (bearing + 360) % 360

class FindGreenRouteView(APIView):
    def post(self, request):
        try:
            start_lat = float(request.data.get('start_lat'))
            start_lon = float(request.data.get('start_lon'))
            end_lat = float(request.data.get('end_lat'))
            end_lon = float(request.data.get('end_lon'))
            
            # Cấu hình tối ưu
            STEP_RADIUS_KM = 3.0  
            MAX_STEPS = 15 # Tăng số bước lên chút vì giờ chạy nhanh rồi
            
            waypoints = []        
            current_lat = start_lat
            current_lon = start_lon
            visited_segment_ids = set()

            now = datetime.now()
            hour = now.hour
            weekday = now.weekday()

            print(f"🚀 Bắt đầu tìm đường siêu tốc...")

            for step in range(MAX_STEPS):
                # 1. Check đích
                dist_to_dest = calculate_distance(current_lat, current_lon, end_lat, end_lon)
                if dist_to_dest <= 2.0:
                    print("🏁 Đã vào vùng tiếp cận đích.")
                    break

                target_bearing = calculate_bearing(current_lat, current_lon, end_lat, end_lon)

                # 2. Query DB (Chỉ lấy các trường cần thiết để nhẹ RAM)
                lat_min = current_lat - (STEP_RADIUS_KM / 111)
                lat_max = current_lat + (STEP_RADIUS_KM / 111)
                lon_min = current_lon - (STEP_RADIUS_KM / 111)
                lon_max = current_lon + (STEP_RADIUS_KM / 111)

                candidates_qs = TrafficSegment.objects.filter(
                    lat_snode__range=(lat_min, lat_max),
                    long_snode__range=(lon_min, lon_max)
                ).exclude(segment_id__in=visited_segment_ids).values(
                    'segment_id', 'street_name', 'lat_snode', 'long_snode', 'lat_enode', 'long_enode'
                ) # Dùng .values() để lấy dict, nhanh hơn lấy object model

                # Chuyển QuerySet thành List để xử lý
                candidates = list(candidates_qs)
                if not candidates:
                    print("⚠️ Không tìm thấy đường nào xung quanh.")
                    break

                # 3. LỌC SỚM (Pre-filter): Chỉ giữ lại đường ĐÚNG HƯỚNG
                # Bước này loại bỏ rác trước khi AI phải làm việc
                valid_candidates = []
                predict_inputs = [] # Danh sách để gom batch dự đoán

                for seg in candidates:
                    # Bỏ qua tên đường lạ
                    if seg['street_name'] not in street_encoder.classes_:
                        continue

                    # Tính góc
                    seg_bearing = calculate_bearing(current_lat, current_lon, seg['lat_snode'], seg['long_snode'])
                    angle_diff = abs(target_bearing - seg_bearing)
                    if angle_diff > 180: angle_diff = 360 - angle_diff
                    
                    # Chỉ lấy hướng tiến (< 85 độ)
                    if angle_diff > 85: 
                        continue
                    
                    # Mã hóa tên đường ngay tại đây
                    street_code = street_encoder.transform([seg['street_name']])[0]
                    
                    # Lưu lại để dự đoán sau
                    valid_candidates.append({
                        **seg, 
                        'street_code': street_code,
                        'angle_diff': angle_diff
                    })
                    
                    # Chuẩn bị input cho Batch Predict: [hour, weekday, street_code]
                    predict_inputs.append([hour, weekday, street_code])

                if not valid_candidates:
                    print("⚠️ Hết đường đúng hướng.")
                    break

                # 4. BATCH PREDICTION (Dự đoán 1 lần cho tất cả)
                # Đây là chìa khóa tăng tốc độ
                input_df = pd.DataFrame(predict_inputs, columns=['hour', 'weekday', 'street_encoded'])
                predictions = traffic_model.predict(input_df) # Trả về mảng ['A', 'B', 'E', ...]

                # 5. TÌM ĐƯỜNG TỐT NHẤT TRONG KẾT QUẢ
                best_next_point = None
                best_score = float('inf')

                for i, seg in enumerate(valid_candidates):
                    pred_los = predictions[i] # Lấy kết quả tương ứng từ mảng dự đoán

                    if pred_los in ['A', 'B']:
                        # Tính khoảng cách tới đích
                        dist_seg_to_dest = calculate_distance(seg['lat_enode'], seg['long_enode'], end_lat, end_lon)
                        
                        # Tính điểm: Ưu tiên gần đích + phạt góc lệch
                        score = dist_seg_to_dest + (seg['angle_diff'] * 0.02)

                        if score < best_score:
                            best_score = score
                            best_next_point = {
                                "lat": seg['lat_enode'],
                                "lon": seg['long_enode'],
                                "name": seg['street_name'],
                                "id": seg['segment_id']
                            }

                if best_next_point:
                    # print(f"👉 Bước {step+1}: Chọn '{best_next_point['name']}' (Batch size: {len(valid_candidates)})")
                    waypoints.append(best_next_point)
                    visited_segment_ids.add(best_next_point['id'])
                    current_lat = best_next_point['lat']
                    current_lon = best_next_point['lon']
                else:
                    # Nếu toàn đường tắc, thử nới lỏng điều kiện (chấp nhận C) hoặc dừng
                    break

            return Response({"status": "success", "waypoints": waypoints})

        except Exception as e:
            traceback.print_exc()
            return Response({"status": "error", "message": str(e)}, status=500)
        
class SavePushTokenView(APIView):
    # permission_classes = [IsAuthenticated] # Bật lên nếu cần login
    def post(self, request):
        token = request.data.get('token')
        if not token:
            return Response({"error": "Thiếu token"}, status=400)
        
        # Lưu token cho user hiện tại
        # Giả sử request.user đã có (nếu dùng Token Auth)
        # Nếu chưa có Auth thì bạn cần gửi kèm username/id
        profile, created = UserProfile.objects.get_or_create(user=request.user)
        profile.expo_push_token = token
        profile.save()
        
        return Response({"status": "success"})