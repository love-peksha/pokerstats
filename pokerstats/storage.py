from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from pokerstats.parser import TournamentRecord


EXPECTED_PRIZE_POOL_WEIGHTS_BY_MULTIPLIER = {
    4: 47_863_940,
    6: 44_624_040,
    8: 2_650_000,
    10: 2_500_000,
    20: 2_350_000,
    100: 8_000,
    200: 4_000,
    200_000: 20,
}
EXPECTED_PLACE_SHARE_PCT = round(100 / 6, 2)
MULTIPLIER_SQL_EXPRESSION = """
CASE
    WHEN buy_in_cents > 0 AND total_prize_pool_cents % buy_in_cents = 0
    THEN total_prize_pool_cents / buy_in_cents
    ELSE NULL
END
""".strip()


@dataclass(slots=True)
class TournamentFilters:
    buy_in_cents: list[int] = field(default_factory=list)
    multipliers: list[int] = field(default_factory=list)
    prize_pool_min_cents: int | None = None
    prize_pool_max_cents: int | None = None
    started_at_from: str | None = None
    started_at_to: str | None = None


def copy_filters(
    filters: TournamentFilters,
    *,
    include_buy_in: bool = True,
    include_multipliers: bool = True,
    include_prize_pool: bool = True,
    include_started_at: bool = True,
) -> TournamentFilters:
    return TournamentFilters(
        buy_in_cents=list(filters.buy_in_cents) if include_buy_in else [],
        multipliers=list(filters.multipliers) if include_multipliers else [],
        prize_pool_min_cents=filters.prize_pool_min_cents if include_prize_pool else None,
        prize_pool_max_cents=filters.prize_pool_max_cents if include_prize_pool else None,
        started_at_from=filters.started_at_from if include_started_at else None,
        started_at_to=filters.started_at_to if include_started_at else None,
    )


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


@contextmanager
def open_connection(db_path: Path) -> sqlite3.Connection:
    connection = connect(db_path)
    try:
        yield connection
    finally:
        connection.close()


def ensure_database(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with open_connection(db_path) as connection:
        connection.executescript(
            """
            PRAGMA journal_mode = WAL;

            CREATE TABLE IF NOT EXISTS tournaments (
                tournament_id TEXT PRIMARY KEY,
                tournament_name TEXT NOT NULL,
                source_archive TEXT NOT NULL,
                source_file TEXT NOT NULL,
                buy_in_cents INTEGER NOT NULL,
                players INTEGER NOT NULL,
                total_prize_pool_cents INTEGER NOT NULL,
                started_at TEXT NOT NULL,
                place INTEGER NOT NULL,
                payout_cents INTEGER NOT NULL,
                hero_name TEXT NOT NULL,
                imported_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_tournaments_buy_in
                ON tournaments (buy_in_cents);

            CREATE INDEX IF NOT EXISTS idx_tournaments_prize_pool
                ON tournaments (total_prize_pool_cents);

            CREATE INDEX IF NOT EXISTS idx_tournaments_place
                ON tournaments (place);

            CREATE INDEX IF NOT EXISTS idx_tournaments_started_at
                ON tournaments (started_at DESC);

            CREATE TABLE IF NOT EXISTS import_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                archive_name TEXT NOT NULL,
                archive_sha256 TEXT NOT NULL,
                total_files INTEGER NOT NULL,
                inserted_count INTEGER NOT NULL,
                duplicate_count INTEGER NOT NULL,
                filtered_count INTEGER NOT NULL,
                parse_error_count INTEGER NOT NULL,
                errors_preview TEXT NOT NULL,
                imported_at TEXT NOT NULL
            );
            """
        )


def insert_tournament(connection: sqlite3.Connection, record: TournamentRecord) -> bool:
    cursor = connection.execute(
        """
        INSERT OR IGNORE INTO tournaments (
            tournament_id,
            tournament_name,
            source_archive,
            source_file,
            buy_in_cents,
            players,
            total_prize_pool_cents,
            started_at,
            place,
            payout_cents,
            hero_name,
            imported_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record.tournament_id,
            record.tournament_name,
            record.source_archive,
            record.source_file,
            record.buy_in_cents,
            record.players,
            record.prize_pool_cents,
            record.started_at,
            record.place,
            record.payout_cents,
            record.hero_name,
            utc_now_iso(),
        ),
    )
    return cursor.rowcount == 1


def log_import_run(
    connection: sqlite3.Connection,
    *,
    archive_name: str,
    archive_sha256: str,
    total_files: int,
    inserted_count: int,
    duplicate_count: int,
    filtered_count: int,
    parse_error_count: int,
    errors_preview: str,
) -> None:
    connection.execute(
        """
        INSERT INTO import_runs (
            archive_name,
            archive_sha256,
            total_files,
            inserted_count,
            duplicate_count,
            filtered_count,
            parse_error_count,
            errors_preview,
            imported_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            archive_name,
            archive_sha256,
            total_files,
            inserted_count,
            duplicate_count,
            filtered_count,
            parse_error_count,
            errors_preview,
            utc_now_iso(),
        ),
    )


def build_where_clause(filters: TournamentFilters) -> tuple[str, list[object]]:
    clauses: list[str] = []
    params: list[object] = []

    if filters.buy_in_cents:
        placeholders = ", ".join("?" for _ in filters.buy_in_cents)
        clauses.append(f"buy_in_cents IN ({placeholders})")
        params.extend(filters.buy_in_cents)

    if filters.multipliers:
        placeholders = ", ".join("?" for _ in filters.multipliers)
        clauses.append(f"{MULTIPLIER_SQL_EXPRESSION} IN ({placeholders})")
        params.extend(filters.multipliers)

    if filters.prize_pool_min_cents is not None:
        clauses.append("total_prize_pool_cents >= ?")
        params.append(filters.prize_pool_min_cents)

    if filters.prize_pool_max_cents is not None:
        clauses.append("total_prize_pool_cents <= ?")
        params.append(filters.prize_pool_max_cents)

    if filters.started_at_from is not None:
        clauses.append("started_at >= ?")
        params.append(filters.started_at_from)

    if filters.started_at_to is not None:
        clauses.append("started_at <= ?")
        params.append(filters.started_at_to)

    if not clauses:
        return "", params

    return "WHERE " + " AND ".join(clauses), params


def _fetch_summary(connection: sqlite3.Connection, filters: TournamentFilters) -> dict[str, float | int]:
    where_clause, params = build_where_clause(filters)
    row = connection.execute(
        f"""
        SELECT
            COUNT(*) AS total_tournaments,
            COALESCE(ROUND(AVG(place), 2), 0) AS average_place,
            COALESCE(SUM(CASE WHEN place = 1 THEN 1 ELSE 0 END), 0) AS wins,
            COALESCE(SUM(CASE WHEN place <= 2 THEN 1 ELSE 0 END), 0) AS top_two,
            COALESCE(SUM(CASE WHEN payout_cents > 0 THEN 1 ELSE 0 END), 0) AS in_the_money,
            COALESCE(
                ROUND(
                    AVG(
                        CASE
                            WHEN total_prize_pool_cents > 0
                            THEN (CAST(payout_cents AS REAL) / total_prize_pool_cents) * 100.0
                            ELSE NULL
                        END
                    ),
                    2
                ),
                0
            ) AS average_prize_pool_share_pct,
            COALESCE(SUM(buy_in_cents), 0) AS total_buy_ins_cents,
            COALESCE(SUM(payout_cents - buy_in_cents), 0) AS net_profit_cents
        FROM tournaments
        {where_clause}
        """,
        params,
    ).fetchone()
    total_tournaments = int(row["total_tournaments"])
    wins = int(row["wins"])
    top_two = int(row["top_two"])
    itm = int(row["in_the_money"])
    return {
        "total_tournaments": total_tournaments,
        "average_place": float(row["average_place"]),
        "wins": wins,
        "win_rate": round((wins / total_tournaments) * 100, 2) if total_tournaments else 0.0,
        "top_two": top_two,
        "top_two_rate": round((top_two / total_tournaments) * 100, 2) if total_tournaments else 0.0,
        "in_the_money": itm,
        "in_the_money_rate": round((itm / total_tournaments) * 100, 2) if total_tournaments else 0.0,
        "average_prize_pool_share_pct": float(row["average_prize_pool_share_pct"]),
        "total_buy_ins_cents": int(row["total_buy_ins_cents"]),
        "net_profit_cents": int(row["net_profit_cents"]),
    }


def _fetch_place_distribution(
    connection: sqlite3.Connection,
    filters: TournamentFilters,
    total_tournaments: int,
) -> list[dict[str, float | int]]:
    where_clause, params = build_where_clause(filters)
    rows = connection.execute(
        f"""
        SELECT place, COUNT(*) AS count
        FROM tournaments
        {where_clause}
        GROUP BY place
        ORDER BY place
        """,
        params,
    ).fetchall()
    distribution: list[dict[str, float | int]] = []
    for row in rows:
        count = int(row["count"])
        percentage = round((count / total_tournaments) * 100, 2) if total_tournaments else 0.0
        distribution.append(
            {
                "place": int(row["place"]),
                "count": count,
                "percentage": percentage,
                "expected_percentage": EXPECTED_PLACE_SHARE_PCT,
                "delta_percentage_points": round(percentage - EXPECTED_PLACE_SHARE_PCT, 2),
            }
        )
    return distribution


def _fetch_breakdown(
    connection: sqlite3.Connection,
    *,
    dimension: str,
    filters: TournamentFilters,
) -> list[dict[str, float | int]]:
    if dimension not in {"buy_in_cents", "total_prize_pool_cents"}:
        raise ValueError(f"Неподдерживаемое измерение: {dimension}")

    where_clause, params = build_where_clause(filters)
    rows = connection.execute(
        f"""
        SELECT
            {dimension} AS dimension_value,
            COUNT(*) AS tournaments,
            ROUND(AVG(place), 2) AS average_place,
            SUM(CASE WHEN place = 1 THEN 1 ELSE 0 END) AS wins
        FROM tournaments
        {where_clause}
        GROUP BY {dimension}
        ORDER BY {dimension}
        """,
        params,
    ).fetchall()

    data: list[dict[str, float | int]] = []
    for row in rows:
        tournaments = int(row["tournaments"])
        wins = int(row["wins"])
        data.append(
            {
                "value_cents": int(row["dimension_value"]),
                "tournaments": tournaments,
                "average_place": float(row["average_place"]),
                "wins": wins,
                "win_rate": round((wins / tournaments) * 100, 2) if tournaments else 0.0,
            }
        )
    return data


def _fetch_recent_tournaments(
    connection: sqlite3.Connection,
    filters: TournamentFilters,
    limit: int = 25,
) -> list[dict[str, float | int | str]]:
    where_clause, params = build_where_clause(filters)
    rows = connection.execute(
        f"""
        SELECT
            tournament_id,
            tournament_name,
            buy_in_cents,
            total_prize_pool_cents,
            started_at,
            place,
            payout_cents
        FROM tournaments
        {where_clause}
        ORDER BY started_at DESC, tournament_id DESC
        LIMIT ?
        """,
        [*params, limit],
    ).fetchall()
    return [
        {
            "tournament_id": row["tournament_id"],
            "tournament_name": row["tournament_name"],
            "buy_in_cents": int(row["buy_in_cents"]),
            "prize_pool_cents": int(row["total_prize_pool_cents"]),
            "started_at": row["started_at"],
            "place": int(row["place"]),
            "payout_cents": int(row["payout_cents"]),
        }
        for row in rows
    ]


def _fetch_prize_pool_frequency_by_buy_in(
    connection: sqlite3.Connection,
    filters: TournamentFilters,
) -> list[dict[str, object]]:
    where_clause, params = build_where_clause(filters)
    rows = connection.execute(
        f"""
        SELECT
            buy_in_cents,
            total_prize_pool_cents,
            COUNT(*) AS tournaments
        FROM tournaments
        {where_clause}
        GROUP BY buy_in_cents, total_prize_pool_cents
        ORDER BY buy_in_cents, total_prize_pool_cents
        """,
        params,
    ).fetchall()

    grouped_rows: dict[int, list[dict[str, int]]] = {}
    for row in rows:
        buy_in_cents = int(row["buy_in_cents"])
        grouped_rows.setdefault(buy_in_cents, []).append(
            {
                "prize_pool_cents": int(row["total_prize_pool_cents"]),
                "count": int(row["tournaments"]),
            }
        )

    groups: list[dict[str, object]] = []
    for buy_in_cents, group_rows in grouped_rows.items():
        total_tournaments = sum(item["count"] for item in group_rows)
        expected_weights: list[int | None] = []
        for item in group_rows:
            prize_pool_cents = item["prize_pool_cents"]
            multiplier = (
                prize_pool_cents // buy_in_cents
                if buy_in_cents and prize_pool_cents % buy_in_cents == 0
                else None
            )
            expected_weights.append(
                EXPECTED_PRIZE_POOL_WEIGHTS_BY_MULTIPLIER.get(multiplier)
                if multiplier is not None
                else None
            )

        expected_weights_complete = all(weight is not None for weight in expected_weights)
        expected_visible_total = sum(weight for weight in expected_weights if weight is not None)
        groups.append(
            {
                "buy_in_cents": buy_in_cents,
                "total_tournaments": total_tournaments,
                "rows": [
                    {
                        "prize_pool_cents": item["prize_pool_cents"],
                        "count": item["count"],
                        "percentage": round((item["count"] / total_tournaments) * 100, 2)
                        if total_tournaments
                        else 0.0,
                        "expected_percentage": round(
                            (expected_weights[index] / expected_visible_total) * 100,
                            2,
                        )
                        if expected_weights_complete
                        and expected_visible_total
                        and expected_weights[index] is not None
                        else None,
                        "delta_percentage_points": round(
                            (
                                round((item["count"] / total_tournaments) * 100, 2)
                                if total_tournaments
                                else 0.0
                            )
                            - round(
                                (expected_weights[index] / expected_visible_total) * 100,
                                2,
                            ),
                            2,
                        )
                        if expected_weights_complete
                        and expected_visible_total
                        and expected_weights[index] is not None
                        else None,
                    }
                    for index, item in enumerate(group_rows)
                ],
            }
        )
    return groups


def _fetch_distinct_values(
    connection: sqlite3.Connection,
    *,
    column_name: str,
    filters: TournamentFilters,
) -> list[int]:
    where_clause, params = build_where_clause(filters)
    rows = connection.execute(
        f"""
        SELECT DISTINCT {column_name} AS value_cents
        FROM tournaments
        {where_clause}
        ORDER BY {column_name}
        """,
        params,
    ).fetchall()
    return [int(row["value_cents"]) for row in rows]


def _fetch_distinct_multipliers(
    connection: sqlite3.Connection,
    filters: TournamentFilters,
) -> list[int]:
    where_clause, params = build_where_clause(filters)
    rows = connection.execute(
        f"""
        SELECT DISTINCT {MULTIPLIER_SQL_EXPRESSION} AS multiplier
        FROM tournaments
        {where_clause}
        ORDER BY multiplier
        """,
        params,
    ).fetchall()
    return [int(row["multiplier"]) for row in rows if row["multiplier"] is not None]


def _fetch_started_at_bounds(
    connection: sqlite3.Connection,
    filters: TournamentFilters,
) -> dict[str, str | None]:
    where_clause, params = build_where_clause(filters)
    row = connection.execute(
        f"""
        SELECT
            MIN(started_at) AS started_at_min,
            MAX(started_at) AS started_at_max
        FROM tournaments
        {where_clause}
        """,
        params,
    ).fetchone()
    return {
        "started_at_min": row["started_at_min"],
        "started_at_max": row["started_at_max"],
    }


def _fetch_filter_options(
    connection: sqlite3.Connection,
    filters: TournamentFilters,
) -> dict[str, list[int] | str | None]:
    buy_in_filters = copy_filters(
        filters,
        include_buy_in=False,
        include_multipliers=True,
        include_prize_pool=True,
        include_started_at=True,
    )
    multiplier_filters = copy_filters(
        filters,
        include_buy_in=True,
        include_multipliers=False,
        include_prize_pool=True,
        include_started_at=True,
    )
    prize_pool_filters = copy_filters(
        filters,
        include_buy_in=True,
        include_multipliers=True,
        include_prize_pool=False,
        include_started_at=True,
    )
    started_at_filters = copy_filters(
        filters,
        include_buy_in=True,
        include_multipliers=True,
        include_prize_pool=True,
        include_started_at=False,
    )

    buy_ins = [
        value
        for value in _fetch_distinct_values(
            connection,
            column_name="buy_in_cents",
            filters=buy_in_filters,
        )
    ]
    prize_pools = [
        value
        for value in _fetch_distinct_values(
            connection,
            column_name="total_prize_pool_cents",
            filters=prize_pool_filters,
        )
    ]
    return {
        "buy_ins_cents": buy_ins,
        "multipliers": _fetch_distinct_multipliers(connection, multiplier_filters),
        "prize_pools_cents": prize_pools,
        **_fetch_started_at_bounds(connection, started_at_filters),
    }


def fetch_filter_options(db_path: Path) -> dict[str, list[int] | str | None]:
    with open_connection(db_path) as connection:
        return _fetch_filter_options(connection, TournamentFilters())


def build_dashboard(db_path: Path, filters: TournamentFilters) -> dict[str, object]:
    with open_connection(db_path) as connection:
        summary = _fetch_summary(connection, filters)
        total_tournaments = int(summary["total_tournaments"])
        return {
            "summary": summary,
            "distribution": _fetch_place_distribution(connection, filters, total_tournaments),
            "buy_in_breakdown": _fetch_breakdown(
                connection,
                dimension="buy_in_cents",
                filters=filters,
            ),
            "prize_pool_breakdown": _fetch_breakdown(
                connection,
                dimension="total_prize_pool_cents",
                filters=filters,
            ),
            "prize_pool_frequency_by_buy_in": _fetch_prize_pool_frequency_by_buy_in(
                connection,
                filters,
            ),
            "recent_tournaments": _fetch_recent_tournaments(connection, filters),
            "filters": _fetch_filter_options(connection, filters),
        }
