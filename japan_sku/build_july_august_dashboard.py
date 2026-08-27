#!/usr/bin/env python3
"""Build the July 1-20 vs August 1-20 campaign dashboard."""

import csv
import os
import zipfile
import tempfile
import xml.etree.ElementTree as ET

import build_analytics_dashboard as dashboard

BASE = os.path.dirname(os.path.abspath(__file__))
JULY = os.path.join(BASE, "july 1 - 20 .csv")
AUGUST = os.path.join(BASE, "august 1 - 20.csv")
OUTPUT = os.path.join(BASE, "MPE_Japan_July_vs_August_1-20_Analytics_Dashboard.xlsx")
NS = dashboard.NS


def read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main():
    inputs = {"June": read_csv(JULY), "July": read_csv(AUGUST)}
    dashboard.load = lambda month: inputs[month]
    dashboard.OUTPUT = OUTPUT
    dashboard.main()

    with tempfile.TemporaryDirectory(prefix="july_august_dashboard_") as tmp:
        with zipfile.ZipFile(OUTPUT) as zin:
            zin.extractall(tmp)

        # Relabel the reusable dashboard template for equal 20-day cutoffs.
        targets = ["xl/workbook.xml"]
        targets += [f"xl/worksheets/sheet{i}.xml" for i in (1, 2, 3)]
        targets += [f"xl/charts/chart{i}.xml" for i in range(1, 8)]
        for rel in targets:
            path = os.path.join(tmp, rel)
            text = open(path, encoding="utf-8").read()
            text = text.replace("July accelerated", "August 1–20 performance changed")
            text = text.replace("performance changed strongly across all commercial KPIs", "performance was lower across the headline commercial KPIs")
            text = text.replace("positive campaign momentum", "a softer equal-cutoff campaign result")
            text = text.replace("June", "__PERIOD_ONE__").replace("July", "__PERIOD_TWO__")
            text = text.replace("__PERIOD_ONE__", "July 1–20").replace("__PERIOD_TWO__", "August 1–20")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(text)

        july_stats = dashboard.stats(inputs["June"])
        august_stats = dashboard.stats(inputs["July"])
        def qualified_qty(rows):
            return sum(float(r["quantity"] or 0) for r in rows if float(r["quantity"] or 0) >= 4)
        def fulfilled_qualified_qty(rows):
            return sum(float(r["quantity"] or 0) for r in rows if r["Status"].strip() == "Fulfilled" and float(r["quantity"] or 0) >= 4)
        def processing_qty(rows):
            return sum(float(r["quantity"] or 0) for r in rows if r["Status"].strip() == "Processing")
        jq, aq = qualified_qty(inputs["June"]), qualified_qty(inputs["July"])
        jfq, afq = fulfilled_qualified_qty(inputs["June"]), fulfilled_qualified_qty(inputs["July"])
        jp, ap = processing_qty(inputs["June"]), processing_qty(inputs["July"])
        sheet1_path = os.path.join(tmp, "xl/worksheets/sheet1.xml")
        sheet1 = ET.parse(sheet1_path).getroot()
        dashboard.set_cell(sheet1, "A9", "All booked tire quantity")
        dashboard.set_cell(sheet1, "A15", "Campaign-qualified tire qty (4+)")
        dashboard.set_cell(sheet1, "B15", aq)
        dashboard.set_cell(sheet1, "A16", "Fulfilled + qualified tire qty")
        dashboard.set_cell(sheet1, "B16", afq)
        dashboard.set_cell(sheet1, "A17", "Processing tire quantity")
        dashboard.set_cell(sheet1, "B17", ap)
        dashboard.set_cell(sheet1, "A18", "4+ tire order qualification rate")
        dashboard.set_cell(sheet1, "B18", august_stats["sets"] / august_stats["orders"], 4)
        dashboard.set_cell(sheet1, "A19", "Fulfilled order rate")
        dashboard.set_cell(sheet1, "B19", august_stats["fulfilled"] / august_stats["orders"], 4)
        dashboard.set_cell(sheet1, "A22", f"Tire volume decreased by {july_stats['qty']-august_stats['qty']:.0f} tires ({dashboard.growth(august_stats['qty'],july_stats['qty']):.1%}).")
        dashboard.set_cell(sheet1, "A23", f"Net sales decreased by ₱{july_stats['sales']-august_stats['sales']:,.0f} ({dashboard.growth(august_stats['sales'],july_stats['sales']):.1%}).")
        dashboard.set_cell(sheet1, "A28", "The equal-cutoff comparison shows softer August campaign performance through day 20.")
        dashboard.set_cell(sheet1, "A29", "August fulfillment is still immature: 15 orders remain Processing as of the export.")
        ET.ElementTree(sheet1).write(sheet1_path, encoding="UTF-8", xml_declaration=True)

        # Make booked, qualified, fulfilled, and pipeline quantities explicit in Summary.
        sheet2_path = os.path.join(tmp, "xl/worksheets/sheet2.xml")
        sheet2 = ET.parse(sheet2_path).getroot()
        dashboard.set_cell(sheet2, "C2", "All Booked Tires")
        dashboard.set_cell(sheet2, "A14", "Campaign-qualified orders (4+)")
        dashboard.set_cell(sheet2, "A15", "Campaign-qualified tire qty")
        dashboard.set_cell(sheet2, "B15", jq); dashboard.set_cell(sheet2, "C15", aq)
        dashboard.set_cell(sheet2, "D15", dashboard.growth(aq, jq), 6)
        dashboard.set_cell(sheet2, "A16", "Fulfilled + qualified tire qty")
        dashboard.set_cell(sheet2, "B16", jfq); dashboard.set_cell(sheet2, "C16", afq)
        dashboard.set_cell(sheet2, "D16", dashboard.growth(afq, jfq), 6)
        dashboard.set_cell(sheet2, "A17", "Processing tire quantity")
        dashboard.set_cell(sheet2, "B17", jp); dashboard.set_cell(sheet2, "C17", ap)
        # More processing is operational risk, so an increase is intentionally red.
        dashboard.set_cell(sheet2, "D17", dashboard.growth(ap, jp), 6)
        dashboard.set_cell(sheet2, "A18", "Qualification rate")
        dashboard.set_cell(sheet2, "B18", july_stats["sets"] / july_stats["orders"], 4)
        dashboard.set_cell(sheet2, "C18", august_stats["sets"] / august_stats["orders"], 4)
        dashboard.set_cell(sheet2, "D18", august_stats["sets"] / august_stats["orders"] - july_stats["sets"] / july_stats["orders"], 7)
        ET.ElementTree(sheet2).write(sheet2_path, encoding="UTF-8", xml_declaration=True)

        sheet3_path = os.path.join(tmp, "xl/worksheets/sheet3.xml")
        sheet3 = ET.parse(sheet3_path).getroot()
        dashboard.set_cell(sheet3, "C1", "All Booked Tire Quantity", 1)
        ET.ElementTree(sheet3).write(sheet3_path, encoding="UTF-8", xml_declaration=True)

        # Clarify the measure used by quantity charts.
        for chart_no in (2, 5, 7):
            chart_path = os.path.join(tmp, f"xl/charts/chart{chart_no}.xml")
            chart_text = open(chart_path, encoding="utf-8").read().replace("Tire Quantity", "All Booked Tire Quantity").replace("Tire Volume", "All Booked Tire Volume")
            with open(chart_path, "w", encoding="utf-8") as handle:
                handle.write(chart_text)

        # Replace the template raw data with only the two requested cutoff files.
        raw_path = os.path.join(tmp, "xl/worksheets/sheet4.xml")
        root = ET.parse(raw_path).getroot()
        sheet_data = root.find(f"{{{NS}}}sheetData")
        sheet_data.clear()
        headers = list(inputs["June"][0].keys()) + ["_period"]
        for col, header in enumerate(headers, 1):
            letters = ""
            n = col
            while n:
                n, rem = divmod(n - 1, 26)
                letters = chr(65 + rem) + letters
            dashboard.set_cell(root, f"{letters}1", header, 1)
        out_rows = [("July 1–20", r) for r in inputs["June"]] + [("August 1–20", r) for r in inputs["July"]]
        for row_no, (period, row) in enumerate(out_rows, 2):
            values = list(row.values()) + [period]
            for col, value in enumerate(values, 1):
                letters = ""
                n = col
                while n:
                    n, rem = divmod(n - 1, 26)
                    letters = chr(65 + rem) + letters
                numeric = col in {3, 9} and str(value).replace(".", "", 1).isdigit()
                dashboard.set_cell(root, f"{letters}{row_no}", float(value) if numeric else str(value))
        ET.ElementTree(root).write(raw_path, encoding="UTF-8", xml_declaration=True)

        rebuilt = OUTPUT + ".tmp"
        with zipfile.ZipFile(rebuilt, "w", zipfile.ZIP_DEFLATED) as zout:
            for root_dir, _, files in os.walk(tmp):
                for name in files:
                    path = os.path.join(root_dir, name)
                    zout.write(path, os.path.relpath(path, tmp))
        os.replace(rebuilt, OUTPUT)
    print(OUTPUT)


if __name__ == "__main__":
    main()
