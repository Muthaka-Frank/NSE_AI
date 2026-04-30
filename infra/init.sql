CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS stocks (
    ticker     VARCHAR(10)  PRIMARY KEY,
    name       VARCHAR(100) NOT NULL,
    sector     VARCHAR(50),
    currency   VARCHAR(5)   DEFAULT 'KES',
    created_at TIMESTAMPTZ  DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS price_history (
    time       TIMESTAMPTZ  NOT NULL,
    ticker     VARCHAR(10)  NOT NULL REFERENCES stocks(ticker),
    open       NUMERIC(12,4),
    high       NUMERIC(12,4),
    low        NUMERIC(12,4),
    close      NUMERIC(12,4),
    volume     BIGINT,
    change_pct NUMERIC(8,4)
);

SELECT create_hypertable('price_history', 'time', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_price_ticker ON price_history (ticker, time DESC);

CREATE TABLE IF NOT EXISTS news_articles (
    id              SERIAL       PRIMARY KEY,
    title           TEXT         NOT NULL,
    summary         TEXT,
    url             TEXT,
    source          VARCHAR(100),
    published_at    TIMESTAMPTZ,
    sentiment_label VARCHAR(10),
    sentiment_score NUMERIC(5,3),
    fetched_at      TIMESTAMPTZ  DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS news_tickers (
    news_id INT REFERENCES news_articles(id) ON DELETE CASCADE,
    ticker  VARCHAR(10) REFERENCES stocks(ticker),
    PRIMARY KEY (news_id, ticker)
);

CREATE TABLE IF NOT EXISTS signals (
    id              SERIAL       PRIMARY KEY,
    ticker          VARCHAR(10)  REFERENCES stocks(ticker),
    direction       VARCHAR(10),
    confidence      NUMERIC(5,3),
    signal_strength VARCHAR(10),
    price_at_signal NUMERIC(12,4),
    price_target    NUMERIC(12,4),
    risk_level      VARCHAR(10),
    reasoning       JSONB,
    generated_at    TIMESTAMPTZ  DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS users (
    id         SERIAL       PRIMARY KEY,
    email      VARCHAR(150) UNIQUE NOT NULL,
    phone      VARCHAR(20),
    created_at TIMESTAMPTZ  DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS watchlists (
    user_id  INT REFERENCES users(id) ON DELETE CASCADE,
    ticker   VARCHAR(10) REFERENCES stocks(ticker),
    added_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (user_id, ticker)
);

INSERT INTO stocks (ticker, name, sector) VALUES
    ('SCOM', 'Safaricom PLC',           'Telecommunications'),
    ('EQTY', 'Equity Group Holdings',   'Banking'),
    ('KCB',  'KCB Group PLC',           'Banking'),
    ('COOP', 'Co-operative Bank',       'Banking'),
    ('EABL', 'East African Breweries',  'Consumer Staples'),
    ('BAT',  'BAT Kenya',               'Consumer Staples'),
    ('KPLC', 'Kenya Power and Lighting','Energy'),
    ('ABSA', 'Absa Bank Kenya',         'Banking'),
    ('NCBA', 'NCBA Group PLC',          'Banking'),
    ('STND', 'Standard Chartered Kenya','Banking'),
    ('BAMB', 'Bamburi Cement',          'Manufacturing'),
    ('KENR', 'Kenya Re-Insurance',      'Insurance'),
    ('JUB',  'Jubilee Holdings',        'Insurance'),
    ('SBIC', 'Stanbic Holdings',        'Banking'),
    ('HFCK', 'HF Group',               'Banking')
ON CONFLICT (ticker) DO NOTHING;
