import json
import re
from decimal import Decimal, InvalidOperation

MAX_CHAPTERS = 5
_CHAPTER = re.compile(r"^\d+(?:\.\d+)?$")
_INTEGER_RANGE = re.compile(r"^(\d+)\s*-\s*(\d+)$")


def normalize_chapter(value: str) -> str:
    value = str(value).strip().casefold()
    value = re.sub(r"^(?:manga/[^/]+/)?chapter[-\s]*", "", value)
    match = re.search(r"\d+(?:\.\d+)?", value)
    if not match:
        return value.strip("/ ")
    try:
        number = Decimal(match.group(0))
    except InvalidOperation:
        return match.group(0)
    return format(number.normalize(), "f")


def parse_chapters(value: str, maximum: int = MAX_CHAPTERS) -> list[str]:
    raw = value.strip()
    if not raw:
        raise ValueError("Chapter wajib diisi.")
    range_match = _INTEGER_RANGE.fullmatch(raw)
    if range_match:
        start, end = map(int, range_match.groups())
        if end < start:
            raise ValueError("Rentang chapter tidak boleh menurun.")
        chapters = [str(number) for number in range(start, end + 1)]
    else:
        parts = [part.strip() for part in raw.split(",")]
        if any(not part for part in parts):
            raise ValueError("Daftar chapter tidak boleh memiliki bagian kosong.")
        if any(not _CHAPTER.fullmatch(part) for part in parts):
            raise ValueError("Gunakan rentang `1-5` atau daftar seperti `1,3,7,8.5`.")
        chapters = [normalize_chapter(part) for part in parts]
    if len(chapters) > maximum:
        raise ValueError(f"Maksimal {maximum} chapter dalam satu tugas.")
    if len(set(chapters)) != len(chapters):
        raise ValueError("Chapter duplikat tidak diperbolehkan.")
    return chapters


def chapter_display(chapters: list[str]) -> str:
    if len(chapters) > 1 and all(item.isdigit() for item in chapters):
        numbers = [int(item) for item in chapters]
        if numbers == list(range(numbers[0], numbers[-1] + 1)):
            return f"{numbers[0]}-{numbers[-1]}"
    return ", ".join(chapters)


def chapters_json(chapters: list[str]) -> str:
    return json.dumps(chapters, ensure_ascii=False, separators=(",", ":"))


def chapters_from_assignment(assignment: dict) -> list[str]:
    raw = assignment.get("chapters")
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list) and parsed:
                return [normalize_chapter(item) for item in parsed]
        except (json.JSONDecodeError, TypeError):
            pass
    try:
        return parse_chapters(str(assignment.get("chapter") or ""))
    except ValueError:
        return [normalize_chapter(str(assignment.get("chapter") or ""))]
