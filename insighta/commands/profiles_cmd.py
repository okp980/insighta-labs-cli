"""`profiles` subcommands: list / get / search / create / export."""

from __future__ import annotations

from typing import Any

import typer

from insighta.api_client import ApiClient
from insighta.credentials import require_credentials
from insighta.errors import InsightaApiError, InsightaError
from insighta.ui.spinners import console, err_console, loader
from insighta.ui.tables import profile_detail_table, profiles_table

profiles_app = typer.Typer(
    name="profiles",
    help="Browse, search, create, and export profiles.",
    no_args_is_help=True,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _coerce_envelope(payload: Any, *, plural: bool) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise InsightaError("Unexpected response shape from the backend.")
    return payload


def _pagination_footer(payload: dict[str, Any]) -> str:
    page = payload.get("page")
    total_pages = payload.get("total_pages")
    total = payload.get("total")
    limit = payload.get("limit")
    parts: list[str] = []
    if page is not None and total_pages is not None:
        parts.append(f"page {page}/{total_pages or 1}")
    if total is not None:
        parts.append(f"total {total}")
    if limit is not None:
        parts.append(f"limit {limit}")
    return "  \u00b7  ".join(parts)


def _build_list_params(
    *,
    page: int,
    limit: int,
    gender: str | None,
    country: str | None,
    age_group: str | None,
    min_age: int | None,
    max_age: int | None,
    sort_by: str | None,
    order: str | None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"page": page, "limit": limit}
    if gender:
        params["gender"] = gender
    if country:
        params["country_id"] = country
    if age_group:
        params["age_group"] = age_group
    if min_age is not None:
        params["min_age"] = min_age
    if max_age is not None:
        params["max_age"] = max_age
    if sort_by:
        params["sort_by"] = sort_by
    if order:
        params["order"] = order
    return params


# ---------------------------------------------------------------------------
# `profiles list`
# ---------------------------------------------------------------------------
@profiles_app.command("list", help="List profiles with optional filters and sorting.")
def list_profiles(
    gender: str | None = typer.Option(
        None, "--gender", help="Filter by gender (male|female).", case_sensitive=False
    ),
    country: str | None = typer.Option(
        None,
        "--country",
        help="Filter by ISO country code (e.g. NG, US).",
        case_sensitive=False,
    ),
    age_group: str | None = typer.Option(
        None,
        "--age-group",
        help="Filter by age group (child|teenager|adult|senior).",
        case_sensitive=False,
    ),
    min_age: int | None = typer.Option(None, "--min-age", help="Minimum age."),
    max_age: int | None = typer.Option(None, "--max-age", help="Maximum age."),
    sort_by: str | None = typer.Option(
        None,
        "--sort-by",
        help="Sort key (age|created_at|gender_probability).",
    ),
    order: str | None = typer.Option(
        None, "--order", help="Sort order (asc|desc).", case_sensitive=False
    ),
    page: int = typer.Option(1, "--page", help="Page number (1-indexed)."),
    limit: int = typer.Option(10, "--limit", help="Items per page (max 50)."),
) -> None:
    require_credentials()
    params = _build_list_params(
        page=page,
        limit=limit,
        gender=gender.lower() if gender else None,
        country=country.upper() if country else None,
        age_group=age_group.lower() if age_group else None,
        min_age=min_age,
        max_age=max_age,
        sort_by=sort_by.lower() if sort_by else None,
        order=order.lower() if order else None,
    )

    with ApiClient() as client:
        with loader("Fetching profiles..."):
            payload = client.get_json("/api/profiles/", params=params)

    payload = _coerce_envelope(payload, plural=True)
    rows = payload.get("data") or []
    if not rows:
        console.print("[yellow]No profiles match those filters.[/]")
        return

    console.print(profiles_table(rows))
    footer = _pagination_footer(payload)
    if footer:
        console.print(f"[dim]{footer}[/]")


# ---------------------------------------------------------------------------
# `profiles get <id>`
# ---------------------------------------------------------------------------
@profiles_app.command("get", help="Show a single profile by id.")
def get_profile(profile_id: str = typer.Argument(..., metavar="ID")) -> None:
    require_credentials()
    with ApiClient() as client:
        with loader("Fetching profile..."):
            try:
                payload = client.get_json(f"/api/profiles/{profile_id}")
            except InsightaApiError as exc:
                if exc.status == 404:
                    err_console.print(f"[yellow]No profile with id {profile_id!r}.[/]")
                    raise typer.Exit(code=1) from exc
                raise

    if not isinstance(payload, dict):
        raise InsightaError("Unexpected response shape from /api/profiles/{id}.")
    profile = payload.get("data") or {}
    if not profile:
        raise InsightaError("Backend returned an empty profile.")
    console.print(profile_detail_table(profile))


# ---------------------------------------------------------------------------
# `profiles search`
# ---------------------------------------------------------------------------
@profiles_app.command("search", help='Natural-language search, e.g. "young males from nigeria".')
def search_profiles(
    query: str = typer.Argument(..., metavar="QUERY"),
    page: int = typer.Option(1, "--page", help="Page number (1-indexed)."),
    limit: int = typer.Option(10, "--limit", help="Items per page (max 50)."),
) -> None:
    require_credentials()
    params: dict[str, Any] = {"q": query, "page": page, "limit": limit}
    with ApiClient() as client:
        with loader(f"Searching for {query!r}..."):
            try:
                payload = client.get_json("/api/profiles/search", params=params)
            except InsightaApiError as exc:
                if exc.status == 404:
                    console.print("[yellow]No profiles match that query.[/]")
                    return
                if exc.status == 400:
                    console.print(f"[yellow]Could not interpret query:[/] {exc.message}")
                    return
                raise

    payload = _coerce_envelope(payload, plural=True)
    rows = payload.get("data") or []
    if not rows:
        console.print("[yellow]No profiles match that query.[/]")
        return

    console.print(profiles_table(rows, title=f'Search: "{query}"'))
    footer = _pagination_footer(payload)
    if footer:
        console.print(f"[dim]{footer}[/]")


# ---------------------------------------------------------------------------
# `profiles create`
# ---------------------------------------------------------------------------
@profiles_app.command(
    "create",
    help='Create a profile from a name (admin only). Example: --name "Harriet Tubman".',
)
def create_profile(
    name: str = typer.Option(..., "--name", help="Full name to enrich and store."),
) -> None:
    require_credentials()
    name = name.strip()
    if not name:
        raise InsightaError("--name cannot be empty.")

    with ApiClient() as client:
        try:
            with loader(f"Creating profile for {name!r}..."):
                payload = client.post_json("/api/profiles/", json={"name": name})
        except InsightaApiError as exc:
            if exc.status == 403:
                err_console.print(
                    "[red]Forbidden:[/] only admins can create profiles. "
                    "Ask an admin to grant your account the [bold]admin[/] role."
                )
                raise typer.Exit(code=1) from exc
            if exc.status in {502, 504}:
                err_console.print(
                    f"[red]Upstream enrichment failed[/] ({exc.status}): {exc.message}"
                )
                raise typer.Exit(code=1) from exc
            raise

    if not isinstance(payload, dict):
        raise InsightaError("Unexpected response from /api/profiles/ POST.")
    profile = payload.get("data") or {}
    if not profile:
        raise InsightaError("Backend returned an empty profile.")

    message = payload.get("message")
    if message:
        console.print(f"[yellow]\u2139[/] {message}")
    else:
        console.print(f"[green]\u2713[/] Created profile for [bold]{name}[/].")
    console.print(profile_detail_table(profile))
