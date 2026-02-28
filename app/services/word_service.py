from __future__ import annotations

from datetime import date
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from docx.shared import Cm, Pt, RGBColor, Inches
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL

from app.config import get_settings
from app.models.report_model import (
    DailyInput,
    GeneratedReport,
    ReportType,
    TestCaseResult,
    ProjectTask,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()

# ─── Colour palette ──────────────────────────────────────────
PRIMARY = RGBColor(0x1F, 0x49, 0x7D)   # Dark blue
SECONDARY = RGBColor(0x2E, 0x75, 0xB6)  # Medium blue
ACCENT = RGBColor(0x70, 0xAD, 0x47)    # Green
DANGER = RGBColor(0xC0, 0x00, 0x00)    # Red
HEADER_BG = "1F497D"                    # Hex for table headers
PASS_COLOR = "70AD47"
FAIL_COLOR = "C00000"
WARN_COLOR = "FF8C00"


class WordService:
    """
    Builds the complete .docx from a GeneratedReport domain object.
    Uses Template Method: _build_cover → _build_toc → _build_body → _build_appendix
    """

    def __init__(self):
        self._output_dir = Path(settings.output_reports_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)

    def generate_docx(
        self,
        report: GeneratedReport,
        daily_input: DailyInput,
    ) -> Path:
        """
        Main entry point. Returns path to generated .docx file.
        """
        doc = Document()
        self._configure_document(doc)

        self._build_cover(doc, report, daily_input)
        self._add_page_break(doc)
        self._build_body_sections(doc, report)
        self._build_data_tables(doc, daily_input, report)
        self._add_page_break(doc)
        self._build_conclusions(doc, report)
        self._build_next_steps(doc, report)

        output_path = self._compute_output_path(report)
        doc.save(str(output_path))
        logger.info(f"✅ Document saved: {output_path}")
        return output_path

    # ─────────────────────────────────────────────────
    # Document configuration
    # ─────────────────────────────────────────────────

    def _configure_document(self, doc: Document) -> None:
        """Set page margins and default styles."""
        section = doc.sections[0]
        section.top_margin = Cm(2.5)
        section.bottom_margin = Cm(2.5)
        section.left_margin = Cm(3.0)
        section.right_margin = Cm(2.5)

        # Set global font to Century Gothic 10pt
        style = doc.styles['Normal']
        font = style.font
        font.name = 'Century Gothic'
        font.size = Pt(10)

        # Header with project identification
        header = section.header
        p = header.paragraphs[0]
        p.text = "auto-report-mcp | Generado automáticamente"
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        p.runs[0].font.size = Pt(8)
        p.runs[0].font.color.rgb = RGBColor(0x80, 0x80, 0x80)

    # ─────────────────────────────────────────────────
    # Cover page
    # ─────────────────────────────────────────────────

    def _build_cover(
        self, doc: Document, report: GeneratedReport, daily_input: DailyInput
    ) -> None:
        # Spacer
        for _ in range(6):
            doc.add_paragraph()

        # Report type label
        type_label = {
            ReportType.FUNCTIONAL_TESTS: "INFORME DE PRUEBAS FUNCIONALES",
            ReportType.PROJECT_PROGRESS: "INFORME DE AVANCE DE PROYECTO",
        }.get(report.report_type, "INFORME TÉCNICO")

        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(type_label)
        run.bold = True
        run.font.size = Pt(22)
        run.font.color.rgb = PRIMARY

        # Project name
        p2 = doc.add_paragraph()
        p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r2 = p2.add_run(report.project_name.upper())
        r2.bold = True
        r2.font.size = Pt(16)
        r2.font.color.rgb = SECONDARY

        # Version
        if daily_input.project_version:
            pv = doc.add_paragraph()
            pv.alignment = WD_ALIGN_PARAGRAPH.CENTER
            pv.add_run(f"Versión {daily_input.project_version}").font.size = Pt(12)

        for _ in range(4):
            doc.add_paragraph()

        # Metadata table
        meta = [
            ("Fecha:", str(report.report_date)),
            ("Ambiente:", report.environment),
            ("Preparado por:", daily_input.prepared_by),
            ("Generado:", str(report.generated_at.strftime("%Y-%m-%d %H:%M UTC"))),
        ]
        tbl = doc.add_table(rows=len(meta), cols=2)
        tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
        tbl.style = "Table Grid"
        for i, (label, value) in enumerate(meta):
            tbl.rows[i].cells[0].text = label
            tbl.rows[i].cells[1].text = value
            tbl.rows[i].cells[0].paragraphs[0].runs[0].bold = True
            tbl.rows[i].cells[0].width = Cm(5)
            tbl.rows[i].cells[1].width = Cm(8)

    # ─────────────────────────────────────────────────
    # Body sections
    # ─────────────────────────────────────────────────

    def _build_body_sections(self, doc: Document, report: GeneratedReport) -> None:
        sorted_sections = sorted(report.sections, key=lambda s: s.section_order)
        for section in sorted_sections:
            doc.add_heading(section.title, level=2)
            for para in section.content.split("\n"):
                if para.strip():
                    doc.add_paragraph(para.strip())

    # ─────────────────────────────────────────────────
    # Data tables
    # ─────────────────────────────────────────────────

    def _build_data_tables(
        self,
        doc: Document,
        daily_input: DailyInput,
        report: GeneratedReport,
    ) -> None:
        if report.report_type == ReportType.FUNCTIONAL_TESTS and daily_input.test_cases:
            self._build_test_cases_table(doc, daily_input.test_cases)
        elif report.report_type == ReportType.PROJECT_PROGRESS and daily_input.tasks:
            self._build_tasks_table(doc, daily_input.tasks)

    def _build_test_cases_table(
        self, doc: Document, test_cases: list[TestCaseResult]
    ) -> None:
        doc.add_heading("PRUEBA(S) DE INTEGRACIÓN", level=2)

        for tc in test_cases:
            # 9-row, 4-column table for each test case
            tbl = doc.add_table(rows=9, cols=4)
            tbl.style = "Table Grid"
            tbl.autofit = False

            # Column widths — total 15.5 cm (A4 21cm - left 3cm - right 2.5cm)
            # col0=3.5 | col1=7.0 | col2=1.5 | col3=3.5
            COL_W = [Cm(3.5), Cm(7.0), Cm(1.5), Cm(3.5)]
            for row in tbl.rows:
                for ci, w in enumerate(COL_W):
                    row.cells[ci].width = w

            # ── R1: Header ───────────────────────────────────────
            r1 = tbl.rows[0]
            c1 = r1.cells[0]
            c1.merge(r1.cells[3])
            c1.text = "PRUEBA(S) DE INTEGRACIÓN"
            self._shade_cell(c1, "E2EFDA")
            p1 = c1.paragraphs[0]
            p1.runs[0].bold = True
            p1.alignment = WD_ALIGN_PARAGRAPH.CENTER

            # ── R2: Módulo / Número de prueba ────────────────────
            r2 = tbl.rows[1]
            # Col 0 – label
            c2_0 = r2.cells[0]
            c2_0.text = "Módulo"
            c2_0.paragraphs[0].runs[0].bold = True
            self._shade_cell(c2_0, "F2F2F2")
            self._vcenter(c2_0)
            # Col 1 – module name
            c2_1 = r2.cells[1]
            c2_1.text = tc.module
            self._vcenter(c2_1)
            # Cols 2-3 merged – test number (gray + bold)
            c2_2 = r2.cells[2]
            c2_2.merge(r2.cells[3])
            c2_2.text = f"Número de la prueba {tc.test_id}"
            c2_2.paragraphs[0].runs[0].bold = True
            self._shade_cell(c2_2, "F2F2F2")
            self._vcenter(c2_2)

            # ── R3: Descripción ──────────────────────────────────
            r3 = tbl.rows[2]
            c3_0 = r3.cells[0]
            c3_0.text = "Descripción"
            c3_0.paragraphs[0].runs[0].bold = True
            self._shade_cell(c3_0, "F2F2F2")
            self._vcenter(c3_0)
            c3_1 = r3.cells[1]
            c3_1.merge(r3.cells[3])
            c3_1.text = tc.description

            # ── R4: Preparada por ────────────────────────────────
            r4 = tbl.rows[3]
            c4_0 = r4.cells[0]
            c4_0.text = "Preparada por"
            c4_0.paragraphs[0].runs[0].bold = True
            self._shade_cell(c4_0, "F2F2F2")
            self._vcenter(c4_0)
            r4.cells[1].text = tc.prepared_by or "—"
            self._vcenter(r4.cells[1])
            c4_2 = r4.cells[2]
            c4_2.text = "Fecha:"
            c4_2.paragraphs[0].runs[0].bold = True
            self._shade_cell(c4_2, "F2F2F2")
            self._vcenter(c4_2)
            r4.cells[3].text = tc.prepare_date or "—"
            self._vcenter(r4.cells[3])

            # ── R5: Probada por ──────────────────────────────────
            r5 = tbl.rows[4]
            c5_0 = r5.cells[0]
            c5_0.text = "Probada por"
            c5_0.paragraphs[0].runs[0].bold = True
            self._shade_cell(c5_0, "F2F2F2")
            self._vcenter(c5_0)
            r5.cells[1].text = tc.tested_by or "—"
            self._vcenter(r5.cells[1])
            c5_2 = r5.cells[2]
            c5_2.text = "Fecha:"
            c5_2.paragraphs[0].runs[0].bold = True
            self._shade_cell(c5_2, "F2F2F2")
            self._vcenter(c5_2)
            r5.cells[3].text = tc.test_date or "—"
            self._vcenter(r5.cells[3])

            # ── R6: Condiciones de ejecución (full-width) ────────
            r6 = tbl.rows[5]
            c6 = r6.cells[0]
            c6.merge(r6.cells[3])
            # Bold title in first paragraph
            p6_title = c6.paragraphs[0]
            p6_title.clear()
            run6 = p6_title.add_run("Condiciones de ejecución")
            run6.bold = True
            # Bullet list
            for pc in (tc.preconditions or ["—"]):
                pb = c6.add_paragraph(pc, style="List Bullet")
                pb.paragraph_format.space_after = Pt(2)

            # ── R7: Pasos de ejecución ───────────────────────────
            r7 = tbl.rows[6]
            c7_0 = r7.cells[0]
            c7_0.text = "Pasos de\nejecución"
            c7_0.paragraphs[0].runs[0].bold = True
            self._shade_cell(c7_0, "F2F2F2")
            c7_1 = r7.cells[1]
            c7_1.merge(r7.cells[3])
            # Remove blank starter paragraph then add numbered steps
            for step in (tc.steps or ["—"]):
                p7 = c7_1.add_paragraph(step, style="List Number")
                p7.paragraph_format.space_after = Pt(2)
            # Remove the initial empty paragraph Word always inserts
            first_p = c7_1.paragraphs[0]
            if not first_p.text and len(c7_1.paragraphs) > 1:
                first_p._element.getparent().remove(first_p._element)

            # ── R8: Resultados esperados (full-width) ────────────
            r8 = tbl.rows[7]
            c8 = r8.cells[0]
            c8.merge(r8.cells[3])
            p8_title = c8.paragraphs[0]
            p8_title.clear()
            run8 = p8_title.add_run("Resultados esperados")
            run8.bold = True
            for exp in (tc.expected_results or ["—"]):
                pe = c8.add_paragraph(exp, style="List Bullet")
                pe.paragraph_format.space_after = Pt(2)

            # ── R9: Resultados obtenidos (full-width) ────────────
            r9 = tbl.rows[8]
            c9 = r9.cells[0]
            c9.merge(r9.cells[3])
            p9_title = c9.paragraphs[0]
            p9_title.clear()
            run9 = p9_title.add_run("Resultados obtenidos")
            run9.bold = True

            status_map = {"PASS": "APROBADA", "FAIL": "REPROBADA", "BLOCKED": "BLOQUEADA"}
            local_status = status_map.get(tc.status, tc.status)

            for act in (tc.actual_results or ["—"]):
                pa = c9.add_paragraph(act, style="List Bullet")
                pa.paragraph_format.space_after = Pt(2)

            # "Resultado de la prueba: APROBADA" bullet
            p_final = c9.add_paragraph(style="List Bullet")
            p_final.paragraph_format.space_after = Pt(2)
            p_final.add_run("Resultado de la prueba: ").bold = True
            p_final.add_run(local_status)

            # Evidence image
            if tc.evidence_image_filename:
                img_path = settings.input_images_path / tc.evidence_image_filename
                if img_path.exists():
                    p_img = c9.add_paragraph()
                    p_img.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    try:
                        p_img.add_run().add_picture(str(img_path), width=Cm(14.0))
                    except Exception as e:
                        logger.warning(f"No se pudo insertar la imagen {img_path.name}: {e}")

            # Space between test case tables
            doc.add_paragraph()

    def _build_tasks_table(
        self, doc: Document, tasks: list[ProjectTask]
    ) -> None:
        doc.add_heading("Detalle de Tareas", level=2)
        headers = ["ID", "Tarea", "Responsable", "Estado", "Avance %", "Sprint"]
        tbl = doc.add_table(rows=1, cols=len(headers))
        tbl.style = "Table Grid"

        for i, h in enumerate(headers):
            self._style_header_cell(tbl.rows[0].cells[i], text=h)

        for task in tasks:
            row = tbl.add_row()
            row.cells[0].text = task.task_id
            row.cells[1].text = task.title
            row.cells[2].text = task.assignee
            row.cells[3].text = task.status
            row.cells[4].text = f"{task.progress_pct}%"
            row.cells[5].text = task.sprint

    # ─────────────────────────────────────────────────
    # Conclusions
    # ─────────────────────────────────────────────────

    def _build_conclusions(self, doc: Document, report: GeneratedReport) -> None:
        doc.add_heading("Conclusiones y Recomendaciones", level=1)
        for para in report.conclusions.split("\n"):
            if para.strip():
                doc.add_paragraph(para.strip())

    def _build_next_steps(self, doc: Document, report: GeneratedReport) -> None:
        if not report.next_steps:
            return
        doc.add_heading("Próximos Pasos", level=2)
        for step in report.next_steps:
            p = doc.add_paragraph(style="List Bullet")
            p.add_run(step)

    # ─────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────

    def _compute_output_path(self, report: GeneratedReport) -> Path:
        rt_str = getattr(report.report_type, "value", str(report.report_type))
        filename = (
            f"{report.report_date}_{rt_str}_{report.project_name}"
            .replace(" ", "_")
            .lower()
            + ".docx"
        )
        return self._output_dir / filename

    @staticmethod
    def _add_page_break(doc: Document) -> None:
        from docx.oxml.ns import qn as _qn
        p = doc.add_paragraph()
        run = p.add_run()
        br = OxmlElement("w:br")
        br.set(_qn("w:type"), "page")
        run._r.append(br)

    @staticmethod
    def _style_header_cell(cell, text: str | None = None) -> None:
        if text:
            cell.text = text
        cell.paragraphs[0].runs[0 if cell.paragraphs[0].runs else -1].bold = True if cell.paragraphs[0].runs else None
        WordService._shade_cell(cell, HEADER_BG)
        if cell.paragraphs[0].runs:
            cell.paragraphs[0].runs[0].font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
            cell.paragraphs[0].runs[0].bold = True

    @staticmethod
    def _shade_cell(cell, fill_hex: str) -> None:
        tc = cell._tc
        tcPr = tc.get_or_add_tcPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"), fill_hex)
        tcPr.append(shd)

    @staticmethod
    def _vcenter(cell) -> None:
        """Set vertical alignment to CENTER for a table cell."""
        tc = cell._tc
        tcPr = tc.get_or_add_tcPr()
        vAlign = OxmlElement("w:vAlign")
        vAlign.set(qn("w:val"), "center")
        tcPr.append(vAlign)
