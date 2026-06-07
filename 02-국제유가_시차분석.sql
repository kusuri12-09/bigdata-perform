-- ============================================================
-- 주제 2: 국제 유가 변동과 국내 주유소 가격 시차 상관관계 분석
-- 대상: 대전광역시 주유소
-- 국제유가: 2023.01.03 ~ 2026.06.04 / 주유소: 2026.05.07 ~ 2026.06.06
-- ============================================================


-- ------------------------------------------------------------
-- 1. 테이블 생성 (DDL)
-- ------------------------------------------------------------

-- 국제 유가 테이블
CREATE TABLE IF NOT EXISTS oil_price (
    price_date DATE        PRIMARY KEY,
    dubai      DECIMAL(8,2),
    brent      DECIMAL(8,2),
    wti        DECIMAL(8,2),
    INDEX idx_date (price_date)
);

-- 주유소 마스터 테이블
CREATE TABLE IF NOT EXISTS gas_station (
    station_id   VARCHAR(20)  PRIMARY KEY,
    station_name VARCHAR(100) NOT NULL,
    address      VARCHAR(200),
    brand        VARCHAR(30)
);

-- 주유소 일별 판매가격 테이블
CREATE TABLE IF NOT EXISTS gas_price (
    id           INT         AUTO_INCREMENT PRIMARY KEY,
    station_id   VARCHAR(20) NOT NULL,
    price_date   DATE        NOT NULL,
    product_type VARCHAR(20) NOT NULL,
    sell_price   INT         NOT NULL,
    FOREIGN KEY (station_id) REFERENCES gas_station(station_id),
    INDEX idx_date    (price_date),
    INDEX idx_station (station_id),
    UNIQUE KEY uq_station_date_type (station_id, price_date, product_type)
);


-- ------------------------------------------------------------
-- 2. 쿼리 2-A: 브랜드별 유가 상승 반응 속도 분석
--    (WITH CTE + JOIN + GROUP BY + AVG)
--    목적: 국제 유가 상승 후 7일 이내 가격을 올린 주유소를
--          브랜드별로 집계하여 평균 반응 일수 비교
-- ------------------------------------------------------------

-- Step 1: 전일 대비 Dubai 유가 상승일 추출
WITH oil_rising AS (
    SELECT
        price_date,
        dubai,
        LAG(dubai) OVER (ORDER BY price_date)                AS prev_dubai,
        dubai - LAG(dubai) OVER (ORDER BY price_date)        AS dubai_change
    FROM oil_price
),

-- Step 2: 유가 상승 후 7일 이내에 판매가를 올린 주유소 추출
price_reaction AS (
    SELECT
        gs.brand,
        gp_curr.station_id,
        gp_curr.price_date                              AS reaction_date,
        oil.price_date                                  AS oil_rise_date,
        DATEDIFF(gp_curr.price_date, oil.price_date)    AS lag_days,
        gp_curr.sell_price - gp_prev.sell_price         AS price_change
    FROM oil_rising oil
    JOIN gas_price gp_curr
        ON gp_curr.price_date BETWEEN oil.price_date
                                  AND DATE_ADD(oil.price_date, INTERVAL 7 DAY)
    JOIN gas_price gp_prev
        ON  gp_prev.station_id   = gp_curr.station_id
        AND gp_prev.price_date   = DATE_SUB(gp_curr.price_date, INTERVAL 1 DAY)
        AND gp_prev.product_type = gp_curr.product_type
    JOIN gas_station gs
        ON gs.station_id = gp_curr.station_id
    WHERE oil.dubai_change > 0
      AND gp_curr.sell_price > gp_prev.sell_price
      AND gp_curr.product_type = '일반'
)

-- Step 3: 브랜드별 평균 반응 일수 및 평균 인상폭 산출
SELECT
    brand,
    COUNT(DISTINCT station_id)  AS station_count,
    ROUND(AVG(lag_days),  2)    AS avg_lag_days,
    ROUND(AVG(price_change), 1) AS avg_price_increase
FROM price_reaction
GROUP BY brand
ORDER BY avg_lag_days ASC;


-- ------------------------------------------------------------
-- 3. 쿼리 2-B: 유가 상승기 vs 하강기 주유소 가격 반응 비교
--    (WITH CTE + 윈도우 함수 AVG OVER + CASE + GROUP BY)
--    목적: 유가 국면(상승기/하강기/보합)별 주유소 가격 변동 비교
--          → "로켓과 깃털" 비대칭성 검증
-- ------------------------------------------------------------

-- Step 1: 7일 이동평균으로 유가 방향(상승기/하강기/보합) 분류
WITH weekly_oil AS (
    SELECT
        price_date,
        dubai,
        AVG(dubai) OVER (
            ORDER BY price_date
            ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
        )                                              AS avg_7d_dubai,
        LAG(
            AVG(dubai) OVER (
                ORDER BY price_date
                ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
            ), 7
        ) OVER (ORDER BY price_date)                   AS prev_7d_dubai
    FROM oil_price
),

oil_direction AS (
    SELECT
        price_date,
        dubai,
        CASE
            WHEN avg_7d_dubai > prev_7d_dubai THEN '상승기'
            WHEN avg_7d_dubai < prev_7d_dubai THEN '하강기'
            ELSE '보합'
        END AS oil_phase
    FROM weekly_oil
    WHERE prev_7d_dubai IS NOT NULL
),

-- Step 2: 유가 국면별 주유소 전일 대비 가격 변동 집계
station_reaction AS (
    SELECT
        od.oil_phase,
        gp_curr.station_id,
        gs.brand,
        gp_curr.price_date,
        gp_curr.sell_price - gp_prev.sell_price AS daily_change
    FROM oil_direction od
    JOIN gas_price gp_curr
        ON gp_curr.price_date = od.price_date
    JOIN gas_price gp_prev
        ON  gp_prev.station_id   = gp_curr.station_id
        AND gp_prev.price_date   = DATE_SUB(gp_curr.price_date, INTERVAL 1 DAY)
        AND gp_prev.product_type = gp_curr.product_type
    JOIN gas_station gs
        ON gs.station_id = gp_curr.station_id
    WHERE gp_curr.product_type = '일반'
)

-- Step 3: 유가 국면 × 브랜드별 평균 가격 변동 및 비대칭성 지표 산출
SELECT
    oil_phase,
    brand,
    COUNT(*)                                                        AS obs_count,
    ROUND(AVG(daily_change), 2)                                     AS avg_daily_change,
    ROUND(AVG(CASE WHEN daily_change > 0 THEN daily_change END), 2) AS avg_increase_when_rising,
    ROUND(AVG(CASE WHEN daily_change < 0 THEN daily_change END), 2) AS avg_decrease_when_falling,
    SUM(CASE WHEN daily_change > 0 THEN 1 ELSE 0 END)               AS days_increased,
    SUM(CASE WHEN daily_change < 0 THEN 1 ELSE 0 END)               AS days_decreased
FROM station_reaction
GROUP BY oil_phase, brand
ORDER BY oil_phase, avg_daily_change DESC;
