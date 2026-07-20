from __future__ import annotations

import os
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from save_issues.github import (
    GitHubClient,
    GitHubError,
    parse_issue_numbers,
    parse_issue_target,
    parse_repo,
)
from save_issues.package import write_issue_zip

console = Console(stderr=True)


def _resolve_token(explicit: str | None) -> str | None:
    if explicit:
        return explicit
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.argument("target", required=False)
@click.argument("issues", nargs=-1)
@click.option(
    "--repo",
    "-r",
    "repo_opt",
    help="Repository as owner/repo (or URL). Required when TARGET is not a URL.",
)
@click.option(
    "--token",
    "-t",
    default=None,
    help="GitHub token. Defaults to GITHUB_TOKEN or GH_TOKEN.",
)
@click.option(
    "--output",
    "-o",
    "output_dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("issues"),
    show_default=True,
    help="Directory for zip files.",
)
@click.option(
    "--state",
    type=click.Choice(["open", "closed", "all"], case_sensitive=False),
    default="all",
    show_default=True,
    help="When fetching all issues, filter by state.",
)
@click.option(
    "--labels",
    default=None,
    help="Comma-separated labels filter when fetching all issues.",
)
@click.option(
    "--limit",
    type=int,
    default=None,
    help="Max issues when fetching all.",
)
@click.option(
    "--all",
    "fetch_all",
    is_flag=True,
    help="Fetch all issues in the repository (skips PRs).",
)
@click.option(
    "--events/--no-events",
    default=True,
    show_default=True,
    help="Include issue timeline events (labeled, closed, etc.).",
)
@click.option(
    "--topic",
    default=None,
    help="Base filename inside zip (default: slugified issue title).",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="List targets without downloading.",
)
def main(
    target: str | None,
    issues: tuple[str, ...],
    repo_opt: str | None,
    token: str | None,
    output_dir: Path,
    state: str,
    labels: str | None,
    limit: int | None,
    fetch_all: bool,
    events: bool,
    topic: str | None,
    dry_run: bool,
) -> None:
    """Save GitHub issues as zip archives.

    \b
    Examples:
      save-issues https://github.com/owner/repo/issues/42
      save-issues owner/repo 1 2 5-10
      save-issues owner/repo --all
      save-issues -r owner/repo 123 --output ./out
    """
    auth = _resolve_token(token)
    owner: str | None = None
    repo: str | None = None
    numbers: list[int] = []

    try:
        if target:
            url_ref = parse_issue_target(target)
            if url_ref is not None:
                owner, repo = url_ref.owner, url_ref.repo
                numbers = [url_ref.number]
                if issues:
                    numbers.extend(parse_issue_numbers(list(issues)))
            else:
                owner, repo = parse_repo(target)
                if issues:
                    numbers = parse_issue_numbers(list(issues))
        elif repo_opt:
            owner, repo = parse_repo(repo_opt)
            if issues:
                numbers = parse_issue_numbers(list(issues))
        else:
            raise click.UsageError(
                "Provide a repo (owner/repo), an issue URL, or use --repo."
            )

        if repo_opt and target and parse_issue_target(target) is None:
            # allow override only when target was not a full issue URL
            owner, repo = parse_repo(repo_opt)

        if not owner or not repo:
            raise click.UsageError("Could not resolve owner/repo.")

        if not numbers and not fetch_all:
            raise click.UsageError(
                "Provide issue numbers, an issue URL, or pass --all."
            )

        with GitHubClient(token=auth) as client:
            if fetch_all:
                console.print(
                    f"[cyan]Listing issues[/] for [bold]{owner}/{repo}[/] "
                    f"(state={state})..."
                )
                numbers = client.list_issue_numbers(
                    owner, repo, state=state, labels=labels, limit=limit
                )
                if not numbers:
                    console.print("[yellow]No issues found.[/]")
                    return

            # de-dupe preserving order
            seen: set[int] = set()
            unique_numbers: list[int] = []
            for n in numbers:
                if n not in seen:
                    seen.add(n)
                    unique_numbers.append(n)
            numbers = unique_numbers

            console.print(
                f"[bold]{len(numbers)}[/] issue(s) from "
                f"[bold]{owner}/{repo}[/] → [bold]{output_dir}[/]"
            )

            if dry_run:
                for n in numbers:
                    console.print(f"  would save #{n}")
                return

            ok = 0
            failed = 0
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("{task.completed}/{task.total}"),
                TimeElapsedColumn(),
                console=console,
            ) as progress:
                task = progress.add_task("Saving", total=len(numbers))
                for number in numbers:
                    progress.update(task, description=f"#{number}")
                    try:
                        data = client.fetch_issue(
                            owner, repo, number, include_events=events
                        )
                        path = write_issue_zip(data, output_dir, topic=topic)
                        console.print(f"[green]✓[/] #{number} → {path}")
                        ok += 1
                    except GitHubError as exc:
                        console.print(f"[red]✗[/] #{number}: {exc}")
                        failed += 1
                    except Exception as exc:  # noqa: BLE001
                        console.print(f"[red]✗[/] #{number}: {exc}")
                        failed += 1
                    progress.advance(task)

            console.print(f"[bold]Done.[/] saved={ok} failed={failed}")
            if failed:
                sys.exit(1)

    except (ValueError, GitHubError) as exc:
        console.print(f"[red]Error:[/] {exc}")
        sys.exit(1)
