import pandas as pd
import joblib
import os
import re
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import accuracy_score

# --- CẤU HÌNH ---
# Đảm bảo bạn đã copy file train.csv vào thư mục ml_models
BASE_DIR = 'ml_models'
DATA_PATH = os.path.join(BASE_DIR, 'train.csv')
MODEL_PATH = os.path.join(BASE_DIR, 'traffic_model.pkl')
ENCODER_PATH = os.path.join(BASE_DIR, 'street_encoder.pkl')

def extract_hour(period_str):
    """
    Chuyển đổi 'period_9_30' thành số 9.
    """
    try:
        # Tìm các số trong chuỗi. Ví dụ period_23_30 -> ['23', '30']
        parts = re.findall(r'\d+', str(period_str))
        if parts:
            return int(parts[0]) # Lấy số đầu tiên là giờ
        return 0
    except:
        return 0

def train():
    print("🚀 Đang đọc file train.csv...")

    if not os.path.exists(DATA_PATH):
        print(f"❌ Lỗi: Không tìm thấy file {DATA_PATH}")
        return

    # 1. Đọc dữ liệu
    try:
        df = pd.read_csv(DATA_PATH)
        print(f"✅ Đã tải {len(df)} dòng dữ liệu.")
    except Exception as e:
        print(f"❌ Lỗi đọc CSV: {e}")
        return

    # 2. Xử lý dữ liệu (Feature Engineering)
    print("⚙️ Đang xử lý dữ liệu...")

    # Xử lý giờ từ cột 'period'
    df['hour'] = df['period'].apply(extract_hour)
    
    # Xử lý tên đường (Chuyển thành chuỗi để tránh lỗi nếu có số lẫn lộn)
    df['street_name'] = df['street_name'].astype(str)

    # 3. Mã hóa tên đường
    le = LabelEncoder()
    df['street_encoded'] = le.fit_transform(df['street_name'])

    # 4. Chọn Input và Output
    # Input: Giờ, Thứ (weekday), Mã tên đường
    X = df[['hour', 'weekday', 'street_encoded']]
    
    # Output: LOS (A, B, C, D, E...) - Bài toán Phân loại (Classification)
    y = df['LOS']

    # 5. Chia tập train/test
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    # 6. Huấn luyện (Dùng Classifier vì output là A,B,C...)
    print("🧠 Đang huấn luyện AI (Random Forest Classifier)...")
    model = RandomForestClassifier(n_estimators=50, n_jobs=-1, random_state=42)
    model.fit(X_train, y_train)

    # 7. Đánh giá
    print("📊 Đang đánh giá độ chính xác...")
    predictions = model.predict(X_test)
    accuracy = accuracy_score(y_test, predictions)
    print(f"✅ Độ chính xác (Accuracy): {accuracy * 100:.2f}%")

    # 8. Lưu model
    joblib.dump(model, MODEL_PATH)
    joblib.dump(le, ENCODER_PATH)
    print(f"💾 Đã lưu model tại: {MODEL_PATH}")

if __name__ == "__main__":
    train()