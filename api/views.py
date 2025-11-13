# api/views.py
from rest_framework import viewsets, permissions
from .models import *
from .serializers import *
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
import google.generativeai as genai
import requests
import os
import json
# Dùng ReadOnlyModelViewSet để chỉ cho phép lệnh GET
class UserViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    # Chỉ Admin mới được xem User
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

class ReviewViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Review.objects.all()
    serializer_class = ReviewSerializer

class ProductViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Product.objects.all().prefetch_related('categories', 'reviews', 'tags')
    serializer_class = ProductSerializer

class CategoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer


# === CẤU HÌNH API ===
try:
    # Lấy key từ file .env (Django sẽ tự động nạp)
    GEMINI_API_KEY = 'AIzaSyCX1xZaCn5kYMYatvolNC9NYMm8RqaT90M'
    genai.configure(api_key=GEMINI_API_KEY)
    
    WEATHER_API_KEY = '12748af8a89d97862b12fcb48001633e'
except ImportError:
    print("Lỗi: Không tìm thấy API Key trong .env")
    GEMINI_API_KEY = None
    WEATHER_API_KEY = None

# === VIEW MỚI CHO TRỢ LÝ AI ===

class TravelAdviceView(APIView):
    """
    Nhận điểm đi, điểm đến, gọi API thời tiết,
    và dùng Gemini AI để đưa ra lời khuyên.
    """

    def post(self, request, *args, **kwargs):
        if not GEMINI_API_KEY or not WEATHER_API_KEY:
            return Response(
                {"error": "API keys chưa được cấu hình trên server."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        # 1. Lấy dữ liệu từ MapScreen.tsx
        data = request.data
        origin = data.get('origin') # {latitude, longitude}
        origin_name = data.get('originName')
        destinations = data.get('destinations') # [{latitude, longitude}, ...]
        destination_names = data.get('destinationNames')

        if not origin or not destinations:
            return Response(
                {"error": "Thiếu 'origin' hoặc 'destinations'."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # 2. Gọi API Thời tiết (ví dụ: cho điểm đi)
            weather_data = self.get_weather_data(origin['latitude'], origin['longitude'])

            # 3. Xây dựng Prompt cho Gemini
            prompt = self.generate_gemini_prompt(
                origin_name, 
                destination_names, 
                weather_data
            )

            # 4. Gọi Gemini AI
            model = genai.GenerativeModel('gemini-2.5-flash')
            response = model.generate_content(prompt)
            
            # 5. Trả lời khuyên về cho app
            try:
                # Gemini trả về một chuỗi (string) JSON, chúng ta cần parse nó
                advice_json = json.loads(response.text)
                
                # Trả về đối tượng JSON đã parse cho app
                return Response(
                    {"advice": advice_json},
                    status=status.HTTP_200_OK
                )
            except json.JSONDecodeError as e:
                # Xử lý nếu Gemini không trả về JSON hợp lệ
                return Response(
                    {"error": f"Lỗi: AI không trả về JSON hợp lệ. Phản hồi gốc: {response.text}"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
        
        except Exception as e:
            return Response(
                {"error": f"Lỗi server: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def get_weather_data(self, lat, lon):
        """
        Gọi API OpenWeatherMap (ví dụ) để lấy thời tiết.
        """
        # (Đây là URL ví dụ, hãy thay bằng API của bạn)
        url = (
            f"http://api.openweathermap.org/data/2.5/weather"
            f"?lat={lat}&lon={lon}&appid={WEATHER_API_KEY}&units=metric&lang=vi"
        )
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            description = data['weather'][0]['description']
            temp = data['main']['temp']
            return f"Thời tiết hiện tại: {description}, nhiệt độ {temp}°C."
        return "Không thể lấy được thông tin thời tiết."

    def generate_gemini_prompt(self, origin_name, destination_names, weather_info):
        """
        Tạo một "câu lệnh" (prompt) chi tiết cho Gemini,
        YÊU CẦU TRẢ VỀ DẠNG JSON (với 5 keys).
        """
        dest_list_str = "\n".join(
            [f"- {name}" for name in destination_names]
        )

        # === PROMPT ĐÃ ĐƯỢC CẬP NHẬT ===
        prompt = f"""
        Bạn là một trợ lý du lịch AI thông minh.
        Một người dùng đang lên kế hoạch cho một chuyến đi.

        **Thông tin chuyến đi:**
        1.  **Điểm xuất phát:** {origin_name}
        2.  **Thông tin thời tiết (tham khảo tại điểm đi):** {weather_info}
        3.  **Các điểm đến theo thứ tự:**
            {dest_list_str}

        **YÊU CẦU:**
        Hãy phân tích thông tin trên và trả lời (bằng tiếng Việt) DƯỚI DẠNG MỘT ĐỐI TƯỢNG JSON HỢP LỆ.
        JSON phải có chính xác 5 key sau:

        1.  `"weather_advice"`: (string) Lời khuyên về thời tiết. 
            (ví dụ: "Trời nắng gắt, nên mang kem chống nắng và kính râm.")

        2.  `"traffic_alert"`: (string) Cảnh báo về giao thông nếu có.
            (ví dụ: "Khu vực trung tâm có thể ùn tắc vào giờ cao điểm.")

        3.  `"other_tips"`: (string) Các lời khuyên bổ sung khác.
            (ví dụ: "Nhớ mang sạc dự phòng và kiểm tra xăng xe.")

        4.  `"recommended_mode"`: (string) ĐỀ XUẤT QUAN TRỌNG NHẤT. Dựa trên thời tiết, lộ trình và các yếu tố khác, hãy chọn phương tiện tốt nhất.
            Giá trị trả về BẮT BUỘC phải là một trong các chuỗi sau:
            - `"drive"` (nếu là ô tô)
            - `"motorcycle"` (nếu là xe máy)
            - `"bicycle"` (nếu là xe đạp)
            - `"walk"` (nếu là đi bộ)
            (ví dụ: Nếu {weather_info} là "Trời mưa to", hãy trả về `"drive"`)

        5.  `"route_advice"`: (string) **VIẾT LỜI GIẢI THÍCH** cho lựa chọn
            của bạn ở key "recommended_mode". Hãy phân tích cụ thể (dựa trên
            thời tiết, khoảng cách, loại phương tiện) để bảo vệ cho lựa chọn đó.
            (Ví dụ: "Vì trời đang mưa và quãng đường di chuyển quá xa, nên tôi đề xuất di chuyển bằng ô tô .")
            
        **QUAN TRỌNG: Chỉ trả về đối tượng JSON, không thêm bất kỳ văn bản nào
        trước hoặc sau nó, không dùng markdown (```json).**
        """
        return prompt