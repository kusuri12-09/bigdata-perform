-- ============================================================
-- 주제 1: 기상 조건에 따른 타슈 대여 패턴 분석
-- 대상: 대전광역시 / 기간: 2026년 1~3월
-- ============================================================


-- ------------------------------------------------------------
-- 1. 테이블 생성 (DDL)
-- ------------------------------------------------------------

-- 대여소 마스터 테이블
CREATE TABLE IF NOT EXISTS rental_station (
    station_id   VARCHAR(20)  PRIMARY KEY,
    station_name VARCHAR(100) NOT NULL,
    district     VARCHAR(20)  NOT NULL,
    dong         VARCHAR(30)  NOT NULL,
    address      VARCHAR(200),
    x_coord      DECIMAL(12,6),
    y_coord      DECIMAL(12,6)
);

-- 기상 관측 데이터 테이블 (ASOS 시간별)
CREATE TABLE IF NOT EXISTS weather (
    id            INT          AUTO_INCREMENT PRIMARY KEY,
    obs_datetime  DATETIME     NOT NULL,
    temperature   DECIMAL(5,1),
    precipitation DECIMAL(5,1) DEFAULT 0.0,
    wind_speed    DECIMAL(5,1),
    wind_dir      SMALLINT,
    humidity      TINYINT,
    feel_temp     DECIMAL(5,1),
    pressure      DECIMAL(7,1),
    INDEX idx_datetime  (obs_datetime),
    INDEX idx_precip    (precipitation)
);

-- 타슈 대여이력 테이블
CREATE TABLE IF NOT EXISTS rental (
    rental_id         VARCHAR(20) NOT NULL,
    rental_datetime   DATETIME    NOT NULL,
    rental_station_id VARCHAR(20) NOT NULL,
    return_datetime   DATETIME    NOT NULL,
    return_station_id VARCHAR(20) NOT NULL,
    use_time_min      SMALLINT    NOT NULL,
    use_distance_km   DECIMAL(7,2),
    PRIMARY KEY (rental_id, rental_datetime),
    FOREIGN KEY (rental_station_id) REFERENCES rental_station(station_id),
    FOREIGN KEY (return_station_id) REFERENCES rental_station(station_id),
    INDEX idx_rental_dt (rental_datetime),
    INDEX idx_rental_st (rental_station_id)
);


-- ------------------------------------------------------------
-- 2. 쿼리 1-A: 강수량 기준 시간당 평균 자전거 대여량 비교
--    (JOIN + GROUP BY)
--    목적: 강수량 조건별(없음 / 10mm 미만 / 10mm 이상)
--          시간당 평균 대여 건수를 비교
-- ------------------------------------------------------------

SELECT
    cat.rain_category,
    COUNT(r.rental_id)                               AS total_rentals,
    COUNT(DISTINCT DATE(w.obs_datetime))             AS total_days,
    ROUND(
        COUNT(r.rental_id)
        / COUNT(DISTINCT DATE(w.obs_datetime))
        / 24.0,
        2
    )                                                AS avg_hourly_rentals
FROM weather w
LEFT JOIN rental r
    ON  DATE(r.rental_datetime) = DATE(w.obs_datetime)
    AND HOUR(r.rental_datetime) = HOUR(w.obs_datetime)
CROSS JOIN LATERAL (
    SELECT
        CASE
            WHEN w.precipitation >= 10 THEN '강우 (10mm 이상)'
            WHEN w.precipitation >  0  THEN '약한 강우 (10mm 미만)'
            ELSE                            '강수 없음'
        END AS rain_category
) AS cat
GROUP BY
    cat.rain_category
ORDER BY
    avg_hourly_rentals DESC;


-- ------------------------------------------------------------
-- 3. 쿼리 1-B: 폭염 기간 대여량 급감 대여소 상위 5곳 추출
--    (WITH CTE + JOIN + GROUP BY)
--    목적: 체감온도 35°C 이상 폭염 구간과 정상 기간의
--          대여소별 대여량 감소율을 비교하여 상위 5곳 추출
-- ------------------------------------------------------------

-- Step 1: 정상 기간(체감온도 35°C 미만) 대여소별 일평균 대여량
WITH normal_period AS (
    SELECT
        r.rental_station_id,
        COUNT(r.rental_id)
            / NULLIF(COUNT(DISTINCT DATE(w.obs_datetime)), 0) AS daily_avg_normal
    FROM rental r
    JOIN weather w
        ON  DATE(r.rental_datetime) = DATE(w.obs_datetime)
        AND HOUR(r.rental_datetime) = HOUR(w.obs_datetime)
    WHERE w.feel_temp < 35
    GROUP BY r.rental_station_id
),

-- Step 2: 폭염 기간(체감온도 35°C 이상) 대여소별 일평균 대여량
heatwave_period AS (
    SELECT
        r.rental_station_id,
        COUNT(r.rental_id)
            / NULLIF(COUNT(DISTINCT DATE(w.obs_datetime)), 0) AS daily_avg_heatwave
    FROM rental r
    JOIN weather w
        ON  DATE(r.rental_datetime) = DATE(w.obs_datetime)
        AND HOUR(r.rental_datetime) = HOUR(w.obs_datetime)
    WHERE w.feel_temp >= 35
    GROUP BY r.rental_station_id
)

-- Step 3: 감소율 계산 후 상위 5개 대여소 추출
SELECT
    rs.station_id,
    rs.station_name,
    rs.district,
    rs.dong,
    ROUND(np.daily_avg_normal,   2) AS avg_normal,
    ROUND(hp.daily_avg_heatwave, 2) AS avg_heatwave,
    ROUND(
        (np.daily_avg_normal - hp.daily_avg_heatwave)
        / NULLIF(np.daily_avg_normal, 0) * 100,
        1
    )                               AS drop_rate_pct
FROM normal_period np
JOIN heatwave_period hp
    ON np.rental_station_id = hp.rental_station_id
JOIN rental_station rs
    ON np.rental_station_id = rs.station_id
ORDER BY drop_rate_pct DESC
LIMIT 5;
