import re
from pathlib import Path

CLI_PATH = Path("cli.py")
assert CLI_PATH.exists(), "cli.py not found — run from project root"

src = CLI_PATH.read_text(encoding="utf-8")

OLD = '''    if note and note.strip():
        with Progress(SpinnerColumn(), TextColumn("[cyan]{task.description}"), console=console) as p:
            p.add_task("Registrando nota…", total=None)
            try:
                chunks = pipeline.ingest_text_note(note)
                p.stop()
                print_ok(f"Nota registrada en la base de conocimiento ({chunks} chunk/s).")
            except Exception as e:
                p.stop()
                print_err(f"Error procesando la nota: {e}")'''

NEW = '''    if note and note.strip():
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
                        f"[bold yellow]⚠  Se encontraron {len(similar)} nota(s) relacionada(s)[/bold yellow]\\n"
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
                print_err(f"Error procesando la nota: {e}")'''

assert OLD in src, "Could not find the target block — has cli.py been modified already?"
patched = src.replace(OLD, NEW, 1)
CLI_PATH.write_text(patched, encoding="utf-8")
print("cli.py patched successfully.")
