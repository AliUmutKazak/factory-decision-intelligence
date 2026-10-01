import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

# Dizin Hiyerarşisi
SRC_DIR = Path(__file__).resolve().parent
BASE_DIR = SRC_DIR.parent

# Test ve Staging izolasyonu için ortam değişkeni desteği
_custom_data_dir = os.getenv("FACTORY_DATA_DIR")
DATA_DIR = Path(_custom_data_dir) if _custom_data_dir else BASE_DIR / "data"

_custom_processed_dir = os.getenv("FACTORY_PROCESSED_DIR")
PROCESSED_DATA_DIR = Path(_custom_processed_dir) if _custom_processed_dir else DATA_DIR / "processed"

RAW_DATA_DIR = DATA_DIR / "raw"
SYNTHETIC_DATA_DIR = DATA_DIR / "synthetic"

_custom_reports_dir = os.getenv("FACTORY_REPORTS_DIR")
REPORTS_DIR = Path(_custom_reports_dir) if _custom_reports_dir else BASE_DIR / "reports"

_custom_db_path = os.getenv("FACTORY_DB_PATH")
DB_PATH = Path(_custom_db_path) if _custom_db_path else DATA_DIR / "factory.db"
CONFIG_PATH = SRC_DIR / "config.py"

# 1. Ortak Fabrika Çalışma Takvimi (Madde 7 Düzeltmesi)
WORK_DAYS_PER_WEEK = 6  # Haftada 6 iş günü (Pazar planlı bakım/tatil)
SHIFTS_PER_DAY = 2  # Günde 2 vardiya
HOURS_PER_SHIFT = 8  # Vardiya başına 8 saat
DAILY_PRODUCTION_HOURS = SHIFTS_PER_DAY * HOURS_PER_SHIFT  # 16 saat/gün
WEEKLY_HOURS_PER_MACHINE = WORK_DAYS_PER_WEEK * DAILY_PRODUCTION_HOURS  # 96 saat/makine
WEEKLY_MINUTES_PER_MACHINE = WEEKLY_HOURS_PER_MACHINE * 60  # 5.760 dakika/makine

# 2. İktisadi & İşçilik Dönüşüm Parametreleri (Madde 14 Düzeltmesi)
# Tezgâh amortisman/işletme maliyetleri machines.csv'den okunur.
# Bu değerler tesis genel operasyon ve operatör işçilik bazını temsil eder.


@dataclass(frozen=True)
class EconomicConfig:
    """Ekonomik Parametreler Tek Gerçek Kaynağı (Economic SSOT).

    Tüm modüller (Cost-to-Serve, Scenario Engine, Aggregate Planning, Dashboard)
    maliyet ve para birimi değerlerini buradan tüketir.
    """

    currency: str = "EUR"
    labor_rate_per_hour: float = 25.0  # Standart operatör/işçilik baz maliyeti (€/saat)
    overtime_multiplier: float = 1.5  # Fazla mesai çarpanı
    setup_cost_per_hour: float = 40.0  # Hat hazırlık/ayar maliyeti (€/saat)
    holding_cost_per_unit_per_day: float = 0.50  # Birim/gün stok tutma maliyeti (€)
    holding_cost_per_batch: float = 25.0  # Parti başına haftalık stok tutma maliyeti (€/lot)
    backlog_penalty_per_batch: float = 1500.0  # Geciken parti cezası (€/planning_lot)
    energy_price_per_kwh: float = 0.18  # Endüstriyel elektrik baz fiyatı (€/kWh)
    carbon_price_per_ton: float = 50.0  # Dahili karbon fiyatı referansı (€/tCO2e)
    expedite_cost_flat: float = 150.0  # Hızlandırılmış sevkiyat sabit maliyeti (€)
    tardiness_cost_per_hour: float = 60.0  # Termin gecikme cezası (€/saat)

    @property
    def labor_cost_overtime_hr(self) -> float:
        return self.labor_rate_per_hour * self.overtime_multiplier


# Global SSOT Örneği
ECONOMIC_CONFIG = EconomicConfig()

# Geriye dönük uyumluluk (Backward-compatibility) aliasları
CURRENCY = ECONOMIC_CONFIG.currency
LABOR_COST_STANDARD_HR = ECONOMIC_CONFIG.labor_rate_per_hour
OVERTIME_MULTIPLIER = ECONOMIC_CONFIG.overtime_multiplier
LABOR_COST_OVERTIME_HR = ECONOMIC_CONFIG.labor_cost_overtime_hr

# 3. Çevre & Sürdürülebilirlik Parametreleri (GHG Protocol & Internal Carbon Pricing)
# 0.440 tCO2e/MWh: T.C. ETKB elektrik emisyon faktörleri (iletim: 0.436, dağıtım: 0.469) aralığındaki sentetik orta nokta varsayımıdır (Synthetic Midpoint Assumption).
# Uluslararası GHG Protocol / CBAM simülasyonları için parametrik olarak güncellenebilir.
GRID_EMISSION_FACTOR = 0.440  # tCO2e / MWh (Scope 2 Synthetic Baseline)
DIESEL_EMISSION_FACTOR = 0.00268  # tCO2e / Litre dizel (Scope 1)
DEFAULT_FORKLIFT_LITERS = 85.0  # Tesis içi lojistik dizel tüketimi (Litre/hafta)
CARBON_PRICE_SCENARIOS_EUR = [
    0,
    50,
    80,
    100,
    120,
]  # Dahili karbon fiyat senaryoları (€/tCO2e - Internal Carbon Pricing)

# 4. Malzeme & Envanter Planlama Parametreleri (MRP-I)
MRP_SERVICE_LEVEL_Z = 1.65  # %95 Çevrim Servis Seviyesi Emniyet Faktörü
INITIAL_INVENTORY = {"RAW_STEEL_A": 4500.0, "RAW_STEEL_B": 8000.0, "RAW_ALLOY_ROD": 6000.0, "COATING_POWDER": 600.0}

# 5. Talep Tahminleme & Taktik Planlama Ufku
PLANNING_HORIZON_WEEKS = 4  # 4 haftalık taktik planlama ufku
FORECAST_HORIZON_DAYS = PLANNING_HORIZON_WEEKS * 7  # 28 günlük günlük tahmin ufku

# --- Demand Forecast & Governance Configuration ---
FORECAST_MODEL_VERSION = os.getenv("FORECAST_MODEL_VERSION", "v3.0-rolling-origin-cv")
FORECAST_FEATURE_VERSION = os.getenv("FORECAST_FEATURE_VERSION", "v1.2-lag-calendar")

# Holt-Winters Varsayılan Hiperparametreleri
HOLT_WINTERS_DEFAULT_PARAMS = {
    "trend": "add",
    "seasonal": "add",
    "seasonal_periods": 7,
    "initialization_method": "estimated",
}

# 6. Taktik Toplu Planlama (Aggregate Planning - LP) Parametreleri
UNITS_PER_BATCH = 25  # 1 Üretim Kolisi / Lot = 25 Perakende Adet
AGGREGATE_CAPACITY_BUFFER = 0.10  # %10 Planlı duruş / bakım kapasite tamponu
AGGREGATE_MAX_OVERTIME_HOURS = 48.0  # Haftalık azami fazla mesai saati
AGGREGATE_HOLDING_COST_PER_BATCH = (
    ECONOMIC_CONFIG.holding_cost_per_batch
)  # Parti başına haftalık stok elde tutma maliyeti (€/planning_lot)
AGGREGATE_BACKLOG_PENALTY_PER_BATCH = ECONOMIC_CONFIG.backlog_penalty_per_batch  # Geciken parti cezası (€/planning_lot)
AGGREGATE_INITIAL_INVENTORY = {"FAM_A": 40.0, "FAM_B": 20.0}

# 7. Detaylı Çizelgeleme & Parti Parametreleri (CP-SAT SSOT)
MRP_EXPEDITE_RELEASE_TIME_MIN = 480  # Malzeme gecikmesi durumundaki erken teslim release time (dk)
PRODUCTION_BATCH_SIZE = 25  # Referans parti büyüklüğü (adet)
ENABLE_LOT_STREAMING = True  # Dev partileri alt transfer lotlarına bölerek overlap sağla
MAX_SUB_LOT_BATCHES = 40  # Bir alt transfer lotunun alabileceği maksimum batch sayısı
CPSAT_TIME_LIMIT_SECONDS = 30.0  # Çözücü zaman limiti (sn)
CPSAT_NUM_SEARCH_WORKERS = 8  # Arama iş parçacığı sayısı
CPSAT_RANDOM_SEED = 42  # Tekrarlanabilirlik tohum değeri


class SchedulingObjectivePolicy(StrEnum):
    """
    Madde 12: Business Objective Layer (Parametrik Çizelgeleme Politikaları).
    İşletmenin anlık operasyonel ve ekonomik hedefine göre solver ağırlıklarını dinamik belirler.
    """

    BALANCED = "BALANCED"
    SERVICE_LEVEL_FIRST = "SERVICE_LEVEL_FIRST"
    THROUGHPUT_MAX = "THROUGHPUT_MAX"
    COST_OPTIMIZED = "COST_OPTIMIZED"


@dataclass(frozen=True)
class ObjectiveWeights:
    makespan_weight: int
    setup_weight: int
    tardiness_weight: int


# Çizelgeleme Politikaları Sözlüğü
OBJECTIVE_POLICIES: dict[SchedulingObjectivePolicy, ObjectiveWeights] = {
    # 1. Feasibility & Dengeli Üretim (Mevcut kararlı üretim akışı korunur)
    SchedulingObjectivePolicy.BALANCED: ObjectiveWeights(
        makespan_weight=100,
        setup_weight=1,
        tardiness_weight=0,
    ),
    # 2. Servis Seviyesi / Weighted Tardiness Öncelikli (VIP müşteri ve termin odaklı)
    SchedulingObjectivePolicy.SERVICE_LEVEL_FIRST: ObjectiveWeights(
        makespan_weight=20,
        setup_weight=1,
        tardiness_weight=100,
    ),
    # 3. Yüksek Hacim / Throughput Odaklı
    SchedulingObjectivePolicy.THROUGHPUT_MAX: ObjectiveWeights(
        makespan_weight=100,
        setup_weight=0,
        tardiness_weight=0,
    ),
    # 4. Ekonomik Etki / Maliyet Odaklı (Sıra bağımlı ayar ve gecikme cezası dengeli)
    SchedulingObjectivePolicy.COST_OPTIMIZED: ObjectiveWeights(
        makespan_weight=30,
        setup_weight=5,
        tardiness_weight=50,
    ),
}

# Geriye dönük uyumluluk için varsayılan ağırlıklar:
SCHEDULING_WEIGHT_MAKESPAN = OBJECTIVE_POLICIES[SchedulingObjectivePolicy.BALANCED].makespan_weight
SCHEDULING_WEIGHT_SETUP = OBJECTIVE_POLICIES[SchedulingObjectivePolicy.BALANCED].setup_weight
SCHEDULING_WEIGHT_TARDINESS = OBJECTIVE_POLICIES[SchedulingObjectivePolicy.BALANCED].tardiness_weight
# Initial Machine Setup State (Planlama ufku başında tezgâhlarda takılı olan ürün/kalıp)
# None verilirse ilk iş için ilave setup gerekmez (soğuk başlangıç/hazır varsayımı)
INITIAL_MACHINE_STATE = {
    "M01": "P01",
    "M02": "P02",
    "M03": "P04",
}
# P2 Scenario Parameters
DEFAULT_ELECTRICITY_PRICE_EUR_PER_KWH = ECONOMIC_CONFIG.energy_price_per_kwh  # Endüstriyel elektrik baz fiyatı (€/kWh)
