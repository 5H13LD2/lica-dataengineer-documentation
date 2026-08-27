#!/usr/bin/env python3
"""Refresh the Japan campaign dashboard from the June and July CSV exports."""

import csv
import os
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter, defaultdict

BASE = os.path.dirname(os.path.abspath(__file__))
SOURCE = os.path.join(BASE, "MPE_Japan_Senior_Analyst_Dashboard.xlsx")
OUTPUT = os.path.join(BASE, "MPE_Japan_Campaign_Analytics_Dashboard.xlsx")
NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
ET.register_namespace("", NS)


def money(value):
    cleaned = re.sub(r"[^0-9.-]", "", value or "")
    return float(cleaned) if cleaned else 0.0


def load(month):
    path = os.path.join(BASE, f"{month.lower()} 1 - 31.csv")
    with open(path, encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def stats(rows):
    by_pattern = defaultdict(lambda: {"orders": 0, "qty": 0.0, "sales": 0.0})
    for row in rows:
        p = row["New Field"].strip()
        by_pattern[p]["orders"] += 1
        by_pattern[p]["qty"] += float(row["quantity"] or 0)
        by_pattern[p]["sales"] += money(row["Net Sales of VAT"])
    return {
        "orders": len(rows),
        "qty": sum(float(r["quantity"] or 0) for r in rows),
        "sales": sum(money(r["Net Sales of VAT"]) for r in rows),
        "gross": sum(money(r["Fulfilled Amount (GROSS)"]) for r in rows),
        "sets": sum(float(r["quantity"] or 0) >= 4 for r in rows),
        "fulfilled": sum(r["Status"].strip() == "Fulfilled" for r in rows),
        "fully_paid": sum(r["payment_status"].strip() == "Fully Paid" for r in rows),
        "status": Counter(r["Status"].strip() for r in rows),
        "pattern": by_pattern,
    }


def split_ref(ref):
    m = re.fullmatch(r"([A-Z]+)(\d+)", ref)
    col = 0
    for ch in m.group(1):
        col = col * 26 + ord(ch) - 64
    return col, int(m.group(2))


def set_cell(root, ref, value, style=None):
    sheet_data = root.find(f"{{{NS}}}sheetData")
    col_no, row_no = split_ref(ref)
    row = next((r for r in sheet_data if int(r.attrib["r"]) == row_no), None)
    if row is None:
        row = ET.Element(f"{{{NS}}}row", {"r": str(row_no)})
        sheet_data.append(row)
        sheet_data[:] = sorted(sheet_data, key=lambda x: int(x.attrib["r"]))
    cell = next((c for c in row if c.attrib.get("r") == ref), None)
    if cell is None:
        cell = ET.Element(f"{{{NS}}}c", {"r": ref})
        row.append(cell)
        row[:] = sorted(row, key=lambda x: split_ref(x.attrib["r"])[0])
    cell.clear()
    cell.attrib["r"] = ref
    if style is not None:
        cell.attrib["s"] = str(style)
    if isinstance(value, str):
        cell.attrib["t"] = "inlineStr"
        inline = ET.SubElement(cell, f"{{{NS}}}is")
        ET.SubElement(inline, f"{{{NS}}}t").text = value
    else:
        cell.attrib["t"] = "n"
        ET.SubElement(cell, f"{{{NS}}}v").text = f"{value:.10g}"


def growth(new, old):
    return new / old - 1 if old else 0


def add_number_styles(path):
    """Add number and traffic-light styles."""
    root = ET.parse(path).getroot()
    num_fmts = root.find(f"{{{NS}}}numFmts")
    num_fmts.set("count", "2")
    ET.SubElement(num_fmts, f"{{{NS}}}numFmt", {"numFmtId": "164", "formatCode": '₱#,##0;[Red]-₱#,##0'})
    ET.SubElement(num_fmts, f"{{{NS}}}numFmt", {"numFmtId": "165", "formatCode": '0.0%;[Red]-0.0%'})
    xfs = root.find(f"{{{NS}}}cellXfs")
    currency_style = len(xfs)
    ET.SubElement(xfs, f"{{{NS}}}xf", {"numFmtId": "164", "fontId": "0", "fillId": "0", "borderId": "0", "applyNumberFormat": "1", "xfId": "0"})
    percent_style = len(xfs)
    ET.SubElement(xfs, f"{{{NS}}}xf", {"numFmtId": "165", "fontId": "0", "fillId": "0", "borderId": "0", "applyNumberFormat": "1", "xfId": "0"})
    fills = root.find(f"{{{NS}}}fills")
    traffic = []
    for color in ("C6EFCE", "FFC7CE", "FFEB9C"):  # green, red, yellow
        fill_id = len(fills)
        fill = ET.SubElement(fills, f"{{{NS}}}fill")
        pattern = ET.SubElement(fill, f"{{{NS}}}patternFill", {"patternType": "solid"})
        ET.SubElement(pattern, f"{{{NS}}}fgColor", {"rgb": "FF" + color})
        ET.SubElement(pattern, f"{{{NS}}}bgColor", {"indexed": "64"})
        style_id = len(xfs)
        ET.SubElement(xfs, f"{{{NS}}}xf", {"numFmtId": "165", "fontId": "1", "fillId": str(fill_id), "borderId": "0", "applyNumberFormat": "1", "applyFill": "1", "xfId": "0"})
        traffic.append(style_id)
    fills.set("count", str(len(fills)))
    xfs.set("count", str(len(xfs)))
    ET.ElementTree(root).write(path, encoding="UTF-8", xml_declaration=True)
    return currency_style, percent_style, traffic[0], traffic[1], traffic[2]


def signal_style(value, green, red, yellow, threshold=0.02):
    if value > threshold:
        return green
    if value < -threshold:
        return red
    return yellow


def main():
    raw_june, raw_july = load("June"), load("July")
    # Campaign rule used throughout the dashboard: count only orders with 4+ tires.
    june_rows = [r for r in raw_june if float(r["quantity"] or 0) >= 4]
    july_rows = [r for r in raw_july if float(r["quantity"] or 0) >= 4]
    june, july = stats(june_rows), stats(july_rows)
    patterns = ["Primacy 5", "Latitude Sport 3", "Pilot Sport 5", "Pilot Sport 4 S", "Pilot Sport Cup 2"]
    totals = {}
    for p in patterns:
        totals[p] = {k: june["pattern"][p][k] + july["pattern"][p][k] for k in ("orders", "qty", "sales")}

    with tempfile.TemporaryDirectory(prefix="gulong_dashboard_") as tmp:
        with zipfile.ZipFile(SOURCE) as zin:
            zin.extractall(tmp)
        currency_style, percent_style, green_style, red_style, yellow_style = add_number_styles(os.path.join(tmp, "xl/styles.xml"))

        # Executive dashboard: KPI cards and decision-ready narrative.
        p1 = os.path.join(tmp, "xl/worksheets/sheet1.xml")
        r1 = ET.parse(p1).getroot()
        executive = {
            "A1": "MPE Japan Campaign | Executive Analytics Dashboard",
            "A2": "June vs July 2026 • qualifying Michelin patterns • only orders with 4+ tires counted",
            "A8": "CORE KPI", "B8": "RESULT",
            "A9": "Campaign-qualified tire volume (4+)", "B9": july["qty"],
            "A10": "Volume growth vs June", "B10": growth(july["qty"], june["qty"]),
            "A11": "Net sales", "B11": july["sales"],
            "A12": "Net sales growth vs June", "B12": growth(july["sales"], june["sales"]),
            "A13": "Campaign-qualified orders (4+)", "B13": july["orders"],
            "A14": "Order growth vs June", "B14": growth(july["orders"], june["orders"]),
            "A15": "Excluded orders below 4 tires", "B15": len(raw_july) - len(july_rows),
            "A16": "Eligible share of source orders", "B16": len(july_rows) / len(raw_july),
            "A17": "Fulfillment rate", "B17": july["fulfilled"] / july["orders"],
            "A18": "Fully paid rate", "B18": july["fully_paid"] / july["orders"],
            "A20": "EXECUTIVE READOUT", "A21": "July accelerated strongly across all commercial KPIs.",
            "A22": f"Volume increased by {july['qty']-june['qty']:.0f} tires (+{growth(july['qty'],june['qty']):.1%}).",
            "A23": f"Net sales increased by ₱{july['sales']-june['sales']:,.0f} (+{growth(july['sales'],june['sales']):.1%}).",
            "A24": f"Primacy 5 generated {july['pattern']['Primacy 5']['qty']/july['qty']:.1%} of July tire volume.",
            "A25": f"{len(july_rows)} of {len(raw_july)} July source orders met the 4+ tire rule ({len(july_rows)/len(raw_july):.1%}).",
            "A27": "INTERPRETATION", "A28": "The June-to-July jump is consistent with positive campaign momentum.",
            "A29": "Treat this as association—not proven causation—without a control group or longer baseline.",
            "D40": "CAMPAIGN MECHANIC",
            "D41": "Customer buys 4 tires (1 set), same qualifying pattern, in one transaction.",
            "D42": "Qualifying: Latitude Sport 3, Primacy 5, Pilot Sport 5, Pilot Sport 4 S,",
            "D43": "Pilot Sport Cup 2, Pilot Sport Cup 2 R, Pilot Sport 4 SUV.",
            "D45": "DATA NOTE",
            "D46": "All dashboard calculations exclude orders below 4 tires; raw rows remain for audit.",
            "A31": "TRAFFIC-LIGHT LEGEND", "A32": "Green", "B32": "Increase > +2%",
            "A33": "Yellow", "B33": "Stable: −2% to +2%", "A34": "Red", "B34": "Decrease < −2%",
        }
        for ref, val in executive.items():
            style = 2 if ref in {"A1", "A20", "A27", "D40", "D45"} else None
            if ref in {"B11"}:
                style = currency_style
            elif ref in {"B10", "B12", "B14", "B16", "B17", "B18"}:
                style = percent_style
            if ref in {"B10", "B12", "B14"}:
                style = signal_style(val, green_style, red_style, yellow_style)
            elif ref == "A32":
                style = green_style
            elif ref == "A33":
                style = yellow_style
            elif ref == "A34":
                style = red_style
            set_cell(r1, ref, val, style)
        ET.ElementTree(r1).write(p1, encoding="UTF-8", xml_declaration=True)

        # Summary table powering the month trend charts.
        p2 = os.path.join(tmp, "xl/worksheets/sheet2.xml")
        r2 = ET.parse(p2).getroot()
        values = {
            "B3": june["orders"], "C3": june["qty"], "D3": june["sales"],
            "B4": july["orders"], "C4": july["qty"], "D4": july["sales"],
            "B8": june["orders"], "C8": july["orders"],
            "B9": june["qty"], "C9": july["qty"],
            "D8": growth(july["orders"], june["orders"]),
            "D9": growth(july["qty"], june["qty"]),
            "B10": june["sales"], "C10": july["sales"], "D10": growth(july["sales"], june["sales"]),
            "A12": "Campaign Qualification", "A13": "Metric", "B13": "June", "C13": "July", "D13": "% Change",
            "A14": "Campaign-qualified orders (4+)", "B14": june["orders"], "C14": july["orders"], "D14": growth(july["orders"], june["orders"]),
            "A15": "Eligible share of source orders", "B15": len(june_rows)/len(raw_june), "C15": len(july_rows)/len(raw_july), "D15": len(july_rows)/len(raw_july)-len(june_rows)/len(raw_june),
            "A16": "Fulfillment rate", "B16": june["fulfilled"]/june["orders"], "C16": july["fulfilled"]/july["orders"], "D16": july["fulfilled"]/july["orders"]-june["fulfilled"]/june["orders"],
            "A17": "Fully paid rate", "B17": june["fully_paid"]/june["orders"], "C17": july["fully_paid"]/july["orders"], "D17": july["fully_paid"]/july["orders"]-june["fully_paid"]/june["orders"],
            "A20": "July Status", "B20": "Orders",
        }
        for i, (status, count) in enumerate(july["status"].most_common(), 21):
            values[f"A{i}"] = status; values[f"B{i}"] = count
        for ref, val in values.items():
            style = 1 if ref in {"A12", "A20"} else None
            if ref in {"D3", "D4", "B10", "C10"}:
                style = currency_style
            elif ref in {"D8", "D9", "D10", "D14", "B15", "C15", "D15", "B16", "C16", "D16", "B17", "C17", "D17"}:
                style = percent_style
            if ref in {"D8", "D9", "D10", "D14", "D15", "D16", "D17"}:
                style = signal_style(val, green_style, red_style, yellow_style)
            set_cell(r2, ref, val, style)
        ET.ElementTree(r2).write(p2, encoding="UTF-8", xml_declaration=True)

        # Pattern contribution table powering mix charts.
        p3 = os.path.join(tmp, "xl/worksheets/sheet3.xml")
        r3 = ET.parse(p3).getroot()
        for row, pattern in enumerate(patterns, 2):
            set_cell(r3, f"D{row}", totals[pattern]["sales"], currency_style)
        # Add month split and incremental contribution for analyst drill-down.
        headers = ["Pattern", "June Tires", "July Tires", "Tire Growth", "June Sales", "July Sales", "Sales Growth", "Share of July Growth"]
        for col, header in enumerate(headers, 6):
            letters = chr(65 + col - 1)
            set_cell(r3, f"{letters}1", header, 1)
        total_delta = july["sales"] - june["sales"]
        for row, pattern in enumerate(patterns, 2):
            j, u = june["pattern"][pattern], july["pattern"][pattern]
            vals = [pattern, j["qty"], u["qty"], growth(u["qty"], j["qty"]), j["sales"], u["sales"], growth(u["sales"], j["sales"]), (u["sales"]-j["sales"])/total_delta]
            for col, val in enumerate(vals, 6):
                style = currency_style if col in {10, 11} else percent_style if col in {9, 12, 13} else None
                if col in {9, 12, 13}:
                    style = signal_style(val, green_style, red_style, yellow_style)
                set_cell(r3, f"{chr(65 + col - 1)}{row}", val, style)
        ET.ElementTree(r3).write(p3, encoding="UTF-8", xml_declaration=True)

        # Keep all source rows for traceability and flag those excluded from analysis.
        p4 = os.path.join(tmp, "xl/worksheets/sheet4.xml")
        r4 = ET.parse(p4).getroot()
        set_cell(r4, "O1", "Campaign Eligibility", 1)
        for row_no, row in enumerate(raw_june + raw_july, 2):
            eligible = float(row["quantity"] or 0) >= 4
            set_cell(r4, f"O{row_no}", "Eligible: 4+ tires" if eligible else "Excluded: below 4 tires")
        ET.ElementTree(r4).write(p4, encoding="UTF-8", xml_declaration=True)

        # Force spreadsheet applications to recalculate charts/cells on open.
        workbook = os.path.join(tmp, "xl/workbook.xml")
        wr = ET.parse(workbook).getroot()
        calc = wr.find(f"{{{NS}}}calcPr")
        calc.set("fullCalcOnLoad", "1"); calc.set("forceFullCalc", "1"); calc.set("calcMode", "auto")
        ET.ElementTree(wr).write(workbook, encoding="UTF-8", xml_declaration=True)

        with zipfile.ZipFile(OUTPUT, "w", zipfile.ZIP_DEFLATED) as zout:
            for root, _, files in os.walk(tmp):
                for name in files:
                    path = os.path.join(root, name)
                    zout.write(path, os.path.relpath(path, tmp))

    print(OUTPUT)


if __name__ == "__main__":
    main()
