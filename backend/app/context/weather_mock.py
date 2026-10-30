"""Weather contexts that do not come from the KMA: demo slider values and 'unavailable'."""
from ..config import rain_level
from ..strategies.base import ResolvedParams, WeatherContext


def demo_weather(rn1_mm: float, alert: str, params: ResolvedParams) -> WeatherContext:
    """Requirement 2.4: demo values replace the KMA values and are labelled as such."""
    return WeatherContext(source="demo", rn1_mm=float(rn1_mm), alert=alert,
                          level=rain_level(rn1_mm, alert, params.thresholds_mm, params.alert_min_level),
                          observed_at=None, real_weather_applied=False, alert_status="not_requested")


def unavailable_weather() -> WeatherContext:
    """Requirement 2.5: no KMA data. Computed as 0 mm and marked 'real rain not applied'."""
    return WeatherContext(source="unavailable", rn1_mm=0.0, alert="none", level=0, observed_at=None,
                          real_weather_applied=False, alert_status="failed")
