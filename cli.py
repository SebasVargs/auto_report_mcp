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
   from app.mcp.tools.save_report_tool import SaveReportTool

   try:
       tool    = SaveReportTool()
       reports = tool.list_manifests()
       if not reports:
           print_info("No hay informes generados aún.")
           return

       t = Table(box=box.SIMPLE_HEAD, border_style="dim", show_edge=False, padding=(0, 2))
       t.add_column("#",       justify="right", style="dim",  min_width=3)
       t.add_column("Fecha",   style="bold",    min_width=12)
       t.add_column("Tipo",    style="cyan",    min_width=20)
       t.add_column("Archivo", style="white")

       for i, r in enumerate(reports, 1):
           t.add_row(
               str(i),
               str(r.get("report_date", "—")),
               str(r.get("report_type", "—")),
               Path(r.get("output_path", "—")).name,
           )
       console.print(t)
   except Exception as e:
       print_err(f"Error listando informes: {e}")

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
                   print_info(f"{fname}: {count} chunk(s)")
           else:
               print_info("Todos los reportes ya estaban ingestados. Sin cambios.")
       except Exception as e:
           p.stop()
           print_err(f"Error en ingestión: {e}")

   console.print()
   console.print("[dim]  Opcional: añade una nota o resumen de cambios del proyecto.[/dim]")
   console.print("[dim]  Ejemplo: 'Se refactorizó el módulo de pagos y se actualizó a Vue 3.'[/dim]")
   console.print()
   note = questionary.text("  Nota (Enter para saltar):", multiline=True, style=MENU_STYLE).ask()

   if note and note.strip():
       # ── Smart consolidation: detect similar existing notes ────────────
       similar: list[dict] = []
       try:
           with Progress(SpinnerColumn(), TextColumn("[cyan]{task.description}"), console=console) as p:
               p.add_task("Buscando notas similares en la base de conocimiento…", total=None)
               similar = pipeline.find_similar_notes(note)
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

           merge_choice = questionary.select(
               "  ¿Qué deseas hacer?",
               choices=[
                   questionary.Choice("  Fusionar con la(s) nota(s) similar(es)  (recomendado)", value="merge"),
                   questionary.Choice("  Guardar como nota nueva independiente",                  value="keep"),
               ],
               style=MENU_STYLE,
           ).ask()

           if merge_choice == "merge":
               from app.services.ai_service import AIService as _AIService
               existing_texts = [c["content"] for c in similar]

               with Progress(SpinnerColumn(), TextColumn("[cyan]{task.description}"), console=console) as p:
                   p.add_task("Fusionando notas con IA…", total=None)
                   try:
                       merged_text = _AIService().merge_notes(note, existing_texts)
                       p.stop()
                   except Exception as e:
                       p.stop()
                       print_err(f"Error al fusionar: {e}")
                       merged_text = note  # fallback: save original note

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
                   old_ids = [c["id"] for c in similar]
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
               return   # exit — either saved merged or cancelled

       # No similar notes (or user chose to keep as new) — plain ingestion
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
   questionary.Choice("  Iniciar servidor API",           value="server"),
   questionary.Separator(),
   questionary.Choice("  Salir",                          value="exit"),
]

ACTIONS = {
   "feed_context":    action_feed_context,
   "query_knowledge": action_query_knowledge,
   "drive_sync":      action_drive_sync,
   "generate":        action_generate,
   "list":            action_list_reports,
   "server":          action_start_server,
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
