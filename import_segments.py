import os
import django
import pandas as pd

# Thiết lập môi trường Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'travellous.settings')
django.setup()

from api.models import TrafficSegment

def import_data():
    csv_path = 'ml_models/train.csv' # Đường dẫn đến file train.csv của bạn
    print("🚀 Đang đọc file CSV...")
    
    try:
        df = pd.read_csv(csv_path)
        
        # 1. LỌC TRÙNG (Chỉ lấy danh sách các đoạn đường duy nhất)
        # Chúng ta chỉ quan tâm đến địa lý, không quan tâm thời gian lúc này
        unique_segments = df.drop_duplicates(subset=['segment_id'])
        
        print(f"✅ Tìm thấy {len(unique_segments)} đoạn đường duy nhất (từ {len(df)} dòng dữ liệu gốc).")
        print("💾 Đang lưu vào Database...")

        segments_to_create = []
        for index, row in unique_segments.iterrows():
            segments_to_create.append(
                TrafficSegment(
                    segment_id=row['segment_id'],
                    street_name=str(row['street_name']),
                    lat_snode=row['lat_snode'],
                    long_snode=row['long_snode'],
                    lat_enode=row['lat_enode'],
                    long_enode=row['long_enode']
                )
            )

        # Dùng bulk_create để insert nhanh hơn
        TrafficSegment.objects.bulk_create(segments_to_create, batch_size=1000)
        print("🎉 Đã Import thành công!")

    except Exception as e:
        print(f"❌ Lỗi: {e}")

if __name__ == "__main__":
    import_data()