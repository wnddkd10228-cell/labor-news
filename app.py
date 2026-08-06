import os
import json
import logging
import threading
from datetime import datetime, date, timedelta
from flask import Flask, render_template, jsonify, request, redirect, url_for, flash
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
import pytz

# .env 강제 로드
basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, ".env"), override=True)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-this")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

KST = pytz.timezone("Asia/Seoul")

# ── Supabase (REST API 직접 호출 - 가벼움) ────────────────────────────────────
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()
SUPABASE_ENABLED = bool(SUPABASE_URL and SUPABASE_KEY)

# ── 공인노무사 특화 키워드 ─────────────────────────────────────────────────────
DEFAULT_KEYWORDS = [
    "근로기준법",
    "남녀고용평등법",
    "기간제법",
    "노조법",
    "고용노동부",
    "노동판결",
    "노동조합파업",
    "근로시간",
    "평균임금",
    "통상임금",
    "연차휴가",
    "정년연장",
]

KEYWORDS_FILE = "keywords.json"

def load_keywords():
    if os.path.exists(KEYWORDS_FILE):
        try:
            with open(KEYWORDS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return DEFAULT_KEYWORDS

def save_keywords(keywords):
    with open(KEYWORDS_FILE, "w", encoding="utf-8") as f:
        json.dump(keywords, f, ensure_ascii=False, indent=2)

# ── 뉴스 수집 (최근 48시간) ───────────────────────────────────────────────────
def fetch_news(keywords):
    import feedparser
    from urllib.parse import quote
    from email.utils import parsedate_to_datetime

    articles = []
    seen_titles = set()
    cutoff = datetime.now(pytz.utc) - timedelta(hours=48)

    for keyword in keywords[:8]:
        try:
            encoded = quote(keyword)
            feed = feedparser.parse(
                f"https://news.google.com/rss/search?q={encoded}&hl=ko&gl=KR&ceid=KR:ko"
            )
            for entry in feed.entries[:3]:
                title = entry.get("title", "").strip()
                if not title or title in seen_titles:
                    continue

                # 날짜 필터 — 48시간 이내만
                published_str = entry.get("published", "")
                if published_str:
                    try:
                        pub_dt = parsedate_to_datetime(published_str)
                        if pub_dt.tzinfo is None:
                            pub_dt = pub_dt.replace(tzinfo=pytz.utc)
                        if pub_dt < cutoff:
                            continue
                    except Exception:
                        pass

                seen_titles.add(title)
                source = ""
                if hasattr(entry, "source"):
                    source = entry.source.get("title", "")
                articles.append({
                    "title": title,
                    "link": entry.get("link", "#"),
                    "source": source or "Google News",
                    "keyword": keyword,
                    "published": published_str
                })
        except Exception as e:
            logger.warning(f"키워드 '{keyword}' 수집 실패: {e}")

    logger.info(f"  → 최근 48시간 기사 {len(articles)}개 수집")
    return articles[:40]

# ── Claude AI 요약 ─────────────────────────────────────────────────────────────
def summarize_with_claude(articles, keywords):
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    logger.info(f"API 키 확인: {'있음 (' + api_key[:12] + '...)' if api_key else '없음'}")

    if not api_key:
        logger.warning("ANTHROPIC_API_KEY 없음 — 샘플 데이터 반환")
        return _mock_summary(articles)

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        articles_text = "\n\n".join([
            f"제목: {a['title']}\n출처: {a['source']}\n발행일: {a['published']}\n링크: {a['link']}"
            for a in articles[:20]
        ])

        today = datetime.now(KST).strftime("%Y년 %m월 %d일")

        prompt = f"""당신은 공인노무사(노무법인 소속)입니다. 오늘({today}) 수집된 최신 노동·인사 관련 뉴스를 공인노무사의 시각으로 분석하고 요약해주세요.

[수집 기사 목록 — 최근 48시간 이내]
{articles_text}

[요약 우선순위]
1순위: 노동관계법령 개정·입법예고·시행 (근로기준법, 산업안전보건법, 노조법, 중대재해처벌법 등)
2순위: 대법원·헌법재판소 노동 관련 주요 판결
3순위: 고용노동부 행정해석·지침·가이드·매뉴얼 신규 발표
4순위: 노동위원회 주요 판정례
5순위: 삼성·현대·LG·SK 등 대기업 노사 이슈, 파업·단체협약
6순위: 최저임금·통상임금·수당 관련 정책·판례
7순위: 중대재해·산업재해 기소·판결·행정처분

단순 채용공고, 홍보성 기사, 지역 단신은 제외하세요.

반드시 아래 JSON 형식으로만 응답 (마크다운 코드블록 없이 순수 JSON):
{{
  "headline": "오늘 공인노무사가 반드시 알아야 할 핵심 이슈 한줄 요약",
  "overview": "오늘의 노동법·인사노무 동향을 공인노무사 시각에서 2-3문장 요약",
  "categories": {{
    "legislation": "법령개정·입법예고 핵심 내용 (없으면 '해당 없음')",
    "court": "주요 판결·판정례 핵심 내용 (없으면 '해당 없음')",
    "admin": "고용노동부 행정해석·지침 핵심 내용 (없으면 '해당 없음')",
    "corporate": "주요 기업 노사이슈 핵심 내용 (없으면 '해당 없음')"
  }},
  "articles": [
    {{
      "category": "법령개정 또는 판례 또는 행정해석 또는 노사이슈 중 하나",
      "title": "기사 제목",
      "source": "출처",
      "link": "URL",
      "summary": "공인노무사 실무 관점에서 핵심 내용과 실무적 의미 2-3문장",
      "importance": "상 또는 중"
    }}
  ],
  "insight": "오늘 이슈 기반으로 공인노무사·노무담당자가 실무에서 주의할 점과 대응방안 3-4문장"
}}

articles는 우선순위 기준 중요한 5-8개만, importance 상인 것을 앞에 배치하세요."""

        message = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=8000,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = message.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            # 응답이 중간에 잘린 경우 복구 시도
            logger.warning("JSON이 잘려서 복구를 시도합니다...")
            result = _recover_json(raw)
            if result is None:
                raise

        logger.info("✅ Claude API 요약 성공!")
        return result
    except Exception as e:
        logger.error(f"Claude API 오류: {e}")
        return _mock_summary(articles)

def _recover_json(raw):
    """중간에 잘린 JSON을 최대한 복구"""
    import re
    # 완성된 article 객체들만 추출
    try:
        headline = re.search(r'"headline"\s*:\s*"([^"]*)"', raw)
        overview = re.search(r'"overview"\s*:\s*"([^"]*)"', raw)
        insight = re.search(r'"insight"\s*:\s*"([^"]*)"', raw)

        # 완성된 article 블록 찾기 (닫는 중괄호까지 있는 것만)
        articles = []
        for m in re.finditer(r'\{\s*"category"\s*:\s*"([^"]*)"\s*,\s*"title"\s*:\s*"([^"]*)"\s*,\s*"source"\s*:\s*"([^"]*)"\s*,\s*"link"\s*:\s*"([^"]*)"\s*,\s*"summary"\s*:\s*"([^"]*)"\s*,\s*"importance"\s*:\s*"([^"]*)"', raw):
            articles.append({
                "category": m.group(1), "title": m.group(2), "source": m.group(3),
                "link": m.group(4), "summary": m.group(5), "importance": m.group(6)
            })

        if not articles:
            return None

        return {
            "headline": headline.group(1) if headline else "오늘의 노동·인사 브리핑",
            "overview": overview.group(1) if overview else "",
            "categories": {"legislation": "해당 없음", "court": "해당 없음", "admin": "해당 없음", "corporate": "해당 없음"},
            "articles": articles,
            "insight": insight.group(1) if insight else ""
        }
    except Exception:
        return None

def _mock_summary(articles):
    return {
        "headline": "API 키 미설정 — 샘플 데이터입니다",
        "overview": "ANTHROPIC_API_KEY가 설정되지 않아 샘플 데이터가 표시됩니다.",
        "categories": {"legislation": "해당 없음", "court": "해당 없음", "admin": "해당 없음", "corporate": "해당 없음"},
        "articles": [{"category": "샘플", "title": a["title"], "source": a["source"], "link": a["link"], "summary": "API 키 설정 후 실제 요약이 표시됩니다.", "importance": "중"} for a in articles[:5]],
        "insight": "ANTHROPIC_API_KEY 환경변수를 설정하면 공인노무사 관점의 실무 인사이트를 제공합니다."
    }

def save_to_supabase(summary_data, collected_date):
    if not SUPABASE_ENABLED:
        return False
    try:
        import urllib.request
        url = f"{SUPABASE_URL}/rest/v1/news_summaries?on_conflict=collected_date"
        payload = json.dumps({
            "collected_date": str(collected_date),
            "headline": summary_data.get("headline", ""),
            "overview": summary_data.get("overview", ""),
            "items": summary_data.get("articles", []),
            "insight": summary_data.get("insight", ""),
            "created_at": datetime.now(KST).isoformat()
        }).encode("utf-8")
        req = urllib.request.Request(url, data=payload, method="POST", headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates"
        })
        urllib.request.urlopen(req, timeout=15)
        return True
    except Exception as e:
        logger.error(f"Supabase 저장 실패: {e}")
        return False

def load_from_supabase(target_date):
    if not SUPABASE_ENABLED:
        return None
    try:
        import urllib.request
        url = f"{SUPABASE_URL}/rest/v1/news_summaries?collected_date=eq.{target_date}&select=*"
        req = urllib.request.Request(url, headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}"
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data:
            row = data[0]
            items = row.get("items", [])
            row["articles"] = json.loads(items) if isinstance(items, str) else items
            return row
    except Exception as e:
        logger.error(f"Supabase 조회 실패: {e}")
    return None

def load_week_from_supabase(start_date, end_date):
    """주간(월~일) 브리핑을 한 번에 조회"""
    if not SUPABASE_ENABLED:
        return []
    try:
        import urllib.request
        url = (f"{SUPABASE_URL}/rest/v1/news_summaries"
               f"?collected_date=gte.{start_date}&collected_date=lte.{end_date}"
               f"&select=*&order=collected_date.asc")
        req = urllib.request.Request(url, headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}"
        })
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        for row in data:
            items = row.get("items", [])
            row["articles"] = json.loads(items) if isinstance(items, str) else items
        return data
    except Exception as e:
        logger.error(f"Supabase 주간 조회 실패: {e}")
        return []

def get_week_range(target=None):
    """해당 날짜가 속한 주의 월요일~일요일 반환"""
    if target is None:
        target = date.today()
    monday = target - timedelta(days=target.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday

def generate_reels_script(selected, week_label):
    """선택된 기사+코멘트로 90초 릴스 대본 생성"""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return {"error": "ANTHROPIC_API_KEY가 설정되지 않았습니다."}

    items_text = ""
    for i, s in enumerate(selected, 1):
        items_text += f"\n[{i}] 제목: {s.get('title','')}\n"
        items_text += f"    출처: {s.get('source','')}\n"
        items_text += f"    요약: {s.get('summary','')}\n"
        if s.get("comment"):
            items_text += f"    내 코멘트: {s.get('comment')}\n"

    prompt = f"""당신은 공인노무사의 SNS 콘텐츠 작가입니다.
아래는 {week_label} 주간 노동 뉴스 중 선별한 항목입니다.
이를 바탕으로 인스타그램 릴스/유튜브 쇼츠용 **90초 분량** 대본을 작성하세요.

[선별된 뉴스]
{items_text}

[작성 규칙]
- 전체 분량: 말하기 기준 90초 (한국어 약 280~330자 내외의 발화량)
- 구어체로, 실제로 말하듯이 자연스럽게
- 첫 3초 안에 시선을 잡는 후킹 문장으로 시작
- 각 뉴스는 "무슨 일이 있었나 → 실무상 의미" 순서로
- '내 코멘트'가 있으면 그 관점을 반드시 반영
- 전문용어는 쉽게 풀어서
- 마지막은 다음 주 예고 또는 팔로우 유도로 마무리

반드시 아래 JSON 형식으로만 응답 (마크다운 코드블록 없이 순수 JSON):
{{
  "title": "영상 제목 (25자 이내, 클릭 유도형)",
  "hook": "첫 3초 후킹 멘트 (한 문장)",
  "sections": [
    {{
      "time": "0:03-0:20",
      "topic": "다룰 뉴스 주제",
      "script": "실제 말할 대사",
      "caption": "화면에 띄울 자막 키워드 (10자 이내)"
    }}
  ],
  "outro": "마무리 멘트",
  "hashtags": ["해시태그5~8개"],
  "caption_text": "게시물 설명글 (150자 내외)"
}}

sections는 후킹 이후부터 아웃트로 전까지를 시간대별로 나누세요."""

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = message.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw.strip())
        logger.info("✅ 릴스 대본 생성 성공")
        return result
    except Exception as e:
        logger.error(f"대본 생성 오류: {e}")
        return {"error": str(e)}

_cache = {}

# ── 이메일 발송 (Resend API) ──────────────────────────────────────────────────
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "").strip()
MAIL_FROM = os.environ.get("MAIL_FROM", "onboarding@resend.dev").strip()
MAIL_TO = os.environ.get("MAIL_TO", "").strip()
EMAIL_ENABLED = bool(RESEND_API_KEY and MAIL_TO)

def _build_email_html(summary, today_str):
    cats = summary.get("categories", {})
    def cat_row(label, val):
        if not val or val == "해당 없음":
            return ""
        return f'<tr><td style="padding:8px 12px;font-weight:bold;color:#1a1a2e;white-space:nowrap;vertical-align:top">{label}</td><td style="padding:8px 12px;color:#444;line-height:1.6">{val}</td></tr>'

    articles_html = ""
    for a in summary.get("articles", []):
        star = "⭐ " if a.get("importance") == "상" else ""
        cat = a.get("category", "")
        articles_html += f"""
        <div style="border:1px solid #e0d8c5;border-radius:8px;padding:14px 16px;margin-bottom:12px">
          <div style="font-size:12px;color:#888;margin-bottom:4px">{star}[{cat}] {a.get('source','')}</div>
          <div style="font-size:16px;font-weight:bold;color:#1a1a2e;margin-bottom:6px;line-height:1.4">{a.get('title','')}</div>
          <div style="font-size:14px;color:#444;line-height:1.7">{a.get('summary','')}</div>
          <a href="{a.get('link','#')}" style="font-size:13px;color:#c0392b;text-decoration:none;display:inline-block;margin-top:8px">원문 보기 →</a>
        </div>"""

    insight = summary.get("insight", "")
    insight_html = ""
    if insight:
        insight_html = f"""
        <div style="background:#1a1a2e;color:#fff;border-radius:8px;padding:18px;margin-top:20px">
          <div style="font-size:13px;color:#a78bfa;margin-bottom:8px">💡 공인노무사 실무 인사이트</div>
          <div style="font-size:14px;line-height:1.8;color:#e0d8f5">{insight}</div>
        </div>"""

    return f"""<!DOCTYPE html><html><body style="margin:0;padding:0;background:#faf8f3">
    <div style="max-width:640px;margin:0 auto;padding:24px;font-family:Apple SD Gothic Neo,Malgun Gothic,sans-serif">
      <div style="text-align:center;background:#1a1a2e;color:#fff;border-radius:8px;padding:24px;margin-bottom:20px">
        <div style="font-size:13px;color:#aaa;letter-spacing:2px">DAILY LABOR LAW BRIEFING</div>
        <div style="font-size:24px;font-weight:bold;margin-top:8px">노동법·인사노무 브리핑</div>
        <div style="font-size:13px;color:#999;margin-top:8px">{today_str}</div>
      </div>
      <div style="background:#1a1a2e;color:#fff;border-radius:8px;padding:16px 20px;border-left:5px solid #c0392b;margin-bottom:16px">
        <div style="font-size:12px;color:#e74c3c;margin-bottom:6px">⚖️ 오늘의 핵심 이슈</div>
        <div style="font-size:17px;font-weight:bold;line-height:1.5">{summary.get('headline','')}</div>
      </div>
      <div style="background:#f0ece0;border-radius:8px;padding:14px 18px;margin-bottom:20px;font-size:14px;line-height:1.7;color:#444">
        <strong>오늘의 동향 —</strong> {summary.get('overview','')}
      </div>
      <table style="width:100%;border-collapse:collapse;background:#fff;border-radius:8px;margin-bottom:20px">{cat_row('📋 법령 개정', cats.get('legislation')) + cat_row('⚖️ 법원·노동위', cats.get('court')) + cat_row('🏛️ 행정해석', cats.get('admin')) + cat_row('🏢 기업 노사', cats.get('corporate'))}</table>
      <div style="font-size:16px;font-weight:bold;color:#1a1a2e;margin-bottom:12px">📌 주요 기사</div>
      {articles_html}
      {insight_html}
      <div style="text-align:center;margin-top:24px;font-size:12px;color:#aaa">
        공인노무사 노동법·인사노무 브리핑 · Claude AI 분석<br>
        <a href="https://labor-news.onrender.com" style="color:#aaa">웹에서 보기</a>
      </div>
    </div></body></html>"""

def send_email(summary, today_str):
    if not EMAIL_ENABLED:
        logger.info("이메일 미설정 — 발송 건너뜀")
        return False
    try:
        import urllib.request
        recipients = [m.strip() for m in MAIL_TO.split(",") if m.strip()]
        payload = json.dumps({
            "from": MAIL_FROM,
            "to": recipients,
            "subject": f"[노동법 브리핑] {today_str} {summary.get('headline','')[:30]}",
            "html": _build_email_html(summary, today_str)
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.resend.com/emails",
            data=payload, method="POST",
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json",
                "User-Agent": "labor-news/1.0"
            }
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            resp.read()
        logger.info(f"✅ 이메일 발송 성공 → {MAIL_TO}")
        return True
    except Exception as e:
        # 오류 본문도 함께 출력 (원인 파악용)
        try:
            err_body = e.read().decode("utf-8") if hasattr(e, "read") else ""
        except Exception:
            err_body = ""
        logger.error(f"이메일 발송 실패: {e} {err_body}")
        return False

def collect_and_summarize():
    logger.info("📰 뉴스 수집 시작...")
    today = date.today()
    today_str = today.strftime("%Y년 %m월 %d일")
    keywords = load_keywords()
    articles = fetch_news(keywords)

    if not articles:
        logger.warning("수집된 기사 없음")
        return

    summary = summarize_with_claude(articles, keywords)
    summary["collected_date"] = str(today)
    summary["article_count"] = len(articles)

    saved = save_to_supabase(summary, today)
    _cache[str(today)] = summary
    logger.info(f"요약 완료 (Supabase: {'성공' if saved else '로컬 캐시'})")

    # 샘플 데이터가 아닐 때만 이메일 발송
    if summary.get("headline") != "API 키 미설정 — 샘플 데이터입니다":
        send_email(summary, today_str)
    return summary

def get_summary(target_date=None):
    if target_date is None:
        target_date = date.today()
    key = str(target_date)
    if key in _cache:
        return _cache[key]
    result = load_from_supabase(target_date)
    if result:
        _cache[key] = result
    return result

# ── 스케줄러 ─────────────────────────────────────────────────────────────────
scheduler = BackgroundScheduler(timezone=KST)
scheduler.add_job(collect_and_summarize, "cron", hour=7, minute=30, id="daily_news", replace_existing=True)
scheduler.start()

# ── 라우트 ───────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    today = date.today()
    summary = get_summary(today)
    return render_template("index.html", summary=summary, today=today.strftime("%Y년 %m월 %d일"), today_raw=str(today))

@app.route("/api/summary")
def api_summary():
    target = request.args.get("date", str(date.today()))
    try:
        target_date = date.fromisoformat(target)
    except ValueError:
        return jsonify({"error": "날짜 형식 오류"}), 400
    return jsonify(get_summary(target_date) or {})

_collecting = {"status": "idle"}

def _background_collect():
    try:
        _collecting["status"] = "running"
        collect_and_summarize()
        _collecting["status"] = "done"
    except Exception as e:
        logger.error(f"백그라운드 수집 오류: {e}")
        _collecting["status"] = "error"

@app.route("/api/collect", methods=["POST"])
def api_collect():
    if _collecting["status"] == "running":
        return jsonify({"ok": True, "status": "running", "message": "이미 수집 중입니다"})
    t = threading.Thread(target=_background_collect, daemon=True)
    t.start()
    return jsonify({"ok": True, "status": "started", "message": "수집을 시작했습니다. 약 1분 후 새로고침하세요."})

@app.route("/api/status")
def api_status():
    return jsonify({"status": _collecting["status"]})

@app.route("/admin", methods=["GET", "POST"])
def admin():
    keywords = load_keywords()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "save_keywords":
            raw = request.form.get("keywords", "")
            new_kw = [k.strip() for k in raw.split("\n") if k.strip()]
            if new_kw:
                save_keywords(new_kw)
                keywords = new_kw
                flash("키워드가 저장되었습니다.", "success")
            else:
                flash("키워드를 입력해주세요.", "error")
        elif action == "collect_now":
            try:
                collect_and_summarize()
                flash("뉴스 수집이 완료되었습니다!", "success")
            except Exception as e:
                flash(f"수집 실패: {e}", "error")
        return redirect(url_for("admin"))

    next_run = scheduler.get_job("daily_news")
    next_run_str = next_run.next_run_time.strftime("%Y-%m-%d %H:%M") if next_run and next_run.next_run_time else "알 수 없음"
    return render_template("admin.html", keywords=keywords, next_run=next_run_str, supabase_connected=SUPABASE_ENABLED)

@app.route("/health")
def health():
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    return jsonify({
        "status": "ok",
        "api_key_set": bool(api_key),
        "api_key_preview": api_key[:12] + "..." if api_key else "없음",
        "email_enabled": EMAIL_ENABLED,
        "supabase_enabled": SUPABASE_ENABLED
    })

@app.route("/cron")
def cron():
    """UptimeRobot이 5분마다 호출. 아침 수집 시간대(KST 07:30~07:55)에만,
    그리고 오늘 아직 수집을 안 했을 때만 실제 수집을 실행한다."""
    now = datetime.now(KST)
    today = date.today()

    in_window = (now.hour == 7 and 30 <= now.minute <= 55)
    already_done = str(today) in _cache or (get_summary(today) is not None)

    if in_window and not already_done and _collecting["status"] != "running":
        t = threading.Thread(target=_background_collect, daemon=True)
        t.start()
        logger.info("⏰ 아침 자동 수집 트리거됨 (cron)")
        return jsonify({"triggered": True, "time": now.strftime("%H:%M")})

    return jsonify({
        "triggered": False,
        "time": now.strftime("%H:%M"),
        "in_window": in_window,
        "already_done": already_done
    })

@app.route("/api/test-email", methods=["POST", "GET"])
def test_email():
    today = date.today()
    summary = get_summary(today)
    if not summary:
        return jsonify({"ok": False, "error": "먼저 뉴스를 수집해주세요."}), 400
    if not EMAIL_ENABLED:
        return jsonify({"ok": False, "error": "이메일 환경변수가 설정되지 않았습니다."}), 400
    ok = send_email(summary, today.strftime("%Y년 %m월 %d일"))
    return jsonify({"ok": ok, "message": "발송 성공! 메일함을 확인하세요." if ok else "발송 실패 (로그 확인)"})

@app.route("/weekly")
def weekly():
    """주간 리뷰 화면 - 그 주 기사 모아보기 + 선택 + 코멘트"""
    week_param = request.args.get("week")
    if week_param:
        try:
            base = date.fromisoformat(week_param)
        except ValueError:
            base = date.today()
    else:
        base = date.today()

    monday, sunday = get_week_range(base)
    days = load_week_from_supabase(monday, sunday)

    # 날짜별 기사 정리
    week_data = []
    total = 0
    for row in days:
        arts = row.get("articles", []) or []
        total += len(arts)
        try:
            d = date.fromisoformat(str(row.get("collected_date")))
            label = d.strftime("%m/%d") + f" ({'월화수목금토일'[d.weekday()]})"
        except Exception:
            label = str(row.get("collected_date"))
        week_data.append({
            "date": str(row.get("collected_date")),
            "label": label,
            "headline": row.get("headline", ""),
            "articles": arts
        })

    prev_week = (monday - timedelta(days=7)).isoformat()
    next_week = (monday + timedelta(days=7)).isoformat()

    return render_template("weekly.html",
                           week_data=week_data,
                           total=total,
                           week_label=f"{monday.strftime('%Y년 %m월 %d일')} ~ {sunday.strftime('%m월 %d일')}",
                           monday=monday.isoformat(),
                           prev_week=prev_week,
                           next_week=next_week)

@app.route("/api/generate-script", methods=["POST"])
def api_generate_script():
    """선택한 기사 + 코멘트로 릴스 대본 생성"""
    data = request.get_json(silent=True) or {}
    selected = data.get("selected", [])
    week_label = data.get("week_label", "")

    if not selected:
        return jsonify({"ok": False, "error": "기사를 1개 이상 선택해주세요."}), 400

    result = generate_reels_script(selected, week_label)
    if "error" in result:
        return jsonify({"ok": False, "error": result["error"]}), 500
    return jsonify({"ok": True, "script": result})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
