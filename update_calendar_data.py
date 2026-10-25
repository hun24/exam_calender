#!/usr/bin/env python3
"""Fetch public holidays and NEIS school schedules and publish a public JSON feed."""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

HOLIDAY_KEY = os.environ.get("HOLIDAY_API_KEY", "").strip()
NEIS_KEY = os.environ.get("NEIS_API_KEY", "").strip()

# 학교/교육청 코드는 비밀키가 아니므로 이 파일에 직접 입력하세요.
# 아래 예시 문자열을 본인 학교의 실제 코드로 바꾼 뒤 GitHub에 올리면 됩니다.
NEIS_ATPT_OFCDC_SC_CODE = "J10"
NEIS_SD_SCHUL_CODE = "7530763"

OFFICE_CODE = NEIS_ATPT_OFCDC_SC_CODE.strip()
SCHOOL_CODE = NEIS_SD_SCHUL_CODE.strip()
OUT = Path("docs/calendar-data.json")


def get_json(url, params):
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(
        f"{url}?{query}",
        headers={"User-Agent": "EvaluationReminderCalendarData/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8-sig"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        # 인증키가 포함된 URL을 로그에 남기지 않습니다.
        raise RuntimeError(f"공공 API 요청 실패: {type(exc).__name__}") from None


def as_list(raw):
    if raw is None:
        return []
    return raw if isinstance(raw, list) else [raw]


def fetch_holidays(year, month):
    data = get_json(
        "https://apis.data.go.kr/B090041/openapi/service/SpcdeInfoService/getRestDeInfo",
        {
            "ServiceKey": HOLIDAY_KEY,
            "solYear": str(year),
            "solMonth": f"{month:02d}",
            "_type": "json",
        },
    )
    try:
        body = data["response"]["body"]
        items = body.get("items", {}).get("item") if body.get("items") else None
    except (KeyError, TypeError):
        result = data.get("response", {}).get("header", {}).get("resultMsg", "응답 구조 오류")
        raise RuntimeError(f"공휴일 API 응답 오류: {result}") from None

    rows = []
    for item in as_list(items):
        if not isinstance(item, dict):
            continue
        raw_date = str(item.get("locdate", ""))
        if len(raw_date) != 8:
            continue
        name = str(item.get("dateName", "공휴일"))
        rows.append({
            "date": f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}",
            "name": name,
            "title": name,
            "isHoliday": str(item.get("isHoliday", "Y")),
            "source": "한국천문연구원 특일정보 API",
        })
    return rows


def fetch_schedules(year, month):
    first = date(year, month, 1)
    if month == 12:
        last = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        last = date(year, month + 1, 1) - timedelta(days=1)

    data = get_json(
        "https://open.neis.go.kr/hub/SchoolSchedule",
        {
            "KEY": NEIS_KEY,
            "Type": "json",
            "pIndex": "1",
            "pSize": "1000",
            "ATPT_OFCDC_SC_CODE": OFFICE_CODE,
            "SD_SCHUL_CODE": SCHOOL_CODE,
            "AA_FROM_YMD": first.strftime("%Y%m%d"),
            "AA_TO_YMD": last.strftime("%Y%m%d"),
        },
    )
    root = data.get("SchoolSchedule") if isinstance(data, dict) else None
    rows = []
    for section in as_list(root):
        if not isinstance(section, dict):
            continue
        section_rows = section.get("row")
        if isinstance(section_rows, list):
            rows.extend(section_rows)
        # NEIS returns a RESULT header when the query has no data or an error.
        for head in as_list(section.get("head")):
            if not isinstance(head, dict) or not isinstance(head.get("RESULT"), dict):
                continue
            result = head["RESULT"]
            code = str(result.get("CODE", ""))
            if code and code not in ("INFO-200", "INFO-000"):
                raise RuntimeError(f"NEIS API 응답 오류: {code}")

    output = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        raw_date = str(item.get("AA_YMD", ""))
        if len(raw_date) != 8:
            continue
        title = str(item.get("EVENT_NM", "학사일정"))
        output.append({
            "date": f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}",
            "title": title,
            "name": title,
            "description": str(item.get("EVENT_CNTNT", "")),
            "source": "나이스 교육정보 개방 포털 학사일정 API",
        })
    return output


def main():
    if not HOLIDAY_KEY or not NEIS_KEY:
        sys.exit("GitHub Actions Secrets에 HOLIDAY_API_KEY와 NEIS_API_KEY를 등록하세요.")
    if (not OFFICE_CODE or not SCHOOL_CODE or
            OFFICE_CODE == "여기에_교육청코드" or SCHOOL_CODE == "여기에_학교코드"):
        sys.exit("scripts/update_calendar_data.py의 교육청 코드와 학교 코드를 실제 값으로 바꾸세요.")

    today = date.today()
    holidays, schedules = [], []
    # 현재 연도와 다음 연도의 일정을 생성합니다.
    for year in (today.year, today.year + 1):
        for month in range(1, 13):
            holidays.extend(fetch_holidays(year, month))
            schedules.extend(fetch_schedules(year, month))

    payload = {
        "updatedAt": today.isoformat(),
        "holidays": holidays,
        "academicSchedules": schedules,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"일정 데이터 갱신 완료: 공휴일 {len(holidays)}건, 학사일정 {len(schedules)}건")


if __name__ == "__main__":
    main()
