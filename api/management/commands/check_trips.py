from django.core.management.base import BaseCommand
from django.utils import timezone
from api.models import UserProfile, TrafficSegment
from trips.models import Trip
from exponent_server_sdk import PushClient, PushMessage
import joblib
import pandas as pd
from datetime import timedelta

class Command(BaseCommand):
    help = 'Quét các chuyến đi sắp tới và gửi cảnh báo'

    def handle(self, *args, **kwargs):
        # 1. Load Model AI
        model = joblib.load('ml_models/traffic_model.pkl')
        encoder = joblib.load('ml_models/street_encoder.pkl')
        
        # 2. Tìm các chuyến đi sẽ khởi hành trong 1 giờ tới
        now = timezone.now()
        one_hour_later = now + timedelta(hours=1)
        
        # Giả sử model Trip có trường 'date' là datetime khởi hành
        upcoming_trips = Trip.objects.filter(date__range=(now, one_hour_later))
        
        for trip in upcoming_trips:
            try:
                user_profile = UserProfile.objects.get(user=trip.user)
                token = user_profile.expo_push_token
                
                if not token: continue

                # 3. Phân tích giao thông điểm xuất phát & điểm đến
                # (Logic đơn giản hóa: check điểm xuất phát)
                street_name = trip.startingPoint # Giả sử startingPoint là tên đường
                
                traffic_status = "Bình thường"
                warning_msg = ""

                if street_name in encoder.classes_:
                    street_code = encoder.transform([street_name])[0]
                    # Dự đoán
                    pred = model.predict([[now.hour, now.weekday(), street_code]])[0]
                    
                    if pred in ['E', 'F']:
                        traffic_status = "TẮC NGHẼN"
                        warning_msg = f"⚠️ Đường {street_name} đang tắc (LOS {pred}). Nên đi sớm hơn!"
                    elif pred == 'D':
                        warning_msg = f"🚗 Đường {street_name} hơi đông. Chú ý nhé."
                    else:
                        warning_msg = f"✅ Giao thông thuận lợi. Chúc chuyến đi vui vẻ!"

                # 4. Gửi thông báo
                message_body = f"Chuyến đi '{trip.tripName}' sắp bắt đầu lúc {trip.date.strftime('%H:%M')}.\n{warning_msg}"
                
                self.send_push_notification(token, message_body)
                print(f"Sent to {trip.user.username}: {message_body}")

            except Exception as e:
                print(f"Error processing trip {trip.id}: {e}")

    def send_push_notification(self, token, message):
        try:
            response = PushClient().publish(
                PushMessage(to=token, body=message, title="📢 Nhắc nhở hành trình")
            )
        except Exception as e:
            print(f"Lỗi gửi push: {e}")