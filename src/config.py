"""
Merkezi Fabrika Yapılandırma Parametreleri (Single Source of Truth)
Tüm modüller (LP, CP-SAT, Enerji, Simülasyon) bu değerleri referans alır.
"""
from pathlib import Path

# Dizin Hiyerarşisi
SRC_DIR = Path(__file__).resolve().parent
BASE_DIR = SRC_DIR.parent
DATA_DIR = BASE_DIR / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
DB_PATH = DATA_DIR / "factory.db"

# 1. Ortak Fabrika Çalışma Takvimi (Madde 7 Düzeltmesi)
WORK_DAYS_PER_WEEK = 6          # Haftada 6 iş günü (Pazar planlı bakım/tatil)
SHIFTS_PER_DAY = 2              # Günde 2 vardiya
HOURS_PER_SHIFT = 8             # Vardiya başına 8 saat
DAILY_PRODUCTION_HOURS = SHIFTS_PER_DAY * HOURS_PER_SHIFT  # 16 saat/gün
WEEKLY_HOURS_PER_MACHINE = WORK_DAYS_PER_WEEK * DAILY_PRODUCTION_HOURS  # 96 saat/makine
WEEKLY_MINUTES_PER_MACHINE = WEEKLY_HOURS_PER_MACHINE * 60            # 5.760 dakika/makine

# 2. İktisadi & İşçilik Dönüşüm Parametreleri (Madde 14 Düzeltmesi)
# Tezgâh amortisman/işletme maliyetleri machines.csv'den okunur.
# Bu değerler tesis genel operasyon ve operatör işçilik bazını temsil eder.
LABOR_COST_STANDARD_HR = 450.0  # Standart saatlik adam/saat maliyeti ($/saat)
OVERTIME_MULTIPLIER = 1.5       # Fazla mesai katsayısı
LABOR_COST_OVERTIME_HR = LABOR_COST_STANDARD_HR * OVERTIME_MULTIPLIER  # 675.0 $/saat
# 3. Çevre & Sürdürülebilirlik Parametreleri (GHG Protocol & EU ETS)
GRID_EMISSION_FACTOR = 0.440        # tCO2e / MWh (Ulusal Şebeke Emisyon Faktörü - Kapsam 2)
DIESEL_EMISSION_FACTOR = 0.00268   # tCO2e / Litre dizel (Kapsam 1)
DEFAULT_FORKLIFT_LITERS = 85.0     # Tesis içi lojistik dizel tüketimi (Litre/hafta)
CARBON_PRICE_SCENARIOS_EUR = [0, 50, 80, 100, 120]  # EU ETS dahili karbon fiyatlandırma senaryoları (€/tCO2e)