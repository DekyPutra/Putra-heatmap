import os
import json
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta

# --- KONFIGURASI ---
SYMBOL = "GC=F"  # Symbol Yahoo Finance: GC=F (Gold/XAUUSD), ^NDX (Nasdaq), EURUSD=X (Forex)
MAX_DAYS_HISTORY = 365 # Rentang waktu FIFO (1 Tahun)
OUTPUT_JSON = "heatmap_data.json"
DATA_STORE_CSV = "historical_m1_store.csv"

def get_yesterday_m1_data():
    """Tarik data candle 1-menit (1m) milik hari kemarin dari Yahoo Finance"""
    print(f"[{datetime.now()}] Mengunduh data 1m terbaru untuk {SYMBOL}...")
    ticker = yf.Ticker(SYMBOL)
    # Mengambil data 5 hari terakhir untuk memastikan menangkap candle 1440 menit sesi harian penuh
    df = ticker.history(period="5d", interval="1m")
    
    if df.empty:
        print("Data gagal ditarik atau pasar libur.")
        return None

    # Reset index agar timestamp jadi kolom biasa
    df = df.reset_index()
    # Format zona waktu ke WIB (UTC+7)
    df['Datetime'] = pd.to_datetime(df['Datetime']).dt.tz_convert('Asia/Jakarta')
    df['TimeStr'] = df['Datetime'].dt.strftime('%H:%M')
    df['DateStr'] = df['Datetime'].dt.strftime('%Y-%m-%d')
    df['ChangePips'] = (df['Close'] - df['Open'])
    
    return df

def update_fifo_database(new_df):
    """Sistem FIFO: Gabungkan data baru, buang data > 365 hari"""
    if os.path.exists(DATA_STORE_CSV):
        old_df = pd.read_csv(DATA_STORE_CSV)
        combined_df = pd.concat([old_df, new_df[['DateStr', 'TimeStr', 'Open', 'Close', 'ChangePips']]])
        combined_df = combined_df.drop_duplicates(subset=['DateStr', 'TimeStr'])
    else:
        combined_df = new_df[['DateStr', 'TimeStr', 'Open', 'Close', 'ChangePips']]

    # Batasi tanggal hanya 365 hari bursa terakhir (FIFO)
    unique_dates = sorted(combined_df['DateStr'].unique())
    if len(unique_dates) > MAX_DAYS_HISTORY:
        cutoff_date = unique_dates[-MAX_DAYS_HISTORY]
        combined_df = combined_df[combined_df['DateStr'] >= cutoff_date]

    combined_df.to_csv(DATA_STORE_CSV, index=False)
    print(f"Database FIFO diperbarui. Total sampel: {len(combined_df['DateStr'].unique())} hari.")
    return combined_df

def calculate_heatmap_probability(df):
    """Hitung Probabilitas UP/DOWN untuk setiap menit 00:00 - 23:59"""
    print("Menghitung matriks probabilitas 1440 menit...")
    result = {}
    
    # Kelompokkan data berdasarkan menit (HH:MM)
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

    # Simpan ke JSON ringkas
    with open(OUTPUT_JSON, "w") as f:
        json.dump(result, f, indent=2)
    print(f"Hasil heatmap berhasil disimpan ke {OUTPUT_JSON}!")

if __name__ == "__main__":
    new_data = get_yesterday_m1_data()
    if new_data is not None:
        full_data = update_fifo_database(new_data)
        calculate_heatmap_probability(full_data)
