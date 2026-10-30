"""AI explanation of the chosen route (requirement 8).

The route logic has already chosen the route and computed every number. This module only
turns those facts into 2-3 Korean sentences:

- build_facts(): finished facts only (no coordinates). Zone names and sources come from the
  server's risk layer, never from the client.
- Bedrock (Converse) writes the sentences. Optional Bedrock Guardrails (contextual grounding,
  word filters) run when KIROTHON_BEDROCK_GUARDRAIL_ID is set.
- check_output() is a second, local guard: no guarantee words, no numbers that are not in
  the facts, no advice to drive or to take another route.
- Any failure (mock mode, quota, timeout, guardrail block, filtered output) -> template_text().
- Successful AI texts are cached in memory, keyed by the facts. Same origin/destination and
  same zones give the same facts, so the cache needs no coordinates.
"""
from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import json
import logging
import os
import re
import threading
import time
from typing import Any, Iterable, get_args

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError, ConnectTimeoutError, ReadTimeoutError

from .ai_quota import QuotaExceeded, reserve_ai_request
from .ai_service import DEFAULT_MODEL, AllowedModel, ai_mode
from .risk.layer import RiskZone
from .strategies.base import MESSAGES

log = logging.getLogger(__name__)

MAX_ZONES_IN_FACTS = 5
MAX_OUTPUT_CHARS = 400
MAX_SENTENCES = 4
CACHE_SIZE = 256
CACHE_TTL_S = 6 * 3600.0
DEFAULT_TIMEOUT_S = 8.0

# Statuses whose screen message is already fixed (requirement 6.5): no AI call.
FIXED_STATUSES = {"baseline", "no_avoid_level", "nothing_on_route"}
ALERT_MODES = {"warning": "호우경보", "advisory": "호우주의보"}
AVOID_FAILED_RESULT = "피해야 할 위험 구간을 모두 피하는 경로를 찾지 못해 일반 경로를 그대로 보여줌"
# B안 (design.md 5.7): hard zones are all avoided, some soft zones remain on the route.
PARTIAL_RESULT = "반드시 피할 위험 구간은 모두 피했고, 되도록 피할 위험 구간 일부는 지남"

SYSTEM_PROMPT = """너는 호우 위험 회피 경로 서비스에서 경로 선택 이유를 설명하는 문장을 쓴다.
사용자 메시지의 JSON에 있는 사실만으로 한국어 해요체 2~3문장을 쓴다.

규칙:
1. JSON에 있는 값만 쓴다. 숫자는 JSON에 적힌 그대로 옮기고, 더하거나 빼거나 반올림하지 않는다.
2. '안전', '보장', '침수되지 않는', '위험이 없는' 같은 표현을 쓰지 않는다. 위험_구간_수가 0인 경로는 "알려진 위험 구간을 지나지 않아요"라고만 쓴다.
3. 과거 기록을 바탕으로 한 자료다. 지금 침수됐는지, 앞으로 침수될지는 말하지 않는다.
4. 다른 경로를 추천하지 않는다. 운전, 출발, 이동을 권하거나 말리지 않는다.
5. 대체_계산이 true이면 기본 후보가 모두 위험 구역을 지나 다른 경로 엔진으로 따로 계산했다는 사실을 한 번 말한다.
6. 좌표, 링크, 목록 기호, 제목 없이 문장만 쓴다."""

QUERY = "추천 경로를 고른 이유를 2~3문장으로 설명해 주세요."

# Local backstop for the guardrail rules above (requirement 8.4).
BANNED_PATTERNS = [re.compile(p) for p in (
    r"안전",
    r"보장",
    r"침수\s*(?:되|돼)?\s*지\s*않",
    r"침수\s*(?:걱정|위험)\s*(?:이|은|도)?\s*없",
    r"위험\s*(?:이|은|도)?\s*없",
    r"(?:현재|지금)\s*(?:은|도)?\s*(?:도로가\s*)?침수",
    r"침수\s*(?:되어|돼)\s*있",
    r"운전\s*(?:하세요|하십시오|해\s*주세요|을\s*권|해도)",
    r"(?:출발|이동)\s*(?:하세요|하십시오|해\s*주세요)",
    r"다른\s*경로\s*(?:를|로)\s*(?:이용|추천|선택)",
    r"https?://",
)]
NUMBER = re.compile(r"\d+(?:\.\d+)?")
SENTENCE_END = re.compile(r"[.!?。](?:\s|$)")
YEARS_IN_NAME = re.compile(r"\(([\d·, ]+)\)\s*$")


@dataclass(frozen=True)
class ZoneLength:
    id: str
    length_m: float


@dataclass(frozen=True)
class ExplainInput:
    status: str
    level: int
    alert: str
    route_duration_s: float
    baseline_duration_s: float
    route_zones: tuple[ZoneLength, ...]
    baseline_zones: tuple[ZoneLength, ...]
    fallback_engine: bool = False  # 대체_계산: no alternative engine exists yet, so always false today


@dataclass(frozen=True)
class ExplainResult:
    text: str
    source: str            # "ai" | "template"
    reason: str | None     # why the template was used; None for AI text
    cached: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {"text": self.text, "source": self.source, "reason": self.reason, "cached": self.cached}


class UnknownZone(ValueError):
    pass


# ---- facts -------------------------------------------------------------------------------------

def _minutes(seconds: float) -> int:
    return max(1, round(seconds / 60)) if seconds > 0 else 0


def _evidence(zone: RiskZone) -> str:
    match = YEARS_IN_NAME.search(zone.name)
    if zone.type == "flood_history" and not zone.is_dummy and match:
        return f"{match.group(1)}년 침수피해 기록"
    return zone.source_name


def _zone_facts(items: Iterable[ZoneLength], zones: dict[str, RiskZone], labels: dict[str, str]) -> dict:
    resolved = []
    for item in items:
        zone = zones.get(item.id)
        if zone is None:
            raise UnknownZone(item.id)
        resolved.append((zone, item.length_m))
    resolved.sort(key=lambda pair: (-pair[1], pair[0].id))
    listed = [{"종류": labels.get(z.type, z.type), "이름": z.name, "근거": _evidence(z),
               "길이_m": int(round(length))} for z, length in resolved[:MAX_ZONES_IN_FACTS]]
    return {"위험_구간_수": len(resolved), "위험_구간": listed}


def _same_route(data: ExplainInput) -> bool:
    return (round(data.route_duration_s, 1) == round(data.baseline_duration_s, 1)
            and {z.id for z in data.route_zones} == {z.id for z in data.baseline_zones})


def needs_ai(data: ExplainInput) -> bool:
    if data.status in FIXED_STATUSES:
        return False
    if data.status == "ranked" and _same_route(data):
        return False
    return True


def build_facts(data: ExplainInput, zones: dict[str, RiskZone], labels: dict[str, str]) -> dict[str, Any]:
    mode = ALERT_MODES.get(data.alert, f"강수 {data.level}단계")
    facts: dict[str, Any] = {"모드": mode, "강수_단계": data.level}
    route_min, base_min = _minutes(data.route_duration_s), _minutes(data.baseline_duration_s)
    if data.status == "avoid_failed":
        facts["결과"] = AVOID_FAILED_RESULT
        facts["추천"] = {"경로": "일반 경로", "소요시간_분": base_min,
                       **_zone_facts(data.baseline_zones, zones, labels)}
    elif not needs_ai(data):
        facts["결과"] = MESSAGES.get(data.status, MESSAGES["ranked"])
        facts["추천"] = {"경로": "일반 경로", "소요시간_분": route_min,
                       **_zone_facts(data.route_zones, zones, labels)}
    else:
        if data.status == "partially_avoided":
            facts["결과"] = PARTIAL_RESULT
        facts["추천"] = {"경로": "회피 경로" if data.status == "avoided" else "추천 경로",
                       "소요시간_분": route_min, **_zone_facts(data.route_zones, zones, labels)}
        facts["비교"] = {"경로": "일반 경로", "소요시간_분": base_min,
                       **_zone_facts(data.baseline_zones, zones, labels)}
        facts["추가_소요시간_분"] = route_min - base_min
    facts["대체_계산"] = bool(data.fallback_engine)
    return facts


# ---- template ----------------------------------------------------------------------------------

def template_text(facts: dict[str, Any]) -> str:
    lead = "기본 후보 경로가 모두 위험 구역을 지나 다른 경로 엔진으로 따로 계산했어요. " if facts["대체_계산"] else ""
    chosen = facts["추천"]
    if "비교" not in facts:
        count = chosen["위험_구간_수"]
        tail = f" 이 경로는 위험 구간 {count}곳을 지나요." if count else " 이 경로는 알려진 위험 구간을 지나지 않아요."
        if facts.get("결과") == AVOID_FAILED_RESULT:
            return lead + "위험 구간을 모두 피하는 경로를 찾지 못해 일반 경로를 보여드려요." + tail
        return lead + facts["결과"] + tail
    base_n, route_n, extra = facts["비교"]["위험_구간_수"], chosen["위험_구간_수"], facts["추가_소요시간_분"]
    first = f"일반 경로는 위험 구간 {base_n}곳을 지나요." if base_n else "일반 경로는 알려진 위험 구간을 지나지 않아요."
    if route_n == 0:
        time_part = (f"{extra}분 더 걸리지만" if extra > 0 else "소요시간은 비슷하지만" if extra == 0
                     else f"{-extra}분 덜 걸리고")
        second = f"추천 경로는 {time_part} 알려진 위험 구간을 지나지 않아요."
    else:
        time_part = (f"{extra}분 더 걸리고" if extra > 0 else "소요시간이 비슷하고" if extra == 0
                     else f"{-extra}분 덜 걸리고")
        second = f"추천 경로는 {time_part} 위험 구간 {route_n}곳을 지나요."
    return f"{lead}{first} {second}"


# ---- output check ------------------------------------------------------------------------------

def check_output(text: str, facts_json: str) -> str | None:
    """Return a reason when the AI text breaks a rule, otherwise None."""
    if not text:
        return "empty"
    if len(text) > MAX_OUTPUT_CHARS or len(SENTENCE_END.findall(text + " ")) > MAX_SENTENCES:
        return "too_long"
    if any(p.search(text) for p in BANNED_PATTERNS):
        return "filtered"
    allowed = set(NUMBER.findall(facts_json))
    if any(n not in allowed for n in NUMBER.findall(text)):
        return "number_mismatch"
    return None


# ---- settings, cache, Bedrock ------------------------------------------------------------------

@dataclass(frozen=True)
class Settings:
    region: str
    model_id: str
    guardrail_id: str
    guardrail_version: str
    timeout_s: float


def settings() -> Settings:
    try:
        timeout = float(os.environ.get("KIROTHON_EXPLAIN_TIMEOUT_S") or DEFAULT_TIMEOUT_S)
    except ValueError:
        timeout = DEFAULT_TIMEOUT_S
    return Settings(
        region=os.environ.get("KIROTHON_BEDROCK_REGION", "ap-northeast-1"),
        model_id=(os.environ.get("KIROTHON_EXPLAIN_MODEL") or DEFAULT_MODEL).strip(),
        guardrail_id=(os.environ.get("KIROTHON_BEDROCK_GUARDRAIL_ID") or "").strip(),
        guardrail_version=(os.environ.get("KIROTHON_BEDROCK_GUARDRAIL_VERSION") or "DRAFT").strip(),
        timeout_s=min(max(timeout, 1.0), 30.0),
    )


class ExplanationCache:
    def __init__(self, size: int = CACHE_SIZE, ttl_s: float = CACHE_TTL_S):
        self.size, self.ttl_s = size, ttl_s
        self._items: OrderedDict[str, tuple[float, str]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> str | None:
        with self._lock:
            item = self._items.get(key)
            if item is None:
                return None
            if time.monotonic() - item[0] > self.ttl_s:
                del self._items[key]
                return None
            self._items.move_to_end(key)
            return item[1]

    def put(self, key: str, text: str) -> None:
        with self._lock:
            self._items[key] = (time.monotonic(), text)
            self._items.move_to_end(key)
            while len(self._items) > self.size:
                self._items.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


cache = ExplanationCache()


def _converse(facts_json: str, cfg: Settings) -> tuple[str | None, str | None]:
    client = boto3.client(
        "bedrock-runtime", region_name=cfg.region,
        config=Config(connect_timeout=3, read_timeout=cfg.timeout_s, retries={"max_attempts": 1}))
    kwargs: dict[str, Any] = {
        "modelId": cfg.model_id,
        "system": [{"text": SYSTEM_PROMPT}],
        "inferenceConfig": {"maxTokens": 300, "temperature": 0.2},
    }
    if cfg.guardrail_id:
        # Contextual grounding check: the facts are the grounding source, QUERY is the query.
        content = [{"guardContent": {"text": {"text": facts_json, "qualifiers": ["grounding_source"]}}},
                   {"guardContent": {"text": {"text": QUERY, "qualifiers": ["query"]}}}]
        kwargs["guardrailConfig"] = {"guardrailIdentifier": cfg.guardrail_id,
                                     "guardrailVersion": cfg.guardrail_version, "trace": "disabled"}
    else:
        content = [{"text": facts_json}, {"text": QUERY}]
    response = client.converse(messages=[{"role": "user", "content": content}], **kwargs)
    if response.get("stopReason") == "guardrail_intervened":
        return None, "guardrail"
    parts = response.get("output", {}).get("message", {}).get("content", [])
    return " ".join(p["text"].strip() for p in parts if "text" in p).strip(), None


def explain(data: ExplainInput, zones: dict[str, RiskZone], labels: dict[str, str]) -> ExplainResult:
    facts = build_facts(data, zones, labels)
    fallback = template_text(facts)

    def use_template(reason: str) -> ExplainResult:
        if reason not in {"not_needed", "mock"}:
            log.warning("경로 설명을 템플릿으로 대체했습니다: %s", reason)  # never log the facts
        return ExplainResult(fallback, "template", reason)

    if not needs_ai(data):
        return use_template("not_needed")
    if ai_mode() == "mock":
        return use_template("mock")
    cfg = settings()
    if cfg.model_id not in get_args(AllowedModel):
        return use_template("config")
    facts_json = json.dumps(facts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    key = hashlib.sha256("|".join((cfg.model_id, cfg.guardrail_id, cfg.guardrail_version,
                                   facts_json)).encode("utf-8")).hexdigest()
    hit = cache.get(key)
    if hit is not None:
        return ExplainResult(hit, "ai", None, cached=True)
    try:
        reserve_ai_request()
    except QuotaExceeded:
        return use_template("quota")
    try:
        text, blocked = _converse(facts_json, cfg)
    except (ReadTimeoutError, ConnectTimeoutError):
        return use_template("timeout")
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        return use_template("throttled" if code == "ThrottlingException" else "error")
    except BotoCoreError:
        return use_template("error")
    except Exception as exc:  # the route result must never fail because of the explanation
        log.warning("경로 설명 호출 오류: %s", type(exc).__name__)
        return use_template("error")
    if blocked:
        return use_template(blocked)
    problem = check_output(text or "", facts_json)
    if problem:
        return use_template(problem)
    cache.put(key, text)
    return ExplainResult(text, "ai", None)
