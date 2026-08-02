"""Shared Rich console and logging helpers for CLI output.

Centralises all terminal styling so commands emit consistent, readable
output: section headers, status lines, warnings, and progress bars.
"""

from contextlib import contextmanager

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.theme import Theme

_THEME = Theme(
    {
        "info": "cyan",
        "step": "bold cyan",
        "success": "bold green",
        "warning": "bold yellow",
        "error": "bold red",
        "detail": "dim",
        "path": "italic blue",
        "metric": "bold magenta",
    }
)

console = Console(theme=_THEME)


def rule(title: str) -> None:
    """Print a horizontal section header."""
    console.rule(f"[step]{title}[/step]", style="cyan")


def step(message: str) -> None:
    """A primary progress step (arrow-prefixed)."""
    console.print(f"[step]→[/step] {message}")


def success(message: str) -> None:
    """A successful, completed action."""
    console.print(f"[success]✓[/success] {message}")


def warning(message: str) -> None:
    """A non-fatal warning."""
    console.print(f"[warning]⚠[/warning] {message}")


def error(message: str) -> None:
    """A fatal error."""
    console.print(f"[error]✗[/error] {message}")


def detail(message: str) -> None:
    """Secondary, dimmed detail line."""
    console.print(f"  [detail]{message}[/detail]")


def saved(label: str, path) -> None:
    """Report that a file was written to disk."""
    console.print(f"  [success]✓[/success] {label}: [path]{path}[/path]")


@contextmanager
def progress_bar(transient: bool = False):
    """A configured determinate progress bar (spinner + bar + count + ETA)."""
    progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=None),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
        transient=transient,
    )
    with progress:
        yield progress


@contextmanager
def status(message: str):
    """A spinner for indeterminate work (e.g. network downloads)."""
    with console.status(f"[info]{message}[/info]", spinner="dots") as st:
        yield st
