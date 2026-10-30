"""Where the weather is read: Gwangju and Jeonnam regions, KMA grid and alert areas.

Alert codes are from KMA's official list (data.go.kr 15043573, 기상특보구역정보_20260601). The June
2026 revision split some counties. A county's alert counts whichever part it covers, so a place
can show an alert that is in effect only in the other part of its county.
"""
from dataclasses import dataclass
import math

LonLat = tuple[float, float]
# 광주광역시, 광주광역시(2026-05-31~), 광주서부, 광주동부. L1013400 is 경기 광주시: excluded on purpose.
GWANGJU_AREA_CODES = frozenset({"L1130000", "L1130100", "L1130110", "L1130120"})
# Gwangju and Jeonnam including its islands. A box, so towns just over the border also pass.
WEATHER_BBOX = (125.0, 33.9, 127.95, 35.6)

# KMA LCC grid (5 km), from the short-term forecast API guide.
EARTH_KM, CELL_KM = 6371.00877, 5.0
LAT1, LAT2, ORIGIN_LON, ORIGIN_LAT = 30.0, 60.0, 126.0, 38.0
ORIGIN_X, ORIGIN_Y = 43, 136


@dataclass(frozen=True)
class WeatherRegion:
    id: str
    name: str
    group: str  # "광주" | "전남"
    lon: float
    lat: float
    alert_codes: frozenset[str]

    def as_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "group": self.group, "lon": self.lon, "lat": self.lat}


def _gwangju(region_id: str, name: str, lon: float, lat: float) -> WeatherRegion:
    return WeatherRegion(region_id, name, "광주", lon, lat, GWANGJU_AREA_CODES)


def _jeonnam(region_id: str, name: str, lon: float, lat: float, *codes: str) -> WeatherRegion:
    return WeatherRegion(region_id, name, "전남", lon, lat, frozenset(codes))


# Coordinates: city hall or county office, close enough for a 5 km grid.
DEFAULT_REGION = _gwangju("gwangju", "광주광역시", 126.8514, 35.1600)
REGIONS: tuple[WeatherRegion, ...] = (
    DEFAULT_REGION,
    _gwangju("gwangju-dong", "광주 동구", 126.9233, 35.1460),
    _gwangju("gwangju-seo", "광주 서구", 126.8900, 35.1520),
    _gwangju("gwangju-nam", "광주 남구", 126.9025, 35.1330),
    _gwangju("gwangju-buk", "광주 북구", 126.9120, 35.1740),
    _gwangju("gwangju-gwangsan", "광주 광산구", 126.7934, 35.1396),
    _jeonnam("mokpo", "목포시", 126.3922, 34.8118, "L1052100"),
    _jeonnam("yeosu", "여수시", 127.6622, 34.7604, "L1051000"),
    _jeonnam("suncheon", "순천시", 127.4872, 34.9506, "L1051200"),
    _jeonnam("naju", "나주시", 126.7108, 35.0159, "L1052800", "L1052810", "L1052820"),
    _jeonnam("gwangyang", "광양시", 127.6959, 34.9407, "L1051100"),
    _jeonnam("damyang", "담양군", 126.9880, 35.3211, "L1050300"),
    _jeonnam("gokseong", "곡성군", 127.2920, 35.2820, "L1052900", "L1052910", "L1052920"),
    _jeonnam("gurye", "구례군", 127.4629, 35.2025, "L1053000", "L1053010", "L1053020"),
    _jeonnam("goheung", "고흥군", 127.2848, 34.6112, "L1053100", "L1053110", "L1053120"),
    _jeonnam("boseong", "보성군", 127.0800, 34.7715, "L1050900"),
    _jeonnam("hwasun", "화순군", 126.9865, 35.0645, "L1050700"),
    _jeonnam("jangheung", "장흥군", 126.9070, 34.6817, "L1051300"),
    _jeonnam("gangjin", "강진군", 126.7673, 34.6421, "L1051400"),
    _jeonnam("haenam", "해남군", 126.5990, 34.5735, "L1053200", "L1053210", "L1053220"),
    _jeonnam("yeongam", "영암군", 126.6968, 34.8003, "L1051700"),
    _jeonnam("muan", "무안군", 126.4817, 34.9904, "L1053400", "L1053410", "L1053420"),
    _jeonnam("hampyeong", "함평군", 126.5164, 35.0659, "L1051900"),
    _jeonnam("yeonggwang", "영광군", 126.5120, 35.2772, "L1052700", "L1052710", "L1052720"),
    _jeonnam("jangseong", "장성군", 126.7846, 35.3019, "L1050600"),
    _jeonnam("wando", "완도군", 126.7550, 34.3110, "L1053300", "L1053310", "L1053320"),
    _jeonnam("jindo", "진도군", 126.2635, 34.4868, "L1052300"),
    _jeonnam("sinan", "신안군", 126.3517, 34.8283, "L1052200"),
    _jeonnam("heuksando", "흑산도·홍도", 125.4310, 34.6840, "L1052400", "L1052500"),
    _jeonnam("geomundo", "거문도·초도", 127.3080, 34.0280, "L1052600"),
)


def in_weather_area(lon: float, lat: float) -> bool:
    return WEATHER_BBOX[0] <= lon <= WEATHER_BBOX[2] and WEATHER_BBOX[1] <= lat <= WEATHER_BBOX[3]


def region_for(lon: float, lat: float) -> WeatherRegion:
    """The nearest listed place. There are no boundary shapes, so near a border this can be the neighbour."""
    scale = math.cos(math.radians(lat))
    return min(REGIONS, key=lambda r: ((r.lon - lon) * scale) ** 2 + (r.lat - lat) ** 2)


def grid_of(lon: float, lat: float) -> tuple[int, int]:
    """KMA forecast grid cell of a point."""
    rad = math.pi / 180.0
    re = EARTH_KM / CELL_KM
    slat1, slat2, olon, olat = LAT1 * rad, LAT2 * rad, ORIGIN_LON * rad, ORIGIN_LAT * rad
    sn = (math.log(math.cos(slat1) / math.cos(slat2))
          / math.log(math.tan(math.pi / 4 + slat2 / 2) / math.tan(math.pi / 4 + slat1 / 2)))
    sf = math.tan(math.pi / 4 + slat1 / 2) ** sn * math.cos(slat1) / sn
    ro = re * sf / math.tan(math.pi / 4 + olat / 2) ** sn
    ra = re * sf / math.tan(math.pi / 4 + lat * rad / 2) ** sn
    theta = (lon * rad - olon) * sn
    return (int(ra * math.sin(theta) + ORIGIN_X + 0.5), int(ro - ra * math.cos(theta) + ORIGIN_Y + 0.5))
