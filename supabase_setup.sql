-- Supabase에서 실행할 SQL
-- Supabase 대시보드 → SQL Editor → 아래 코드 붙여넣기 후 실행

CREATE TABLE IF NOT EXISTS news_summaries (
  id            BIGSERIAL PRIMARY KEY,
  collected_date DATE UNIQUE NOT NULL,
  headline      TEXT,
  overview      TEXT,
  items         JSONB,
  insight       TEXT,
  created_at    TIMESTAMPTZ DEFAULT NOW()
);

-- 날짜 기준 빠른 조회를 위한 인덱스
CREATE INDEX IF NOT EXISTS idx_news_summaries_date
  ON news_summaries (collected_date DESC);

-- 확인용 조회
SELECT * FROM news_summaries ORDER BY collected_date DESC LIMIT 5;
