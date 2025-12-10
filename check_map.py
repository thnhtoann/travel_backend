import pandas as pd
import os

BASE_DIR = 'ml_models'

try:
    df_nodes = pd.read_csv(os.path.join(BASE_DIR, 'nodes.csv'), nrows=1)
    df_streets = pd.read_csv(os.path.join(BASE_DIR, 'streets.csv'), nrows=1)
    df_segments = pd.read_csv(os.path.join(BASE_DIR, 'segments.csv'), nrows=1)

    print("\n=== TÊN CỘT TRONG FILE CSV ===")
    print(f"1. Nodes.csv:    {list(df_nodes.columns)}")
    print(f"2. Streets.csv:  {list(df_streets.columns)}")
    print(f"3. Segments.csv: {list(df_segments.columns)}")
    print("==============================\n")
except Exception as e:
    print(f"Lỗi: {e}")