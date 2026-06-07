"""
주제 2: 국제 유가 변동과 국내 주유소 가격 시차 상관관계 분석
- 데이터 로드 → SQLite DB 적재 → 쿼리 실행 → 결과 출력
"""

import sqlite3
import csv
import os

# ── 경로 설정 ──────────────────────────────────────────────────
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
DATA_DIR    = os.path.join(BASE_DIR, "data")
OIL_CSV     = os.path.join(DATA_DIR, "국제_원유가격20230101_20260604.csv")
GAS_CSV     = os.path.join(DATA_DIR, "과거_판매가격(주유소)20260507-20260606.csv")
DB_PATH     = os.path.join(BASE_DIR, "oil_gas.db")


# ── 1. DB 및 테이블 초기화 ────────────────────────────────────
def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS oil_price (
            price_date TEXT PRIMARY KEY,
            dubai      REAL,
            brent      REAL,
            wti        REAL
        );
        CREATE INDEX IF NOT EXISTS idx_oil_date ON oil_price(price_date);

        CREATE TABLE IF NOT EXISTS gas_station (
            station_id   TEXT PRIMARY KEY,
            station_name TEXT NOT NULL,
            address      TEXT,
            brand        TEXT
        );

        CREATE TABLE IF NOT EXISTS gas_price (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            station_id   TEXT NOT NULL,
            price_date   TEXT NOT NULL,
            product_type TEXT NOT NULL,
            sell_price   INTEGER NOT NULL,
            FOREIGN KEY (station_id) REFERENCES gas_station(station_id),
            UNIQUE (station_id, price_date, product_type)
        );
        CREATE INDEX IF NOT EXISTS idx_gas_date    ON gas_price(price_date);
        CREATE INDEX IF NOT EXISTS idx_gas_station ON gas_price(station_id);
    """)
    conn.commit()
    print("[DB] 테이블 초기화 완료")


# ── 2. 국제 유가 데이터 적재 ──────────────────────────────────
def load_oil_price(conn: sqlite3.Connection) -> None:
    """
    국제_원유가격 CSV 적재
    컬럼: 기간(예: 23년01월03일), Dubai, Brent, WTI
    → price_date를 YYYY-MM-DD 형식으로 변환
    """
    rows = []
    with open(OIL_CSV, encoding="cp949") as f:
        reader = csv.reader(f)
        next(reader)  # 헤더 스킵
        for row in reader:
            if len(row) < 4:
                continue
            try:
                raw = row[0].strip()  # 예: '23년01월03일'
                # 파싱: 앞 2자리=연도, 중간=월, 끝=일
                yy  = raw[:2]
                mm  = raw[3:5]
                dd  = raw[6:8]
                date_str = f"20{yy}-{mm}-{dd}"
                rows.append((
                    date_str,
                    float(row[1]) if row[1].strip() else None,
                    float(row[2]) if row[2].strip() else None,
                    float(row[3]) if row[3].strip() else None,
                ))
            except (ValueError, IndexError):
                continue

    conn.executemany("""
        INSERT OR IGNORE INTO oil_price (price_date, dubai, brent, wti)
        VALUES (?, ?, ?, ?)
    """, rows)
    conn.commit()
    print(f"[국제유가] {len(rows):,}건 적재 완료\n")


# ── 3. 주유소 판매가격 데이터 적재 ───────────────────────────
def load_gas_price(conn: sqlite3.Connection) -> None:
    """
    과거_판매가격(주유소) CSV 적재
    컬럼: 번호(ID), 상호, 사업자명, 주소, 기간(YYYYMMDD),
          표준(브랜드), 상품유형, (공백), 판매가격, 비교가격, ...
    2번째 줄은 기간 설명 줄 → 스킵
    """
    stations, prices = [], []

    with open(GAS_CSV, encoding="cp949") as f:
        reader = csv.reader(f)
        next(reader)  # 헤더 스킵
        next(reader)  # 기간 설명 줄 스킵

        for row in reader:
            if len(row) < 10:
                continue
            try:
                station_id   = row[0].strip()
                station_name = row[1].strip()
                address      = row[3].strip()
                brand        = row[5].strip()
                raw_date     = row[4].strip()          # YYYYMMDD
                price_date   = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"
                product_type = row[6].strip()          # 일반, 고급, 경유 등
                sell_price   = int(row[8]) if row[8].strip().isdigit() else None

                if sell_price is None or sell_price == 0:
                    continue

                stations.append((station_id, station_name, address, brand))
                prices.append((station_id, price_date, product_type, sell_price))
            except (ValueError, IndexError):
                continue

    conn.executemany("""
        INSERT OR IGNORE INTO gas_station (station_id, station_name, address, brand)
        VALUES (?, ?, ?, ?)
    """, stations)
    conn.executemany("""
        INSERT OR IGNORE INTO gas_price (station_id, price_date, product_type, sell_price)
        VALUES (?, ?, ?, ?)
    """, prices)
    conn.commit()
    print(f"[주유소] 주유소 {len(set(s[0] for s in stations)):,}개소 / 가격 {len(prices):,}건 적재 완료\n")


# ── 4. 쿼리 실행 ─────────────────────────────────────────────
def run_query_2a(conn: sqlite3.Connection) -> None:
    """쿼리 2-A: 브랜드별 국제 유가 상승 반응 속도 분석"""
    print("=" * 65)
    print("쿼리 2-A: 브랜드별 유가 상승 후 평균 반응 일수")
    print("=" * 65)

    sql = """
    WITH oil_rising AS (
        SELECT
            price_date,
            dubai,
            LAG(dubai) OVER (ORDER BY price_date)              AS prev_dubai,
            dubai - LAG(dubai) OVER (ORDER BY price_date)      AS dubai_change
        FROM oil_price
    ),
    price_reaction AS (
        SELECT
            gs.brand,
            gp_curr.station_id,
            JULIANDAY(gp_curr.price_date) - JULIANDAY(oil.price_date) AS lag_days,
            gp_curr.sell_price - gp_prev.sell_price                   AS price_change
        FROM oil_rising oil
        JOIN gas_price gp_curr
            ON  gp_curr.price_date >= oil.price_date
            AND gp_curr.price_date <= DATE(oil.price_date, '+7 days')
        JOIN gas_price gp_prev
            ON  gp_prev.station_id   = gp_curr.station_id
            AND gp_prev.price_date   = DATE(gp_curr.price_date, '-1 days')
            AND gp_prev.product_type = gp_curr.product_type
        JOIN gas_station gs ON gs.station_id = gp_curr.station_id
        WHERE oil.dubai_change > 0
          AND gp_curr.sell_price > gp_prev.sell_price
          AND gp_curr.product_type = '일반'
    )
    SELECT
        brand,
        COUNT(DISTINCT station_id)           AS station_count,
        ROUND(AVG(lag_days),   2)            AS avg_lag_days,
        ROUND(AVG(price_change), 1)          AS avg_price_increase
    FROM price_reaction
    GROUP BY brand
    ORDER BY avg_lag_days ASC
    """

    cur = conn.execute(sql)
    rows = cur.fetchall()
    if not rows:
        print("  (결과 없음 — 두 데이터의 날짜 범위가 겹치지 않을 수 있습니다)\n")
        return
    print(f"{'브랜드':<20} {'주유소수':>6} {'평균반응일':>10} {'평균인상폭(원)':>13}")
    print("-" * 55)
    for row in rows:
        print(f"{row[0]:<20} {row[1]:>6} {row[2]:>10} {row[3]:>13}")
    print()


def run_query_2b(conn: sqlite3.Connection) -> None:
    """쿼리 2-B: 유가 상승기 vs 하강기 주유소 가격 반응 비대칭성"""
    print("=" * 65)
    print("쿼리 2-B: 유가 국면별 주유소 가격 변동 비교 (상승기 vs 하강기)")
    print("=" * 65)

    sql = """
    WITH weekly_oil AS (
        SELECT
            price_date,
            dubai,
            AVG(dubai) OVER (
                ORDER BY price_date
                ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
            ) AS avg_7d,
            LAG(
                AVG(dubai) OVER (
                    ORDER BY price_date
                    ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
                ), 7
            ) OVER (ORDER BY price_date) AS prev_7d
        FROM oil_price
    ),
    oil_direction AS (
        SELECT
            price_date,
            CASE
                WHEN avg_7d > prev_7d THEN '상승기'
                WHEN avg_7d < prev_7d THEN '하강기'
                ELSE '보합'
            END AS oil_phase
        FROM weekly_oil
        WHERE prev_7d IS NOT NULL
    ),
    station_reaction AS (
        SELECT
            od.oil_phase,
            gs.brand,
            gp_curr.sell_price - gp_prev.sell_price AS daily_change
        FROM oil_direction od
        JOIN gas_price gp_curr ON gp_curr.price_date = od.price_date
        JOIN gas_price gp_prev
            ON  gp_prev.station_id   = gp_curr.station_id
            AND gp_prev.price_date   = DATE(gp_curr.price_date, '-1 days')
            AND gp_prev.product_type = gp_curr.product_type
        JOIN gas_station gs ON gs.station_id = gp_curr.station_id
        WHERE gp_curr.product_type = '일반'
    )
    SELECT
        oil_phase,
        brand,
        COUNT(*)                                                         AS obs_count,
        ROUND(AVG(daily_change), 2)                                      AS avg_daily_change,
        ROUND(AVG(CASE WHEN daily_change > 0 THEN daily_change END), 2)  AS avg_increase,
        ROUND(AVG(CASE WHEN daily_change < 0 THEN daily_change END), 2)  AS avg_decrease,
        SUM(CASE WHEN daily_change > 0 THEN 1 ELSE 0 END)                AS days_up,
        SUM(CASE WHEN daily_change < 0 THEN 1 ELSE 0 END)                AS days_down
    FROM station_reaction
    GROUP BY oil_phase, brand
    ORDER BY oil_phase, avg_daily_change DESC
    """

    cur = conn.execute(sql)
    rows = cur.fetchall()
    if not rows:
        print("  (결과 없음 — 두 데이터의 날짜 범위가 겹치지 않을 수 있습니다)\n")
        return
    print(f"{'국면':<6} {'브랜드':<18} {'건수':>5} {'일변동':>7} {'인상폭':>7} {'인하폭':>7} {'상승일':>6} {'하락일':>6}")
    print("-" * 70)
    for row in rows:
        print(f"{row[0]:<6} {row[1]:<18} {row[2]:>5} {row[3]:>7} {str(row[4]):>7} {str(row[5]):>7} {row[6]:>6} {row[7]:>6}")
    print()


# ── 메인 ─────────────────────────────────────────────────────
if __name__ == "__main__":
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")

    init_db(conn)
    load_oil_price(conn)
    load_gas_price(conn)
    run_query_2a(conn)
    run_query_2b(conn)

    conn.close()
    print("완료.")
