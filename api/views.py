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
from .utils import get_external_context, find_and_save_place_info
# from dotenv import load_dotenv
# load_dotenv()
BASE_DIR = settings.BASE_DIR
ML_DIR = os.path.join(BASE_DIR, 'ml_models')

# 1. Load AI Models
print("⏳ Initializing AI & Digital Map system...")
try:
    traffic_model = joblib.load(os.path.join(ML_DIR, 'traffic_model.pkl'))
    street_encoder = joblib.load(os.path.join(ML_DIR, 'street_encoder.pkl'))
    known_streets = set(street_encoder.classes_) 
    print("AI Model loaded successfully.")
except Exception as e:
    traffic_model = None
    print(f" AI Model load error: {e}")

# 2. Load Spatial Data (Nodes & Streets)
spatial_tree = None
node_street_map = {} 
spatial_nodes_ids = []

try:
    print("⏳ Loading map data (Nodes/Streets)...")
    df_nodes = pd.read_csv(os.path.join(ML_DIR, 'nodes.csv'))
    df_segments = pd.read_csv(os.path.join(ML_DIR, 'segments.csv'))
    df_streets = pd.read_csv(os.path.join(ML_DIR, 'streets.csv'))

    # Merge Segment with Street
    merged = pd.merge(df_segments, df_streets, left_on='street_id', right_on='_id', how='inner')
    
    # Create Map: Node -> Street Name
    temp_map = dict(zip(merged['s_node_id'], merged['name'].astype(str).str.strip())) 
    node_street_map = temp_map

    # Filter Nodes and create KDTree
    NODE_ID_COL = '_id' 
    valid_nodes = df_nodes[df_nodes[NODE_ID_COL].isin(node_street_map.keys())]
    
    node_coords = valid_nodes[['lat', 'long']].values 
    node_ids = valid_nodes[NODE_ID_COL].values 
    
    spatial_tree = cKDTree(node_coords)
    spatial_nodes_ids = node_ids
    
    print(f"✅ Digital map loaded ({len(valid_nodes)} nodes).")

except Exception as e:
    print(f"⚠️ Unable to load spatial map data: {e}")

try:
    GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
    if GEMINI_API_KEY:
        genai.configure(api_key=GEMINI_API_KEY)
    
    WEATHER_API_KEY = os.environ.get('WEATHER_API_KEY')
    SERPAPI_API_KEY = os.environ.get('SERPAPI_API_KEY')
    GEOAPIFY_API_KEY = os.environ.get('GEOAPIFY_API_KEY')
except Exception as e:
    print(f"API Key configuration error: {e}")

# === HELPER FUNCTIONS ===
def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371  # Earth radius (km)
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
    if hours > 0: return f"{hours} hr {minutes} min"
    return f"{minutes} min"

def format_distance(meters):
    return f"{round(meters / 1000, 1)} km"

# === SECTION 1: BASIC VIEWSETS ===
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
            return Response({"error": "Missing lat/lon coordinates"}, status=400)

        try:
            user_lat = float(lat)
            user_lon = float(lon)
        except ValueError:
            return Response({"error": "Invalid coordinates"}, status=400)

        # 1. CHECK CACHE
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

        # 2. CALL EXTERNAL API
        print(f"CACHE MISS: Calling Google Maps via SerpApi...")
        
        keyword_map = {
            'sights': 'top sights', 'coffee': 'coffee shops', 'food': 'restaurants',
            'park': 'parks', 'shopping': 'shopping malls', 'hotel': 'hotels',
            'entertainment': 'entertainment'
        }
        search_query = keyword_map.get(request_type, 'tourist attractions')

        try:
            if not SERPAPI_API_KEY: return Response({"error": "No API Key configured"}, 500)
            
            params = {
                "engine": "google_maps", "q": search_query, "ll": f"@{lat},{lon},15z",
                "type": "search", "google_domain": "google.com.vn", "hl": "en",
                "api_key": SERPAPI_API_KEY
            }
            res = requests.get("https://serpapi.com/search", params=params)
            local_results = res.json().get('local_results', [])

            if not local_results: return Response([], status=200)

            def prepare_data(item):
                try:
                    title = item.get('title', '')
                    place_type = item.get('type', '')
                    category = item.get('category', '')
                    description = item.get('description') or item.get('snippet')
                    
                    if not description and item.get('extensions'):
                        description = ", ".join([str(ext) for ext in item.get('extensions', [])])
                    
                    title_lower = title.lower()
                    type_lower = place_type.lower()
                    cat_lower = category.lower()

                    # === AGGRESSIVE FILTER ===
                    type_blacklist = [
                        'travel agency', 'tour operator', 'tour agency', 
                        'corporate office', 'bus station', 'transit station',
                        'establishment', 'point of interest', 'company', 'agency', 'office'
                    ]
                    
                    title_blacklist = [
                        'travel', 'tour', 'ticket', 'booking', 'transport', 'limousine', 
                        'visa', 'service', 'office', 'du lịch', 'xe khách'
                    ]

                    if any(bad in type_lower for bad in type_blacklist): return None
                    if any(bad in cat_lower for bad in type_blacklist): return None
                    if request_type == 'sights':
                        if any(bad in title_lower for bad in title_blacklist): return None

                    place_id = item.get('place_id') or item.get('data_id')
                    if not place_id or not title: return None

                    image_url = item.get('thumbnail', "https://via.placeholder.com/200x150.png?text=No+Image")
                    try:
                        search_service = ImageSearchService()
                        images = search_service.find_images_for_destination(title, "Vietnam", 1)
                        if images: image_url = images[0]['image']
                    except: pass

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
                except Exception: 
                    return None

            # STEP 3: RUN PARALLEL DATA FETCHING
            data_to_save = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                results = executor.map(prepare_data, local_results)
                for res in results:
                    if res: data_to_save.append(res)

            # STEP 4: SAVE TO DB (Main thread for SQLite safety)
            saved_places = []
            print(f"Saving {len(data_to_save)} places to database...")
            
            for item_data in data_to_save:
                try:
                    place_obj, created = Place.objects.update_or_create(
                        place_id=item_data['place_id'],
                        defaults=item_data
                    )
                    saved_places.append(place_obj)
                except Exception as db_err:
                    print(f"Database save error for {item_data['name']}: {db_err}")

            serializer = PlaceSerializer(saved_places, many=True)
            return Response(serializer.data, status=200)

        except Exception as e:
            print("Server Error:", e)
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

# === SECTION 2: AI ASSISTANT VIEW (TRAVEL ADVICE) ===

class TravelAdviceView(APIView):
    def post(self, request, *args, **kwargs):
        if not GEMINI_API_KEY or not WEATHER_API_KEY or not GEOAPIFY_API_KEY:
            return Response({"error": "API Keys not fully configured"}, status=500)

        data = request.data
        origin = data.get('origin')
        origin_name = data.get('originName')
        destinations = data.get('destinations')
        destination_names = data.get('destinationNames')

        if not origin or not destinations:
            return Response({"error": "Missing location data"}, status=400)

        try:
            # 1. WEATHER
            weather_details = []
            origin_weather = self.get_weather_data(origin['latitude'], origin['longitude'], origin_name)
            if origin_weather: weather_details.append(origin_weather)

            for i, dest in enumerate(destinations):
                name = destination_names[i] if destination_names and i < len(destination_names) else f"Destination {i+1}"
                dest_weather = self.get_weather_data(dest['latitude'], dest['longitude'], name)
                if dest_weather: weather_details.append(dest_weather)

            # 2. ROUTES
            route_list = self.get_all_routes(origin, destinations[0])

            # 3. TRAFFIC FORECAST
            traffic_reports = []
            traffic_reports.append(self.get_traffic_forecast(origin['latitude'], origin['longitude'], origin_name))
            
            for i, dest in enumerate(destinations):
                name = destination_names[i] if destination_names and i < len(destination_names) else f"Dest {i}"
                traffic_reports.append(self.get_traffic_forecast(dest['latitude'], dest['longitude'], name))
            
            traffic_summary_str = "\n".join([t for t in traffic_reports if t])

            # 4. PREPARE PROMPT DATA
            weather_summary_str = "; ".join([f"{w['name']}: {w['desc']}, {w['temp']}°C" for w in weather_details])

            # 5. GENERATE PROMPT
            prompt = self.generate_gemini_prompt(
                origin_name, 
                destination_names, 
                weather_summary_str, 
                traffic_summary_str,
                route_list
            )

            # 6. CALL GEMINI
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
                return Response({"error": "AI returned invalid format"}, status=500)

        except Exception as e:
            print(f"❌ Error: {e}")
            return Response({"error": str(e)}, status=500)

    def get_weather_data(self, lat, lon, name):
        try:
            url = f"http://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={WEATHER_API_KEY}&units=metric&lang=en"
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
                        "time": self.format_time(props.get('time', 0)),
                        "distance": self.format_distance(props.get('distance', 0))
                    })
            except: pass
        return routes

    def get_traffic_forecast(self, lat, lon, name):
        if not traffic_model or not spatial_tree:
            return None
            
        try:
            radius_deg = 0.2 / 111.0 
            distances, indices = spatial_tree.query([float(lat), float(lon)], k=1)
            
            target_street = None
            if indices < len(spatial_nodes_ids):
                real_node_id = spatial_nodes_ids[indices]
                s_name = node_street_map.get(real_node_id)
                if s_name and str(s_name).strip() in known_streets:
                    target_street = str(s_name).strip()
            
            if not target_street:
                return f"- At {name}: No historical traffic data available."

            now = datetime.now()
            hour = now.hour
            weekday = now.weekday()
            
            street_code = street_encoder.transform([target_street])[0]
            input_data = pd.DataFrame([[hour, weekday, street_code]], columns=['hour', 'weekday', 'street_encoded'])
            pred_los = traffic_model.predict(input_data)[0]
            
            status = "Normal"
            if pred_los in ['E', 'F']: status = "HIGH CONGESTION (LOS E/F)"
            elif pred_los in ['C', 'D']: status = "Busy (LOS C/D)"
            elif pred_los in ['A', 'B']: status = "Clear (LOS A/B)"
            
            return f"- At {name} (Area: {target_street}): Predicted {status}."
            
        except Exception as e:
            print(f"Traffic Forecast Error: {e}")
            return None

    def generate_gemini_prompt(self, origin_name, destination_names, weather_str, traffic_str, route_list):
        dest_list_str = "\n".join([f"- {name}" for name in destination_names])
        route_info_str = "\n".join([f"- {r['mode']}: {r['distance']}, takes {r['time']}" for r in route_list])

        return f"""
        You are a smart travel assistant. Analyze the following trip data:

        1. ITINERARY:
           - Origin: {origin_name}
           - Destinations: {dest_list_str}

        2. REAL-TIME CONDITIONS:
           - Weather: {weather_str}
           - AI Traffic Forecast: 
             {traffic_str}

        3. TRAVEL OPTIONS (Geoapify):
           {route_info_str}

        JSON RESPONSE REQUIREMENT (No Markdown, pure JSON only):
        {{
            "weather_advice": "Brief weather advice (e.g., if raining, suggest raincoats)",
            "traffic_alert": "Thorough analysis of traffic data above. If 'HIGH CONGESTION', issue a strong warning and suggest leaving early or changing transport mode.",
            "recommended_mode": "Pick 1 optimal transport mode (drive/motorcycle/bicycle/walk) based on both weather and traffic.",
            "route_advice": "Reasoning for the recommended mode (e.g., Great weather but heavy traffic, suggest motorcycle for flexibility...)",
            "other_tips": "A fun or useful travel tip."
        }}
        """

    def format_time(self, seconds):
        minutes = round(seconds / 60)
        if minutes < 60: return f"{minutes} min"
        return f"{minutes // 60} hr {minutes % 60} min"

    def format_distance(self, meters):
        if meters < 1000: return f"{meters} m"
        return f"{round(meters / 1000, 1)} km"

# === SECTION 3: OPTIMIZE ROUTE ===
class OptimizeRouteView(APIView):
    """
    Receives origin and list of destinations.
    Reorders destinations for shortest total distance (Nearest Neighbor).
    """
    def post(self, request, *args, **kwargs):
        if not GEOAPIFY_API_KEY:
             return Response({"error": "API Key missing"}, status=500)

        data = request.data
        origin_data = data.get('origin')
        destinations = data.get('destinations')

        if not origin_data or not destinations:
            return Response({"error": "Missing origin or destinations data"}, status=400)

        try:
            start_coords = None
            
            if isinstance(origin_data, dict) and 'latitude' in origin_data and 'longitude' in origin_data:
                start_coords = [origin_data['longitude'], origin_data['latitude']]
            
            elif isinstance(origin_data, str):
                start_coords = self.geocode(origin_data)

            if not start_coords:
                 return Response({"error": "Could not determine origin coordinates"}, status=400)

            jobs = []
            for dest in destinations:
                if isinstance(dest, dict) and 'latitude' in dest and 'longitude' in dest:
                     coords = [dest['longitude'], dest['latitude']]
                else:
                     coords = self.geocode(dest.get('name'))
                
                if coords:
                    jobs.append({
                        "location": coords,
                        "id": str(dest['id']) 
                    })
            
            if not jobs:
                return Response({"error": "No coordinates found for any destinations"}, status=400)

            sorted_ids = self.solve_tsp(start_coords, jobs)
            
            final_result = []
            for sorted_id in sorted_ids:
                for dest in destinations:
                    if str(dest['id']) == sorted_id:
                        final_result.append(dest)
                        break
            
            return Response({"optimized_destinations": final_result}, status=200)

        except Exception as e:
            print(f"Optimize Error: {str(e)}")
            return Response({"error": str(e)}, status=500)

    def geocode(self, address):
        try:
            if not address: return None
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
        R = 6371000  # Radius in meters
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lon2 - lon1)

        a = math.sin(delta_phi / 2) ** 2 + \
            math.cos(phi1) * math.cos(phi2) * \
            math.sin(delta_lambda / 2) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        return R * c

    def solve_tsp(self, start, jobs):
        current_coords = start 
        unvisited = jobs.copy()
        path_ids = []

        while unvisited:
            nearest_job = min(unvisited, key=lambda x: self.haversine(
                current_coords[1], current_coords[0],
                x['location'][1], x['location'][0]
            ))
            
            path_ids.append(nearest_job['id'])
            current_coords = nearest_job['location']
            unvisited.remove(nearest_job)
            
        return path_ids

class PredictTrafficView(APIView):
    def post(self, request):
        now = datetime.now()
        current_hour = now.hour
        current_weekday = now.weekday()

        lat = request.data.get('lat')
        lon = request.data.get('lon')
        street_name_input = request.data.get('street_name') 
        
        target_streets = [] 
        detected_street_name = ""

        # STRATEGY 1: SPATIAL COORDINATE SEARCH
        if lat and lon and spatial_tree:
            try:
                radius_deg = 0.2 / 111.0 
                distances, indices = spatial_tree.query([float(lat), float(lon)], k=1) 
                
                if indices < len(spatial_nodes_ids):
                    real_node_id = spatial_nodes_ids[indices]
                    s_name = node_street_map.get(real_node_id)
                    
                    if s_name:
                        clean_name = str(s_name).strip()
                        if clean_name in known_streets:
                            target_streets = [clean_name]
                            detected_street_name = clean_name
                            print(f"📍 Mapping: Coords ({lat},{lon}) -> Street '{clean_name}'")
            except Exception as e:
                print(f"Spatial Search Error: {e}")
        
        if not target_streets:
             return Response({
                 "street": street_name_input,
                 "status": "No Data",
                 "message": "No traffic data found at this location",
                 "timeline": []
             })

        # PREDICTION LOGIC
        timeline_result = []
        for i in range(3):
            target_hour = (current_hour + i) % 24
            target_weekday = current_weekday
            if current_hour + i >= 24: target_weekday = (current_weekday + 1) % 7
            
            st = target_streets[0] 
            try:
                street_code = street_encoder.transform([st])[0]
                input_data = pd.DataFrame([[target_hour, target_weekday, street_code]], 
                                          columns=['hour', 'weekday', 'street_encoded'])
                pred_los = traffic_model.predict(input_data)[0]
                
                status_map = {
                    'A': ("Clear", "#28A745"), 'B': ("Clear", "#28A745"),
                    'C': ("Busy", "#FFC107"), 'D': ("Busy", "#FFC107"),
                    'E': ("Congested", "#DC3545"), 'F': ("Gridlock", "#8B0000")
                }
                status_text, color_hex = status_map.get(pred_los, ("Unknown", "#9E9E9E"))

                timeline_result.append({
                    "time_display": f"{target_hour}:00",
                    "status": status_text,
                    "color": color_hex,
                    "los": pred_los
                })
            except:
                continue

        current = timeline_result[0] if timeline_result else {}

        return Response({
            "input_name": street_name_input, 
            "street": detected_street_name,
            "current_status": current.get('status', 'N/A'),
            "current_color": current.get('color', '#9E9E9E'),
            "current_los": current.get('los', 'N/A'),
            "timeline": timeline_result
        })
    
class FavoriteView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Get user's favorites list"""
        favorites = Favorite.objects.filter(user=request.user).order_by('-created_at')
        places = [fav.place for fav in favorites]
        serializer = PlaceSerializer(places, many=True)
        return Response(serializer.data, status=200)

    def post(self, request):
        """Toggle Like/Unlike: Send { "place_id": "..." }"""
        place_id_str = request.data.get('place_id')
        
        if not place_id_str:
            return Response({"error": "Missing place_id"}, status=400)

        try:
            input_id = request.data.get('place_id')
            
            if str(input_id).isdigit():
                place = Place.objects.get(id=int(input_id))
            else:
                place = Place.objects.get(place_id=input_id)

            favorite_item = Favorite.objects.filter(user=request.user, place=place).first()

            if favorite_item:
                favorite_item.delete()
                return Response({"status": "unliked", "place_id": input_id}, status=200)
            else:
                Favorite.objects.create(user=request.user, place=place)
                return Response({"status": "liked", "place_id": input_id}, status=201)

        except Place.DoesNotExist:
            return Response({"error": "Place does not exist"}, status=404)
        except Exception as e:
            return Response({"error": str(e)}, status=500)
        
class PlanTripSmartView(APIView):
    def post(self, request):
        data = request.data
        origin = data.get('origin', 'Ho Chi Minh City')
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
            You are a traffic assistant. The user departs at: {departure_time_str}.
            Context: Weather {weather_desc}, Traffic {traffic_desc}.
            Assess if this time is REASONABLE for tourism?
            RETURN JSON: {{ "is_reasonable": boolean, "reason": "...", "suggested_time": "HH:mm" }}
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
        I am currently at '{origin}'.
        I want to schedule a trip visiting these {len(destinations)} locations (in the most logical order):
        
        {destinations_formatted}
        
        Departure Time: {departure_time_str}.
        
        IMPORTANT REQUIREMENTS:
        1. Only return exactly {len(destinations)} locations in the JSON list (exclude origin).
        2. DO NOT split locations based on commas (e.g., "Ben Thanh Market, District 1" is one location).
        3. Respond in English.
        4. RETURN JSON ARRAY:
        [
            {{
                "location_name": "Exact location name",
                "arrival_time": "HH:mm",
                "duration": "e.g., 60 - 90 minutes",
                "travel_to_next": {{ "time": "...", "distance": "..." }} (or null if last stop)
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

        # DATA ENRICHMENT PHASE
        def clean_place_name(name):
            return re.sub(r'^[\d\.\-\*\s]+', '', name).strip()

        def enrich_location_data(item):
            raw_name = item.get('location_name', '')
            clean_name = clean_place_name(raw_name)
            place = Place.objects.filter(name__iexact=clean_name).first()
            
            if not place:
                all_places = list(Place.objects.values('id', 'name'))
                choices = {p['name']: p['id'] for p in all_places}
                
                if choices:
                    best_match = process.extractOne(clean_name, choices.keys(), scorer=fuzz.token_set_ratio)
                    if best_match:
                        match_name, score = best_match
                        if score >= 85: 
                            print(f"✨ Fuzzy Match: '{clean_name}' ≈ '{match_name}' (Score: {score})")
                            place_id = choices[match_name]
                            place = Place.objects.get(id=place_id)

            if place:
                item['image'] = place.image
                item['highlight'] = place.description
                item['location_name'] = place.name 
            else:
                result = find_and_save_place_info(clean_name)
                if hasattr(result, 'image'): 
                    item['image'] = result.image
                    item['highlight'] = result.description
                elif isinstance(result, dict):
                    item['image'] = result.get('image')
                    item['highlight'] = result.get('description')
                else:
                    item['image'] = "https://via.placeholder.com/400x200"
                    item['highlight'] = "Interesting sight to visit."

            return item

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
            if traffic_model is None or street_encoder is None:
                return Response({"status": "error", "message": "AI Model not ready"}, status=53)

            user_lat = request.data.get('lat')
            user_lon = request.data.get('lon')
            radius_km = request.data.get('radius', 5)

            if user_lat is None or user_lon is None:
                return Response({"status": "error", "message": "Missing lat/lon coordinates"}, status=400)

            user_lat = float(user_lat)
            user_lon = float(user_lon)
            radius_km = float(radius_km)

            lat_min = user_lat - (radius_km / 111)
            lat_max = user_lat + (radius_km / 111)
            lon_min = user_lon - (radius_km / 111)
            lon_max = user_lon + (radius_km / 111)

            nearby_segments = TrafficSegment.objects.filter(
                lat_snode__range=(lat_min, lat_max),
                long_snode__range=(lon_min, lon_max)
            )
            
            if nearby_segments.count() == 0:
                return Response({"status": "success", "good_routes": [], "message": "No roads found nearby"})

            now = datetime.now()
            current_hour = now.hour
            current_weekday = now.weekday()
            
            good_roads = []
            for seg in nearby_segments:
                try:
                    if seg.street_name in street_encoder.classes_:
                        street_code = street_encoder.transform([seg.street_name])[0]
                        input_df = pd.DataFrame([[current_hour, current_weekday, street_code]], 
                                                columns=['hour', 'weekday', 'street_encoded'])
                        pred_los = traffic_model.predict(input_df)[0]
                        
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
                except:
                    continue 

            return Response({"status": "success", "good_routes": good_roads})

        except Exception as e:
            return Response({"status": "error", "message": str(e)}, status=500)
        
def calculate_bearing(lat1, lon1, lat2, lon2):
    dLon = math.radians(lon2 - lon1)
    lat1 = math.radians(lat1)
    lat2 = math.radians(lat2)

    y = math.sin(dLon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - \
        math.sin(lat1) * math.cos(lat2) * math.cos(dLon)
    
    bearing = math.atan2(y, x)
    bearing = math.degrees(bearing)
    return (bearing + 360) % 360

class FindGreenRouteView(APIView):
    def post(self, request):
        try:
            # 1. Lấy dữ liệu đầu vào
            start_lat = float(request.data.get('start_lat'))
            start_lon = float(request.data.get('start_lon'))
            end_lat = float(request.data.get('end_lat'))
            end_lon = float(request.data.get('end_lon'))
            
            STEP_RADIUS_KM = 3.0
            MAX_STEPS = 25
            
            waypoints = []        
            current_lat = start_lat
            current_lon = start_lon
            visited_segment_ids = set()

            now = datetime.now()
            hour = now.hour
            weekday = now.weekday()

            # 2. Vòng lặp tìm đường (Greedy)
            for step in range(MAX_STEPS):
                dist_to_dest = calculate_distance(current_lat, current_lon, end_lat, end_lon)
                
                # Nếu đã đủ gần đích, thoát vòng lặp để thêm điểm đích cuối cùng
                if dist_to_dest <= 1.2:
                    break

                target_bearing = calculate_bearing(current_lat, current_lon, end_lat, end_lon)

                # Truy vấn DB (giữ nguyên logic cũ của bạn)
                lat_min = current_lat - (STEP_RADIUS_KM / 111)
                lat_max = current_lat + (STEP_RADIUS_KM / 111)
                lon_min = current_lon - (STEP_RADIUS_KM / 111)
                lon_max = current_lon + (STEP_RADIUS_KM / 111)

                candidates_qs = TrafficSegment.objects.filter(
                    lat_snode__range=(lat_min, lat_max),
                    long_snode__range=(lon_min, lon_max)
                ).exclude(segment_id__in=visited_segment_ids).values(
                    'segment_id', 'street_name', 'lat_snode', 'long_snode', 'lat_enode', 'long_enode'
                )

                candidates = list(candidates_qs)
                if not candidates: break # Bị kẹt do không có dữ liệu đường

                valid_candidates = []
                predict_inputs = [] 

                for seg in candidates:
                    if seg['street_name'] not in street_encoder.classes_: continue
                    seg_bearing = calculate_bearing(current_lat, current_lon, seg['lat_snode'], seg['long_snode'])
                    angle_diff = abs(target_bearing - seg_bearing)
                    if angle_diff > 180: angle_diff = 360 - angle_diff
                    if angle_diff > 90: continue
                    
                    street_code = street_encoder.transform([seg['street_name']])[0]
                    valid_candidates.append({**seg, 'street_code': street_code, 'angle_diff': angle_diff})
                    predict_inputs.append([hour, weekday, street_code])

                if not valid_candidates: break # Bị kẹt do không có đường đúng hướng

                input_df = pd.DataFrame(predict_inputs, columns=['hour', 'weekday', 'street_encoded'])
                predictions = traffic_model.predict(input_df)

                best_next_point = None
                best_score = float('inf')

                # Logic Fallback (A,B -> C -> D)
                priority_configs = [
                    {'levels': ['A', 'B'], 'penalty': 0},
                    {'levels': ['C'],      'penalty': 2.5},
                    {'levels': ['D'],      'penalty': 6.0}
                ]

                for config in priority_configs:
                    for i, seg in enumerate(valid_candidates):
                        if predictions[i] in config['levels']:
                            dist_seg_to_dest = calculate_distance(seg['lat_enode'], seg['long_enode'], end_lat, end_lon)
                            score = dist_seg_to_dest + (seg['angle_diff'] * 0.03) + config['penalty']
                            if score < best_score:
                                best_score = score
                                best_next_point = {
                                    "lat": seg['lat_enode'], "lon": seg['long_enode'],
                                    "name": seg['street_name'], "id": seg['segment_id']
                                }
                    if best_next_point: break

                if best_next_point:
                    waypoints.append(best_next_point)
                    visited_segment_ids.add(best_next_point['id'])
                    current_lat = best_next_point['lat']
                    current_lon = best_next_point['lon']
                else:
                    break # Bị kẹt do tất cả đường đều tắc (Level E, F)

            # ==========================================================
            # 3. LOGIC QUAN TRỌNG: ĐẢM BẢO LUÔN VỀ ĐÍCH
            # ==========================================================
            # Kiểm tra xem điểm cuối cùng trong danh sách đã phải là đích chưa
            # Nếu chưa, hoặc danh sách trống, ta thêm tọa độ đích vào cuối.
            
            final_destination_point = {
                "lat": end_lat,
                "lon": end_lon,
                "name": "Destination",
                "id": "final_dest"
            }

            if not waypoints:
                # Nếu không tìm được bất kỳ điểm xanh nào, nối thẳng từ Start đến End
                waypoints.append(final_destination_point)
            else:
                last_point = waypoints[-1]
                dist_to_final = calculate_distance(last_point['lat'], last_point['lon'], end_lat, end_lon)
                
                # Nếu điểm cuối cùng cách đích > 100 mét, thêm đích vào để khép kín lộ trình
                if dist_to_final > 0.1:
                    waypoints.append(final_destination_point)

            return Response({
                "status": "success", 
                "waypoints": waypoints,
                "is_complete": True
            })

        except Exception as e:
            return Response({"status": "error", "message": str(e)}, status=500)
        
class SavePushTokenView(APIView):
    def post(self, request):
        token = request.data.get('token')
        if not token:
            return Response({"error": "Missing token"}, status=400)
        
        profile, created = UserProfile.objects.get_or_create(user=request.user)
        profile.expo_push_token = token
        profile.save()
        
        return Response({"status": "success"})