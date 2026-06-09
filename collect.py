#!/usr/bin/env python3
"""
데일리 브리프 수집·요약 스크립트
- 채널별 유튜브 RSS + 블로그 RSS를 읽어 최근 N시간 신규 항목을 모으고
- Claude API(Haiku)로 요약/핵심/활용아이디어를 생성한 뒤
- docs/feed.json 으로 저장한다. (GitHub Pages가 이 폴더를 서빙)
환경변수: ANTHROPIC_API_KEY (GitHub Secrets로 주입)
"""

import os
import json
import time
import html
import datetime as dt
import urllib.request
import xml.etree.ElementTree as ET

# ----------------------------------------------------------------------------
# 1) 소스 목록 (업로드 엑셀에서 확정한 채널 ID)
#    id 가 빈 문자열이면 건너뛴다. 블로그는 type=article, rss 에 직접 주소.
# ----------------------------------------------------------------------------
YT = "https://www.youtube.com/feeds/videos.xml?channel_id="

SOURCES = [
    {"category": "economy",   "source": "경제사냥꾼",        "rss": YT + "UC7usMJDHmtbs_oegmzQKKMA", "type": "video"},
    {"category": "economy",   "source": "부투스쿨",          "rss": YT + "UCCTOzFObhmZoMkJVQKgAQJQ", "type": "video"},
    {"category": "marketing", "source": "곽팀장",            "rss": YT + "UC-ALJHclOi2SioUH2aVlvAQ", "type": "video"},
    {"category": "marketing", "source": "WLDO",             "rss": YT + "UCijBTYEiKT1OJO54C6PnRqw", "type": "video"},
    {"category": "marketing", "source": "무빙워터",          "rss": YT + "UCY0gKpXFzg_Db399xEv0Ojw", "type": "video"},
    {"category": "marketing", "source": "돌고래유괴단",      "rss": YT + "UCUsLcIQq0poAfOxRyJbxlLA", "type": "video"},
    {"category": "marketing", "source": "마케팅학교",        "rss": YT + "UCCZEqe3-h1IKKsMLNIZmJ1A", "type": "video"},
    {"category": "design",    "source": "디고디원찬",        "rss": YT + "UCvcGy6uMg0kwTyEab6hkSlQ", "type": "video"},
    {"category": "design",    "source": "페이퍼로지",        "rss": YT + "UCowbfOj8HKvTeL6KGIt2waw", "type": "video"},
    {"category": "design",    "source": "디자인하는AI",      "rss": YT + "UCk_xkR8ORNwtMkaffvYArGA", "type": "video"},
    {"category": "design",    "source": "실무자",            "rss": YT + "UCtalWvUPhsOFVqxnzM9gedg", "type": "video"},
    {"category": "design",    "source": "김그륜",            "rss": YT + "UCAQ-_H4rACX-aoMPDPGGxBQ", "type": "video"},
    {"category": "growth",    "source": "소울정",            "rss": YT + "UCOad7XBQl83FAzunMVN7Ujg", "type": "video"},
    # 아래는 ID/주소 확보 후 채워넣기 (지금은 건너뜀)
    {"category": "growth",    "source": "최성운의 사고실험",  "rss": "", "type": "video"},
    {"category": "lego",      "source": "원더랜드 블로그",    "rss": "", "type": "article"},  # 예: https://rss.blog.naver.com/블로그아이디.xml
]

LOOKBACK_HOURS = int(os.environ.get("LOOKBACK_HOURS", "26"))
MODEL = os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
OUT_PATH = os.environ.get("OUT_PATH", "docs/feed.json")
API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

ATOM = "{http://www.w3.org/2005/Atom}"
MEDIA = "{http://search.yahoo.com/mrss/}"


def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 daily-brief"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def parse_dt(s):
    if not s:
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            return dt.datetime.strptime(s, fmt)
        except ValueError:
            pass
    # RFC822 (블로그 RSS pubDate)
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(s)
    except Exception:
        return None


def read_feed(src):
    """유튜브(Atom) / 블로그(RSS) 모두에서 항목 리스트를 표준 형태로 추출."""
    if not src["rss"]:
        return []
    try:
        raw = fetch(src["rss"])
    except Exception as e:
        print(f"  ! RSS 실패: {src['source']} ({e})")
        return []

    items = []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        print(f"  ! 파싱 실패: {src['source']} ({e})")
        return []

    # 유튜브 Atom 형식
    entries = root.findall(f"{ATOM}entry")
    if entries:
        for e in entries:
            title = (e.findtext(f"{ATOM}title") or "").strip()
            link_el = e.find(f"{ATOM}link")
            link = link_el.get("href") if link_el is not None else ""
            published = e.findtext(f"{ATOM}published") or ""
            gid = e.findtext(f"{ATOM}id") or link
            desc = ""
            grp = e.find(f"{MEDIA}group")
            if grp is not None:
                desc = (grp.findtext(f"{MEDIA}description") or "").strip()
            items.append({"title": title, "link": link, "guid": gid,
                          "published": published, "content": desc})
        return items

    # 일반 RSS 2.0 형식 (네이버 블로그 등)
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        published = it.findtext("pubDate") or ""
        gid = (it.findtext("guid") or link).strip()
        desc = (it.findtext("description") or "").strip()
        items.append({"title": title, "link": link, "guid": gid,
                      "published": published, "content": desc})
    return items


def is_recent(published, cutoff):
    d = parse_dt(published)
    if d is None:
        return False
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d >= cutoff


def strip_tags(s):
    out = []
    skip = False
    for ch in s:
        if ch == "<":
            skip = True
        elif ch == ">":
            skip = False
        elif not skip:
            out.append(ch)
    return html.unescape("".join(out))


def summarize(title, content):
    """Claude API 호출. 실패 시 빈 요약 반환(파이프라인은 계속)."""
    if not API_KEY:
        return {"summary": "(API 키 없음)", "takeaways": [], "idea": ""}
    body = {
        "model": MODEL,
        "max_tokens": 700,
        "messages": [{
            "role": "user",
            "content": (
                "다음 콘텐츠를 분석해 JSON만 출력하라. 설명·마크다운·코드펜스 금지. "
                '형식: {"summary":"한 문장 요약","takeaways":["핵심1","핵심2","핵심3"],'
                '"idea":"마케터/디자이너 관점에서 실무에 활용·발전시킬 구체적 아이디어 한 문장"}\n\n'
                f"제목: {title}\n내용: {strip_tags(content)[:1500]}"
            ),
        }],
    }
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "x-api-key": API_KEY,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read())
        txt = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        txt = txt.replace("```json", "").replace("```", "").strip()
        p = json.loads(txt)
        return {
            "summary": p.get("summary", ""),
            "takeaways": p.get("takeaways", []) if isinstance(p.get("takeaways"), list) else [],
            "idea": p.get("idea", ""),
        }
    except Exception as e:
        print(f"  ! 요약 실패: {title[:30]} ({e})")
        return {"summary": "(요약 생성 실패)", "takeaways": [], "idea": ""}


def main():
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=LOOKBACK_HOURS)
    collected = []
    seen = set()

    for src in SOURCES:
        if not src["rss"]:
            print(f"- 건너뜀(주소 없음): {src['source']}")
            continue
        print(f"- 수집: {src['source']}")
        for raw in read_feed(src):
            if not is_recent(raw["published"], cutoff):
                continue
            gid = raw["guid"] or raw["link"]
            if gid in seen:
                continue
            seen.add(gid)
            s = summarize(raw["title"], raw["content"])
            collected.append({
                "id": gid,
                "category": src["category"],
                "source": src["source"],
                "type": src["type"],
                "title": raw["title"],
                "url": raw["link"],
                "publishedAt": (parse_dt(raw["published"]) or dt.datetime.now(dt.timezone.utc)).isoformat(),
                "summary": s["summary"],
                "takeaways": s["takeaways"],
                "idea": s["idea"],
            })
            time.sleep(0.4)  # API 레이트리밋 여유

    collected.sort(key=lambda x: x["publishedAt"], reverse=True)
    feed = {"generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(), "items": collected}

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(feed, f, ensure_ascii=False, indent=2)
    print(f"\n완료: {len(collected)}건 → {OUT_PATH}")


if __name__ == "__main__":
    main()
