"""
ui.py — Componentes visuales personalizados para auto-report-mcp
Importar en cli.py: from ui import *
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Generator, Sequence

from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    DownloadColumn,
    MofNCompleteColumn,
    Progress,
    ProgressColumn,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
    Task,
)
from rich.rule import Rule
from rich.table import Table
from rich.text import Text
from rich.theme import Theme
from rich.live import Live
from rich.columns import Columns
from rich.markup import escape
from rich import box
import questionary

# ─────────────────────────────────────────────────────────────────
# THEME & CONSOLE
# ─────────────────────────────────────────────────────────────────

THEME = Theme(
    {
        "ok":       "bold bright_green",
        "warn":     "bold yellow",
        "err":      "bold red",
        "info":     "dim cyan",
        "accent":   "bold cyan",
        "muted":    "dim white",
        "label":    "dim",
        "value":    "white",
        "heading":  "bold white",
        "progress.bar":        "cyan",
        "progress.bar.done":   "bright_green",
        "progress.percentage": "bold cyan",
        "progress.elapsed":    "dim",
        "progress.spinner":    "cyan",
    }
)

console = Console(theme=THEME, highlight=False)

MENU_STYLE = questionary.Style(
    [
        ("qmark",       "fg:#00bfff bold"),
        ("question",    "bold"),
        ("answer",      "fg:#00bfff bold"),
        ("pointer",     "fg:#00bfff bold"),
        ("highlighted", "fg:#00bfff bold"),
        ("selected",    "fg:#00bfff"),
        ("separator",   "fg:#444444"),
        ("instruction", "fg:#555555"),
    ]
)


# ─────────────────────────────────────────────────────────────────
# HEADER
# ─────────────────────────────────────────────────────────────────

def header() -> None:
    console.print()
    console.print(
        Panel(
            Text.from_markup(
                "[bold white]auto-report-mcp[/bold white]  "
                "[dim]Generación de informes Word con IA + RAG + Google Drive[/dim]"
            ),
            border_style="cyan",
            padding=(0, 2),
        )
    )


def section(title: str) -> None:
    console.print()
    console.print(Rule(f"[heading]{title}[/heading]", style="dim"))
    console.print()


# ─────────────────────────────────────────────────────────────────
# STATUS MESSAGES
# ─────────────────────────────────────────────────────────────────

def print_ok(msg: str) -> None:
    console.print(f"  [ok]✓[/ok]  {msg}")


def print_warn(msg: str) -> None:
    console.print(f"  [warn]⚠[/warn]  {msg}")


def print_err(msg: str) -> None:
    console.print(f"  [err]✗[/err]  {msg}")


def print_info(msg: str) -> None:
    console.print(f"  [info]→[/info]  {msg}")


def print_suggestion(label: str, text: str) -> None:
    console.print(f"  [label]Sugerencia IA para {label}:[/label]")
    console.print(Panel(f"[muted]{escape(text)}[/muted]", border_style="dim", padding=(0, 2)))


def print_step(index: int, total: int, description: str) -> None:
    """Numbered step indicator."""
    console.print(
        f"  [dim cyan][ {index}/{total} ][/dim cyan]  [white]{description}[/white]"
    )


# ─────────────────────────────────────────────────────────────────
# CUSTOM PROGRESS COLUMN
# ─────────────────────────────────────────────────────────────────

class StepColumn(ProgressColumn):
    """Shows  '3 / 10 archivos'  next to the bar."""

    def __init__(self, unit: str = "items") -> None:
        super().__init__()
        self.unit = unit

    def render(self, task: Task) -> Text:
        if task.total is None:
            return Text("")
        completed = int(task.completed)
        total     = int(task.total)
        return Text(
            f"{completed} / {total} {self.unit}",
            style="dim cyan",
        )


# ─────────────────────────────────────────────────────────────────
# PROGRESS FACTORIES
# ─────────────────────────────────────────────────────────────────

def spinner_progress(description: str = "") -> Progress:
    """Simple indeterminate spinner — for operations without a known total."""
    return Progress(
        SpinnerColumn(spinner_name="dots", style="cyan"),
        TextColumn("[cyan]{task.description}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    )


def file_download_progress() -> Progress:
    """Progress bar for file downloads — shows count, bar, elapsed."""
    return Progress(
        SpinnerColumn(spinner_name="dots2", style="cyan"),
        TextColumn("[cyan]{task.description}"),
        BarColumn(
            bar_width=28,
            style="progress.bar",
            complete_style="progress.bar.done",
            finished_style="bright_green",
        ),
        StepColumn("archivos"),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    )


def image_sync_progress(total: int) -> Progress:
    """
    Dedicated bar for image sync — shows  N / total imágenes  + %.
    Usage:
        p = image_sync_progress(len(images))
        task = p.add_task("Sincronizando imágenes…", total=total)
        with p:
            for img in images:
                do_something(img)
                p.advance(task)
    """
    return Progress(
        SpinnerColumn(spinner_name="dots", style="cyan"),
        TextColumn("[cyan]{task.description}"),
        BarColumn(
            bar_width=30,
            style="progress.bar",
            complete_style="progress.bar.done",
            finished_style="bright_green",
        ),
        TaskProgressColumn(),
        StepColumn("imágenes"),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    )


def knowledge_progress() -> Progress:
    """Progress bar for knowledge ingestion — shows chunk count."""
    return Progress(
        SpinnerColumn(spinner_name="line", style="cyan"),
        TextColumn("[cyan]{task.description}"),
        BarColumn(
            bar_width=28,
            style="progress.bar",
            complete_style="progress.bar.done",
            finished_style="bright_green",
        ),
        StepColumn("chunks"),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    )


def generation_progress() -> Progress:
    """Multi-step progress bar for report generation pipeline."""
    return Progress(
        SpinnerColumn(spinner_name="aesthetic", style="cyan"),
        TextColumn("[cyan]{task.description:<40}"),
        BarColumn(
            bar_width=24,
            style="progress.bar",
            complete_style="bright_green",
            finished_style="bright_green",
        ),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    )


# ─────────────────────────────────────────────────────────────────
# CONTEXT MANAGERS (drop-in replacements for old spinner blocks)
# ─────────────────────────────────────────────────────────────────

@contextmanager
def spinning(description: str) -> Generator[None, None, None]:
    """
    Simple context manager — shows a spinner while the block runs.

    Usage:
        with spinning("Conectando con Google Drive…"):
            result = do_work()
    """
    with spinner_progress() as p:
        p.add_task(description, total=None)
        yield


@contextmanager
def downloading_files(
    file_list: Sequence,
    description: str = "Descargando archivos",
    unit: str = "archivos",
) -> Generator[Progress, None, None]:
    """
    Context manager that yields a pre-configured Progress object
    ready for file-by-file advancement.

    Usage:
        with downloading_files(files, "Descargando reportes") as (p, task):
            for f in files:
                fetch(f)
                p.advance(task)
    """
    p = file_download_progress()
    with p:
        task = p.add_task(description, total=len(file_list))
        yield p, task


# ─────────────────────────────────────────────────────────────────
# TABLES
# ─────────────────────────────────────────────────────────────────

def report_summary_table(report_id: str, output_path: str, message: str) -> None:
    """Render the generated-report summary box."""
    t = Table(
        box=box.ROUNDED,
        show_header=False,
        border_style="cyan",
        padding=(0, 2),
        expand=False,
    )
    t.add_column("Campo", style="label",  min_width=12, no_wrap=True)
    t.add_column("Valor", style="value")
    t.add_row("ID",       f"[accent]{report_id}[/accent]")
    t.add_row("Archivo",  output_path)
    t.add_row("Mensaje",  message)
    console.print()
    console.print(t)


def candidates_table(candidates: list[dict]) -> None:
    """Render the list-reports table."""
    t = Table(
        box=box.SIMPLE_HEAD,
        border_style="dim",
        show_edge=False,
        padding=(0, 2),
        header_style="bold dim",
    )
    t.add_column("#",      justify="right", style="dim", min_width=3)
    t.add_column("Nombre", style="white",   min_width=35)
    t.add_column("Fuente", style="cyan",    min_width=10)
    for i, c in enumerate(candidates, 1):
        badge = "[bright_yellow]☁ Drive[/bright_yellow]" if c["source"] == "drive" else "[green]💾 Local[/green]"
        t.add_row(str(i), c["name"], badge)
    console.print()
    console.print(t)


def backups_table(backups: list[dict]) -> None:
    """Render the knowledge backup list table."""
    t = Table(
        box=box.SIMPLE_HEAD,
        border_style="dim",
        show_edge=False,
        padding=(0, 2),
        header_style="bold dim",
    )
    t.add_column("#",       justify="right", style="dim", min_width=3)
    t.add_column("Archivo", style="white",   min_width=40)
    t.add_column("Fecha",   style="dim cyan", min_width=16)
    for i, b in enumerate(backups, 1):
        fecha = b.get("modifiedTime", "")[:10] if b.get("modifiedTime") else "—"
        t.add_row(str(i), b["name"], fecha)
    console.print()
    console.print(t)


def ingestion_results_table(results: dict[str, int]) -> None:
    """Show per-file ingestion chunk counts."""
    t = Table(
        box=box.SIMPLE,
        show_header=True,
        border_style="dim",
        padding=(0, 2),
        header_style="bold dim",
    )
    t.add_column("Archivo", style="white",    min_width=40)
    t.add_column("Chunks",  style="accent",   justify="right", min_width=8)
    for fname, count in results.items():
        t.add_row(fname, str(count))
    console.print()
    console.print(t)


# ─────────────────────────────────────────────────────────────────
# PANELS
# ─────────────────────────────────────────────────────────────────

def session_recovery_panel(summary: str) -> None:
    console.print()
    console.print(
        Panel(
            Text.from_markup(
                "[bold yellow]⚠  Sesión anterior encontrada[/bold yellow]\n"
                f"[dim]{summary}[/dim]\n\n"
                "Si el computador se apagó o trabó durante la generación de un informe, "
                "puedes retomar desde donde quedaste."
            ),
            border_style="yellow",
            padding=(1, 2),
        )
    )
    console.print()


def similar_notes_panel(similar: list[dict]) -> None:
    console.print()
    console.print(
        Panel(
            Text.from_markup(
                f"[bold yellow]⚠  Se encontraron {len(similar)} nota(s) relacionada(s)[/bold yellow]\n"
                "[dim]Puedes fusionarlas para mantener la base de conocimiento compacta y sin contradicciones.[/dim]"
            ),
            border_style="yellow",
            padding=(1, 2),
        )
    )


def answer_panel(answer: str) -> None:
    console.print()
    console.print(
        Panel(
            answer,
            border_style="dim",
            title="[dim]Respuesta[/dim]",
            padding=(1, 2),
        )
    )


def merged_note_panel(text: str) -> None:
    console.print()
    console.print("[dim]  Resultado de la fusión:[/dim]")
    console.print(Panel(f"[dim]{escape(text)}[/dim]", border_style="green", padding=(0, 2)))
    console.print()


def note_preview_panel(text: str) -> None:
    console.print()
    console.print("[dim]  Resumen generado:[/dim]")
    console.print(Panel(f"[dim]{escape(text)}[/dim]", border_style="cyan", padding=(0, 2)))
    console.print()


def document_preview_panel(name: str, preview: str) -> None:
    console.print()
    console.print(
        Panel(
            preview,
            title=f"[cyan]{escape(name)}[/cyan]",
            border_style="dim",
            padding=(1, 2),
        )
    )


# ─────────────────────────────────────────────────────────────────
# CASE HEADER
# ─────────────────────────────────────────────────────────────────

def case_rule(image_name: str, index: int, total: int, report_type: str = "functional_tests") -> None:
    """Decorative separator for each test-case in the guided flow."""
    type_badge = {
        "functional_tests":  "[cyan]Caja Negra[/cyan]",
        "integration_tests": "[cyan]Caja Negra[/cyan] + [yellow]Caja Blanca[/yellow]",
        "unit_tests":        "[yellow]Caja Blanca[/yellow]",
    }.get(report_type, "")

    console.print()
    console.print(
        Rule(
            f"[accent]Caso {index}/{total}[/accent]  ·  [white]{escape(image_name)}[/white]  {type_badge}",
            style="dim cyan",
        )
    )
    console.print()


# ─────────────────────────────────────────────────────────────────
# IMAGE SYNC HELPER
# ─────────────────────────────────────────────────────────────────

def sync_images_with_progress(images: list, sync_fn) -> None:
    """
    Run sync_fn(img) for each image in `images`, showing a rich progress bar.
    `sync_fn` receives the image Path object and should return nothing.
    If `images` is empty, sync_fn is called once with no args (bulk download).
    """
    if not images:
        with spinning("Sincronizando imágenes de evidencia…"):
            sync_fn()
        return

    p = image_sync_progress(len(images))
    task = p.add_task("Sincronizando imágenes de evidencia…", total=len(images))
    with p:
        for img in images:
            p.update(task, description=f"[cyan]{escape(img.name)}[/cyan]")
            sync_fn(img)
            p.advance(task)
    print_ok(f"{len(images)} imagen(es) sincronizada(s).")


# ─────────────────────────────────────────────────────────────────
# DRIVE DOWNLOAD HELPER
# ─────────────────────────────────────────────────────────────────

def download_files_with_progress(
    files: list,
    description: str,
    download_fn,
    unit: str = "archivos",
) -> list:
    """
    Show a rich progress bar while downloading `files`.
    `download_fn(f)` is called for each item and should return a Path or None.
    Returns list of successfully downloaded items (truthy return values).
    """
    downloaded = []
    p = file_download_progress()
    task = p.add_task(description, total=len(files))
    with p:
        for f in files:
            name = getattr(f, "name", str(f))
            p.update(task, description=f"{description}  [dim]({escape(name)})[/dim]")
            result = download_fn(f)
            if result:
                downloaded.append(result)
            p.advance(task)
    return downloaded


# ─────────────────────────────────────────────────────────────────
# KNOWLEDGE INGESTION HELPER
# ─────────────────────────────────────────────────────────────────

def ingest_with_progress(
    files: list,
    ingest_fn,
    description: str = "Ingiriendo en base de conocimiento…",
) -> dict[str, int]:
    """
    Ingest each file showing chunk counts.
    `ingest_fn(file)` → int (chunk count)
    Returns dict {filename: chunk_count}
    """
    results: dict[str, int] = {}
    p = knowledge_progress()
    task = p.add_task(description, total=len(files))
    with p:
        for f in files:
            name = getattr(f, "name", str(f))
            p.update(task, description=f"Ingiriendo [cyan]{escape(name)}[/cyan]…")
            count = ingest_fn(f)
            results[name] = count
            p.advance(task)
    return results


# ─────────────────────────────────────────────────────────────────
# QUERY SPINNER
# ─────────────────────────────────────────────────────────────────

@contextmanager
def querying_knowledge(description: str = "Consultando base de conocimiento…"):
    """Spinner context for RAG queries."""
    p = Progress(
        SpinnerColumn(spinner_name="dots2", style="cyan"),
        TextColumn(f"[cyan]{description}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    )
    with p:
        p.add_task("", total=None)
        yield


@contextmanager
def generating_ai(description: str = "Consultando IA…"):
    """Transient spinner for AI generation steps."""
    p = Progress(
        SpinnerColumn(spinner_name="line", style="dim cyan"),
        TextColumn(f"[dim]{description}[/dim]"),
        console=console,
        transient=True,
    )
    with p:
        p.add_task("", total=None)
        yield