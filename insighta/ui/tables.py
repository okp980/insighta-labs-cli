"""Rich table renderers for profile data."""

from __future__ import annotations

from typing import Any, Iterable

from rich.table import Table


def _fmt_pct(value: Any) -> str:
    if value is None:
        return ""
    try:
        return f"{float(value) * 100:.0f}%" if float(value) <= 1 else f"{float(value):.0f}%"
    except (TypeError, ValueError):
        return str(value)


def _short_id(value: Any) -> str:
    if value is None:
        return ""
    s = str(value)
    return f"{s[:8]}\u2026" if len(s) > 12 else s


def profiles_table(profiles: Iterable[dict[str, Any]], *, title: str | None = None) -> Table:
    table = Table(
        title=title,
        title_style="bold",
        header_style="bold cyan",
        row_styles=["", "dim"],
        show_lines=False,
        expand=True,
    )
    table.add_column("ID", no_wrap=True)
    table.add_column("Name")
    table.add_column("Gender", justify="center")
    table.add_column("Age", justify="right")
    table.add_column("Group", justify="center")
    table.add_column("Country")
    table.add_column("Gender %", justify="right")
    table.add_column("Country %", justify="right")

    for profile in profiles:
        table.add_row(
            _short_id(profile.get("id")),
            str(profile.get("name") or ""),
            str(profile.get("gender") or ""),
            str(profile.get("age") if profile.get("age") is not None else ""),
            str(profile.get("age_group") or ""),
            str(profile.get("country_name") or profile.get("country_id") or ""),
            _fmt_pct(profile.get("gender_probability")),
            _fmt_pct(profile.get("country_probability")),
        )
    return table


def profile_detail_table(profile: dict[str, Any]) -> Table:
    table = Table(
        show_header=False,
        title="Profile",
        title_style="bold",
        box=None,
        pad_edge=False,
    )
    table.add_column("field", style="bold cyan", no_wrap=True)
    table.add_column("value")

    fields = [
        ("ID", str(profile.get("id") or "")),
        ("Name", str(profile.get("name") or "")),
        ("Gender", str(profile.get("gender") or "")),
        ("Gender confidence", _fmt_pct(profile.get("gender_probability"))),
        ("Age", str(profile.get("age") if profile.get("age") is not None else "")),
        ("Age group", str(profile.get("age_group") or "")),
        ("Country", str(profile.get("country_name") or "")),
        ("Country code", str(profile.get("country_id") or "")),
        ("Country confidence", _fmt_pct(profile.get("country_probability"))),
        ("Created at", str(profile.get("created_at") or "")),
    ]
    for label, value in fields:
        table.add_row(label, value)
    return table
