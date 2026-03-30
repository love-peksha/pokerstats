from __future__ import annotations

from datetime import datetime
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, urlsplit

from pokerstats.importer import import_archive_bytes
from pokerstats.parser import money_to_cents
from pokerstats.storage import TournamentFilters, build_dashboard


def _safe_filename(filename: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(filename).name)
    return cleaned or "archive.zip"


def _pick_upload_path(uploads_dir: Path, filename: str) -> Path:
    candidate = uploads_dir / filename
    if not candidate.exists():
        return candidate

    stem = candidate.stem
    suffix = candidate.suffix
    counter = 1
    while True:
        candidate = uploads_dir / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def _normalize_started_at(value: str, *, boundary: str) -> str:
    cleaned = value.strip()
    parsed = datetime.fromisoformat(cleaned)

    if len(cleaned) == 10:
        parsed = parsed.replace(
            hour=0 if boundary == "start" else 23,
            minute=0 if boundary == "start" else 59,
            second=0 if boundary == "start" else 59,
            microsecond=0,
        )
    elif len(cleaned) == 16:
        parsed = parsed.replace(
            second=0 if boundary == "start" else 59,
            microsecond=0,
        )
    else:
        parsed = parsed.replace(microsecond=0)

    return parsed.strftime("%Y-%m-%d %H:%M:%S")


def _parse_filters(query: str) -> TournamentFilters:
    params = parse_qs(query, keep_blank_values=False)
    buy_in_values = [money_to_cents(value) for value in params.get("buy_in", []) if value]
    multiplier_values: list[int] = []
    for value in params.get("multiplier", []):
        if not value:
            continue
        try:
            multiplier = int(value)
        except ValueError as error:
            raise ValueError(f"Некорректный множитель: {value}") from error
        if multiplier <= 0:
            raise ValueError(f"Некорректный множитель: {value}")
        multiplier_values.append(multiplier)

    prize_pool_min_cents = None
    prize_pool_max_cents = None
    if params.get("prize_pool_min"):
        prize_pool_min_cents = money_to_cents(params["prize_pool_min"][0])
    if params.get("prize_pool_max"):
        prize_pool_max_cents = money_to_cents(params["prize_pool_max"][0])

    started_at_from = None
    started_at_to = None
    if params.get("started_at_from"):
        started_at_from = _normalize_started_at(params["started_at_from"][0], boundary="start")
    if params.get("started_at_to"):
        started_at_to = _normalize_started_at(params["started_at_to"][0], boundary="end")

    return TournamentFilters(
        buy_in_cents=buy_in_values,
        multipliers=multiplier_values,
        prize_pool_min_cents=prize_pool_min_cents,
        prize_pool_max_cents=prize_pool_max_cents,
        started_at_from=started_at_from,
        started_at_to=started_at_to,
    )


class _ReusableServer(ThreadingHTTPServer):
    allow_reuse_address = True


class PokerStatsHandler(BaseHTTPRequestHandler):
    db_path: Path
    static_dir: Path
    uploads_dir: Path

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlsplit(self.path)
        if parsed.path == "/":
            return self._serve_static("index.html", "text/html; charset=utf-8")
        if parsed.path == "/static/style.css":
            return self._serve_static("style.css", "text/css; charset=utf-8")
        if parsed.path == "/static/app.js":
            return self._serve_static("app.js", "application/javascript; charset=utf-8")
        if parsed.path == "/api/dashboard":
            return self._handle_dashboard(parsed.query)
        if parsed.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return

        self.send_error(404, "Not found")

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlsplit(self.path)
        if parsed.path == "/api/import":
            return self._handle_import()

        self.send_error(404, "Not found")

    def _serve_static(self, file_name: str, content_type: str) -> None:
        path = self.static_dir / file_name
        if not path.exists():
            self.send_error(404, "Static file not found")
            return

        content = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _send_json(self, payload: dict[str, object], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_dashboard(self, query: str) -> None:
        try:
            filters = _parse_filters(query)
        except ValueError as error:
            self._send_json({"error": str(error)}, status=400)
            return

        payload = build_dashboard(self.db_path, filters)
        self._send_json(payload)

    def _parse_multipart(self) -> list[dict[str, object]]:
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            raise ValueError("Ожидался запрос multipart/form-data.")

        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length)
        parser = BytesParser(policy=default)
        message = parser.parsebytes(
            (
                f"Content-Type: {content_type}\r\n"
                "MIME-Version: 1.0\r\n\r\n"
            ).encode("utf-8")
            + raw_body
        )

        files: list[dict[str, object]] = []
        for part in message.iter_parts():
            if part.get_content_disposition() != "form-data":
                continue

            filename = part.get_filename()
            if not filename:
                continue

            files.append(
                {
                    "filename": filename,
                    "content": part.get_payload(decode=True) or b"",
                }
            )

        return files

    def _handle_import(self) -> None:
        try:
            files = self._parse_multipart()
        except ValueError as error:
            self._send_json({"error": str(error)}, status=400)
            return

        archive_files = [item for item in files if str(item["filename"]).lower().endswith(".zip")]
        if not archive_files:
            self._send_json({"error": "Нужно передать хотя бы один ZIP-архив."}, status=400)
            return

        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        results: list[dict[str, object]] = []

        for file_info in archive_files:
            content = file_info["content"]
            if not isinstance(content, bytes):
                continue

            upload_name = _safe_filename(str(file_info["filename"]))
            upload_path = _pick_upload_path(self.uploads_dir, upload_name)
            upload_path.write_bytes(content)

            result = import_archive_bytes(
                self.db_path,
                archive_name=upload_path.name,
                archive_bytes=content,
            )
            results.append(result.to_dict())

        payload = {
            "results": results,
            "dashboard": build_dashboard(self.db_path, TournamentFilters()),
        }
        self._send_json(payload)


def _build_handler(
    *,
    db_path: Path,
    static_dir: Path,
    uploads_dir: Path,
) -> type[PokerStatsHandler]:
    class ConfiguredHandler(PokerStatsHandler):
        pass

    ConfiguredHandler.db_path = db_path
    ConfiguredHandler.static_dir = static_dir
    ConfiguredHandler.uploads_dir = uploads_dir
    return ConfiguredHandler


def run_server(
    *,
    db_path: Path,
    static_dir: Path,
    uploads_dir: Path,
    host: str,
    port: int,
) -> None:
    handler = _build_handler(
        db_path=db_path,
        static_dir=static_dir,
        uploads_dir=uploads_dir,
    )

    with _ReusableServer((host, port), handler) as httpd:
        print(f"Статистика доступна на http://{host}:{port}")
        httpd.serve_forever()
