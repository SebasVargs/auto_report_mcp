#!/usr/bin/env python3
"""
auto-report-mcp — CLI interactivo
Ejecutar: python cli.py
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import questionary
from rich import print as rprint
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.rule import Rule
from rich.text import Text
from rich import box

console = Console()

from app.services.session_manager import ReportSessionManager

# ─────────────────────────────────────────────────────────────────
# STYLE
# ─────────────────────────────────────────────────────────────────

MENU_STYLE = questionary.Style([
   ("qmark",       "fg:#00bfff bold"),
   ("question",    "bold"),
   ("answer",      "fg:#00bfff bold"),
   ("pointer",     "fg:#00bfff bold"),
   ("highlighted", "fg:#00bfff bold"),
   ("selected",    "fg:#00bfff"),
   ("separator",   "fg:#444444"),
   ("instruction", "fg:#555555"),
])

def header():
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

def print_ok(msg: str):
   rprint(f"[bold green]  ✓[/bold green]  {msg}")

def print_warn(msg: str):
   rprint(f"[bold yellow]  ⚠[/bold yellow]  {msg}")

def print_err(msg: str):
   rprint(f"[bold red]  ✗[/bold red]  {msg}")

def print_info(msg: str):
   rprint(f"[dim]  →[/dim]  {msg}")

def print_suggestion(label: str, text: str):
   console.print(f"  [dim]Sugerencia IA para {label}:[/dim]")
   console.print(Panel(f"[dim]{text}[/dim]", border_style="dim", padding=(0, 2)))

def section(title: str):
   console.print()
   console.print(Rule(f"[bold white]{title}[/bold white]", style="dim"))
   console.print()

# ─────────────────────────────────────────────────────────────────
# ACTIONS
# ─────────────────────────────────────────────────────────────────

def action_drive_sync():
   section("Sincronizar desde Google Drive")
   from app.config import get_settings
   settings = get_settings()

   if not settings.drive_enabled:
       print_warn("Drive no está habilitado. Activa DRIVE_ENABLED=true en .env")
       return

   with Progress(SpinnerColumn(), TextColumn("[cyan]{task.description}"), console=console) as p:
       task = p.add_task("Conectando con Google Drive...", total=None)
       try:
           from app.services.drive_service import DriveService
           svc = DriveService()
           p.update(task, description="Descargando archivos nuevos...")
           downloaded = svc.sync_raw_reports()
           p.stop()
           if downloaded:
               print_ok(f"{len(downloaded)} archivo(s) descargado(s):")
               for f in downloaded:
                   rprint(f"     [green]{f.name}[/green]")
           else:
               print_info("No hay archivos nuevos en Drive.")
       except Exception as e:
           p.stop()
           print_err(f"Error de Drive: {e}")

def _pick_report_type() -> str:
   return questionary.select(
       "Tipo de informe:",
       choices=[
           questionary.Separator("  ── Pruebas de Software ──"),
           questionary.Choice("  Pruebas funcionales      (Caja Negra)",              value="functional_tests"),
           questionary.Choice("  Pruebas de integración  (Caja Negra + Blanca)",     value="integration_tests"),
           questionary.Choice("  Pruebas unitarias        (Caja Blanca)",             value="unit_tests"),
           questionary.Separator("  ── Proyecto ──"),
           questionary.Choice("  Avance de proyecto",                                 value="project_progress"),
       ],
       style=MENU_STYLE,
   ).ask()

def _pick_date() -> date:
   choice = questionary.select(
       "Fecha del informe:",
       choices=[
           questionary.Choice("Hoy",        value="today"),
           questionary.Choice("Ayer",        value="yesterday"),
           questionary.Choice("Otra fecha…", value="custom"),
       ],
       style=MENU_STYLE,
   ).ask()

   if choice == "today":
       return date.today()
   if choice == "yesterday":
       return date.today() - timedelta(days=1)

   raw = questionary.text(
       "Fecha (YYYY-MM-DD):",
       validate=lambda v: True if _is_valid_date(v) else "Formato inválido. Usa YYYY-MM-DD",
       style=MENU_STYLE,
   ).ask()
   return date.fromisoformat(raw)

def _is_valid_date(s: str) -> bool:
   try:
       date.fromisoformat(s)
       return True
   except ValueError:
       return False

# ─────────────────────────────────────────────────────────────────
# INTERACTIVE GUIDED NARRATIVE
# ─────────────────────────────────────────────────────────────────

def _collect_test_case_guided(
   image_name: str,
   case_index: int,
   assistant,
   report_type: str = "functional_tests",
) -> dict:
   from app.services.interactive_narrative_assistant import (
       TestCaseDraft, get_sections_for_type, LIST_SECTIONS, NUMERIC_SECTIONS,
       parse_list_suggestion,
   )

   SECTIONS = get_sections_for_type(report_type)

   type_header = {
       "functional_tests":  "[cyan]Caja Negra[/cyan]",
       "integration_tests": "[cyan]Caja Negra[/cyan] + [yellow]Caja Blanca[/yellow]",
       "unit_tests":        "[yellow]Caja Blanca[/yellow]",
   }.get(report_type, "")

   console.print()
   console.print(Rule(
       f"[cyan]Caso {case_index}  ·  {image_name}[/cyan]  {type_header}",
       style="dim cyan",
   ))
   console.print()

   draft = TestCaseDraft()

   draft.module = questionary.text("  Módulo evaluado:", style=MENU_STYLE).ask() or ""
   draft.test_name = questionary.text(
       "  Nombre del caso (ej. CP-01: Login con credenciales válidas):",
       style=MENU_STYLE,
   ).ask() or ""

   console.print()
   print_info("Consultando historial del proyecto para generar sugerencias…")

   for section_key, section_label in SECTIONS:
       console.print()
       console.print(f"  [bold]{section_label}[/bold]")

       with Progress(
           SpinnerColumn(),
           TextColumn("[dim]  Generando sugerencia…[/dim]"),
           console=console,
           transient=True,
       ) as p:
           p.add_task("", total=None)
           suggestion = assistant.get_suggestion(section_key, draft, report_type=report_type)

       is_list    = section_key in LIST_SECTIONS
       is_numeric = section_key in NUMERIC_SECTIONS

       if suggestion:
           display_suggestion = suggestion.strip()
           print_suggestion(section_label, display_suggestion)
           use_suggestion = questionary.confirm(
               "  ¿Usar esta sugerencia?",
               default=True,
               style=MENU_STYLE,
           ).ask()
           if not use_suggestion:
               display_suggestion = ""
       else:
           display_suggestion = ""

       if is_list:
           user_input = questionary.text(
               f"  {section_label}:",
               default=display_suggestion,
               multiline=True,
               style=MENU_STYLE,
           ).ask() or display_suggestion
           value = parse_list_suggestion(user_input) if user_input.strip() else []

       elif is_numeric:
           raw_num = questionary.text(
               f"  {section_label} (solo número):",
               default=display_suggestion or "0",
               style=MENU_STYLE,
           ).ask() or "0"
           try:
               value = float(raw_num.strip().rstrip("%"))
           except ValueError:
               value = 0.0

       elif section_key == "status":
           status_default = (
               display_suggestion.strip().upper()
               if display_suggestion.strip().upper() in ("PASS", "FAIL", "BLOCKED")
               else "PASS"
           )
           value = questionary.select(
               f"  {section_label}:",
               choices=[
                   questionary.Choice("PASS",    value="PASS"),
                   questionary.Choice("FAIL",    value="FAIL"),
                   questionary.Choice("BLOCKED", value="BLOCKED"),
               ],
               default=status_default,
               style=MENU_STYLE,
           ).ask()

       else:
           user_input = questionary.text(
               f"  {section_label}:",
               default=display_suggestion,
               multiline=True,
               style=MENU_STYLE,
           ).ask() or display_suggestion
           value = user_input.strip()

       setattr(draft, section_key, value)

   return draft.to_dict()

def _collect_narratives_guided(
   images: list[Path],
   metadata: dict,
   session: ReportSessionManager | None = None,
   prefilled_cases: list[dict] | None = None,
) -> list[dict]:
   from app.services.interactive_narrative_assistant import InteractiveNarrativeAssistant

   report_type    = metadata.get("report_type", "functional_tests")
   prefilled      = prefilled_cases or []
   prefilled_names = {tc.get("evidence_image_filename") for tc in prefilled}
   pending_images = [img for img in images if img.name not in prefilled_names]
   image_names    = [img.name for img in images]

   console.print()
   if prefilled:
       print_ok(f"Retomando sesión — {len(prefilled)} caso(s) ya completado(s), {len(pending_images)} pendiente(s).")
   else:
       print_info(f"Modo asistido activado — {len(images)} imagen(es) detectada(s).")
   console.print("[dim]  El sistema consultará el historial del proyecto para sugerir cada sección.[/dim]")

   assistant  = InteractiveNarrativeAssistant()
   test_cases = list(prefilled)

   for img in pending_images:
       global_index = image_names.index(img.name) + 1
       tc = _collect_test_case_guided(img.name, global_index, assistant, report_type=report_type)
       tc["evidence_image_filename"] = img.name
       tc["test_id"]      = str(global_index)
       tc["prepared_by"]  = metadata.get("prepared_by", "")
       tc["tested_by"]    = metadata.get("prepared_by", "")
       tc["prepare_date"] = metadata.get("report_date", "")
       tc["test_date"]    = metadata.get("report_date", "")
       test_cases.append(tc)

       if session:
           session.save(metadata, image_names, test_cases)
           print_info(f"  Progreso guardado ({len(test_cases)}/{len(images)})")

   return test_cases

def _build_daily_input_from_test_cases(test_cases: list[dict], metadata: dict) -> dict:
   return {
       "report_date":     metadata["report_date"],
       "report_type":     metadata.get("report_type", "functional_tests"),
       "project_name":    metadata["project_name"],
       "environment":     metadata["environment"],
       "prepared_by":     metadata["prepared_by"],
       "project_version": metadata.get("project_version", ""),
       "test_cases":      test_cases,
       "tasks":           [],
       "general_notes":   "",
       "risks":           [],
       "next_steps":      [],
   }

# ─────────────────────────────────────────────────────────────────
# GENERATE REPORT
# ─────────────────────────────────────────────────────────────────

def action_generate():
   section("Generar informe")

   # ── Session recovery check ───────────────────────────────────
   session = ReportSessionManager()
   prefilled_cases: list[dict] = []
   session_metadata: dict = {}

   if session.exists():
       console.print()
       console.print(
           Panel(
               Text.from_markup(
                   "[bold yellow]⚠  Sesión anterior encontrada[/bold yellow]\n"
                   f"[dim]{session.summary()}[/dim]\n\n"
                   "Si el computador se apagó o trabó durante la generación de un informe, "
                   "puedes retomar desde donde quedaste."
               ),
               border_style="yellow",
               padding=(1, 2),
           )
       )
       console.print()
       recovery_choice = questionary.select(
           "¿Qué deseas hacer?",
           choices=[
               questionary.Choice("  ↩  Retomar sesión anterior",    value="resume"),
               questionary.Choice("  ✗  Empezar desde cero",         value="fresh"),
           ],
           style=MENU_STYLE,
       ).ask()

       if recovery_choice == "resume":
           data = session.load()
           prefilled_cases  = data.get("completed_cases", [])
           session_metadata = data.get("metadata", {})
           print_ok(f"Retomando — {len(prefilled_cases)} caso(s) ya registrado(s).")
       else:
           session.clear()
           print_info("Sesión anterior descartada. Empezando desde cero.")
   # ────────────────────────────────────────────────────────────

   # If resuming, skip date/type/method questions and go straight
   # to collecting the remaining images.
   if prefilled_cases and session_metadata:
       report_date  = session_metadata.get("report_date", str(date.today()))
       report_type  = session_metadata.get("report_type", "functional_tests")
       input_method = "ai"  # resumed sessions always came from the AI path
   else:
       report_date = _pick_date()
       report_type = _pick_report_type()

       console.print()
       rprint(f"  [dim]Fecha:[/dim] [bold]{report_date}[/bold]   [dim]Tipo:[/dim] [bold]{report_type}[/bold]")
       console.print()

       input_method = questionary.select(
           "Origen de datos:",
           choices=[
               questionary.Choice("Describir en texto libre  (la IA genera el JSON)", value="ai"),
               questionary.Choice("Usar JSON existente        (Drive / local)",        value="file"),
           ],
           style=MENU_STYLE,
       ).ask()

   if input_method == "ai":
       from app.services.ai_service import AIService
       from app.services.data_service import DataService
       from app.config import get_settings

       settings = get_settings()

       if prefilled_cases and session_metadata:
           # Restore metadata from the saved session
           metadata     = session_metadata
           project_name = metadata.get("project_name", "")
           environment  = metadata.get("environment", "QA")
           prepared_by  = metadata.get("prepared_by", "")
       else:
           console.print()
           console.print(Rule("[dim]Datos del informe[/dim]", style="dim"))
           console.print()

           project_name = questionary.text("  Nombre del proyecto:", default="Proyecto Default", style=MENU_STYLE).ask()
           environment  = questionary.text("  Ambiente:",            default="QA",              style=MENU_STYLE).ask()
           prepared_by  = questionary.text("  Preparado por:",       default="QA Engineer",     style=MENU_STYLE).ask()

           metadata = {
               "report_date":  str(report_date),
               "report_type":  report_type,
               "project_name": project_name,
               "environment":  environment,
               "prepared_by":  prepared_by,
           }

       images: list[Path] = []
       _TEST_TYPES = ("functional_tests", "integration_tests", "unit_tests")

       if report_type in _TEST_TYPES:
           if settings.drive_enabled and getattr(settings, "drive_input_images_folder_id", ""):
               try:
                   from app.services.drive_service import DriveService
                   console.print()
                   print_info("Sincronizando imágenes de evidencia desde Google Drive…")
                   with Progress(SpinnerColumn(), TextColumn("[cyan]{task.description}"), console=console) as p:
                       p.add_task("Descargando imágenes...", total=None)
                       DriveService().sync_input_images()
               except Exception as e:
                   print_warn(f"No se pudieron sincronizar imágenes de Drive: {e}")

           if settings.input_images_path.exists():
               images = sorted(
                   f for f in settings.input_images_path.iterdir()
                   if f.is_file() and f.suffix.lower() in (".png", ".jpg", ".jpeg")
               )

       ai = AIService()

       if images and report_type in _TEST_TYPES:
           test_cases       = _collect_narratives_guided(
               images, metadata, session=session, prefilled_cases=prefilled_cases
           )
           daily_input_dict = _build_daily_input_from_test_cases(test_cases, metadata)

           with Progress(SpinnerColumn(), TextColumn("[cyan]{task.description}"), console=console) as p:
               p.add_task("Validando y guardando JSON estructurado…", total=None)
               try:
                   from app.models.report_model import DailyInput
                   normalized  = AIService._normalize_daily_input_json(daily_input_dict, metadata)
                   daily_input = DailyInput.model_validate(normalized)
                   DataService().save_daily_input(daily_input)
                   p.stop()
                   print_ok("JSON estructurado guardado exitosamente.")
               except Exception as e:
                   p.stop()
                   print_err(f"Error al guardar: {e}")
                   return

       elif not images and report_type in _TEST_TYPES:
           console.print()
           console.print("[dim]  No se encontraron imágenes. Describe las pruebas en texto libre.[/dim]")
           console.print()
           user_text = questionary.text("  Narrativa:", multiline=True, style=MENU_STYLE).ask()

           with Progress(SpinnerColumn(), TextColumn("[cyan]{task.description}"), console=console) as p:
               p.add_task("Analizando texto y generando JSON…", total=None)
               try:
                   daily_input = ai.extract_daily_input(user_text, metadata)
                   DataService().save_daily_input(daily_input)
                   p.stop()
                   print_ok("JSON estructurado generado exitosamente.")
               except Exception as e:
                   p.stop()
                   print_err(f"Error al procesar el texto: {e}")
                   return
       else:
           console.print()
           console.print("[dim]  Describe el avance del proyecto, tareas completadas, bloqueos y riesgos.[/dim]")
           console.print()
           user_text = questionary.text("  Narrativa:", multiline=True, style=MENU_STYLE).ask()

           with Progress(SpinnerColumn(), TextColumn("[cyan]{task.description}"), console=console) as p:
               p.add_task("Analizando texto y generando JSON…", total=None)
               try:
                   daily_input = ai.extract_daily_input(user_text, metadata)
                   DataService().save_daily_input(daily_input)
                   p.stop()
                   print_ok("JSON estructurado generado exitosamente.")
               except Exception as e:
                   p.stop()
                   print_err(f"Error al procesar el texto: {e}")
                   return

   with Progress(SpinnerColumn(), TextColumn("[cyan]{task.description}"), console=console) as p:
       task = p.add_task("Iniciando pipeline…", total=None)
       try:
           from app.models.report_model import GenerateReportRequest, ReportType
           from app.mcp.tools.generate_report_tool import GenerateReportTool

           request = GenerateReportRequest(
               report_date=report_date,
               report_type=ReportType(report_type),
               skip_drive_sync=(input_method == "ai"),
           )
           tool   = GenerateReportTool()
           p.update(task, description="Generando informe Word…")
           result = asyncio.run(tool.execute(request))
           p.stop()

           console.print()
           print_ok("Informe generado exitosamente.")
           console.print()

           t = Table(box=box.SIMPLE, show_header=False, border_style="dim", padding=(0, 2))
           t.add_column("Campo", style="dim",  min_width=12)
           t.add_column("Valor", style="white")
           t.add_row("ID",      result.report_id)
           t.add_row("Archivo", str(result.output_path))
           t.add_row("Mensaje", result.message)
           console.print(t)

           # ── Clear session checkpoint on success ───────────
           session.clear()
           _cleanup_temp_files()

       except FileNotFoundError as e:
           p.stop()
           print_err(f"Datos de entrada no encontrados: {e}")
           print_info(
               f"Sube el archivo [bold]{report_date}_{report_type}.json[/bold] "
               "a la carpeta daily_inputs de Drive."
           )
       except Exception as e:
           p.stop()
           print_err(f"Error generando informe: {e}")

def _cleanup_temp_files() -> None:
   import shutil
   from app.config import get_settings
   settings = get_settings()

   dirs_to_clean = [
       Path(settings.input_images_dir),
       Path(settings.daily_inputs_dir),
       Path(settings.raw_reports_dir),
   ]
   cleaned = []
   for d in dirs_to_clean:
       if d.exists():
           file_count = 0
           for f in d.iterdir():
               if f.is_file():
                   f.unlink()
                   file_count += 1
               elif f.is_dir():
                   shutil.rmtree(f, ignore_errors=True)
           if file_count:
               cleaned.append(f"{d.name}/ ({file_count} archivos)")
   if cleaned:
       print_info(f"Archivos temporales eliminados: {', '.join(cleaned)}")

def action_list_reports():
   section("Informes generados")
   from app.config import get_settings
   settings = get_settings()

   # ── 1. Collect candidate reports ──────────────────────────────
   # Format: {"name": str, "source": "drive"|"local", "id": str|None, "path": Path|None}
   candidates: list[dict] = []

   # Local .docx files
   local_out = Path(settings.output_reports_dir)
   if local_out.exists():
       for f in sorted(local_out.glob("*.docx"), reverse=True):
           candidates.append({"name": f.name, "source": "local", "id": None, "path": f})

   # Google Drive output reports
   if settings.drive_enabled and settings.drive_output_folder_id:
       with Progress(SpinnerColumn(), TextColumn("[cyan]{task.description}"), console=console) as p:
           p.add_task("Consultando Google Drive…", total=None)
           try:
               from app.services.drive_service import DriveService
               drive = DriveService()
               drive_files = drive._list_files(settings.drive_output_folder_id)
               p.stop()
               for f in drive_files:
                   mime = f.get("mimeType", "")
                   if not (mime.endswith("wordprocessingml.document") or mime == "application/vnd.google-apps.document"):
                       continue
                   name = f["name"]
                   if not name.endswith(".docx"):
                       name += ".docx"
                   # Avoid showing files already in the local list
                   if not any(c["name"] == name and c["source"] == "local" for c in candidates):
                       candidates.append({"name": name, "source": "drive", "id": f["id"], "mime": mime, "path": None})
           except Exception as e:
               p.stop()
               print_warn(f"No se pudo consultar Drive: {e}")

   if not candidates:
       print_info("No se encontraron informes en local ni en Drive.")
       return

   # ── 2. Show selection table ────────────────────────────────────
   console.print()
   t = Table(box=box.SIMPLE_HEAD, border_style="dim", show_edge=False, padding=(0, 2))
   t.add_column("#",       justify="right", style="dim",  min_width=3)
   t.add_column("Nombre",  style="white",   min_width=35)
   t.add_column("Fuente",  style="cyan",    min_width=8)
   for i, c in enumerate(candidates, 1):
       badge = "☁ Drive" if c["source"] == "drive" else "💾 Local"
       t.add_row(str(i), c["name"], badge)
   console.print(t)

   choices = [questionary.Choice(f"  {c['name']}", value=i-1) for i, c in enumerate(candidates, 1)]
   choices.append(questionary.Choice("  Cancelar", value=-1))
   idx = questionary.select("  Selecciona un informe:", choices=choices, style=MENU_STYLE).ask()
   if idx == -1:
       return

   report = candidates[idx]

   # ── 3. Ensure file is local ────────────────────────────────────
   if report["source"] == "drive":
       with Progress(SpinnerColumn(), TextColumn("[cyan]{task.description}"), console=console) as p:
           p.add_task(f"Descargando {report['name']} desde Drive…", total=None)
           try:
               from app.services.drive_service import DriveService
               drive = DriveService()
               dest = local_out / report["name"]
               local_out.mkdir(parents=True, exist_ok=True)
               drive._download_file(report["id"], dest, mime_type=report.get("mime", ""))
               p.stop()
               report["path"] = dest
               print_ok(f"Descargado en {dest}")
           except Exception as e:
               p.stop()
               print_err(f"Error al descargar: {e}")
               return

   docx_path: Path = report["path"]

   # ── 4. Extract and preview text ───────────────────────────────
   from app.rag.knowledge_ingestion import KnowledgeIngestionPipeline
   pipeline = KnowledgeIngestionPipeline()
   text = pipeline._extract_docx_text(docx_path)

   if not text.strip():
       print_warn("El archivo no contiene texto extraíble.")
   else:
       preview = text[:1200] + ("…\n[dim](texto truncado)[/dim]" if len(text) > 1200 else "")
       console.print()
       console.print(Panel(preview, title=f"[cyan]{docx_path.name}[/cyan]", border_style="dim", padding=(1, 2)))

   # ── 5. Action menu ─────────────────────────────────────────────
   console.print()
   action = questionary.select(
       "  ¿Qué deseas hacer con este informe?",
       choices=[
           questionary.Choice("  📂  Mover a context_reports (usar como contexto RAG)", value="context"),
           questionary.Choice("  📝  Guardar resumen como Nota de conocimiento",         value="note"),
           questionary.Choice("  🔁  Hacer ambas cosas",                                 value="both"),
           questionary.Choice("  ❌  Solo visualizar — no hacer nada",                   value="skip"),
       ],
       style=MENU_STYLE,
   ).ask()

   do_context = action in ("context", "both")
   do_note    = action in ("note",    "both")

   # ── 5a. Move / copy to context_reports ────────────────────────
   if do_context:
       import shutil
       ctx_dir = Path(settings.context_reports_dir)
       ctx_dir.mkdir(parents=True, exist_ok=True)
       dest_ctx = ctx_dir / docx_path.name
       try:
           shutil.copy2(docx_path, dest_ctx)
           print_ok(f"Copiado a context_reports/: {docx_path.name}")
           # Trigger ingestion right away
           with Progress(SpinnerColumn(), TextColumn("[cyan]{task.description}"), console=console) as p:
               p.add_task("Ingiriendo en base de conocimiento…", total=None)
               try:
                   results = pipeline.ingest_all_context_reports()
                   p.stop()
                   chunk_count = results.get(docx_path.name, 0)
                   if chunk_count:
                       print_ok(f"Base de conocimiento actualizada — {chunk_count} chunk(s) añadidos.")
                   else:
                       # File was already in registry — force it
                       forced = pipeline.ingest_all_context_reports(force=True)
                       p2_count = forced.get(docx_path.name, 0)
                       if p2_count:
                           print_ok(f"Re-ingesta forzada exitosa — {p2_count} chunk(s).")
                       else:
                           print_warn("El archivo no generó nuevos chunks. Verifica que contenga texto.")
               except Exception as e:
                   p.stop()
                   print_err(f"Error en ingesta: {e}")
       except Exception as e:
           print_err(f"Error copiando archivo: {e}")

   # ── 5b. Save key content as a note ────────────────────────────
   if do_note and text.strip():
       console.print()
       console.print("[dim]  Escribe el resumen/nota que quieres guardar (o presiona Enter para auto-generar una)[/dim]")
       manual_note = questionary.text("  Nota (Enter para saltar):", multiline=True, style=MENU_STYLE).ask()

       note_text = manual_note.strip() if manual_note and manual_note.strip() else None

       if not note_text:
           # Auto-summarize using AI
           with Progress(SpinnerColumn(), TextColumn("[cyan]{task.description}"), console=console) as p:
               p.add_task("Generando resumen automático del informe…", total=None)
               try:
                   from app.services.ai_service import AIService
                   prompt = (
                       f"Resume el siguiente informe técnico en un párrafo conciso en español, "
                       f"destacando módulos cubiertos, resultados y observaciones clave.\n\n{text[:3000]}"
                   )
                   resp = AIService()._call_json(
                       f"Responde con JSON: {{\"summary\": \"<resumen>\"}}\n\n{prompt}"
                   )
                   note_text = resp.get("summary", "").strip()
                   p.stop()
               except Exception as e:
                   p.stop()
                   print_warn(f"No se pudo auto-generar el resumen: {e}")

       if note_text:
           console.print()
           console.print("[dim]  Resumen generado:[/dim]")
           console.print(Panel(f"[dim]{note_text}[/dim]", border_style="cyan", padding=(0, 2)))
           console.print()
           
           approved_note = questionary.text(
               "  Edita si es necesario y presiona Enter para guardar (vacío para cancelar):",
               default=note_text,
               multiline=True,
               style=MENU_STYLE
           ).ask()

           if approved_note and approved_note.strip():
               _save_note_with_consolidation(approved_note.strip(), pipeline)
           else:
               print_info("Guardado cancelado.")
       else:
           print_info("No se guardó ninguna nota.")

# ─────────────────────────────────────────────────────────────────
# TARGET DATA / HELPER
# ─────────────────────────────────────────────────────────────────

def _save_note_with_consolidation(note: str, pipeline) -> None:
    """Helper to save a note with similarity detection and AI merging."""
    # ── Smart consolidation: detect similar existing notes ────────────
    similar: list[dict] = []
    try:
        with Progress(SpinnerColumn(), TextColumn("[cyan]{task.description}"), console=console) as p:
            p.add_task("Buscando notas similares en la base de conocimiento…", total=None)
            # Use threshold 0.4 (lower is more permissive since chunks might just be conceptually similar)
            similar = pipeline.find_similar_notes(note, threshold=0.4)
    except Exception as e:
        print_warn(f"No se pudo verificar similitud: {e}")

    if similar:
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
        for idx, chunk in enumerate(similar, 1):
            score_pct = int(chunk["relevance_score"] * 100)
            console.print(f"  [dim]Nota existente {idx}  (similitud {score_pct}%):[/dim]")
            console.print(
                Panel(f"[dim]{chunk['content'][:400]}[/dim]", border_style="dim", padding=(0, 2))
            )

        choices = [
            questionary.Choice(f"Nota existente {idx} (Similitud: {int(chunk['relevance_score'] * 100)}%)", value=chunk, checked=True)
            for idx, chunk in enumerate(similar, 1)
        ]

        selected_to_merge = questionary.checkbox(
            "  Selecciona las notas que deseas fusionar (Espacio para (des)marcar, Enter para confirmar, ninguna para guardar como nueva):",
            choices=choices,
            style=MENU_STYLE,
        ).ask()

        if selected_to_merge:
            from app.services.ai_service import AIService as _AIService
            existing_texts = [c["content"] for c in selected_to_merge]

            with Progress(SpinnerColumn(), TextColumn("[cyan]{task.description}"), console=console) as p:
                p.add_task("Fusionando notas con IA…", total=None)
                try:
                    merged_text = _AIService().merge_notes(note, existing_texts)
                    p.stop()
                except Exception as e:
                    p.stop()
                    print_err(f"Error al fusionar: {e}")
                    merged_text = note

            console.print()
            console.print("[dim]  Resultado de la fusión:[/dim]")
            console.print(Panel(f"[dim]{merged_text}[/dim]", border_style="green", padding=(0, 2)))
            console.print()

            approve = questionary.confirm(
                "  ¿Aprobar y guardar la nota fusionada?",
                default=True,
                style=MENU_STYLE,
            ).ask()

            if approve:
                old_ids = [c["id"] for c in selected_to_merge]
                with Progress(SpinnerColumn(), TextColumn("[cyan]{task.description}"), console=console) as p:
                    p.add_task("Eliminando notas antiguas e ingresando nota consolidada…", total=None)
                    try:
                        pipeline.delete_notes(old_ids)
                        chunks = pipeline.ingest_text_note(merged_text)
                        p.stop()
                        print_ok(
                            f"Nota consolidada guardada ({chunks} chunk/s). "
                            f"{len(old_ids)} nota(s) anterior(es) eliminada(s)."
                        )
                    except Exception as e:
                        p.stop()
                        print_err(f"Error al consolidar: {e}")
            else:
                print_info("Fusión cancelada. La nota no fue guardada.")
            return

    with Progress(SpinnerColumn(), TextColumn("[cyan]{task.description}"), console=console) as p:
        p.add_task("Registrando nota…", total=None)
        try:
            chunks = pipeline.ingest_text_note(note)
            p.stop()
            print_ok(f"Nota registrada en la base de conocimiento ({chunks} chunk/s).")
        except Exception as e:
            p.stop()
            print_err(f"Error procesando la nota: {e}")



# ─────────────────────────────────────────────────────────────────
# KNOWLEDGE BASE
# ─────────────────────────────────────────────────────────────────

def action_feed_context():
   section("Base de conocimiento del proyecto")
   from app.rag.knowledge_ingestion import KnowledgeIngestionPipeline
   from app.config import get_settings

   settings = get_settings()
   pipeline = KnowledgeIngestionPipeline()

   if settings.drive_enabled:
       sync = questionary.confirm(
           "  ¿Sincronizar reportes de contexto desde Google Drive?",
           default=True,
           style=MENU_STYLE,
       ).ask()
       if sync:
           with Progress(SpinnerColumn(), TextColumn("[cyan]{task.description}"), console=console) as p:
               p.add_task("Sincronizando Drive…", total=None)
               try:
                   from app.services.drive_service import DriveService
                   downloaded = DriveService().sync_context_reports()
                   p.stop()
                   if downloaded:
                       print_ok(f"{len(downloaded)} reporte(s) descargado(s).")
                   else:
                       print_info("No hay reportes nuevos en Drive.")
               except Exception as e:
                   p.stop()
                   print_err(f"Error sincronizando: {e}")

   with Progress(SpinnerColumn(), TextColumn("[cyan]{task.description}"), console=console) as p:
       p.add_task("Procesando reportes de contexto (.docx)…", total=None)
       try:
           results = pipeline.ingest_all_context_reports()
           p.stop()
           if results:
               print_ok(f"Ingestión completa — {len(results)} archivo(s):")
               for fname, count in results.items():
                   print_info(f"  {fname}: {count} chunk(s)")
           else:
               print_info("Todos los reportes ya estaban ingestados.")
               # Offer forced re-ingestion so the user can recover when ChromaDB
               # has no chunks even though the registry says the file is processed.
               context_dir = Path(settings.context_reports_dir)
               available   = sorted(context_dir.glob("*.docx")) if context_dir.exists() else []
               if available:
                   force = questionary.confirm(
                       "  ¿Forzar re-ingesta? (útil si la base vectorial estaba vacía)",
                       default=False,
                       style=MENU_STYLE,
                   ).ask()
                   if force:
                       with Progress(SpinnerColumn(), TextColumn("[cyan]{task.description}"), console=console) as p2:
                           p2.add_task("Forzando re-ingesta de todos los archivos…", total=None)
                           try:
                               forced = pipeline.ingest_all_context_reports(force=True)
                               p2.stop()
                               if forced:
                                   print_ok(f"Re-ingesta completada — {sum(forced.values())} chunk(s) totales:")
                                   for fname, count in forced.items():
                                       print_info(f"  {fname}: {count} chunk(s)")
                               else:
                                   print_warn("No se encontraron archivos .docx en la carpeta de contexto.")
                           except Exception as e:
                               p2.stop()
                               print_err(f"Error en re-ingesta: {e}")
       except Exception as e:
           p.stop()
           print_err(f"Error en ingestión: {e}")


   console.print()
   console.print("[dim]  Opcional: añade una nota o resumen de cambios del proyecto.[/dim]")
   console.print("[dim]  Ejemplo: 'Se refactorizó el módulo de pagos y se actualizó a Vue 3.'[/dim]")
   console.print()
   note = questionary.text("  Nota (Enter para saltar):", multiline=True, style=MENU_STYLE).ask()

   if note and note.strip():
       _save_note_with_consolidation(note.strip(), pipeline)

# ─────────────────────────────────────────────────────────────────
# QUERY KNOWLEDGE — with post-response options loop
# ─────────────────────────────────────────────────────────────────

def action_query_knowledge():
   section("Consultar conocimiento del proyecto")

   from app.rag.knowledge_retriever import KnowledgeRetriever
   from app.rag.knowledge_ingestion import KnowledgeIngestionPipeline

   retriever = KnowledgeRetriever()
   pipeline  = KnowledgeIngestionPipeline()

   # Conversation history — lives in memory for this session only
   # Format: [{"role": "user"|"assistant", "content": "..."}]
   history: list[dict] = []
   _MAX_HISTORY = 20  # 10 turns × 2 messages

   turn = 0
   while True:
       turn += 1
       console.print()

       # ── Ask the question ──────────────────────────────────────
       label = "  Consulta:" if turn == 1 else "  Siguiente pregunta:"
       question = questionary.text(label, style=MENU_STYLE).ask()

       if not question or not question.strip():
           print_info("Sin consulta. Volviendo al menú.")
           break

       # ── Retrieve + answer ─────────────────────────────────────
       with Progress(
           SpinnerColumn(),
           TextColumn("[cyan]{task.description}"),
           console=console,
       ) as p:
           p.add_task("Consultando base de conocimiento…", total=None)
           try:
               answer = retriever.answer_with_history(question, history=history)
           except Exception as e:
               p.stop()
               print_err(f"Error en la consulta: {e}")
               break

       # ── Display answer ────────────────────────────────────────
       console.print()
       console.print(
           Panel(
               answer,
               border_style="dim",
               title="[dim]Respuesta[/dim]",
               padding=(1, 2),
           )
       )

       # ── Update history (keep last _MAX_HISTORY messages) ──────
       history.append({"role": "user",      "content": question})
       history.append({"role": "assistant", "content": answer})
       if len(history) > _MAX_HISTORY:
           history = history[-_MAX_HISTORY:]

       # ── Post-response options ─────────────────────────────────
       console.print()
       post_action = questionary.select(
           "  ¿Qué deseas hacer?",
           choices=[
               questionary.Choice(
                   "Reajustar contexto con esta respuesta",
                   value="reajust",
               ),
               questionary.Choice(
                   "Continuar conversación",
                   value="continue",
               ),
               questionary.Choice(
                   "Finalizar",
                   value="exit",
               ),
           ],
           style=MENU_STYLE,
       ).ask()

       # ── Reajustar contexto ────────────────────────────────────
       if post_action == "reajust":
           # Mostrar la respuesta de la IA como sugerencia y preguntar si usarla como base
           console.print()
           print_suggestion("nota de contexto", answer)
           use_answer = questionary.confirm(
               "  ¿Usar esta respuesta como base para la nota?",
               default=True,
               style=MENU_STYLE,
           ).ask()

           note_default = answer.strip() if use_answer else ""

           note_to_save = questionary.text(
               "  Nota de contexto (edita o escribe desde cero):",
               default=note_default,
               multiline=True,
               style=MENU_STYLE,
           ).ask()

           if not note_to_save or not note_to_save.strip():
               print_info("Nota vacía — no se guardó nada en la base de conocimiento.")
           else:
               with Progress(
                   SpinnerColumn(),
                   TextColumn("[cyan]{task.description}"),
                   console=console,
               ) as p:
                   p.add_task("Guardando nota en la base de conocimiento…", total=None)
                   try:
                       chunks = pipeline.ingest_text_note(note_to_save)
                       p.stop()
                       print_ok(
                           f"Nota guardada en project_knowledge "
                           f"({chunks} chunk/s)."
                       )
                   except Exception as e:
                       p.stop()
                       print_err(f"Error al guardar contexto: {e}")

           # Después de reajustar, preguntar si continuar o salir
           console.print()
           keep_going = questionary.select(
               "  ¿Continuar la sesión?",
               choices=[
                   questionary.Choice("Continuar conversación", value="continue"),
                   questionary.Choice("Finalizar",              value="exit"),
               ],
               style=MENU_STYLE,
           ).ask()

           if keep_going == "exit":
               break
           # else: loop continues to next turn

       # ── Continuar conversación ────────────────────────────────
       elif post_action == "continue":
           continue   # loop back — history already updated above

       # ── Finalizar ─────────────────────────────────────────────
       else:
           break

   console.print()
   print_info("Sesión de consulta finalizada.")

def action_start_server():
   section("Iniciar servidor API")
   from app.config import get_settings
   settings = get_settings()

   print_info(f"Servidor en http://{settings.api_host}:{settings.api_port}")
   print_info("Presiona Ctrl+C para detener.")
   console.print()

   import uvicorn
   uvicorn.run(
       "app.main:app",
       host=settings.api_host,
       port=settings.api_port,
       reload=settings.api_debug,
       log_level=settings.api_log_level.lower(),
   )

# ─────────────────────────────────────────────────────────────────
# MENU
# ─────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────
# BACKUP & RESTORE
# ─────────────────────────────────────────────────────────────────

def action_backup_knowledge():
   section("Backup / Restauración de Base de Conocimiento")
   from app.config import get_settings
   settings = get_settings()

   if not settings.drive_enabled:
       print_warn("Drive no está habilitado. Activa DRIVE_ENABLED=true en el .env.")
       return

   if not settings.drive_knowledge_backup_folder_id:
       print_warn(
           "No has configurado DRIVE_KNOWLEDGE_BACKUP_FOLDER_ID en el .env.\n"
           "  1. Crea una carpeta en Google Drive llamada 'knowledge_backups'\n"
           "  2. Copia su ID desde la URL de Drive\n"
           "  3. Agrégalo a tu .env como:  DRIVE_KNOWLEDGE_BACKUP_FOLDER_ID=<id>"
       )
       return

   from app.services.drive_service import DriveService
   drive = DriveService()

   action = questionary.select(
       "  ¿Qué deseas hacer?",
       choices=[
           questionary.Choice("  ☁️  Crear backup ahora (subir a Drive)",       value="backup"),
           questionary.Choice("  ⬇️  Restaurar desde un backup en Drive",       value="restore"),
           questionary.Choice("  📋  Listar backups disponibles en Drive",       value="list"),
           questionary.Choice("  ❌  Cancelar",                                  value="cancel"),
       ],
       style=MENU_STYLE,
   ).ask()

   if action == "cancel" or action is None:
       return

   # ── Backup ────────────────────────────────────────────────────
   if action == "backup":
       with Progress(SpinnerColumn(), TextColumn("[cyan]{task.description}"), console=console) as p:
           p.add_task("Comprimiendo y subiendo base de conocimiento a Drive…", total=None)
           try:
               url = drive.backup_knowledge()
               p.stop()
               print_ok("¡Backup creado exitosamente!")
               console.print(f"  [dim]📎 {url}[/dim]")
           except ValueError as e:
               p.stop()
               print_warn(str(e))
           except Exception as e:
               p.stop()
               print_err(f"Error al crear el backup: {e}")

   # ── List ──────────────────────────────────────────────────────
   elif action in ("list", "restore"):
       with Progress(SpinnerColumn(), TextColumn("[cyan]{task.description}"), console=console) as p:
           p.add_task("Consultando backups en Drive…", total=None)
           try:
               backups = drive.list_knowledge_backups()
               p.stop()
           except Exception as e:
               p.stop()
               print_err(f"Error listando backups: {e}")
               return

       if not backups:
           print_info("No hay backups en Drive todavía. Crea uno primero.")
           return

       # Show table
       t = Table(box=box.SIMPLE_HEAD, border_style="dim", show_edge=False, padding=(0, 2))
       t.add_column("#",       justify="right", style="dim", min_width=3)
       t.add_column("Archivo", style="white",   min_width=40)
       for i, b in enumerate(backups, 1):
           t.add_row(str(i), b["name"])
       console.print()
       console.print(t)

       if action == "list":
           return

       # ── Restore ───────────────────────────────────────────────
       choices_b = [questionary.Choice(f"  {b['name']}", value=i-1) for i, b in enumerate(backups, 1)]
       choices_b.append(questionary.Choice("  Cancelar", value=-1))
       idx = questionary.select("  Selecciona el backup a restaurar:", choices=choices_b, style=MENU_STYLE).ask()
       if idx == -1 or idx is None:
           return

       chosen = backups[idx]
       console.print()
       confirm = questionary.confirm(
           f"  ⚠️  Esto SOBREESCRIBIRÁ tu vector_db/ y knowledge_processed.json locales.\n"
           f"  ¿Restaurar desde '{chosen['name']}'?",
           default=False,
           style=MENU_STYLE,
       ).ask()
       if not confirm:
           print_info("Restauración cancelada.")
           return

       with Progress(SpinnerColumn(), TextColumn("[cyan]{task.description}"), console=console) as p:
           p.add_task(f"Descargando y restaurando {chosen['name']}…", total=None)
           try:
               drive.restore_knowledge(chosen["id"], chosen["name"])
               p.stop()
               print_ok("¡Base de conocimiento restaurada exitosamente!")
               print_info("Reinicia el sistema para que ChromaDB reconozca los datos restaurados.")
           except Exception as e:
               p.stop()
               print_err(f"Error al restaurar: {e}")


MENU_CHOICES = [
   questionary.Separator("  Conocimiento del proyecto"),
   questionary.Choice("  Alimentar contexto",             value="feed_context"),
   questionary.Choice("  Consultar conocimiento",         value="query_knowledge"),
   questionary.Separator("  Sincronización"),
   questionary.Choice("  Sincronizar desde Google Drive", value="drive_sync"),
   questionary.Separator("  Reportes"),
   questionary.Choice("  Generar informe",                value="generate"),
   questionary.Choice("  Listar informes generados",      value="list"),
   questionary.Separator("  Sistema"),
   questionary.Choice("  Backup / Restaurar base de conocimiento", value="backup_knowledge"),
   questionary.Choice("  Iniciar servidor API",                    value="server"),
   questionary.Separator(),
   questionary.Choice("  Salir",                          value="exit"),
]

ACTIONS = {
   "feed_context":      action_feed_context,
   "query_knowledge":   action_query_knowledge,
   "drive_sync":        action_drive_sync,
   "generate":          action_generate,
   "list":              action_list_reports,
   "backup_knowledge":  action_backup_knowledge,
   "server":            action_start_server,
}

def main():
   header()

   while True:
       console.print()
       choice = questionary.select(
           "¿Qué deseas hacer?",
           choices=MENU_CHOICES,
           style=MENU_STYLE,
           use_shortcuts=False,
       ).ask()

       if choice is None or choice == "exit":
           console.print()
           rprint("[dim]Hasta luego.[/dim]")
           console.print()
           break

       action = ACTIONS.get(choice)
       if action:
           action()

       questionary.press_any_key_to_continue(
           "  Presiona cualquier tecla para continuar…",
           style=MENU_STYLE,
       ).ask()
       console.clear()
       header()

if __name__ == "__main__":
   main()
