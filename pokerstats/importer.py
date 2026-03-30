from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import zipfile

from pokerstats.parser import decode_text, parse_tournament_text
from pokerstats.storage import insert_tournament, log_import_run, open_connection


@dataclass(slots=True)
class ImportResult:
    archive_name: str
    archive_sha256: str
    total_files: int = 0
    inserted_count: int = 0
    duplicate_count: int = 0
    filtered_count: int = 0
    parse_error_count: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "archive_name": self.archive_name,
            "archive_sha256": self.archive_sha256,
            "total_files": self.total_files,
            "inserted_count": self.inserted_count,
            "duplicate_count": self.duplicate_count,
            "filtered_count": self.filtered_count,
            "parse_error_count": self.parse_error_count,
            "errors": self.errors,
        }


def collect_archive_paths(paths: list[Path], recursive: bool) -> list[Path]:
    archive_paths: list[Path] = []
    for path in paths:
        if path.is_file() and path.suffix.lower() == ".zip":
            archive_paths.append(path.resolve())
            continue

        if path.is_dir():
            pattern = "**/*.zip" if recursive else "*.zip"
            archive_paths.extend(item.resolve() for item in path.glob(pattern) if item.is_file())

    return sorted(set(archive_paths))


def _limit_errors(errors: list[str]) -> str:
    if not errors:
        return ""
    preview = errors[:10]
    if len(errors) > 10:
        preview.append(f"... и еще {len(errors) - 10} ошибок")
    return "\n".join(preview)


def _persist_result(db_path: Path, result: ImportResult) -> None:
    with open_connection(db_path) as connection:
        log_import_run(
            connection,
            archive_name=result.archive_name,
            archive_sha256=result.archive_sha256,
            total_files=result.total_files,
            inserted_count=result.inserted_count,
            duplicate_count=result.duplicate_count,
            filtered_count=result.filtered_count,
            parse_error_count=result.parse_error_count,
            errors_preview=_limit_errors(result.errors),
        )
        connection.commit()


def import_archive_file(db_path: Path, archive_path: Path) -> ImportResult:
    archive_bytes = archive_path.read_bytes()
    return import_archive_bytes(db_path, archive_path.name, archive_bytes)


def import_archive_bytes(db_path: Path, archive_name: str, archive_bytes: bytes) -> ImportResult:
    result = ImportResult(
        archive_name=archive_name,
        archive_sha256=sha256(archive_bytes).hexdigest(),
    )

    try:
        archive = zipfile.ZipFile(BytesIO(archive_bytes))
    except zipfile.BadZipFile as error:
        result.parse_error_count = 1
        result.errors.append(f"Архив не читается как ZIP: {error}")
        _persist_result(db_path, result)
        return result

    with archive:
        txt_entries = [
            entry
            for entry in archive.infolist()
            if not entry.is_dir() and entry.filename.lower().endswith(".txt")
        ]
        result.total_files = len(txt_entries)

        with open_connection(db_path) as connection:
            for entry in txt_entries:
                try:
                    text = decode_text(archive.read(entry))
                    record = parse_tournament_text(
                        text,
                        source_file=Path(entry.filename).name,
                        source_archive=archive_name,
                    )
                    inserted = insert_tournament(connection, record)
                    if inserted:
                        result.inserted_count += 1
                    else:
                        result.duplicate_count += 1
                except Exception as error:  # noqa: BLE001
                    result.parse_error_count += 1
                    result.errors.append(f"{entry.filename}: {error}")

            log_import_run(
                connection,
                archive_name=result.archive_name,
                archive_sha256=result.archive_sha256,
                total_files=result.total_files,
                inserted_count=result.inserted_count,
                duplicate_count=result.duplicate_count,
                filtered_count=result.filtered_count,
                parse_error_count=result.parse_error_count,
                errors_preview=_limit_errors(result.errors),
            )
            connection.commit()

    return result
