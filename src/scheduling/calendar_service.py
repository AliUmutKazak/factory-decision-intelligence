"""
MachineCalendarService: Fabrika Takvim ve Vardiya Yönetimi Tekil Gerçeklik Kaynağı (SSOT)
Scheduler, Energy Analytics, Capacity ve Maintenance modüllerine standart takvim semantiği sağlar.
"""

class MachineCalendarService:
    MINUTES_IN_HOUR = 60
    HOURS_IN_DAY = 24
    MINUTES_IN_DAY = 1440  # 24 * 60
    DAYS_IN_WEEK = 7
    MINUTES_IN_WEEK = 10080  # 7 * 1440

    # Fabrika Vardiya Tanımları (Pzt - Cmt):
    # Gece OT Penceresi : 00:00 - 08:00 (480 dk)
    # Düzenli 2 Vardiya : 08:00 - 24:00 (960 dk)
    # Pazar Günü        : 24 saat Kapalı / Bakım (Hard Closed)
    OT_WINDOW_MINUTES = 8 * 60   # 480 dk
    REGULAR_SHIFT_START_MIN = 8 * 60  # 480 dk

    @classmethod
    def get_week_and_day(cls, time_min: float) -> tuple[int, int, float]:
        """
        Verilen mutlak dakika için (week_index, day_of_week, day_cursor_min) döner.
        day_of_week: 0=Pazartesi, ..., 5=Cumartesi, 6=Pazar
        """
        week_idx = int(time_min // cls.MINUTES_IN_WEEK) + 1
        t_in_week = time_min % cls.MINUTES_IN_WEEK
        day_of_week = int(t_in_week // cls.MINUTES_IN_DAY)
        day_cursor_min = t_in_week % cls.MINUTES_IN_DAY
        return week_idx, day_of_week, day_cursor_min

    @classmethod
    def is_sunday_closed(cls, time_min: float) -> bool:
        """Pazar günü (Gün 6) tüm gün fabrika planlı kapalıdır."""
        _, day_of_week, _ = cls.get_week_and_day(time_min)
        return day_of_week == 6

    @classmethod
    def is_regular_calendar_shift(cls, time_min: float) -> bool:
        """
        Pzt - Cmt (Gün 0-5) günlerinde 08:00 - 24:00 arası düzenli çalışma saatidir.
        """
        _, day_of_week, day_cursor_min = cls.get_week_and_day(time_min)
        if day_of_week == 6:  # Pazar kapalı
            return False
        return day_cursor_min >= cls.REGULAR_SHIFT_START_MIN

    @classmethod
    def is_overtime_window(cls, time_min: float) -> bool:
        """
        Pzt - Cmt (Gün 0-5) günlerinde 00:00 - 08:00 arası fazla mesai penceresidir.
        """
        _, day_of_week, day_cursor_min = cls.get_week_and_day(time_min)
        if day_of_week == 6:  # Pazar kapalı
            return False
        return day_cursor_min < cls.OT_WINDOW_MINUTES