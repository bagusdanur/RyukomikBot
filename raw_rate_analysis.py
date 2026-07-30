"""Small, deterministic helpers for RAW workload based pay-rate suggestions."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RawWorkload:
    page_count: int
    measured_pages: int
    total_height: int
    max_height: int
    tall_pages: int


def classify_workload(workload: RawWorkload) -> tuple[str, int, str]:
    """Return (label, level, human readable reason); level is 0..2.

    Page count is always authoritative. Height data is only used when it was
    actually read, so a temporarily inaccessible image cannot inflate pay.
    """
    page_level = 0 if workload.page_count <= 15 else 1 if workload.page_count <= 25 else 2
    average_height = workload.total_height // workload.measured_pages if workload.measured_pages else 0
    height_level = 0
    if workload.max_height > 16_000 or workload.tall_pages >= 4 or average_height > 10_000:
        height_level = 2
    elif workload.max_height > 8_192 or workload.tall_pages or average_height > 5_500:
        height_level = 1
    level = max(page_level, height_level)
    labels = ("Ringan", "Sedang", "Berat")
    reason = f"{workload.page_count} halaman"
    if workload.measured_pages:
        reason += f", tinggi maks. {workload.max_height:,} px"
        if workload.tall_pages:
            reason += f", {workload.tall_pages} gambar vertikal panjang"
    return labels[level], level, reason


def suggested_rate(minimum: int, maximum: int, workload: RawWorkload) -> int:
    """Suggest conservatively; a single tall page must not jump to max rate."""
    average_height = workload.total_height // workload.measured_pages if workload.measured_pages else 0
    score = 0.0
    if workload.page_count > 15:
        score += 0.20
    if workload.page_count > 20:
        score += 0.16
    if workload.page_count > 25:
        score += 0.20
    if workload.max_height > 8_192:
        score += 0.10
    if workload.tall_pages >= 2:
        score += 0.10
    if average_height > 6_500:
        score += 0.10
    if workload.max_height > 16_000 or average_height > 10_000:
        score += 0.15
    # A short chapter is still short. Even several vertical pages should only
    # nudge its rate, not make it equal to a genuinely long package.
    if workload.page_count <= 15:
        score = min(score, 0.22)
    target = minimum + (maximum - minimum) * min(score, 0.90)
    return max(minimum, min(maximum, int(round(target / 500.0) * 500)))
