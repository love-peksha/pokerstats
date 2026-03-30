from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re


_MONEY_STEP = Decimal("0.01")
_TEXT_ENCODINGS = ("utf-8-sig", "utf-8", "cp1251", "latin-1")

_TITLE_RE = re.compile(
    r"^Tournament #(?P<tournament_id>\d+),\s*(?P<tournament_name>[^,\r\n]+),",
    re.MULTILINE,
)
_BUY_IN_RE = re.compile(r"^Buy-in:\s*\$(?P<value>\d+(?:\.\d+)?)$", re.MULTILINE)
_PLAYERS_RE = re.compile(r"^(?P<value>\d+)\s+Players$", re.MULTILINE)
_PRIZE_POOL_RE = re.compile(
    r"^Total Prize Pool:\s*\$(?P<value>\d+(?:\.\d+)?)$",
    re.MULTILINE,
)
_STARTED_RE = re.compile(
    r"^Tournament started\s+(?P<value>\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2})\s*$",
    re.MULTILINE,
)
_PLACE_RE = re.compile(
    r"^You finished in (?P<value>\d+)(?:st|nd|rd|th) place\.$",
    re.MULTILINE,
)
_RESULT_LINE_RE = re.compile(
    r"^(?P<place>\d+)(?:st|nd|rd|th)\s*:\s*(?P<hero>.+?),\s*\$(?P<payout>\d+(?:\.\d+)?)$",
    re.MULTILINE,
)


@dataclass(frozen=True, slots=True)
class TournamentRecord:
    tournament_id: str
    tournament_name: str
    buy_in_cents: int
    players: int
    prize_pool_cents: int
    started_at: str
    place: int
    payout_cents: int
    hero_name: str
    source_archive: str
    source_file: str


def decode_text(raw_bytes: bytes) -> str:
    last_error: UnicodeDecodeError | None = None
    for encoding in _TEXT_ENCODINGS:
        try:
            return raw_bytes.decode(encoding)
        except UnicodeDecodeError as error:
            last_error = error
    if last_error is not None:
        raise last_error
    return raw_bytes.decode("utf-8", errors="replace")


def money_to_cents(value: str) -> int:
    try:
        decimal_value = Decimal(value).quantize(_MONEY_STEP, rounding=ROUND_HALF_UP)
    except InvalidOperation as error:
        raise ValueError(f"Некорректная денежная сумма: {value}") from error
    return int((decimal_value * 100).to_integral_value(rounding=ROUND_HALF_UP))


def _must_match(pattern: re.Pattern[str], text: str, field_name: str) -> re.Match[str]:
    match = pattern.search(text)
    if match is None:
        raise ValueError(f"Не найдено поле '{field_name}'.")
    return match


def parse_tournament_text(
    text: str,
    *,
    source_file: str,
    source_archive: str,
) -> TournamentRecord:
    title_match = _must_match(_TITLE_RE, text, "tournament_id")
    buy_in_match = _must_match(_BUY_IN_RE, text, "buy_in")
    players_match = _must_match(_PLAYERS_RE, text, "players")
    prize_pool_match = _must_match(_PRIZE_POOL_RE, text, "prize_pool")
    started_match = _must_match(_STARTED_RE, text, "started_at")
    place_match = _must_match(_PLACE_RE, text, "place")
    result_line_match = _must_match(_RESULT_LINE_RE, text, "result_line")

    started_at = datetime.strptime(
        started_match.group("value"),
        "%Y/%m/%d %H:%M:%S",
    ).isoformat(sep=" ")

    place = int(place_match.group("value"))
    result_place = int(result_line_match.group("place"))
    if result_place != place:
        raise ValueError(
            f"Место в строке результата ({result_place}) не совпадает с итоговым ({place})."
        )

    return TournamentRecord(
        tournament_id=title_match.group("tournament_id"),
        tournament_name=title_match.group("tournament_name").strip(),
        buy_in_cents=money_to_cents(buy_in_match.group("value")),
        players=int(players_match.group("value")),
        prize_pool_cents=money_to_cents(prize_pool_match.group("value")),
        started_at=started_at,
        place=place,
        payout_cents=money_to_cents(result_line_match.group("payout")),
        hero_name=result_line_match.group("hero").strip(),
        source_archive=source_archive,
        source_file=source_file,
    )
