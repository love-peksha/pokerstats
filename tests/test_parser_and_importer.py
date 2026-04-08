from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import io
import unittest
import zipfile

from pokerstats.importer import import_archive_bytes
from pokerstats.parser import parse_tournament_text
from pokerstats.server import _parse_filters
from pokerstats.storage import TournamentFilters, build_dashboard, ensure_database


SAMPLE_1_DOLLAR = """Tournament #273606766, Spin&Gold #11, Hold'em No Limit
Buy-in: $1
6 Players
Total Prize Pool: $8
Tournament started 2026/03/24 15:32:56 
2nd : Hero, $3
You finished in 2nd place.
"""

SAMPLE_5_DOLLAR = """Tournament #273517027, Spin&Gold #16, Hold'em No Limit
Buy-in: $5
6 Players
Total Prize Pool: $30
Tournament started 2026/03/24 02:59:41 
4th : Hero, $0
You finished in 4th place.
"""

SAMPLE_025_DOLLAR = """Tournament #273614396, Spin&Gold #14, Hold'em No Limit
Buy-in: $0.25
6 Players
Total Prize Pool: $1.5
Tournament started 2026/03/24 16:25:29 
4th : Hero, $0
You finished in 4th place.
"""

SAMPLE_MONDAY = """Tournament #273700001, Spin&Gold #18, Hold'em No Limit
Buy-in: $1
6 Players
Total Prize Pool: $6
Tournament started 2026/03/23 21:10:00 
1st : Hero, $6
You finished in 1st place.
"""


def build_zip_bytes(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file_name, content in files.items():
            archive.writestr(file_name, content)
    return buffer.getvalue()


class ParserAndImporterTests(unittest.TestCase):
    def test_parse_filters_normalizes_datetime_local_range(self) -> None:
        filters = _parse_filters(
            "multiplier=6&multiplier=8&weekday=1&weekday=7&time_slot=night&time_slot=evening&started_at_from=2026-03-24T15%3A32&started_at_to=2026-03-24T15%3A32"
        )

        self.assertEqual(filters.multipliers, [6, 8])
        self.assertEqual(filters.weekdays, [1, 7])
        self.assertEqual(filters.time_slots, ["night", "evening"])
        self.assertEqual(filters.started_at_from, "2026-03-24 15:32:00")
        self.assertEqual(filters.started_at_to, "2026-03-24 15:32:59")

    def test_parser_extracts_core_fields(self) -> None:
        record = parse_tournament_text(
            SAMPLE_5_DOLLAR,
            source_file="example.txt",
            source_archive="archive.zip",
        )

        self.assertEqual(record.tournament_id, "273517027")
        self.assertEqual(record.tournament_name, "Spin&Gold #16")
        self.assertEqual(record.buy_in_cents, 500)
        self.assertEqual(record.prize_pool_cents, 3000)
        self.assertEqual(record.place, 4)
        self.assertEqual(record.payout_cents, 0)

    def test_import_keeps_025_and_deduplicates(self) -> None:
        archive_bytes = build_zip_bytes(
            {
                "one.txt": SAMPLE_1_DOLLAR,
                "two.txt": SAMPLE_5_DOLLAR,
                "three.txt": SAMPLE_025_DOLLAR,
            }
        )

        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "stats.sqlite3"
            ensure_database(db_path)

            first_import = import_archive_bytes(db_path, "batch-1.zip", archive_bytes)
            second_import = import_archive_bytes(db_path, "batch-2.zip", archive_bytes)

            self.assertEqual(first_import.inserted_count, 3)
            self.assertEqual(first_import.filtered_count, 0)
            self.assertEqual(first_import.duplicate_count, 0)

            self.assertEqual(second_import.inserted_count, 0)
            self.assertEqual(second_import.filtered_count, 0)
            self.assertEqual(second_import.duplicate_count, 3)

            dashboard = build_dashboard(db_path, TournamentFilters())

            self.assertEqual(dashboard["summary"]["total_tournaments"], 3)
            self.assertEqual(dashboard["summary"]["total_buy_ins_cents"], 625)
            self.assertEqual(dashboard["summary"]["total_entry_buy_ins_cents"], 3750)
            self.assertEqual(dashboard["summary"]["total_prize_pools_cents"], 3950)
            self.assertEqual(dashboard["summary"]["actual_rake_pct"], -5.33)
            self.assertEqual(dashboard["summary"]["roi_pct"], -52.0)
            self.assertEqual(dashboard["summary"]["average_prize_pool_share_pct"], 12.5)
            self.assertEqual(len(dashboard["distribution"]), 2)
            self.assertEqual(dashboard["distribution"][0]["place"], 2)
            self.assertEqual(dashboard["distribution"][0]["expected_percentage"], 16.67)
            self.assertEqual(dashboard["distribution"][0]["percentage"], 33.33)
            self.assertEqual(len(dashboard["prize_pool_frequency_by_buy_in"]), 3)
            self.assertEqual(
                dashboard["prize_pool_frequency_by_buy_in"][0]["rows"][0]["percentage"],
                100.0,
            )
            self.assertEqual(
                dashboard["prize_pool_frequency_by_buy_in"][0]["rows"][0]["expected_percentage"],
                100.0,
            )
            self.assertEqual(dashboard["filters"]["buy_ins_cents"], [25, 100, 500])
            self.assertEqual(dashboard["filters"]["weekdays"], [2])
            self.assertEqual(dashboard["filters"]["time_slots"], ["night", "day"])

            filtered_dashboard = build_dashboard(
                db_path,
                TournamentFilters(buy_in_cents=[500]),
            )
            self.assertEqual(filtered_dashboard["summary"]["total_tournaments"], 1)
            self.assertEqual(filtered_dashboard["summary"]["total_buy_ins_cents"], 500)
            self.assertEqual(filtered_dashboard["summary"]["total_entry_buy_ins_cents"], 3000)
            self.assertEqual(filtered_dashboard["summary"]["total_prize_pools_cents"], 3000)
            self.assertEqual(filtered_dashboard["summary"]["actual_rake_pct"], 0.0)
            self.assertEqual(filtered_dashboard["summary"]["roi_pct"], -100.0)
            self.assertEqual(filtered_dashboard["summary"]["average_prize_pool_share_pct"], 0.0)
            self.assertEqual(filtered_dashboard["filters"]["prize_pools_cents"], [3000])

            multiplier_filtered_dashboard = build_dashboard(
                db_path,
                TournamentFilters(multipliers=[8]),
            )
            self.assertEqual(multiplier_filtered_dashboard["summary"]["total_tournaments"], 1)
            self.assertEqual(multiplier_filtered_dashboard["recent_tournaments"][0]["tournament_id"], "273606766")
            self.assertEqual(multiplier_filtered_dashboard["filters"]["multipliers"], [6, 8])

            time_filtered_dashboard = build_dashboard(
                db_path,
                TournamentFilters(
                    started_at_from="2026-03-24 03:00:00",
                    started_at_to="2026-03-24 23:59:59",
                ),
            )
            self.assertEqual(time_filtered_dashboard["summary"]["total_tournaments"], 2)
            self.assertEqual(time_filtered_dashboard["recent_tournaments"][0]["tournament_id"], "273614396")
            self.assertEqual(time_filtered_dashboard["filters"]["buy_ins_cents"], [25, 100])
            self.assertEqual(time_filtered_dashboard["filters"]["multipliers"], [6, 8])
            self.assertEqual(time_filtered_dashboard["filters"]["weekdays"], [2])
            self.assertEqual(time_filtered_dashboard["filters"]["time_slots"], ["day"])
            self.assertEqual(time_filtered_dashboard["filters"]["started_at_min"], "2026-03-24 02:59:41")
            self.assertEqual(time_filtered_dashboard["filters"]["started_at_max"], "2026-03-24 16:25:29")

    def test_dashboard_filters_by_weekday(self) -> None:
        archive_bytes = build_zip_bytes(
            {
                "one.txt": SAMPLE_1_DOLLAR,
                "two.txt": SAMPLE_5_DOLLAR,
                "three.txt": SAMPLE_025_DOLLAR,
                "monday.txt": SAMPLE_MONDAY,
            }
        )

        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "stats.sqlite3"
            ensure_database(db_path)
            import_archive_bytes(db_path, "batch-weekdays.zip", archive_bytes)

            monday_dashboard = build_dashboard(
                db_path,
                TournamentFilters(weekdays=[1]),
            )

            self.assertEqual(monday_dashboard["summary"]["total_tournaments"], 1)
            self.assertEqual(monday_dashboard["recent_tournaments"][0]["tournament_id"], "273700001")
            self.assertEqual(monday_dashboard["filters"]["weekdays"], [1, 2])

    def test_dashboard_filters_by_time_slot(self) -> None:
        archive_bytes = build_zip_bytes(
            {
                "one.txt": SAMPLE_1_DOLLAR,
                "two.txt": SAMPLE_5_DOLLAR,
                "three.txt": SAMPLE_025_DOLLAR,
                "monday.txt": SAMPLE_MONDAY,
            }
        )

        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "stats.sqlite3"
            ensure_database(db_path)
            import_archive_bytes(db_path, "batch-timeslots.zip", archive_bytes)

            night_dashboard = build_dashboard(
                db_path,
                TournamentFilters(time_slots=["night"]),
            )

            self.assertEqual(night_dashboard["summary"]["total_tournaments"], 1)
            self.assertEqual(night_dashboard["recent_tournaments"][0]["tournament_id"], "273517027")
            self.assertEqual(night_dashboard["filters"]["time_slots"], ["night", "day", "evening"])


if __name__ == "__main__":
    unittest.main()
