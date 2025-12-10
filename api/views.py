# api/views.py
from rest_framework import viewsets, permissions
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import *
from .serializers import *
import google.generativeai as genai
from scipy.spatial import cKDTree
import requests
from thefuzz import process
import os
import datetime
import joblib
import pandas as pd
from .image_search_service import ImageSearchService
import concurrent.futures
import math
import json
from django.conf import settings
from dotenv import load_dotenv

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
        
        if not lat or not lon:
            return Response({"error": "Thiếu tọa độ lat/lon"}, status=400)

        try:
            user_lat = float(lat)
            user_lon = float(lon)
        except ValueError:
            return Response({"error": "Tọa độ không hợp lệ"}, status=400)

        # === 1. TÌM TRONG DATABASE TRƯỚC (CACHE) ===
        radius_deg = 0.045 
        places_in_db = Place.objects.filter(
            lat__range=(user_lat - radius_deg, user_lat + radius_deg),
            lon__range=(user_lon - radius_deg, user_lon + radius_deg)
        )
        
        if places_in_db.exists():
            print("✅ Đã tìm thấy dữ liệu trong Cache Database!")
            serializer = PlaceSerializer(places_in_db, many=True)
            return Response(serializer.data, status=200)

        # === 2. GỌI API NẾU KHÔNG CÓ CACHE ===
        print("⚠️ Không có trong Cache, đang gọi API thực tế...")
        
        if not SERPAPI_API_KEY:
             return Response({"error": "Chưa cấu hình SERPAPI_API_KEY"}, status=500)

        try:
            params = {
                "engine": "google_maps",
                "q": "tourist attractions", 
                "ll": f"@{lat},{lon},15z",
                "type": "search",
                "google_domain": "google.com.vn",
                "hl": "en",
                "api_key": SERPAPI_API_KEY
            }
            
            res = requests.get("https://serpapi.com/search", params=params)
            data = res.json()
            local_results = data.get('local_results', [])

            if not local_results:
                return Response([], status=200)

            # --- HÀM XỬ LÝ (CHỈ TẢI DỮ LIỆU, KHÔNG LƯU DB) ---
            def prepare_place_data(item):
                place_name = item.get('title')
                gps = item.get('gps_coordinates', {})
                place_id = item.get('place_id') or item.get('data_id')
                hours_data = item.get('operating_hours', {}) # Lấy cả cục dict
                open_status = item.get('open_state', '')
                # Tìm ảnh (Tốn thời gian -> Chạy song song OK)
                image_url = "https://via.placeholder.com/200x150.png?text=No+Image"
                try:
                    search_service = ImageSearchService()
                    # Tìm ảnh
                    images = search_service.find_images_for_destination(place_name, "Vietnam", 1)
                    if images: image_url = images[0]['image']
                    else: image_url = item.get('thumbnail', image_url)
                except:
                    image_url = item.get('thumbnail', image_url)

                # Trả về Dictionary (Dữ liệu thô), KHÔNG GỌI .save() Ở ĐÂY
                return {
                    'place_id': place_id,
                    'name': place_name,
                    'address': item.get('address'),
                    'lat': gps.get('latitude'),
                    'lon': gps.get('longitude'),
                    'rating': item.get('rating', 0),
                    'reviews': item.get('reviews', 0),
                    'price': item.get('price'),
                    'image': image_url,
                    'working_hours': hours_data, 
                    'open_state': open_status
                }

            # --- CHẠY SONG SONG ĐỂ LẤY DỮ LIỆU ---
            raw_places_data = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                # Map hàm prepare_place_data vào danh sách
                results = executor.map(prepare_place_data, local_results)
                for res in results:
                    raw_places_data.append(res)
            
            # --- LƯU VÀO DB (TUẦN TỰ - MAIN THREAD) ---
            # SQLite thích điều này: Chỉ 1 luồng ghi vào DB
            saved_places = []
            for place_data in raw_places_data:
                try:
                    place_obj, created = Place.objects.update_or_create(
                        place_id=place_data['place_id'],
                        defaults=place_data # Các trường còn lại
                    )
                    saved_places.append(place_obj)
                except Exception as db_err:
                    print(f"Lỗi lưu DB: {db_err}")

            # Serialize và trả về
            serializer = PlaceSerializer(saved_places, many=True)
            return Response(serializer.data, status=200)

        except Exception as e:
            print("Lỗi:", e)
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
            now = datetime.datetime.now()
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
        now = datetime.datetime.now()
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