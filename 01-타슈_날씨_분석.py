"""
주제 1: 기상 조건에 따른 타슈 대여 패턴 분석
- 데이터 로드 → SQLite DB 적재 → 쿼리 실행 → 결과 출력
"""

import sqlite3
import zipfile
import csv
import io
import glob
import os

# ── 경로 설정 ──────────────────────────────────────────────────
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
DATA_DIR    = os.path.join(BASE_DIR, "data")
TASHU_DIR   = os.path.join(DATA_DIR, "대전교통공사_대전시 공영자전거 타슈 대여이력 정보_20260331")
ASOS_DIR    = os.path.join(DATA_DIR, "기상데이터ASOS")
DB_PATH     = os.path.join(BASE_DIR, "tashu_weather.db")


# ── 1. DB 및 테이블 초기화 ────────────────────────────────────
def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS rental_station (
            station_id   TEXT PRIMARY KEY,
            station_name TEXT NOT NULL,
            district     TEXT NOT NULL,
            dong         TEXT NOT NULL,
            address      TEXT,
            x_coord      REAL,
            y_coord      REAL
        );

        CREATE TABLE IF NOT EXISTS weather (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            obs_datetime  TEXT NOT NULL,
            temperature   REAL,
            precipitation REAL DEFAULT 0.0,
            wind_speed    REAL,
            wind_dir      INTEGER,
            humidity      INTEGER,
            feel_temp     REAL,
            pressure      REAL
        );
        CREATE INDEX IF NOT EXISTS idx_weather_dt     ON weather(obs_datetime);
        CREATE INDEX IF NOT EXISTS idx_weather_precip ON weather(precipitation);

        CREATE TABLE IF NOT EXISTS rental (
            rental_id         TEXT NOT NULL,
            rental_datetime   TEXT NOT NULL,
            rental_station_id TEXT NOT NULL,
            return_datetime   TEXT NOT NULL,
            return_station_id TEXT NOT NULL,
            use_time_min      INTEGER NOT NULL,
            use_distance_km   REAL,
            PRIMARY KEY (rental_id, rental_datetime),
            FOREIGN KEY (rental_station_id) REFERENCES rental_station(station_id),
            FOREIGN KEY (return_station_id) REFERENCES rental_station(station_id)
        );
        CREATE INDEX IF NOT EXISTS idx_rental_dt ON rental(rental_datetime);
        CREATE INDEX IF NOT EXISTS idx_rental_st ON rental(rental_station_id);
    """)
    conn.commit()
    print("[DB] 테이블 초기화 완료")


# ── 2. ASOS 기상 데이터 적재 ──────────────────────────────────
def load_weather(conn: sqlite3.Connection) -> None:
    """
    기상데이터ASOS 폴더의 ZIP 파일(분 단위 MI)을 읽어 weather 테이블에 적재.
    컬럼 순서: 지점, 일시, 기온, 강수량, 풍속, 풍향, 습도, 현지기압,
               이슬점온도, 해면기압, 지면기압, ..., 실황온도(23번째 컬럼)
    """
    zip_files = sorted(glob.glob(os.path.join(ASOS_DIR, "SURFACE_ASOS_133_MI_*.zip")))
    total = 0

    for zpath in zip_files:
        with zipfile.ZipFile(zpath) as z:
            name = z.namelist()[0]
            with z.open(name) as f:
                reader = csv.reader(io.TextIOWrapper(f, encoding="euc-kr"))
                next(reader)  # 헤더 스킵
                rows = []
                for row in reader:
                    if len(row) < 23:
                        continue
                    try:
                        rows.append((
                            row[1].strip(),                          # obs_datetime
                            float(row[2])  if row[2].strip() else None,  # temperature
                            float(row[3])  if row[3].strip() else 0.0,   # precipitation
                            float(row[4])  if row[4].strip() else None,  # wind_speed
                            int(row[5])    if row[5].strip() else None,  # wind_dir
                            int(row[6])    if row[6].strip() else None,  # humidity
                            float(row[22]) if row[22].strip() else None, # feel_temp (실황온도)
                            float(row[8])  if row[8].strip() else None,  # pressure
                        ))
                    except (ValueError, IndexError):
                        continue

                conn.executemany("""
                    INSERT OR IGNORE INTO weather
                        (obs_datetime, temperature, precipitation, wind_speed,
                         wind_dir, humidity, feel_temp, pressure)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, rows)
                conn.commit()
                total += len(rows)
                print(f"  [기상] {os.path.basename(zpath)} → {len(rows):,}건 적재")

    print(f"[기상] 총 {total:,}건 적재 완료\n")


# ── 3. 타슈 대여이력 적재 ─────────────────────────────────────
def load_rental(conn: sqlite3.Connection) -> None:
    """
    타슈 CSV 파일(26년01월~03월)을 읽어 rental_station, rental 테이블에 적재.
    컬럼: 자전거번호, 대여일시, 대여_대여소ID, 대여_대여소명,
          대여_X좌표, 대여_Y좌표, 대여_구, 대여_동, 대여_대여소주소,
          반납일시, 반납_대여소ID, 반납_대여소명, 반납_X좌표, 반납_Y좌표,
          반납_구, 반납_동, 반납_대여소주소, 이용시간(분), 이용거리(km)
    """
    csv_files = sorted(glob.glob(os.path.join(TASHU_DIR, "*.csv")))
    total_rental = 0

    for fpath in csv_files:
        stations, rentals = [], []
        with open(fpath, encoding="cp949", errors="replace") as f:
            reader = csv.reader(f)
            next(reader)  # 헤더 스킵
            for row in reader:
                if len(row) < 19:
                    continue
                try:
                    # 대여소 정보 (대여)
                    stations.append((
                        row[2].strip(), row[3].strip(),
                        row[6].strip(), row[7].strip(),
                        row[8].strip(),
                        float(row[5]) if row[5].strip() else None,  # y_coord(위도)
                        float(row[4]) if row[4].strip() else None,  # x_coord(경도)
                    ))
                    # 대여소 정보 (반납)
                    stations.append((
                        row[10].strip(), row[11].strip(),
                        row[14].strip(), row[15].strip(),
                        row[16].strip(),
                        float(row[13]) if row[13].strip() else None,
                        float(row[12]) if row[12].strip() else None,
                    ))
                    # 대여이력
                    rentals.append((
                        row[0].strip(),   # rental_id (자전거번호)
                        row[1].strip(),   # rental_datetime
                        row[2].strip(),   # rental_station_id
                        row[9].strip(),   # return_datetime
                        row[10].strip(),  # return_station_id
                        int(row[17])  if row[17].strip() else 0,
                        float(row[18]) if row[18].strip() else None,
                    ))
                except (ValueError, IndexError):
                    continue

        conn.executemany("""
            INSERT OR IGNORE INTO rental_station
                (station_id, station_name, district, dong, address, y_coord, x_coord)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, stations)
        conn.executemany("""
            INSERT OR IGNORE INTO rental
                (rental_id, rental_datetime, rental_station_id,
                 return_datetime, return_station_id, use_time_min, use_distance_km)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, rentals)
        conn.commit()
        total_rental += len(rentals)
        print(f"  [타슈] {os.path.basename(fpath)[:30]} → {len(rentals):,}건 적재")

    print(f"[타슈] 총 {total_rental:,}건 적재 완료\n")


# ── 4. 쿼리 실행 ─────────────────────────────────────────────
def run_query_1a(conn: sqlite3.Connection) -> None:
    """쿼리 1-A: 강수량 조건별 시간당 평균 대여량 비교"""
    print("=" * 60)
    print("쿼리 1-A: 강수량 조건별 시간당 평균 대여량")
    print("=" * 60)

    sql = """
    SELECT
        CASE
            WHEN w.precipitation >= 10 THEN '강우 (10mm 이상)'
            WHEN w.precipitation >  0  THEN '약한 강우 (10mm 미만)'
            ELSE                            '강수 없음'
        END                                                   AS rain_category,
        COUNT(r.rental_id)                                    AS total_rentals,
        COUNT(DISTINCT DATE(w.obs_datetime))                  AS total_days,
        ROUND(
            CAST(COUNT(r.rental_id) AS REAL)
            / COUNT(DISTINCT DATE(w.obs_datetime))
            / 24.0,
            2
        )                                                     AS avg_hourly_rentals
    FROM weather w
    LEFT JOIN rental r
        ON  DATE(r.rental_datetime) = DATE(w.obs_datetime)
        AND STRFTIME('%H', r.rental_datetime) = STRFTIME('%H', w.obs_datetime)
    GROUP BY rain_category
    ORDER BY avg_hourly_rentals DESC
    """

    cur = conn.execute(sql)
    header = [d[0] for d in cur.description]
    rows = cur.fetchall()
    print(f"{'강수 조건':<22} {'총 대여수':>10} {'일수':>6} {'시간당 평균':>10}")
    print("-" * 55)
    for row in rows:
        print(f"{row[0]:<22} {row[1]:>10,} {row[2]:>6} {row[3]:>10}")
    print()


def run_query_1b(conn: sqlite3.Connection) -> None:
    """쿼리 1-B: 폭염 기간 대여량 급감 대여소 상위 5곳"""
    print("=" * 60)
    print("쿼리 1-B: 폭염 기간 대여량 급감 대여소 TOP 5")
    print("=" * 60)

    sql = """
    WITH normal_period AS (
        SELECT
            r.rental_station_id,
            CAST(COUNT(r.rental_id) AS REAL)
                / NULLIF(COUNT(DISTINCT DATE(w.obs_datetime)), 0) AS daily_avg_normal
        FROM rental r
        JOIN weather w
            ON  DATE(r.rental_datetime) = DATE(w.obs_datetime)
            AND STRFTIME('%H', r.rental_datetime) = STRFTIME('%H', w.obs_datetime)
        WHERE w.feel_temp < 35
        GROUP BY r.rental_station_id
    ),
    heatwave_period AS (
        SELECT
            r.rental_station_id,
            CAST(COUNT(r.rental_id) AS REAL)
                / NULLIF(COUNT(DISTINCT DATE(w.obs_datetime)), 0) AS daily_avg_heatwave
        FROM rental r
        JOIN weather w
            ON  DATE(r.rental_datetime) = DATE(w.obs_datetime)
            AND STRFTIME('%H', r.rental_datetime) = STRFTIME('%H', w.obs_datetime)
        WHERE w.feel_temp >= 35
        GROUP BY r.rental_station_id
    )
    SELECT
        rs.station_id,
        rs.station_name,
        rs.district,
        ROUND(np.daily_avg_normal,   2) AS avg_normal,
        ROUND(hp.daily_avg_heatwave, 2) AS avg_heatwave,
        ROUND(
            (np.daily_avg_normal - hp.daily_avg_heatwave)
            / NULLIF(np.daily_avg_normal, 0) * 100,
            1
        )                               AS drop_rate_pct
    FROM normal_period np
    JOIN heatwave_period hp ON np.rental_station_id = hp.rental_station_id
    JOIN rental_station rs  ON np.rental_station_id = rs.station_id
    ORDER BY drop_rate_pct DESC
    LIMIT 5
    """

    cur = conn.execute(sql)
    rows = cur.fetchall()
    print(f"{'대여소ID':<12} {'대여소명':<22} {'구':<8} {'정상평균':>8} {'폭염평균':>8} {'감소율(%)':>9}")
    print("-" * 75)
    for row in rows:
        print(f"{row[0]:<12} {row[1]:<22} {row[2]:<8} {row[3]:>8} {row[4]:>8} {row[5]:>9}")
    print()


# ── 메인 ─────────────────────────────────────────────────────
if __name__ == "__main__":
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")

    init_db(conn)
    load_weather(conn)
    load_rental(conn)
    run_query_1a(conn)
    run_query_1b(conn)

    conn.close()
    print("완료.")
