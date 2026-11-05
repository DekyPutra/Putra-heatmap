import os
import json
import pandas as pd
import yfinance as yf
from datetime import datetime

SYMBOL = "GC=F"  # Ticker Yahoo Finance (Gold/XAUUSD)
MAX_DAYS_HISTORY = 1825  # Simpan hingga 5 tahun
OUTPUT_JSON = "heatmap_data.json"
DATA_STORE_CSV = "historical_m1_store.csv"

def load_and_convert_mt5_csv(csv_path):
    """Membaca file CSV hasil export dari MT5"""
    try:
        df = pd.read_csv(csv_path, sep='\t')
        if '<DATE>' in df.columns:
            df = df.rename(columns={
                '<DATE>': 'DateStr',
                '<TIME>': 'TimeStr',
                '<OPEN>': 'Open',
                '<CLOSE>': 'Close'
            })
            df['DateStr'] = df['DateStr'].astype(str).str.replace('.', '-', regex=False)
            df['TimeStr'] = df['TimeStr'].astype(str).str.slice(0, 5)
            df['ChangePips'] = df['Close'] - df['Open']
            return df[['DateStr', 'TimeStr', 'Open', 'Close', 'ChangePips']]
    except Exception:
        pass
    return pd.read_csv(csv_path)

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
    df['ChangePips'] = (df['Close'] - df['Open'])
    return df[['DateStr', 'TimeStr', 'Open', 'Close', 'ChangePips']]

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

def calc_stats_for_subset(df_subset):
    """Fungsi pembantu menghitung winrate per jam/menit"""
    stats = {}
    grouped = df_subset.groupby('TimeStr')
    for time_str, group in grouped:
        total = len(group)
        if total == 0:
            continue
        up_count = (group['ChangePips'] > 0).sum()
        down_count = (group['ChangePips'] < 0).sum()
        
        up_prob = round((up_count / total) * 100, 1)
        down_prob = round((down_count / total) * 100, 1)
        dominant = "UP" if up_prob >= down_prob else "DOWN"
        prob_val = up_prob if dominant == "UP" else down_prob
        
        stats[time_str] = {
            "direction": dominant,
            "probability": prob_val,
            "samples": total
        }
    return stats

def calculate_multi_timeframe_heatmap(df):
    unique_dates = sorted(df['DateStr'].unique())
    total_days = len(unique_dates)
    
    # Ambil filter 30 hari & 60 hari terakhir
    dates_1m = unique_dates[-30:] if total_days >= 30 else unique_dates
    dates_2m = unique_dates[-60:] if total_days >= 60 else unique_dates
    
    df_1m = df[df['DateStr'].isin(dates_1m)]
    df_2m = df[df['DateStr'].isin(dates_2m)]
    
    stats_1m = calc_stats_for_subset(df_1m)
    stats_2m = calc_stats_for_subset(df_2m)
    stats_all = calc_stats_for_subset(df)
    
    # Gabungkan semua menit yang ada
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
