from __future__ import annotations

import argparse
from pathlib import Path

from pokerstats.importer import collect_archive_paths, import_archive_file
from pokerstats.server import run_server
from pokerstats.storage import ensure_database


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = BASE_DIR / "data" / "poker_stats.sqlite3"
STATIC_DIR = BASE_DIR / "static"
UPLOADS_DIR = BASE_DIR / "data" / "uploads"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Импорт истории турниров и локальная веб-статистика."
    )
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB_PATH),
        help="Путь к SQLite-базе со статистикой.",
    )

    subparsers = parser.add_subparsers(dest="command")

    import_parser = subparsers.add_parser(
        "import",
        help="Импортировать ZIP-архивы в базу.",
    )
    import_parser.add_argument(
        "paths",
        nargs="+",
        help="Файлы или папки с ZIP-архивами.",
    )
    import_parser.add_argument(
        "--recursive",
        action="store_true",
        help="Искать ZIP-архивы в папках рекурсивно.",
    )

    serve_parser = subparsers.add_parser(
        "serve",
        help="Запустить веб-интерфейс статистики.",
    )
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8000)
    serve_parser.add_argument(
        "--no-scan-root",
        action="store_true",
        help="Не импортировать ZIP-архивы из корня проекта перед запуском сервера.",
    )

    return parser


def print_import_result(archive_path: Path, result: dict[str, object]) -> None:
    print(f"\n{archive_path.name}")
    print(f"  txt-файлов: {result['total_files']}")
    print(f"  добавлено: {result['inserted_count']}")
    print(f"  дубликатов: {result['duplicate_count']}")
    print(f"  ошибок парсинга: {result['parse_error_count']}")


def import_paths(db_path: Path, raw_paths: list[str], recursive: bool) -> None:
    archive_paths = collect_archive_paths([Path(item) for item in raw_paths], recursive)
    if not archive_paths:
        print("ZIP-архивы не найдены.")
        return

    total_inserted = 0
    total_duplicates = 0
    total_errors = 0

    for archive_path in archive_paths:
        result = import_archive_file(db_path, archive_path)
        print_import_result(archive_path, result.to_dict())
        total_inserted += result.inserted_count
        total_duplicates += result.duplicate_count
        total_errors += result.parse_error_count

    print("\nИтог:")
    print(f"  добавлено: {total_inserted}")
    print(f"  дубликатов: {total_duplicates}")
    print(f"  ошибок парсинга: {total_errors}")


def import_root_archives(db_path: Path) -> None:
    archive_paths = sorted(BASE_DIR.glob("*.zip"))
    for archive_path in archive_paths:
        import_archive_file(db_path, archive_path)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    db_path = Path(args.db).resolve()
    ensure_database(db_path)

    if args.command == "import":
        import_paths(db_path, args.paths, args.recursive)
        return

    if args.command in {None, "serve"}:
        if not getattr(args, "no_scan_root", False):
            import_root_archives(db_path)
        host = getattr(args, "host", "127.0.0.1")
        port = getattr(args, "port", 8000)
        run_server(
            db_path=db_path,
            static_dir=STATIC_DIR,
            uploads_dir=UPLOADS_DIR,
            host=host,
            port=port,
        )
        return

    parser.print_help()


if __name__ == "__main__":
    main()
