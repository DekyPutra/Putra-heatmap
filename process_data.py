import os
import json
import pandas as pd
import yfinance as yf
from datetime import datetime

SYMBOL = "GC=F"  # Ticker Yahoo Finance untuk Emas (XAUUSD)
MAX_DAYS_HISTORY = 1825  # Simpan hingga 5 tahun (1825 hari)
OUTPUT_JSON = "heatmap_data.json"
DATA_STORE_CSV = "historical_m1_store.csv"

def load_and_convert_mt5_csv(csv_path):
    """Membaca file CSV hasil export dari MT5 (otomatis menangani format TAB/titik)"""
    try:
        # Coba baca format bawaan MT5 (Tab separated)
        df = pd.read_csv(csv_path, sep='\t')
        if '<DATE>' in df.columns:
            df = df.rename(columns={
                '<DATE>': 'DateStr',
                '<TIME>': 'TimeStr',
                '<OPEN>': 'Open',
                '<CLOSE>': 'Close'
            })
            # Ubah format tanggal 2023.01.03 menjadi 2023-01-03
            df['DateStr'] = df['DateStr'].astype(str).str.replace('.', '-', regex=False)
            df['TimeStr'] = df['TimeStr'].astype(str).str.slice(0, 5) # Ambil HH:MM saja
            df['ChangePips'] = df['Close'] - df['Open']
            return df[['DateStr', 'TimeStr', 'Open', 'Close', 'ChangePips']]
    except Exception as e:
        print(f"Mencoba membaca format standar CSV: {e}")
    
    # Jika sudah format standar CSV
    return pd.read_csv(csv_path)

def get_yesterday_m1_data():
    """Tarik data candle 1m terbaru dari Yahoo Finance"""
    print(f"[{datetime.now()}] Mengunduh data 1m terbaru...")
    ticker = yf.Ticker(SYMBOL)
    df = ticker.history(period="5d", interval="1m")
    
    if df.empty:
        return None

    df = df.reset_index()
    df['Datetime'] = pd.to_datetime(df['Datetime']).dt.tz_convert('Asia/Jakarta')
    df['TimeStr'] = df['Datetime'].dt.strftime('%H:%M')
    df['DateStr'] = df['Datetime'].dt.strftime('%Y-%m-%d')
    df['ChangePips'] = (df['Close'] - df['Open'])
    
    return df[['DateStr', 'TimeStr', 'Open', 'Close', 'ChangePips']]

def update_fifo_database(new_df):
    """Penggabungan FIFO Data"""
    if os.path.exists(DATA_STORE_CSV):
        old_df = load_and_convert_mt5_csv(DATA_STORE_CSV)
        combined_df = pd.concat([old_df, new_df])
        combined_df = combined_df.drop_duplicates(subset=['DateStr', 'TimeStr'])
    else:
        combined_df = new_df

    unique_dates = sorted(combined_df['DateStr'].unique())
    if len(unique_dates) > MAX_DAYS_HISTORY:
        cutoff_date = unique_dates[-MAX_DAYS_HISTORY]
        combined_df = combined_df[combined_df['DateStr'] >= cutoff_date]

    combined_df.to_csv(DATA_STORE_CSV, index=False)
    print(f"Total sampel tersimpan: {len(combined_df['DateStr'].unique())} hari.")
    return combined_df

def calculate_heatmap_probability(df):
    result = {}
    grouped = df.groupby('TimeStr')
    
    for time_str, group in grouped:
        total_sample = len(group)
        if total_sample == 0:
            continue
            
        up_count = (group['ChangePips'] > 0).sum()
        down_count = (group['ChangePips'] < 0).sum()
        
        up_prob = round((up_count / total_sample) * 100, 1)
        down_prob = round((down_count / total_sample) * 100, 1)
        
        dominant = "UP" if up_prob >= down_prob else "DOWN"
        prob_val = up_prob if dominant == "UP" else down_prob
        
        result[time_str] = {
            "direction": dominant,
            "probability": prob_val,
            "samples": total_sample
        }

    with open(OUTPUT_JSON, "w") as f:
        json.dump(result, f, indent=2)

if __name__ == "__main__":
    new_data = get_yesterday_m1_data()
    if new_data is not None:
        full_data = update_fifo_database(new_data)
        calculate_heatmap_probability(full_data)
