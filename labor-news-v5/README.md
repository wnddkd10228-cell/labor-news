# 📰 노동·인사 뉴스 브리핑 자동화 앱

매일 오전 7:30, 인사/노무/노동 관련 뉴스를 자동 수집하고 Claude AI로 요약해주는 웹 앱입니다.

---

## 📁 파일 구조

```
labor-news/
│
├── app.py                 ← 핵심 코드 (Flask 서버 + 스케줄러 + AI 요약)
├── requirements.txt       ← 설치할 패키지 목록
├── Procfile               ← Render 배포용 실행 명령
├── .env.example           ← 환경변수 예시 파일
├── .gitignore             ← Git에 올리면 안 되는 파일 목록
├── supabase_setup.sql     ← Supabase 테이블 생성 SQL
│
└── templates/
    ├── index.html         ← 메인 화면 (오늘의 브리핑)
    └── admin.html         ← 관리자 화면 (키워드 관리)
```

---

## 🚀 로컬에서 실행하기 (단계별)

### 1단계 · Python 설치 확인

터미널(또는 명령 프롬프트)을 열고 입력:
```bash
python --version
# Python 3.10 이상이면 OK. 없으면 https://python.org 에서 설치
```

### 2단계 · 프로젝트 폴더로 이동

```bash
cd labor-news
```

### 3단계 · 가상환경 만들기 (선택하지 않아도 되지만 권장)

```bash
# macOS / Linux
python -m venv venv
source venv/bin/activate

# Windows
python -m venv venv
venv\Scripts\activate
```

### 4단계 · 패키지 설치

```bash
pip install -r requirements.txt
```

### 5단계 · 환경변수 설정

`.env.example` 파일을 복사해서 `.env` 파일을 만드세요:

```bash
# macOS / Linux
cp .env.example .env

# Windows
copy .env.example .env
```

그런 다음 `.env` 파일을 메모장(또는 VS Code)으로 열고 실제 값 입력:

```
ANTHROPIC_API_KEY=sk-ant-실제키입력   ← 필수!
SECRET_KEY=아무_랜덤_문자열_입력       ← 필수!
SUPABASE_URL=...                       ← 선택 (없어도 실행됨)
SUPABASE_KEY=...                       ← 선택
```

> 💡 **Anthropic API 키 발급 방법**
> 1. https://console.anthropic.com 접속
> 2. 회원가입 / 로그인
> 3. "API Keys" 메뉴 → "Create Key"
> 4. 발급된 키(`sk-ant-...`)를 `.env`에 붙여넣기

### 6단계 · 서버 실행

```bash
python app.py
```

브라우저에서 http://localhost:5000 접속하면 메인 화면이 보입니다!

### 7단계 · 뉴스 수집 테스트

- 메인 화면의 **"🔄 지금 뉴스 수집하기"** 버튼 클릭
- 약 30초~1분 후 뉴스가 표시되면 성공!

---

## 🗄️ Supabase 설정 (선택 사항)

Supabase를 연결하면 수집된 뉴스가 클라우드 DB에 저장되어  
서버를 재시작해도 데이터가 유지됩니다.

### 1단계 · Supabase 프로젝트 생성

1. https://supabase.com → "Start your project"
2. GitHub 계정으로 로그인
3. "New project" → 이름 입력 → "Create new project"

### 2단계 · 테이블 생성

1. 좌측 메뉴 → **SQL Editor**
2. `supabase_setup.sql` 파일 내용 전체 복사
3. SQL Editor에 붙여넣기 → **"Run"** 클릭

### 3단계 · API 키 가져오기

1. 좌측 메뉴 → **Settings** → **API**
2. `Project URL` 복사 → `.env`의 `SUPABASE_URL`에 입력
3. `anon public` 키 복사 → `.env`의 `SUPABASE_KEY`에 입력

---

## ☁️ Render에 배포하기

무료로 인터넷에 공개할 수 있습니다!

### 1단계 · GitHub에 코드 올리기

```bash
git init
git add .
git commit -m "첫 배포"
git branch -M main
git remote add origin https://github.com/계정명/labor-news.git
git push -u origin main
```

> ⚠️ `.gitignore`에 `.env`가 포함되어 있어 비밀 키는 자동으로 제외됩니다.

### 2단계 · Render 계정 만들기

1. https://render.com → "Get Started for Free"
2. GitHub 계정으로 로그인

### 3단계 · 웹 서비스 생성

1. Dashboard → **"New +"** → **"Web Service"**
2. GitHub 저장소 선택
3. 설정:
   - **Name**: `labor-news` (원하는 이름)
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app --bind 0.0.0.0:$PORT`
4. **"Create Web Service"** 클릭

### 4단계 · 환경변수 설정

Render 대시보드 → 해당 서비스 → **"Environment"** 탭:

| Key | Value |
|-----|-------|
| `ANTHROPIC_API_KEY` | sk-ant-... |
| `SUPABASE_URL` | https://xxx.supabase.co |
| `SUPABASE_KEY` | eyJ... |
| `SECRET_KEY` | 랜덤문자열 |

**"Save Changes"** 클릭 → 자동 재배포 완료!

> 🎉 배포가 완료되면 `https://labor-news.onrender.com` 같은 URL이 생성됩니다.

---

## ⏰ 자동 수집 관련 참고사항

- **로컬 실행**: `python app.py`로 실행 중일 때만 스케줄러가 동작합니다
- **Render 무료 플랜**: 15분 동안 요청이 없으면 서버가 잠들 수 있습니다
  - 해결책: [UptimeRobot](https://uptimerobot.com) 무료 서비스로 15분마다 핑 전송 설정
  - UptimeRobot → "Add New Monitor" → HTTP(s) → URL 입력 → 15분 간격

---

## 🔧 자주 묻는 질문

**Q: 뉴스가 수집되지 않아요**  
A: `ANTHROPIC_API_KEY`가 `.env`에 올바르게 입력되었는지 확인하세요. 인터넷 연결도 확인해주세요.

**Q: 키워드를 바꾸고 싶어요**  
A: http://localhost:5000/admin 접속 → 키워드 수정 → 저장

**Q: Supabase 없이도 되나요?**  
A: 네! Supabase 없이도 실행됩니다. 다만 서버 재시작 시 당일 데이터는 초기화됩니다.

**Q: 뉴스 수집이 너무 느려요**  
A: 구글 뉴스 RSS를 사용하며 키워드당 약 3초 소요됩니다. 키워드 수를 줄이면 빨라집니다.

---

## 📝 기술 스택

| 구분 | 기술 |
|------|------|
| 백엔드 | Python + Flask |
| AI 요약 | Anthropic Claude API |
| 뉴스 수집 | Google News RSS (feedparser) |
| 스케줄러 | APScheduler |
| 데이터베이스 | Supabase (PostgreSQL) |
| 배포 | Render |

---

Made with ❤️ for HR professionals
