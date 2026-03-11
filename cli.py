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

# ── All visual / UI helpers live in ui.py ───────────────────────
from ui import (
    console,
    MENU_STYLE,
    # layout
    header,
    section,
    # status messages
    print_ok,
    print_warn,
    print_err,
    print_info,
    print_suggestion,
    print_step,
    # panels
    session_recovery_panel,
    similar_notes_panel,
    answer_panel,
    merged_note_panel,
    note_preview_panel,
    document_preview_panel,
    # tables
    report_summary_table,
    candidates_table,
    backups_table,
    ingestion_results_table,
    # case header
    case_rule,
    # progress helpers
    spinning,
    downloading_files,
    sync_images_with_progress,
    download_files_with_progress,
    ingest_with_progress,
    querying_knowledge,
    generating_ai,
    image_sync_progress,
    file_download_progress,
    generation_progress,
    spinner_progress,
)

from rich.markup import escape
from rich.text import Text
from rich.panel import Panel
from rich import box
from rich.progress import Progress, SpinnerColumn, TextColumn

from app.services.session_manager import ReportSessionManager


# ─────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────

def _pick_report_type() -> str:
    return questionary.select(
        "Tipo de informe:",
        choices=[
            questionary.Separator("  ── Pruebas de Software ──"),
            questionary.Choice("  Pruebas funcionales      (Caja Negra)",          value="functional_tests"),
            questionary.Choice("  Pruebas de integración  (Caja Negra + Blanca)", value="integration_tests"),
            questionary.Choice("  Pruebas unitarias        (Caja Blanca)",          value="unit_tests"),
            questionary.Separator("  ── Proyecto ──"),
            questionary.Choice("  Avance de proyecto",                              value="project_progress"),
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



# INTERACTIVE GUIDED NARRATIVE
# ─────────────────────────────────────────────────────────────────

def _collect_test_case_guided(
    image_name: str,
    case_index: int,
    total_cases: int,
    assistant,
    report_type: str = "functional_tests",
) -> dict:
    from app.services.interactive_narrative_assistant import (
        TestCaseDraft,
        get_sections_for_type,
        LIST_SECTIONS,
        NUMERIC_SECTIONS,
        parse_list_suggestion,
    )

    SECTIONS = get_sections_for_type(report_type)

    case_rule(image_name, case_index, total_cases, report_type)

    draft = TestCaseDraft()
    draft.module    = questionary.text("  Módulo evaluado:", style=MENU_STYLE).ask() or ""
    draft.test_name = questionary.text(
        "  Nombre del caso (ej. CP-01: Login con credenciales válidas):",
        style=MENU_STYLE,
    ).ask() or ""

    console.print()
    print_info("Consultando historial del proyecto para generar sugerencias…")

    total_sections = len(SECTIONS)
    for sec_idx, (section_key, section_label) in enumerate(SECTIONS, 1):
        console.print()
        console.print(
            f"  [dim cyan][{sec_idx}/{total_sections}][/dim cyan]  [bold]{section_label}[/bold]"
        )

        with generating_ai("Generando sugerencia…"):
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

    report_type     = metadata.get("report_type", "functional_tests")
    prefilled       = prefilled_cases or []
    prefilled_names = {tc.get("evidence_image_filename") for tc in prefilled}
    pending_images  = [img for img in images if img.name not in prefilled_names]
    image_names     = [img.name for img in images]

    console.print()
    if prefilled:
        print_ok(
            f"Retomando sesión — {len(prefilled)} caso(s) ya completado(s), "
            f"{len(pending_images)} pendiente(s)."
        )
    else:
        print_info(f"Modo asistido activado — {len(images)} imagen(es) detectada(s).")
    console.print("[dim]  El sistema consultará el historial del proyecto para sugerir cada sección.[/dim]")

    assistant  = InteractiveNarrativeAssistant()
    test_cases = list(prefilled)
    total      = len(images)

    for img in pending_images:
        global_index = image_names.index(img.name) + 1
        tc = _collect_test_case_guided(
            img.name, global_index, total, assistant, report_type=report_type
        )
        tc["evidence_image_filename"] = img.name
        tc["test_id"]      = str(global_index)
        tc["prepared_by"]  = metadata.get("prepared_by", "")
        tc["tested_by"]    = metadata.get("prepared_by", "")
        tc["prepare_date"] = metadata.get("report_date", "")
        tc["test_date"]    = metadata.get("report_date", "")
        test_cases.append(tc)

        if session:
            session.save(metadata, image_names, test_cases)
            print_info(f"Progreso guardado ({len(test_cases)}/{total})")

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

def action_generate() -> None:
    section("Generar informe")

    # ── Session recovery ─────────────────────────────────────────
    session          = ReportSessionManager()
    prefilled_cases: list[dict] = []
    session_metadata: dict      = {}

    if session.exists():
        session_recovery_panel(session.summary())
        recovery_choice = questionary.select(
            "¿Qué deseas hacer?",
            choices=[
                questionary.Choice("  ↩  Retomar sesión anterior", value="resume"),
                questionary.Choice("  ✗  Empezar desde cero",      value="fresh"),
            ],
            style=MENU_STYLE,
        ).ask()

        if recovery_choice == "resume":
            data             = session.load()
            prefilled_cases  = data.get("completed_cases", [])
            session_metadata = data.get("metadata", {})
            print_ok(f"Retomando — {len(prefilled_cases)} caso(s) ya registrado(s).")
        else:
            session.clear()
            print_info("Sesión anterior descartada. Empezando desde cero.")

    # ── Date / type / method ─────────────────────────────────────
    if prefilled_cases and session_metadata:
        report_date  = session_metadata.get("report_date", str(date.today()))
        report_type  = session_metadata.get("report_type", "functional_tests")
        input_method = "ai"
    else:
        report_date  = _pick_date()
        report_type  = _pick_report_type()

        console.print()
        console.print(
            f"  [label]Fecha:[/label] [bold]{report_date}[/bold]   "
            f"[label]Tipo:[/label] [bold]{report_type}[/bold]"
        )
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
            metadata     = session_metadata
            project_name = metadata.get("project_name", "")
            environment  = metadata.get("environment", "QA")
            prepared_by  = metadata.get("prepared_by", "")
        else:
            console.print()
            console.print(Panel(
                Text.from_markup("[dim]Completa los datos del informe[/dim]"),
                border_style="dim",
                padding=(0, 2),
            ))
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
                    svc = DriveService()

                    # Limpiar imágenes locales previas por si quedó basura de una ejecución fallida
                    if settings.input_images_path.exists():
                        for f in settings.input_images_path.iterdir():
                            if f.is_file() and f.suffix.lower() in (".png", ".jpg", ".jpeg"):
                                try:
                                    f.unlink()
                                except Exception:
                                    pass

                    # Ask Drive how many images are waiting BEFORE downloading
                    pending_drive = svc.list_input_images()

                    if pending_drive:
                        p    = image_sync_progress(len(pending_drive))
                        task = p.add_task(
                            "Descargando imágenes desde Drive…",
                            total=len(pending_drive),
                        )
                        with p:
                            for item in pending_drive:
                                name = item.get("name", "imagen")
                                p.update(
                                    task,
                                    description=f"[cyan]{escape(name)}[/cyan]",
                                )
                                svc.download_input_image(item)
                                p.advance(task)
                        print_ok(f"{len(pending_drive)} imagen(es) descargada(s) desde Drive.")
                    else:
                        print_info("No hay imágenes nuevas en Drive.")

                except Exception as e:
                    print_warn(f"No se pudieron sincronizar imágenes de Drive: {e}")

            if settings.input_images_path.exists():
                all_imgs = sorted(
                    f for f in settings.input_images_path.iterdir()
                    if f.is_file() and f.suffix.lower() in (".png", ".jpg", ".jpeg")
                )
                if all_imgs:
                    print_ok(f"{len(all_imgs)} imagen(es) lista(s) para procesar.")
                    images = all_imgs

        ai = AIService()

        if images and report_type in _TEST_TYPES:
            test_cases       = _collect_narratives_guided(
                images, metadata, session=session, prefilled_cases=prefilled_cases
            )
            daily_input_dict = _build_daily_input_from_test_cases(test_cases, metadata)

            with spinning("Validando y guardando JSON estructurado…"):
                try:
                    from app.models.report_model import DailyInput
                    normalized  = AIService._normalize_daily_input_json(daily_input_dict, metadata)
                    daily_input = DailyInput.model_validate(normalized)
                    DataService().save_daily_input(daily_input)
                    print_ok("JSON estructurado guardado exitosamente.")
                except Exception as e:
                    print_err(f"Error al guardar: {e}")
                    return

        elif not images and report_type in _TEST_TYPES:
            console.print()
            console.print("[dim]  No se encontraron imágenes. Describe las pruebas en texto libre.[/dim]")
            console.print()
            user_text = questionary.text("  Narrativa:", multiline=True, style=MENU_STYLE).ask()

            with spinning("Analizando texto y generando JSON…"):
                try:
                    daily_input = ai.extract_daily_input(user_text, metadata)
                    DataService().save_daily_input(daily_input)
                    print_ok("JSON estructurado generado exitosamente.")
                except Exception as e:
                    print_err(f"Error al procesar el texto: {e}")
                    return
        else:
            console.print()
            console.print("[dim]  Describe el avance del proyecto, tareas completadas, bloqueos y riesgos.[/dim]")
            console.print()
            user_text = questionary.text("  Narrativa:", multiline=True, style=MENU_STYLE).ask()

            with spinning("Analizando texto y generando JSON…"):
                try:
                    daily_input = ai.extract_daily_input(user_text, metadata)
                    DataService().save_daily_input(daily_input)
                    print_ok("JSON estructurado generado exitosamente.")
                except Exception as e:
                    print_err(f"Error al procesar el texto: {e}")
                    return

    # ── Pipeline ─────────────────────────────────────────────────
    p    = generation_progress()
    task = p.add_task("Iniciando pipeline…", total=4)
    with p:
        try:
            from app.models.report_model import GenerateReportRequest, ReportType
            from app.mcp.tools.generate_report_tool import GenerateReportTool

            request = GenerateReportRequest(
                report_date=report_date,
                report_type=ReportType(report_type),
                skip_drive_sync=(input_method == "ai"),
            )
            tool = GenerateReportTool()

            p.update(task, description="Cargando datos de entrada…")
            p.advance(task)

            p.update(task, description="Construyendo estructura del informe…")
            p.advance(task)

            p.update(task, description="Generando documento Word…")
            result = asyncio.run(tool.execute(request))
            p.advance(task)

            p.update(task, description="Finalizando y guardando…")
            p.advance(task)

        except FileNotFoundError as e:
            print_err(f"Datos de entrada no encontrados: {e}")
            print_info(
                f"Sube el archivo [bold]{report_date}_{report_type}.json[/bold] "
                "a la carpeta daily_inputs de Drive."
            )
            return
        except Exception as e:
            print_err(f"Error generando informe: {e}")
            return

    console.print()
    print_ok("Informe generado exitosamente.")
    report_summary_table(result.report_id, str(result.output_path), result.message)

    session.clear()
    _cleanup_temp_files()


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


# ─────────────────────────────────────────────────────────────────
# LIST REPORTS
# ─────────────────────────────────────────────────────────────────

def action_list_reports() -> None:
    section("Informes generados")
    from app.config import get_settings
    settings = get_settings()

    candidates: list[dict] = []

    local_out = Path(settings.output_reports_dir)
    if local_out.exists():
        for f in sorted(local_out.glob("*.docx"), reverse=True):
            candidates.append({"name": f.name, "source": "local", "id": None, "path": f})

    if settings.drive_enabled and settings.drive_output_folder_id:
        with spinning("Consultando Google Drive…"):
            try:
                from app.services.drive_service import DriveService
                drive       = DriveService()
                drive_files = drive._list_files(settings.drive_output_folder_id)
                for f in drive_files:
                    mime = f.get("mimeType", "")
                    if not (mime.endswith("wordprocessingml.document") or mime == "application/vnd.google-apps.document"):
                        continue
                    name = f["name"]
                    if not name.endswith(".docx"):
                        name += ".docx"
                    if not any(c["name"] == name and c["source"] == "local" for c in candidates):
                        candidates.append({"name": name, "source": "drive", "id": f["id"], "mime": mime, "path": None})
            except Exception as e:
                print_warn(f"No se pudo consultar Drive: {e}")

    if not candidates:
        print_info("No se encontraron informes en local ni en Drive.")
        return

    candidates_table(candidates)

    choices = [questionary.Choice(f"  {c['name']}", value=i - 1) for i, c in enumerate(candidates, 1)]
    choices.append(questionary.Choice("  Cancelar", value=-1))
    idx = questionary.select("\n Selecciona un informe:", choices=choices, style=MENU_STYLE).ask()
    if idx == -1:
        return

    report = candidates[idx]

    if report["source"] == "drive":
        with spinning(f"Descargando {escape(report['name'])} desde Drive…"):
            try:
                from app.services.drive_service import DriveService
                drive = DriveService()
                dest  = local_out / report["name"]
                local_out.mkdir(parents=True, exist_ok=True)
                drive._download_file(report["id"], dest, mime_type=report.get("mime", ""))
                report["path"] = dest
                print_ok(f"Descargado en {dest}")
            except Exception as e:
                print_err(f"Error al descargar: {e}")
                return

    docx_path: Path = report["path"]

    from app.rag.knowledge_ingestion import KnowledgeIngestionPipeline
    pipeline = KnowledgeIngestionPipeline()
    text     = pipeline._extract_docx_text(docx_path)

    if not text.strip():
        print_warn("El archivo no contiene texto extraíble.")
    else:
        preview = text[:1200] + ("…\n[dim](texto truncado)[/dim]" if len(text) > 1200 else "")
        document_preview_panel(docx_path.name, preview)

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

    if do_context:
        import shutil
        ctx_dir = Path(settings.context_reports_dir)
        ctx_dir.mkdir(parents=True, exist_ok=True)
        dest_ctx = ctx_dir / docx_path.name
        try:
            shutil.copy2(docx_path, dest_ctx)
            print_ok(f"Copiado a context_reports/: {docx_path.name}")

            if settings.drive_enabled:
                with spinning("Subiendo a Google Drive (Context Reports)…"):
                    try:
                        from app.services.drive_service import DriveService
                        url = DriveService().upload_context_report(dest_ctx)
                        if url:
                            print_ok(f"Subido a Drive exitosamente: {url}")
                    except Exception as e:
                        print_warn(f"No se pudo subir a Drive: {e}")

            with spinning("Ingiriendo en base de conocimiento…"):
                try:
                    results    = pipeline.ingest_all_context_reports()
                    chunk_count = results.get(docx_path.name, 0)
                    if chunk_count:
                        print_ok(f"Base de conocimiento actualizada — {chunk_count} chunk(s) añadidos.")
                    else:
                        forced    = pipeline.ingest_all_context_reports(force=True)
                        p2_count  = forced.get(docx_path.name, 0)
                        if p2_count:
                            print_ok(f"Re-ingesta forzada exitosa — {p2_count} chunk(s).")
                        else:
                            print_warn("El archivo no generó nuevos chunks. Verifica que contenga texto.")
                except Exception as e:
                    print_err(f"Error en ingesta: {e}")
        except Exception as e:
            print_err(f"Error copiando archivo: {e}")

    if do_note and text.strip():
        console.print()
        console.print("[dim]  Escribe el resumen/nota que quieres guardar (o presiona Enter para auto-generar una)[/dim]")
        manual_note = questionary.text("  Nota (Enter para saltar):", multiline=True, style=MENU_STYLE).ask()
        note_text   = manual_note.strip() if manual_note and manual_note.strip() else None

        if not note_text:
            with generating_ai("Generando resumen automático del informe…"):
                try:
                    from app.services.ai_service import AIService
                    prompt    = (
                        f"Resume el siguiente informe técnico en un párrafo conciso en español, "
                        f"destacando módulos cubiertos, resultados y observaciones clave.\n\n{text[:3000]}"
                    )
                    resp      = AIService()._call_json(
                        f"Responde con JSON: {{\"summary\": \"<resumen>\"}}\n\n{prompt}"
                    )
                    note_text = resp.get("summary", "").strip()
                except Exception as e:
                    print_warn(f"No se pudo auto-generar el resumen: {e}")

        if note_text:
            note_preview_panel(note_text)
            approved_note = questionary.text(
                "  Edita si es necesario y presiona Enter para guardar (vacío para cancelar):",
                default=note_text,
                multiline=True,
                style=MENU_STYLE,
            ).ask()

            if approved_note and approved_note.strip():
                _save_note_with_consolidation(approved_note.strip(), pipeline)
            else:
                print_info("Guardado cancelado.")
        else:
            print_info("No se guardó ninguna nota.")


# ─────────────────────────────────────────────────────────────────
# NOTE CONSOLIDATION HELPER
# ─────────────────────────────────────────────────────────────────

def _save_note_with_consolidation(note: str, pipeline) -> None:
    similar: list[dict] = []
    try:
        with spinning("Buscando notas similares en la base de conocimiento…"):
            similar = pipeline.find_similar_notes(note, threshold=0.4)
    except Exception as e:
        print_warn(f"No se pudo verificar similitud: {e}")

    if similar:
        similar_notes_panel(similar)
        for idx, chunk in enumerate(similar, 1):
            score_pct = int(chunk["relevance_score"] * 100)
            console.print(f"  [dim]Nota existente {idx}  (similitud {score_pct}%):[/dim]")
            console.print(Panel(f"[dim]{chunk['content'][:400]}[/dim]", border_style="dim", padding=(0, 2)))

        choices = [
            questionary.Choice(
                f"Nota existente {idx} (Similitud: {int(chunk['relevance_score'] * 100)}%)",
                value=chunk,
                checked=True,
            )
            for idx, chunk in enumerate(similar, 1)
        ]

        selected_to_merge = questionary.checkbox(
            "  Selecciona las notas que deseas fusionar (Espacio para (des)marcar):",
            choices=choices,
            style=MENU_STYLE,
        ).ask()

        if selected_to_merge:
            from app.services.ai_service import AIService as _AIService
            existing_texts = [c["content"] for c in selected_to_merge]

            with generating_ai("Fusionando notas con IA…"):
                try:
                    merged_text = _AIService().merge_notes(note, existing_texts)
                except Exception as e:
                    print_err(f"Error al fusionar: {e}")
                    merged_text = note

            merged_note_panel(merged_text)

            approve = questionary.confirm(
                "  ¿Aprobar y guardar la nota fusionada?",
                default=True,
                style=MENU_STYLE,
            ).ask()

            if approve:
                old_ids = [c["id"] for c in selected_to_merge]
                with spinning("Eliminando notas antiguas e ingresando nota consolidada…"):
                    try:
                        pipeline.delete_notes(old_ids)
                        chunks = pipeline.ingest_text_note(merged_text)
                        print_ok(
                            f"Nota consolidada guardada ({chunks} chunk/s). "
                            f"{len(old_ids)} nota(s) anterior(es) eliminada(s)."
                        )
                    except Exception as e:
                        print_err(f"Error al consolidar: {e}")
            else:
                print_info("Fusión cancelada. La nota no fue guardada.")
            return

    with spinning("Registrando nota en la base de conocimiento…"):
        try:
            chunks = pipeline.ingest_text_note(note)
            print_ok(f"Nota registrada en la base de conocimiento ({chunks} chunk/s).")
        except Exception as e:
            print_err(f"Error procesando la nota: {e}")


# ─────────────────────────────────────────────────────────────────
# KNOWLEDGE BASE
# ─────────────────────────────────────────────────────────────────

def action_feed_context() -> None:
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
            with spinning("Sincronizando reportes desde Drive…"):
                try:
                    from app.services.drive_service import DriveService
                    downloaded = DriveService().sync_context_reports()
                    if downloaded:
                        print_ok(f"{len(downloaded)} reporte(s) descargado(s).")
                    else:
                        print_info("No hay reportes nuevos en Drive.")
                except Exception as e:
                    print_err(f"Error sincronizando: {e}")

    with spinning("Procesando reportes de contexto (.docx)…"):
        try:
            results = pipeline.ingest_all_context_reports()
        except Exception as e:
            print_err(f"Error en ingestión: {e}")
            results = {}

    if results:
        print_ok(f"Ingestión completa — {len(results)} archivo(s):")
        ingestion_results_table(results)
    else:
        print_info("Todos los reportes ya estaban ingestados.")
        context_dir = Path(settings.context_reports_dir)
        available   = sorted(context_dir.glob("*.docx")) if context_dir.exists() else []
        if available:
            force = questionary.confirm(
                "  ¿Forzar re-ingesta? (útil si la base vectorial estaba vacía)",
                default=False,
                style=MENU_STYLE,
            ).ask()
            if force:
                with spinning("Forzando re-ingesta de todos los archivos…"):
                    try:
                        forced = pipeline.ingest_all_context_reports(force=True)
                        if forced:
                            print_ok(f"Re-ingesta completada — {sum(forced.values())} chunk(s) totales:")
                            ingestion_results_table(forced)
                        else:
                            print_warn("No se encontraron archivos .docx en la carpeta de contexto.")
                    except Exception as e:
                        print_err(f"Error en re-ingesta: {e}")

    console.print()
    console.print("[dim]  Opcional: añade una nota o resumen de cambios del proyecto.[/dim]")
    console.print("[dim]  Ejemplo: 'Se refactorizó el módulo de pagos y se actualizó a Vue 3.'[/dim]")
    console.print()
    note = questionary.text("  Nota (Enter para saltar):", multiline=True, style=MENU_STYLE).ask()

    if note and note.strip():
        _save_note_with_consolidation(note.strip(), pipeline)


# ─────────────────────────────────────────────────────────────────
# QUERY KNOWLEDGE
# ─────────────────────────────────────────────────────────────────

def action_query_knowledge() -> None:
    section("Consultar conocimiento del proyecto")

    from app.rag.knowledge_retriever import KnowledgeRetriever
    from app.rag.knowledge_ingestion import KnowledgeIngestionPipeline

    retriever = KnowledgeRetriever()
    pipeline  = KnowledgeIngestionPipeline()

    history: list[dict] = []
    _MAX_HISTORY = 20
    turn = 0

    while True:
        turn += 1
        console.print()

        label    = "  Consulta:" if turn == 1 else "  Siguiente pregunta:"
        question = questionary.text(label, style=MENU_STYLE).ask()

        if not question or not question.strip():
            print_info("Sin consulta. Volviendo al menú.")
            break

        try:
            with querying_knowledge("Consultando base de conocimiento…"):
                answer = retriever.answer_with_history(question, history=history)
        except Exception as e:
            print_err(f"Error en la consulta: {e}")
            break

        answer_panel(answer)

        history.append({"role": "user",      "content": question})
        history.append({"role": "assistant", "content": answer})
        if len(history) > _MAX_HISTORY:
            history = history[-_MAX_HISTORY:]

        console.print()
        post_action = questionary.select(
            "  ¿Qué deseas hacer?",
            choices=[
                questionary.Choice("Reajustar contexto con esta respuesta", value="reajust"),
                questionary.Choice("Continuar conversación",                 value="continue"),
                questionary.Choice("Finalizar",                              value="exit"),
            ],
            style=MENU_STYLE,
        ).ask()

        if post_action == "reajust":
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
                with spinning("Guardando nota en la base de conocimiento…"):
                    try:
                        chunks = pipeline.ingest_text_note(note_to_save)
                        print_ok(f"Nota guardada en project_knowledge ({chunks} chunk/s).")
                    except Exception as e:
                        print_err(f"Error al guardar contexto: {e}")

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

        elif post_action == "continue":
            continue
        else:
            break

    console.print()
    print_info("Sesión de consulta finalizada.")


# ─────────────────────────────────────────────────────────────────
# SERVER
# ─────────────────────────────────────────────────────────────────

def action_start_server() -> None:
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
# BACKUP & RESTORE
# ─────────────────────────────────────────────────────────────────

def action_backup_knowledge() -> None:
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
            questionary.Choice("  ☁️  Crear backup ahora (subir a Drive)",  value="backup"),
            questionary.Choice("  ⬇️  Restaurar desde un backup en Drive", value="restore"),
            questionary.Choice("  📋  Listar backups disponibles en Drive", value="list"),
            questionary.Choice("  ❌  Cancelar",                            value="cancel"),
        ],
        style=MENU_STYLE,
    ).ask()

    if action == "cancel" or action is None:
        return

    if action == "backup":
        with spinning("Comprimiendo y subiendo base de conocimiento a Drive…"):
            try:
                url = drive.backup_knowledge()
                print_ok("¡Backup creado exitosamente!")
                console.print(f"  [dim]📎 {url}[/dim]")
            except ValueError as e:
                print_warn(str(e))
            except Exception as e:
                print_err(f"Error al crear el backup: {e}")

    elif action in ("list", "restore"):
        with spinning("Consultando backups en Drive…"):
            try:
                backups = drive.list_knowledge_backups()
            except Exception as e:
                print_err(f"Error listando backups: {e}")
                return

        if not backups:
            print_info("No hay backups en Drive todavía. Crea uno primero.")
            return

        backups_table(backups)

        if action == "list":
            return

        choices_b = [questionary.Choice(f"  {b['name']}", value=i - 1) for i, b in enumerate(backups, 1)]
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

        with spinning(f"Descargando y restaurando {escape(chosen['name'])}…"):
            try:
                drive.restore_knowledge(chosen["id"], chosen["name"])
                print_ok("¡Base de conocimiento restaurada exitosamente!")
                print_info("Reinicia el sistema para que ChromaDB reconozca los datos restaurados.")
            except Exception as e:
                print_err(f"Error al restaurar: {e}")


# ─────────────────────────────────────────────────────────────────
# MAIN MENU
# ─────────────────────────────────────────────────────────────────

MENU_CHOICES = [
    questionary.Separator("  Conocimiento del proyecto"),
    questionary.Choice("  Alimentar contexto",             value="feed_context"),
    questionary.Choice("  Consultar conocimiento",         value="query_knowledge"),
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
    "feed_context":     action_feed_context,
    "query_knowledge":  action_query_knowledge,
    "generate":         action_generate,
    "list":             action_list_reports,
    "backup_knowledge": action_backup_knowledge,
    "server":           action_start_server,
}


def main() -> None:
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
            console.print("[dim]Hasta luego.[/dim]")
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