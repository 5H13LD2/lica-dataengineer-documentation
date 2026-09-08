#!/usr/bin/env python3
"""Build a formatted June-August Jeanel/Taira analysis workbook with LibreOffice."""

import csv
import os
import pathlib
import shutil
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from datetime import datetime

import uno
from com.sun.star.beans import PropertyValue


BASE = pathlib.Path(__file__).resolve().parent
OUTPUT = BASE / "Jeanel_Taira_June_July_August_2026_Analysis.xlsx"
SOURCES = {
    "June": BASE / "jeanel_co_june_2026_gold.csv",
    "July": BASE / "jeanel_co_july_2026.csv",
    "August": BASE / "jeanel_co_aug_2026.csv",
}
COLORS = {
    "navy": 0x17365D,
    "blue": 0x2F75B5,
    "light_blue": 0xD9EAF7,
    "teal": 0x00A6A6,
    "green": 0x70AD47,
    "light_green": 0xE2F0D9,
    "orange": 0xED7D31,
    "light_orange": 0xFCE4D6,
    "red": 0xC00000,
    "light_red": 0xF4CCCC,
    "gray": 0x666666,
    "light_gray": 0xF2F2F2,
    "white": 0xFFFFFF,
}


def prop(name, value):
    p = PropertyValue()
    p.Name, p.Value = name, value
    return p


def rectangle(x, y, width, height):
    value = uno.createUnoStruct("com.sun.star.awt.Rectangle")
    value.X, value.Y, value.Width, value.Height = x, y, width, height
    return value


def range_address(sheet, start_col, start_row, end_col, end_row):
    value = uno.createUnoStruct("com.sun.star.table.CellRangeAddress")
    value.Sheet = sheet.RangeAddress.Sheet
    value.StartColumn, value.StartRow = start_col, start_row
    value.EndColumn, value.EndRow = end_col, end_row
    return value


def load_rows():
    rows = []
    for month, path in SOURCES.items():
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                if row["date"] == "Total":
                    continue
                dt = datetime.strptime(row["date"], "%Y-%m-%d")
                rows.append({
                    "month": month,
                    "date": dt,
                    "inquiries": int(row["inquiries_assigned"]),
                    "moderate": int(row["moderate_high"]),
                    "bookings": int(row["bookings"]),
                })
    return rows


def summarize(rows):
    summary = {}
    for month in SOURCES:
        selected = [r for r in rows if r["month"] == month]
        inquiries = sum(r["inquiries"] for r in selected)
        moderate = sum(r["moderate"] for r in selected)
        bookings = sum(r["bookings"] for r in selected)
        summary[month] = {
            "days": len(selected), "inquiries": inquiries, "moderate": moderate,
            "bookings": bookings, "intent_rate": moderate / inquiries,
            "booking_rate": bookings / inquiries,
            "moderate_conversion": bookings / moderate,
            "avg_inquiries": inquiries / len(selected),
        }
    return summary


def set_text(sheet, col, row, value, style=None):
    cell = sheet.getCellByPosition(col, row)
    if isinstance(value, (int, float)):
        cell.Value = value
    else:
        cell.String = str(value)
    if style:
        style(cell)
    return cell


def paint(cell, bg=None, fg=None, bold=False, size=None, align=None):
    if bg is not None:
        cell.CellBackColor = bg
    if fg is not None:
        cell.CharColor = fg
    cell.CharWeight = 150 if bold else 100
    if size:
        cell.CharHeight = size
    if align is not None:
        cell.HoriJustify = align


def title_style(cell):
    paint(cell, COLORS["navy"], COLORS["white"], True, 18)


def header_style(cell):
    paint(cell, COLORS["blue"], COLORS["white"], True, 10, 3)


def section_style(cell):
    paint(cell, COLORS["navy"], COLORS["white"], True, 11)


def add_title(sheet, title, subtitle, last_col=7):
    sheet.getCellRangeByPosition(0, 0, last_col, 0).merge(True)
    set_text(sheet, 0, 0, title, title_style)
    sheet.getRows().getByIndex(0).Height = 900
    sheet.getCellRangeByPosition(0, 1, last_col, 1).merge(True)
    c = set_text(sheet, 0, 1, subtitle)
    paint(c, COLORS["light_blue"], COLORS["navy"], False, 10)
    sheet.getRows().getByIndex(1).Height = 550


def pct(cell):
    cell.NumberFormat = 10


def integer(cell):
    cell.NumberFormat = 3


def add_chart(sheet, name, rect, ranges, title, diagram_service="com.sun.star.chart.ColumnDiagram"):
    charts = sheet.Charts
    charts.addNewByName(name, rectangle(*rect), tuple(ranges), True, True)
    chart = charts.getByName(name).EmbeddedObject
    chart.HasMainTitle = True
    chart.Title.String = title
    chart.HasLegend = True
    return chart


def convert_daily_chart_to_line(path):
    """Convert the exported daily chart from OOXML bar-chart markup to line-chart markup."""
    chart_ns = "http://schemas.openxmlformats.org/drawingml/2006/chart"
    drawing_ns = "http://schemas.openxmlformats.org/drawingml/2006/main"
    ET.register_namespace("c", chart_ns)
    ET.register_namespace("a", "http://schemas.openxmlformats.org/drawingml/2006/main")
    with tempfile.TemporaryDirectory(prefix="jeanel_chart_patch_") as tmp:
        with zipfile.ZipFile(path) as source:
            source.extractall(tmp)
        chart_dir = pathlib.Path(tmp) / "xl" / "charts"
        converted = 0
        for chart_path in chart_dir.glob("chart*.xml"):
            tree = ET.parse(chart_path)
            root = tree.getroot()
            title_text = "".join(root.itertext())
            if not any(title in title_text for title in (
                "Daily Inquiries |", "Daily Moderate / High |", "Daily Bookings |",
                "Monthly Inquiries |", "Monthly Moderate / High |", "Monthly Bookings |"
            )):
                continue
            bar = root.find(f".//{{{chart_ns}}}barChart")
            if bar is None:
                continue
            bar.tag = f"{{{chart_ns}}}lineChart"
            for child_name in ("barDir", "gapWidth", "overlap"):
                for child in list(bar.findall(f"{{{chart_ns}}}{child_name}")):
                    bar.remove(child)
            grouping = bar.find(f"{{{chart_ns}}}grouping")
            if grouping is not None:
                grouping.set("val", "standard")
            for series in bar.findall(f"{{{chart_ns}}}ser"):
                for child in list(series.findall(f"{{{chart_ns}}}invertIfNegative")):
                    series.remove(child)
                marker = ET.Element(f"{{{chart_ns}}}marker")
                symbol = ET.SubElement(marker, f"{{{chart_ns}}}symbol")
                symbol.set("val", "none")
                series.insert(2, marker)
                # Match the working Japan dashboard line-series pattern: a
                # solid, rounded 2.25pt stroke. The original bar series has a
                # noFill line, which makes a converted line chart invisible.
                series_shape = series.find(f"{{{chart_ns}}}spPr")
                if series_shape is not None:
                    color_node = series_shape.find(f".//{{{drawing_ns}}}srgbClr")
                    color = color_node.get("val") if color_node is not None else "4a7ebb"
                    line = series_shape.find(f"{{{drawing_ns}}}ln")
                    if line is None:
                        line = ET.SubElement(series_shape, f"{{{drawing_ns}}}ln")
                    else:
                        line.clear()
                    line.set("w", "28440")
                    solid = ET.SubElement(line, f"{{{drawing_ns}}}solidFill")
                    ET.SubElement(solid, f"{{{drawing_ns}}}srgbClr", {"val": color})
                    ET.SubElement(line, f"{{{drawing_ns}}}round")
                smooth = ET.SubElement(series, f"{{{chart_ns}}}smooth")
                smooth.set("val", "1")
            plot_visible = root.find(f".//{{{chart_ns}}}plotVisOnly")
            if plot_visible is not None:
                plot_visible.set("val", "1")
            tree.write(chart_path, encoding="UTF-8", xml_declaration=True)
            converted += 1
        if converted != 6:
            raise RuntimeError(f"Expected six trend charts to convert, found {converted}")
        rebuilt = str(path) + ".tmp"
        with zipfile.ZipFile(rebuilt, "w", zipfile.ZIP_DEFLATED) as target:
            for root_dir, _, files in os.walk(tmp):
                for name in files:
                    item = pathlib.Path(root_dir) / name
                    target.write(item, item.relative_to(tmp))
        os.replace(rebuilt, path)


def build_dashboard(doc, summary):
    sheet = doc.Sheets.getByName("Executive Dashboard")
    add_title(sheet, "JEANEL CO / TAIRA | THREE-MONTH PERFORMANCE DASHBOARD",
              "June–August 2026 • daily inquiries, Moderate/High intent, and attributed bookings", 8)

    months = list(SOURCES)
    set_text(sheet, 0, 3, "CORE KPI", header_style)
    for i, month in enumerate(months, 1):
        set_text(sheet, i, 3, month.upper(), header_style)
    set_text(sheet, 4, 3, "JUL vs JUN", header_style)
    set_text(sheet, 5, 3, "AUG vs JUL", header_style)
    metrics = [
        ("Inquiries", "inquiries", False),
        ("Moderate / High", "moderate", False),
        ("Bookings", "bookings", False),
        ("Moderate / High rate", "intent_rate", True),
        ("Inquiry → booking rate", "booking_rate", True),
        ("Moderate → booking rate", "moderate_conversion", True),
        ("Average daily inquiries", "avg_inquiries", False),
    ]
    for r, (label, key, is_pct) in enumerate(metrics, 4):
        set_text(sheet, 0, r, label)
        for c, month in enumerate(months, 1):
            cell = set_text(sheet, c, r, summary[month][key])
            pct(cell) if is_pct else integer(cell)
        for c, (new, old) in enumerate((("July", "June"), ("August", "July")), 4):
            change = summary[new][key] / summary[old][key] - 1 if summary[old][key] else 0
            cell = set_text(sheet, c, r, change)
            pct(cell)
            paint(cell, COLORS["light_green"] if change >= 0 else COLORS["light_red"],
                  COLORS["green"] if change >= 0 else COLORS["red"], True)

    set_text(sheet, 0, 13, "EXECUTIVE READOUT", section_style)
    sheet.getCellRangeByPosition(0, 13, 5, 13).merge(True)
    insights = [
        f"Demand expanded: inquiries rose {summary['July']['inquiries']/summary['June']['inquiries']-1:.1%} in July and {summary['August']['inquiries']/summary['July']['inquiries']-1:.1%} in August.",
        f"Qualified volume grew to {summary['August']['moderate']:,}, but qualification rate eased from {summary['June']['intent_rate']:.1%} to {summary['August']['intent_rate']:.1%}.",
        f"Bookings peaked at {summary['July']['bookings']:,} in July, then fell {summary['August']['bookings']/summary['July']['bookings']-1:.1%} to {summary['August']['bookings']:,} in August.",
        f"Inquiry-to-booking conversion declined from {summary['June']['booking_rate']:.2%} in June to {summary['August']['booking_rate']:.2%} in August despite higher traffic.",
        "Priority: investigate August booking leakage and reconcile attribution logic before using cross-layer conversion targets.",
    ]
    for idx, line in enumerate(insights, 14):
        sheet.getCellRangeByPosition(0, idx, 5, idx).merge(True)
        cell = set_text(sheet, 0, idx, "• " + line)
        cell.IsTextWrapped = True
        if idx == 18:
            paint(cell, COLORS["light_orange"], COLORS["red"], True)
        sheet.getRows().getByIndex(idx).Height = 600

    # Compact source block used by dashboard charts.
    for c, h in enumerate(("Month", "Inquiries", "Moderate/High", "Bookings"), 10):
        set_text(sheet, c, 3, h, header_style)
    for r, month in enumerate(months, 4):
        set_text(sheet, 10, r, month)
        set_text(sheet, 11, r, summary[month]["inquiries"])
        set_text(sheet, 12, r, summary[month]["moderate"])
        set_text(sheet, 13, r, summary[month]["bookings"])
    addr = range_address(sheet, 10, 3, 13, 6)
    add_chart(sheet, "VolumeChart", (15500, 1800, 15000, 8500), (addr,), "Monthly KPI Volume")

    for c in range(0, 6):
        sheet.getColumns().getByIndex(c).Width = 4200 if c == 0 else 3000
    sheet.getColumns().getByIndex(6).Width = 600


def build_summary(doc, summary):
    sheet = doc.Sheets.getByName("Monthly Summary")
    add_title(sheet, "MONTHLY KPI SUMMARY", "Month-over-month scale, qualification, and conversion performance", 9)
    headers = ["Month", "Days", "Inquiries", "Moderate/High", "Bookings", "M/H Rate",
               "Inquiry→Booking", "M/H→Booking", "Avg Daily Inquiries"]
    for c, h in enumerate(headers):
        set_text(sheet, c, 3, h, header_style)
    for r, month in enumerate(SOURCES, 4):
        s = summary[month]
        values = [month, s["days"], s["inquiries"], s["moderate"], s["bookings"],
                  s["intent_rate"], s["booking_rate"], s["moderate_conversion"], s["avg_inquiries"]]
        for c, val in enumerate(values):
            cell = set_text(sheet, c, r, val)
            if c in (5, 6, 7): pct(cell)
            elif c > 0: integer(cell)
            if r % 2 == 0: cell.CellBackColor = COLORS["light_gray"]
    set_text(sheet, 0, 9, "MONTH-OVER-MONTH CHANGE", section_style)
    sheet.getCellRangeByPosition(0, 9, 8, 9).merge(True)
    for c, h in enumerate(["Comparison", "Inquiries", "Moderate/High", "Bookings", "M/H Rate Δ",
                           "Booking Rate Δ", "M/H Conversion Δ"]):
        set_text(sheet, c, 10, h, header_style)
    for r, (label, old, new) in enumerate((("July vs June", "June", "July"), ("August vs July", "July", "August")), 11):
        values = [label,
                  summary[new]["inquiries"] / summary[old]["inquiries"] - 1,
                  summary[new]["moderate"] / summary[old]["moderate"] - 1,
                  summary[new]["bookings"] / summary[old]["bookings"] - 1,
                  summary[new]["intent_rate"] - summary[old]["intent_rate"],
                  summary[new]["booking_rate"] - summary[old]["booking_rate"],
                  summary[new]["moderate_conversion"] - summary[old]["moderate_conversion"]]
        for c, val in enumerate(values):
            cell = set_text(sheet, c, r, val)
            if c:
                pct(cell)
                paint(cell, COLORS["light_green"] if val >= 0 else COLORS["light_red"],
                      COLORS["green"] if val >= 0 else COLORS["red"], True)
    for c in range(9): sheet.getColumns().getByIndex(c).Width = 3600 if c else 4200


def build_monthly_trends(doc, summary):
    sheet = doc.Sheets.getByName("3-Month Trends")
    add_title(sheet, "THREE-MONTH TREND DIRECTION",
              "June → July → August 2026 • month-level view showing whether each KPI is rising or falling", 9)
    headers = ["KPI", "June", "July", "August", "Jul vs Jun", "Aug vs Jul", "3-Month Direction", "Overall Change"]
    for c, h in enumerate(headers): set_text(sheet, c, 3, h, header_style)
    metrics = [
        ("Inquiries", "inquiries"),
        ("Moderate / High", "moderate"),
        ("Bookings", "bookings"),
        ("Moderate / High rate", "intent_rate"),
        ("Inquiry → booking rate", "booking_rate"),
        ("Moderate → booking rate", "moderate_conversion"),
    ]
    for r, (label, key) in enumerate(metrics, 4):
        values = [summary[m][key] for m in ("June", "July", "August")]
        jul_change = values[1] / values[0] - 1 if values[0] else 0
        aug_change = values[2] / values[1] - 1 if values[1] else 0
        overall = values[2] / values[0] - 1 if values[0] else 0
        if values[2] > values[1] > values[0]: direction = "↑ UP"
        elif values[2] < values[1] < values[0]: direction = "↓ DOWN"
        elif values[2] < values[1]: direction = "↓ DOWN vs July"
        elif values[2] > values[1]: direction = "↑ UP vs July"
        else: direction = "→ FLAT"
        set_text(sheet, 0, r, label)
        for c, value in enumerate(values, 1):
            cell = set_text(sheet, c, r, value)
            pct(cell) if key in ("intent_rate", "booking_rate", "moderate_conversion") else integer(cell)
        for c, value in ((4, jul_change), (5, aug_change), (7, overall)):
            cell = set_text(sheet, c, r, value); pct(cell)
            paint(cell, COLORS["light_green"] if value >= 0 else COLORS["light_red"],
                  COLORS["green"] if value >= 0 else COLORS["red"], True)
        cell = set_text(sheet, 6, r, direction)
        latest_up = values[2] >= values[1]
        paint(cell, COLORS["light_green"] if latest_up else COLORS["light_red"],
              COLORS["green"] if latest_up else COLORS["red"], True, 11, 3)

    set_text(sheet, 0, 11, "QUICK READ", section_style)
    sheet.getCellRangeByPosition(0, 11, 7, 11).merge(True)
    messages = [
        "↑ Inquiries: UP in both July and August — traffic is expanding.",
        "↑ Moderate / High volume: UP in both months, but slower than inquiry growth.",
        "↓ Bookings: UP in July, then DOWN in August — the latest direction is negative.",
        "↓ Conversion efficiency: inquiry-to-booking rate fell across the three-month period.",
    ]
    for r, message in enumerate(messages, 12):
        sheet.getCellRangeByPosition(0, r, 7, r).merge(True)
        cell = set_text(sheet, 0, r, message)
        cell.IsTextWrapped = True
        if "↓" in message: paint(cell, COLORS["light_red"], COLORS["red"], True)
        else: paint(cell, COLORS["light_green"], COLORS["green"], True)
        sheet.getRows().getByIndex(r).Height = 600

    # Monthly chart source block.
    for c, h in enumerate(("Month", "Inquiries", "Moderate/High", "Bookings"), 10):
        set_text(sheet, c, 3, h, header_style)
    for r, month in enumerate(("June", "July", "August"), 4):
        set_text(sheet, 10, r, month)
        set_text(sheet, 11, r, summary[month]["inquiries"])
        set_text(sheet, 12, r, summary[month]["moderate"])
        set_text(sheet, 13, r, summary[month]["bookings"])
    month_range = range_address(sheet, 10, 3, 10, 6)
    inquiry_range = range_address(sheet, 11, 3, 11, 6)
    moderate_range = range_address(sheet, 12, 3, 12, 6)
    booking_range = range_address(sheet, 13, 3, 13, 6)
    add_chart(sheet, "MonthlyInquiryLine", (1000, 10500, 15000, 7800),
              (month_range, inquiry_range), "Monthly Inquiries | June–August", "line")
    add_chart(sheet, "MonthlyModerateLine", (16500, 10500, 15000, 7800),
              (month_range, moderate_range), "Monthly Moderate / High | June–August", "line")
    add_chart(sheet, "MonthlyBookingLine", (32000, 10500, 15000, 7800),
              (month_range, booking_range), "Monthly Bookings | June–August", "line")
    for c in range(8): sheet.getColumns().getByIndex(c).Width = 3900 if c == 0 else 3200


def build_daily(doc, rows):
    sheet = doc.Sheets.getByName("Daily Trends")
    add_title(sheet, "DAILY PERFORMANCE TRENDS", "Daily operating view with rates calculated from each source CSV", 9)
    headers = ["Date", "Month", "Day", "Inquiries", "Moderate/High", "Bookings",
               "M/H Rate", "Inquiry→Booking", "M/H→Booking"]
    for c, h in enumerate(headers): set_text(sheet, c, 3, h, header_style)
    for rno, row in enumerate(rows, 4):
        vals = [row["date"], row["month"], row["date"].strftime("%a"), row["inquiries"],
                row["moderate"], row["bookings"], row["moderate"] / row["inquiries"],
                row["bookings"] / row["inquiries"], row["bookings"] / row["moderate"] if row["moderate"] else 0]
        for c, val in enumerate(vals):
            cell = set_text(sheet, c, rno, val)
            if c == 0:
                cell.Value = (row["date"] - datetime(1899, 12, 30)).days
                cell.NumberFormat = 37
            elif c >= 6: pct(cell)
            elif c >= 3: integer(cell)
            if rno % 2 == 0: cell.CellBackColor = COLORS["light_gray"]
    for c in range(9): sheet.getColumns().getByIndex(c).Width = 3000
    sheet.getColumns().getByIndex(0).Width = 3300


def build_line_graphs(doc, rows):
    sheet = doc.Sheets.getByName("Line Graphs")
    add_title(sheet, "DAILY TREND LINE GRAPHS",
              "Jeanel Co / Taira • June–August 2026 • three source metrics shown separately for readable scale", 9)
    # Chart source data sits to the right; the charts themselves begin in the
    # visible top-left area so users see them immediately on opening the file.
    headers = ("Date", "Inquiries", "Moderate/High", "Bookings")
    for c, h in enumerate(headers, 10): set_text(sheet, c, 3, h, header_style)
    for rno, row in enumerate(rows, 4):
        date_cell = set_text(sheet, 10, rno, (row["date"] - datetime(1899, 12, 30)).days)
        date_cell.NumberFormat = 37
        set_text(sheet, 11, rno, row["inquiries"])
        set_text(sheet, 12, rno, row["moderate"])
        set_text(sheet, 13, rno, row["bookings"])
    last_row = 3 + len(rows)
    date_range = range_address(sheet, 10, 3, 10, last_row)
    inquiry_range = range_address(sheet, 11, 3, 11, last_row)
    moderate_range = range_address(sheet, 12, 3, 12, last_row)
    booking_range = range_address(sheet, 13, 3, 13, last_row)
    add_chart(sheet, "DailyInquiryLine", (1000, 1800, 23500, 8000),
              (date_range, inquiry_range), "Daily Inquiries | June–August", "line")
    add_chart(sheet, "DailyModerateLine", (1000, 10200, 23500, 8000),
              (date_range, moderate_range), "Daily Moderate / High | June–August", "line")
    add_chart(sheet, "DailyBookingLine", (1000, 18600, 23500, 8000),
              (date_range, booking_range), "Daily Bookings | June–August", "line")


def build_weekday(doc, rows):
    sheet = doc.Sheets.getByName("Weekday Analysis")
    add_title(sheet, "DAY-OF-WEEK ANALYSIS", "Combined June–August operating patterns; weighted rates use total volumes", 8)
    grouped = defaultdict(list)
    for row in rows: grouped[row["date"].strftime("%A")].append(row)
    order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    headers = ["Day", "Days", "Inquiries", "Moderate/High", "Bookings", "Avg Inquiries",
               "M/H Rate", "Inquiry→Booking", "M/H→Booking"]
    for c, h in enumerate(headers): set_text(sheet, c, 3, h, header_style)
    for r, day in enumerate(order, 4):
        x = grouped[day]; iq = sum(v["inquiries"] for v in x); mh = sum(v["moderate"] for v in x); bk = sum(v["bookings"] for v in x)
        vals = [day, len(x), iq, mh, bk, iq/len(x), mh/iq, bk/iq, bk/mh]
        for c, val in enumerate(vals):
            cell = set_text(sheet, c, r, val)
            if c >= 6: pct(cell)
            elif c > 0: integer(cell)
            if day == "Sunday": paint(cell, COLORS["light_orange"], COLORS["navy"], c == 0)
    for c in range(9): sheet.getColumns().getByIndex(c).Width = 3300
    addr = range_address(sheet, 0, 3, 4, 10)
    add_chart(sheet, "WeekdayChart", (1500, 8500, 22000, 9000), (addr,), "Volume by Day of Week")


def build_raw(doc, rows):
    sheet = doc.Sheets.getByName("Raw Data")
    headers = ["date", "month", "inquiries_assigned", "moderate_high", "bookings", "source_file"]
    for c, h in enumerate(headers): set_text(sheet, c, 0, h, header_style)
    for rno, row in enumerate(rows, 1):
        vals = [row["date"].strftime("%Y-%m-%d"), row["month"], row["inquiries"], row["moderate"], row["bookings"], SOURCES[row["month"]].name]
        for c, val in enumerate(vals): set_text(sheet, c, rno, val)
    for c in range(6): sheet.getColumns().getByIndex(c).Width = 4300 if c in (0, 5) else 3200


def build_notes(doc):
    sheet = doc.Sheets.getByName("Methodology")
    add_title(sheet, "METHODOLOGY & DATA-QUALITY NOTES", "Read before using cross-month conversion comparisons", 6)
    notes = [
        ("Scope", "Jeanel Co / Taira daily inquiries, Moderate/High intent, and attributed bookings for June–August 2026."),
        ("June source", "jeanel_co_june_2026_gold.csv, extracted from p_looker_agent_daily_conversion for agent_key='chatbot/jco'."),
        ("July source", "jeanel_co_july_2026.csv, extracted from t_inquiry_funnel_conversion_daily_v2 using Taira original-owner attribution."),
        ("August source", "jeanel_co_aug_2026.csv dated rows only. Its stale Total row is excluded."),
        ("Comparability", "June uses the official staged Looker metric; July/August use the funnel mart. Intent correction and booking-attribution logic differ, so cross-month trends are directional rather than strict same-layer parity."),
        ("Moderate/High", "The workbook uses the CSV field as supplied. July/August combine Moderate, High, and Hot; June maps p_looker total_moderate_intents into the same display column."),
        ("Bookings", "Bookings are inquiry-date attributed in the funnel exports. The gold layer can differ at daily grain due to its separate reporting pipeline."),
        ("Rates", "M/H Rate = Moderate/High ÷ inquiries. Inquiry→Booking = bookings ÷ inquiries. M/H→Booking = bookings ÷ Moderate/High."),
        ("Generated", datetime.now().strftime("%Y-%m-%d %H:%M Asia/Manila")),
    ]
    for c, h in enumerate(("Topic", "Definition / caveat")): set_text(sheet, c, 3, h, header_style)
    for r, (topic, note) in enumerate(notes, 4):
        set_text(sheet, 0, r, topic)
        cell = set_text(sheet, 1, r, note)
        cell.IsTextWrapped = True
        sheet.getRows().getByIndex(r).Height = 850
        if topic == "Comparability": paint(cell, COLORS["light_orange"], COLORS["red"], True)
    sheet.getColumns().getByIndex(0).Width = 4000
    sheet.getColumns().getByIndex(1).Width = 18000


def main():
    rows = load_rows()
    summary = summarize(rows)
    profile = tempfile.mkdtemp(prefix="jeanel_lo_profile_")
    soffice = subprocess.Popen([
        shutil.which("soffice"), "--headless", f"-env:UserInstallation=file://{profile}",
        "--accept=socket,host=localhost,port=2083;urp;StarOffice.ComponentContext", "--norestore", "--nodefault"
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        local_ctx = uno.getComponentContext()
        resolver = local_ctx.ServiceManager.createInstanceWithContext("com.sun.star.bridge.UnoUrlResolver", local_ctx)
        ctx = None
        for _ in range(40):
            try:
                ctx = resolver.resolve("uno:socket,host=localhost,port=2083;urp;StarOffice.ComponentContext")
                break
            except Exception:
                time.sleep(0.25)
        if ctx is None: raise RuntimeError("Could not connect to LibreOffice")
        desktop = ctx.ServiceManager.createInstanceWithContext("com.sun.star.frame.Desktop", ctx)
        doc = desktop.loadComponentFromURL("private:factory/scalc", "_blank", 0, (prop("Hidden", True),))
        sheets = doc.Sheets
        sheets.getByIndex(0).Name = "Executive Dashboard"
        for name in ("3-Month Trends", "Line Graphs", "Monthly Summary", "Daily Trends", "Weekday Analysis", "Raw Data", "Methodology"):
            sheets.insertNewByName(name, sheets.Count)
        build_dashboard(doc, summary)
        build_monthly_trends(doc, summary)
        build_line_graphs(doc, rows)
        build_summary(doc, summary)
        build_daily(doc, rows)
        build_weekday(doc, rows)
        build_raw(doc, rows)
        build_notes(doc)
        doc.CurrentController.setActiveSheet(sheets.getByName("3-Month Trends"))
        doc.storeAsURL(uno.systemPathToFileUrl(str(OUTPUT)), (prop("FilterName", "Calc MS Excel 2007 XML"), prop("Overwrite", True)))
        doc.close(True)
        convert_daily_chart_to_line(OUTPUT)
    finally:
        soffice.terminate()
        try: soffice.wait(timeout=5)
        except subprocess.TimeoutExpired: soffice.kill()
        shutil.rmtree(profile, ignore_errors=True)
    print(OUTPUT)


if __name__ == "__main__":
    main()
