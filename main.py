import numpy as np
import pandas as pd

# Portföy başlangıç veri analizi
data = {
    "Departman": ["Üretim", "Kalite", "Planlama", "Lojistik"],
    "Verimlilik": [88.5, 94.2, 91.0, 86.8],
    "Kapasite_Kullanim": [0.82, 0.90, 0.85, 0.79],
}

df = pd.DataFrame(data)

print("--- Fabrika Performans Özeti ---")
print(df)
print("\nOrtalama Verimlilik:", round(df["Verimlilik"].mean(), 2))