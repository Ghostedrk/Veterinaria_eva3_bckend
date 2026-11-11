"""Dashboard estadístico de Jefatura y exportación de reportes (PDF y Excel)."""
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from io import BytesIO

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce, TruncMonth
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_safe

from . import roles
from .models import Atencion, Cita, Disponibilidad, OrdenCompra, Profesional
from .views import staff_required

MONTHS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def clp(value):
    return f"${int(value or 0):,}".replace(",", ".")


def parse_period(request):
    today = timezone.localdate()
    try:
        start = date.fromisoformat(request.GET.get("desde", ""))
    except ValueError:
        start = today.replace(day=1)
    try:
        end = date.fromisoformat(request.GET.get("hasta", ""))
    except ValueError:
        end = today
    if end < start:
        start, end = end, start
    if (end - start).days > 366 * 3:
        start = end - timedelta(days=366 * 3)
    return start, end


def bounds(start, end):
    tz = timezone.get_current_timezone()
    return (timezone.make_aware(datetime.combine(start, time.min), tz),
            timezone.make_aware(datetime.combine(end + timedelta(days=1), time.min), tz))


def minutes(a, b):
    return max((b - a).total_seconds() / 60, 0)


def metrics(start, end):
    first, last = bounds(start, end)
    visits = Atencion.objects.filter(fecha__range=(start, end))
    money = visits.aggregate(total=Coalesce(Sum("monto"), 0), n=Count("pk"), paid=Count("pk", filter=Q(monto__gt=0)))
    expenses = OrdenCompra.objects.filter(estado=OrdenCompra.Estado.PAGADA, pagada_en__gte=first,
                                          pagada_en__lt=last).aggregate(total=Coalesce(Sum("total"), 0))["total"]

    # Ingresos de los últimos 6 meses hasta el mes de "hasta".
    month = end.replace(day=1)
    months = []
    for _ in range(6):
        months.append(month)
        month = (month - timedelta(days=1)).replace(day=1)
    months.reverse()
    by_month = {
        row["mes"].date() if hasattr(row["mes"], "date") else row["mes"]: row["total"]
        for row in Atencion.objects.filter(fecha__gte=months[0], fecha__lte=end)
        .annotate(mes=TruncMonth("fecha")).values("mes").annotate(total=Coalesce(Sum("monto"), 0))
    }
    peak = max([by_month.get(m, 0) for m in months] + [1])
    monthly = [{"label": f"{MONTHS[m.month - 1]} {m:%y}", "total": by_month.get(m, 0),
                "pct": round(by_month.get(m, 0) / peak * 100)} for m in months]

    # Ocupación: minutos agendados sobre minutos disponibles, por profesional y especialidad.
    available, booked = defaultdict(float), defaultdict(float)
    for w in Disponibilidad.objects.filter(inicio__lt=last, fin__gt=first):
        available[w.profesional_id] += minutes(max(w.inicio, first), min(w.fin, last))
    for c in Cita.objects.filter(inicio__lt=last, fin__gt=first).exclude(estado=Cita.Estado.CANCELADA):
        booked[c.profesional_id] += minutes(max(c.inicio, first), min(c.fin, last))
    occupancy, by_specialty = [], defaultdict(lambda: [0.0, 0.0])
    for p in Profesional.objects.filter(pk__in=set(available) | set(booked)):
        free, used = available[p.pk], booked[p.pk]
        occupancy.append({"name": str(p), "specialty": p.especialidad, "hours": round(used / 60, 1),
                          "available": round(free / 60, 1), "pct": min(round(used / free * 100), 100) if free else 0})
        by_specialty[p.especialidad][0] += used
        by_specialty[p.especialidad][1] += free
    occupancy.sort(key=lambda r: -r["pct"])
    specialties = sorted(({"name": k, "pct": min(round(u / f * 100), 100) if f else 0}
                          for k, (u, f) in by_specialty.items()), key=lambda r: -r["pct"])

    ranking = list(visits.values("servicio__nombre").annotate(n=Count("pk"), total=Coalesce(Sum("monto"), 0))
                   .order_by("-n", "-total")[:8])
    top = max([r["n"] for r in ranking] + [1])
    for row in ranking:
        row["name"] = row["servicio__nombre"] or "Sin servicio asignado"
        row["pct"] = round(row["n"] / top * 100)

    past = Cita.objects.filter(inicio__gte=first, inicio__lt=min(last, timezone.now()))
    counts = past.aggregate(
        attended=Count("pk", filter=Q(estado=Cita.Estado.ATENDIDA)),
        missed=Count("pk", filter=Q(estado=Cita.Estado.NO_ASISTIO)),
        cancelled=Count("pk", filter=Q(estado=Cita.Estado.CANCELADA)),
        tutor_cancelled=Count("pk", filter=Q(respuesta_tutor=Cita.Respuesta.CANCELADA)),
    )
    closed = counts["attended"] + counts["missed"]
    return {
        "income": money["total"], "visits": money["n"], "expenses": expenses,
        "ticket": round(money["total"] / money["paid"]) if money["paid"] else 0,
        "balance": money["total"] - expenses,
        "monthly": monthly, "occupancy": occupancy, "specialties": specialties, "ranking": ranking,
        "no_show": round(counts["missed"] / closed * 100, 1) if closed else 0, **counts,
    }


@staff_required
@require_safe
def dashboard(request):
    if not request.user.is_superuser:
        raise PermissionDenied
    start, end = parse_period(request)
    return render(request, "clinic/reports.html", {"start": start, "end": end, "m": metrics(start, end)})


# Exportación -------------------------------------------------------------------

def clinical_rows(start, end):
    header = ["Fecha", "Mascota", "Especie", "Tutor", "Profesional", "Servicio", "Peso (kg)", "Diagnóstico",
              "Tratamiento", "Receta", "Exámenes"]
    rows = [[v.fecha, v.mascota.nombre, v.mascota.especie, v.mascota.tutor.nombre, v.profesional.nombre,
             v.servicio.nombre if v.servicio else "", float(v.peso_kg) if v.peso_kg else "", v.diagnostico,
             v.tratamiento, v.receta, v.examenes]
            for v in Atencion.objects.filter(fecha__range=(start, end))
            .select_related("mascota__tutor", "profesional", "servicio").order_by("fecha", "pk")]
    return header, rows


def accounting_rows(start, end):
    first, last = bounds(start, end)
    income = [[v.fecha, v.mascota.nombre, v.mascota.tutor.nombre, v.servicio.nombre if v.servicio else "",
               v.monto or 0]
              for v in Atencion.objects.filter(fecha__range=(start, end))
              .select_related("mascota__tutor", "servicio").order_by("fecha", "pk")]
    expenses = [[timezone.localdate(o.pagada_en), o.numero, o.proveedor, o.codigo_autorizacion, o.total]
                for o in OrdenCompra.objects.filter(estado=OrdenCompra.Estado.PAGADA, pagada_en__gte=first,
                                                    pagada_en__lt=last).order_by("pagada_en")]
    return ((["Fecha", "Mascota", "Tutor", "Servicio", "Monto (CLP)"], income),
            (["Fecha de pago", "Orden", "Proveedor", "Autorización", "Total (CLP)"], expenses))


def xlsx_response(filename, sheets, start, end):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    book = Workbook()
    book.remove(book.active)
    for title, header, rows, money_col in sheets:
        sheet = book.create_sheet(title)
        sheet.append([f"Veterinaria San Francisco · {title}"])
        sheet.append([f"Período: {start:%d/%m/%Y} al {end:%d/%m/%Y}"])
        sheet.append([])
        sheet.append(header)
        for cell in sheet[4]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="174A2A")
        for row in rows:
            sheet.append(row)
        sheet["A1"].font = Font(bold=True, size=14, color="174A2A")
        if money_col is not None and rows:
            total_row = sheet.max_row + 1
            letter = chr(ord("A") + money_col)
            sheet.cell(total_row, money_col, "Total").font = Font(bold=True)
            sheet.cell(total_row, money_col + 1, f"=SUM({letter}5:{letter}{total_row - 1})").font = Font(bold=True)
        for column in sheet.iter_cols(min_row=4):
            width = max(len(str(c.value or "")) for c in column)
            sheet.column_dimensions[column[0].column_letter].width = min(max(width + 2, 10), 50)
            for cell in column[1:]:
                if isinstance(cell.value, date):
                    cell.number_format = "DD/MM/YYYY"
                elif money_col is not None and cell.column == money_col + 1:
                    cell.number_format = '"$"#,##0'
                cell.alignment = Alignment(vertical="top", wrap_text=True)
        sheet.freeze_panes = "A5"
    buffer = BytesIO()
    book.save(buffer)
    response = HttpResponse(buffer.getvalue(),
                            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="{filename}.xlsx"'
    return response


def pdf_response(filename, title, sections, start, end, summary=()):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    styles = getSampleStyleSheet()
    cell = styles["BodyText"].clone("cell", fontSize=7.5, leading=9.5)
    green = colors.HexColor("#174A2A")
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), leftMargin=1.2 * cm, rightMargin=1.2 * cm,
                            topMargin=1.2 * cm, bottomMargin=1.2 * cm, title=title)
    story = [Paragraph(f"<font color='#174A2A'>Veterinaria San Francisco · {title}</font>", styles["Title"]),
             Paragraph(f"Período: {start:%d/%m/%Y} al {end:%d/%m/%Y} · Generado el "
                       f"{timezone.localtime():%d/%m/%Y %H:%M}", styles["Normal"]), Spacer(1, 10)]
    for label, value in summary:
        story.append(Paragraph(f"<b>{label}:</b> {value}", styles["Normal"]))
    if summary:
        story.append(Spacer(1, 10))

    def fmt(value):
        if isinstance(value, date):
            return f"{value:%d/%m/%Y}"
        return str(value)

    for subtitle, header, rows, money_col in sections:
        if subtitle:
            story += [Paragraph(subtitle, styles["Heading2"]), Spacer(1, 4)]
        data = [[Paragraph(f"<b>{h}</b>", cell) for h in header]]
        for row in rows:
            data.append([Paragraph(clp(v) if i == money_col else fmt(v).replace("\n", "<br/>"), cell)
                         for i, v in enumerate(row)])
        if not rows:
            data.append([Paragraph("Sin registros en el período.", cell)] + [""] * (len(header) - 1))
        table = Table(data, repeatRows=1, colWidths=[(doc.width / len(header))] * len(header))
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), green), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#DCE4D9")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F6F1")]),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story += [table, Spacer(1, 14)]
    doc.build(story)
    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}.pdf"'
    return response


@staff_required
@require_safe
def export(request):
    if not roles.is_full_staff(request.user):
        raise PermissionDenied
    kind, fmt = request.GET.get("tipo"), request.GET.get("formato")
    if kind not in ("clinico", "contable") or fmt not in ("pdf", "xlsx"):
        messages.error(request, "Elige un tipo de reporte y un formato válidos.")
        return redirect("reports-export-form")
    start, end = parse_period(request)
    filename = f"petcare_{kind}_{start:%Y-%m-%d}_{end:%Y-%m-%d}"
    if kind == "clinico":
        header, rows = clinical_rows(start, end)
        if fmt == "xlsx":
            return xlsx_response(filename, [("Reporte clínico", header, rows, None)], start, end)
        return pdf_response(filename, "Reporte clínico", [("", header, rows, None)], start, end)

    (income_header, income), (expense_header, expenses) = accounting_rows(start, end)
    total_in, total_out = sum(r[4] for r in income), sum(r[4] for r in expenses)
    if fmt == "xlsx":
        return xlsx_response(filename, [("Ingresos", income_header, income, 4),
                                        ("Egresos", expense_header, expenses, 4)], start, end)
    summary = [("Ingresos por atenciones", clp(total_in)), ("Egresos por compras pagadas", clp(total_out)),
               ("Resultado del período", clp(total_in - total_out))]
    return pdf_response(filename, "Reporte contable",
                        [("Ingresos por atenciones", income_header, income, 4),
                         ("Egresos por compras de insumos", expense_header, expenses, 4)],
                        start, end, summary)


@staff_required
@require_safe
def export_form(request):
    if not roles.is_full_staff(request.user):
        raise PermissionDenied
    start, end = parse_period(request)
    return render(request, "clinic/export.html", {"start": start, "end": end})
