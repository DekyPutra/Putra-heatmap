import os
import json
import pandas as pd
import yfinance as yf
from datetime import datetime

SYMBOL = "GC=F"  # Gold / XAUUSD Futures
MAX_DAYS_HISTORY = 1825  # Simpan hingga 5 tahun
OUTPUT_JSON = "heatmap_data.json"
DATA_STORE_CSV = "historical_m1_store.csv"

# Parameter Trading (Bisa disesuaikan)
TARGET_PIPS = 0.50  # 50 pips / $0.50 pada XAUUSD (misal Entry 2700.00 -> TP Buy 2700.50, SL Buy 2699.50)
HOLDING_WINDOW_MINUTES = 15  # Batas maksimal holding time (15 candle M1 ke depan)

def load_and_convert_mt5_csv(csv_path):
    """Membaca file CSV hasil export dari MT5"""
    try:
        df = pd.read_csv(csv_path, sep='\t')
        if '<DATE>' in df.columns:
            df = df.rename(columns={
                '<DATE>': 'DateStr',
                '<TIME>': 'TimeStr',
                '<OPEN>': 'Open',
                '<HIGH>': 'High',
                '<LOW>': 'Low',
                '<CLOSE>': 'Close'
            })
            df['DateStr'] = df['DateStr'].astype(str).str.replace('.', '-', regex=False)
            df['TimeStr'] = df['TimeStr'].astype(str).str.slice(0, 5)
            return df[['DateStr', 'TimeStr', 'Open', 'High', 'Low', 'Close']]
    except Exception:
        pass
    
    df_std = pd.read_csv(csv_path)
    # Jika CSV standar belum punya High/Low, buat perkiraan dari Open/Close
    if 'High' not in df_std.columns:
        df_std['High'] = df_std[['Open', 'Close']].max(axis=1)
        df_std['Low'] = df_std[['Open', 'Close']].min(axis=1)
    return df_std

def get_yesterday_m1_data():
    """Tarik data candle 1m terbaru dari Yahoo Finance"""
    ticker = yf.Ticker(SYMBOL)
    df = ticker.history(period="5d", interval="1m")
    if df.empty:
        return None

    df = df.reset_index()
    df['Datetime'] = pd.to_datetime(df['Datetime']).dt.tz_convert('Asia/Jakarta')
    df['TimeStr'] = df['Datetime'].dt.strftime('%H:%M')
    df['DateStr'] = df['Datetime'].dt.strftime('%Y-%m-%d')
    return df[['DateStr', 'TimeStr', 'Open', 'High', 'Low', 'Close']]

def update_fifo_database(new_df):
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
    return combined_df

def simulate_tp_sl_outcomes(df_subset):
    """Simulasi testing pergerakan 15 candle ke depan dengan TP/SL 50 pips"""
    df_sorted = df_subset.sort_values(by=['DateStr', 'TimeStr']).reset_index(drop=True)
    stats = {}
    
    # Kelompokkan baris berdasarkan waktu (HH:MM)
    time_indices = df_sorted.groupby('TimeStr').indices

    for time_str, idx_list in time_indices.items():
        total_samples = 0
        buy_wins = 0
        sell_wins = 0

        for idx in idx_list:
            # Ambil jendela 15 candle M1 ke depan untuk simulasi holding
            future_candles = df_sorted.iloc[idx : idx + HOLDING_WINDOW_MINUTES]
            if len(future_candles) < 2:
                continue
            
            entry_price = future_candles.iloc[0]['Open']
            tp_buy = entry_price + TARGET_PIPS
            sl_buy = entry_price - TARGET_PIPS
            
            tp_sell = entry_price - TARGET_PIPS
            sl_sell = entry_price + TARGET_PIPS

            # Evaluasi BUY
            buy_hit_tp = False
            for _, row in future_candles.iterrows():
                if row['Low'] <= sl_buy:
                    break
                if row['High'] >= tp_buy:
                    buy_hit_tp = True
                    break
            
            # Evaluasi SELL
            sell_hit_tp = False
            for _, row in future_candles.iterrows():
                if row['High'] >= sl_sell:
                    break
                if row['Low'] <= tp_sell:
                    sell_hit_tp = True
                    break

            total_samples += 1
            if buy_hit_tp:
                buy_wins += 1
            if sell_hit_tp:
                sell_wins += 1

        if total_samples == 0:
            continue

        buy_prob = round((buy_wins / total_samples) * 100, 1)
        sell_prob = round((sell_wins / total_samples) * 100, 1)

        dominant = "BUY" if buy_prob >= sell_prob else "SELL"
        prob_val = buy_prob if dominant == "BUY" else sell_prob

        stats[time_str] = {
            "direction": dominant,
            "probability": prob_val,
            "samples": total_samples
        }
        
    return stats

def calculate_multi_timeframe_heatmap(df):
    unique_dates = sorted(df['DateStr'].unique())
    total_days = len(unique_dates)
    
    dates_1m = unique_dates[-30:] if total_days >= 30 else unique_dates
    dates_2m = unique_dates[-60:] if total_days >= 60 else unique_dates
    
    df_1m = df[df['DateStr'].isin(dates_1m)]
    df_2m = df[df['DateStr'].isin(dates_2m)]
    
    print("Menghitung simulasi TP/SL 50 pips untuk 1 Bulan...")
    stats_1m = simulate_tp_sl_outcomes(df_1m)
    print("Menghitung simulasi TP/SL 50 pips untuk 2 Bulan...")
    stats_2m = simulate_tp_sl_outcomes(df_2m)
    print("Menghitung simulasi TP/SL 50 pips untuk Seluruh Data...")
    stats_all = simulate_tp_sl_outcomes(df)
    
    all_times = sorted(list(set(df['TimeStr'].unique())))
    
    final_output = {
        "metadata": {
            "total_days_all": total_days,
            "days_1m": len(dates_1m),
            "days_2m": len(dates_2m)
        },
        "heatmap": {}
    }
    
    for t in all_times:
        final_output["heatmap"][t] = {
            "m1": stats_1m.get(t, {"direction": "-", "probability": 0, "samples": 0}),
            "m2": stats_2m.get(t, {"direction": "-", "probability": 0, "samples": 0}),
            "all": stats_all.get(t, {"direction": "-", "probability": 0, "samples": 0})
        }

    with open(OUTPUT_JSON, "w") as f:
        json.dump(final_output, f, indent=2)

if __name__ == "__main__":
    new_data = get_yesterday_m1_data()
    if new_data is not None:
        full_data = update_fifo_database(new_data)
        calculate_multi_timeframe_heatmap(full_data)
