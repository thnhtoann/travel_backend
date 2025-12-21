import pandas as pd
import joblib
import os
import re
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import accuracy_score

# --- CONFIGURATION ---
BASE_DIR = 'ml_models'
DATA_PATH = os.path.join(BASE_DIR, 'train.csv')
MODEL_PATH = os.path.join(BASE_DIR, 'traffic_model.pkl')
ENCODER_PATH = os.path.join(BASE_DIR, 'street_encoder.pkl')

def extract_hour(period_str):
    """
    Extracts the hour integer from a string format like 'period_9_30'.
    Returns the first numeric group found or 0 if no digits exist.
    """
    try:
        # Find numeric parts in the string. Example: 'period_23_30' -> ['23', '30']
        parts = re.findall(r'\d+', str(period_str))
        if parts:
            return int(parts[0])  # The first number represents the hour
        return 0
    except (ValueError, TypeError):
        return 0

def train_model():
    """
    Loads data, preprocesses features, trains the Random Forest model,
    evaluates performance, and saves the artifacts.
    """
    print("Step 1: Reading train.csv...")

    if not os.path.exists(DATA_PATH):
        print(f"Error: File not found at {DATA_PATH}")
        return

    # 1. Load data
    try:
        df = pd.read_csv(DATA_PATH)
        print(f"Successfully loaded {len(df)} rows.")
    except Exception as e:
        print(f"Error reading CSV: {e}")
        return

    # 2. Feature Engineering
    print("Step 2: Preprocessing data...")

    # Extract hour from 'period' column
    df['hour'] = df['period'].apply(extract_hour)
    
    # Ensure street names are strings to prevent type errors during encoding
    df['street_name'] = df['street_name'].astype(str)

    # 3. Encode Street Names
    # Categorical data must be converted to numerical values for the model
    le = LabelEncoder()
    df['street_encoded'] = le.fit_transform(df['street_name'])

    # 4. Feature Selection
    # Input features: Hour of the day, Day of the week (weekday), and Encoded street
    X = df[['hour', 'weekday', 'street_encoded']]
    
    # Target variable: Level of Service (LOS) - A, B, C, D, E, etc.
    y = df['LOS']

    # 5. Split Dataset
    # 80% for training, 20% for testing
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )

    # 6. Training
    print("Step 3: Training Random Forest Classifier...")
    # n_jobs=-1 uses all available processors for faster training
    model = RandomForestClassifier(n_estimators=50, n_jobs=-1, random_state=42)
    model.fit(X_train, y_train)

    # 7. Evaluation
    print("Step 4: Evaluating model accuracy...")
    predictions = model.predict(X_test)
    accuracy = accuracy_score(y_test, predictions)
    print(f"Model Accuracy: {accuracy * 100:.2f}%")

    # 8. Save Artifacts
    # Ensure the directory exists before saving
    if not os.path.exists(BASE_DIR):
        os.makedirs(BASE_DIR)
        
    joblib.dump(model, MODEL_PATH)
    joblib.dump(le, ENCODER_PATH)
    print(f"Model and Encoder saved successfully in {BASE_DIR}/")

if __name__ == "__main__":
    train_model()