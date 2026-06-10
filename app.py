import os
import json
import logging
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
    "노동법개정",
    "고용노동부행정해석",
    "대법원노동판결",
    "노동위원회판정",
    "고용노동부지침",
    "산업재해판례",
    "부당해고판결",
    "노동조합파업",
    "삼성파업",
    "현대차노사",
    "최저임금고시",
    "중대재해처벌법",
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
            for a in articles[:30]
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
            max_tokens=3000,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = message.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw.strip())
        logger.info("✅ Claude API 요약 성공!")
        return result
    except Exception as e:
        logger.error(f"Claude API 오류: {e}")
        return _mock_summary(articles)

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

_cache = {}

def collect_and_summarize():
    logger.info("📰 뉴스 수집 시작...")
    today = date.today()
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

import threading
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
    return jsonify({"status": "ok", "api_key_set": bool(api_key), "api_key_preview": api_key[:12] + "..." if api_key else "없음"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
