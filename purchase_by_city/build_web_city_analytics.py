#!/usr/bin/env python3
"""Build June-vs-July 2026 web purchase-by-city analytics."""

import csv
import tempfile
from pathlib import Path

from build_taira_cs_city_analytics import cell, sheet


BASE = Path(__file__).resolve().parent
JUNE = BASE / "june purchase by city.csv"
JULY = BASE / "juyl_by_city_full_1_to_74.csv"
CSV_OUT = BASE / "web_purchase_by_city_june_vs_july_2026.csv"
XML_OUT = BASE / "web_purchase_by_city_analytics_2026.xml"
XLSX_OUT = BASE / "Web_Purchase_By_City_Analytics_June_vs_July_2026.xlsx"

ALIASES = {
    "mandaluyong city": "Mandaluyong",
    "cagayan de oro city": "Cagayan de Oro",
    "city of santa rosa": "Santa Rosa",
    "paranaque": "Parañaque",
    "las pinas": "Las Piñas",
    "san juan city": "San Juan",
    "general santos city (dadiangas)": "General Santos City",
    "bacolod city": "Bacolod",
    "antipolo city": "Antipolo",
    "pasig city": "Pasig",
    "taguig city": "Taguig",
}


def number(value):
    value = (value or "").strip().replace(",", "")
    if not value or value.lower() == "null":
        return None
    return int(float(value))


def city_name(value):
    value = " ".join((value or "").strip().split())
    low = value.casefold()
    if low == "(not set)":
        return "(not set)"
    return ALIASES.get(low, value)


def load(path, month):
    output = {}
    declared_total = None
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            normalized = {k.strip().casefold(): v for k, v in row.items()}
            city = city_name(normalized.get("city"))
            purchase = number(normalized.get("purchase")) or 0
            users = number(normalized.get("total users"))
            if city.casefold() == "grand total":
                declared_total = (purchase, users)
                continue
            current = output.setdefault(city, {"purchase": 0, "users": 0})
            current["purchase"] += purchase
            current["users"] += users or 0
    computed = (sum(v["purchase"] for v in output.values()), sum(v["users"] for v in output.values()))
    return output, declared_total or computed, computed


def growth(new, old):
    return new / old - 1 if old else None


HEADERS = [
    "City", "June Purchases", "July Purchases", "Purchase Change", "Purchase Growth Rate",
    "June Purchase Share", "July Purchase Share", "Purchase Share Change (pp)",
    "June Total Users", "July Total Users", "User Change", "User Growth Rate",
    "June Purchase per User", "July Purchase per User", "Rate Change (pp)",
    "June Purchase Rank", "July Purchase Rank", "Rank Improvement",
]


def build_rows(june, july, june_total, july_total):
    cities = sorted(set(june) | set(july))
    june_rank = {c: i + 1 for i, c in enumerate(sorted(cities, key=lambda x: (-june.get(x, {}).get("purchase", 0), x)))}
    july_rank = {c: i + 1 for i, c in enumerate(sorted(cities, key=lambda x: (-july.get(x, {}).get("purchase", 0), x)))}
    rows = []
    for city in cities:
        jp = june.get(city, {}).get("purchase", 0); up = july.get(city, {}).get("purchase", 0)
        ju = june.get(city, {}).get("users", 0); uu = july.get(city, {}).get("users", 0)
        js, us = jp / june_total[0], up / july_total[0]
        jr, ur = (jp / ju if ju else 0), (up / uu if uu else 0)
        rows.append([city, jp, up, up-jp, growth(up, jp), js, us, us-js, ju, uu, uu-ju,
                     growth(uu, ju), jr, ur, ur-jr, june_rank[city], july_rank[city], june_rank[city]-july_rank[city]])
    rows.sort(key=lambda r: (-r[2], -r[1], r[0]))
    return rows


def write_csv(rows):
    with CSV_OUT.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADERS)
        writer.writerows(rows)


def write_workbook(rows, june_total, july_total, june_detail_total, july_detail_total):
    pchg = growth(july_total[0], june_total[0]); uchg = growth(july_total[1], june_total[1])
    june_rate = june_total[0] / june_total[1]; july_rate = july_total[0] / july_total[1]
    known_june = june_total[0] - next((r[1] for r in rows if r[0] == "(not set)"), 0)
    known_july = july_total[0] - next((r[2] for r in rows if r[0] == "(not set)"), 0)
    exec_rows = [
        [cell("Web Purchase by City | Executive Analytics Dashboard", "Title")],
        [cell("June vs July 2026 • GA city export • purchases and total users", "Subtitle")], [],
        [cell("KPI", "Header"), cell("June", "Header"), cell("July", "Header"), cell("Change", "Header"), cell("Growth", "Header")],
        [cell("Purchases"), cell(june_total[0], "Integer"), cell(july_total[0], "Integer"), cell(july_total[0]-june_total[0], "Integer"), cell(pchg, "Percent")],
        [cell("Total users"), cell(june_total[1], "Integer"), cell(july_total[1], "Integer"), cell(july_total[1]-june_total[1], "Integer"), cell(uchg, "Percent")],
        [cell("Purchase per user"), cell(june_rate, "Percent"), cell(july_rate, "Percent"), cell(july_rate-june_rate, "Percent"), cell(growth(july_rate, june_rate), "Percent")],
        [cell("Purchases with identified city"), cell(known_june, "Integer"), cell(known_july, "Integer"), cell(known_july-known_june, "Integer"), cell(growth(known_july, known_june), "Percent")],
        [cell("City-row purchase sum (audit)"), cell(june_detail_total[0], "Integer"), cell(july_detail_total[0], "Integer"), cell(july_detail_total[0]-june_detail_total[0], "Integer"), cell(growth(july_detail_total[0], june_detail_total[0]), "Percent")],
        [], [cell("Top cities by July purchases", "Section")],
        [cell("City", "Header"), cell("June", "Header"), cell("July", "Header"), cell("Change", "Header"), cell("July Share", "Header")],
    ]
    for r in [r for r in rows if r[0] != "(not set)"][:15]:
        exec_rows.append([cell(r[0]), cell(r[1], "Integer"), cell(r[2], "Integer"), cell(r[3], "Integer"), cell(r[6], "Percent")])
    exec_rows += [[], [cell("Executive interpretation", "Section")],
        [cell(f"Purchases increased by {july_total[0]-june_total[0]:+,} ({pchg:+.1%}) while total users changed by {july_total[1]-june_total[1]:+,} ({uchg:+.1%}).")],
        [cell(f"Purchase per user moved from {june_rate:.3%} to {july_rate:.3%}, a {(july_rate-june_rate)*100:+.2f} percentage-point change.")],
        [cell("City results are descriptive GA location analytics; they do not prove geographic causation or campaign lift.")],
    ]
    percent_cols = {4, 5, 6, 7, 11, 12, 13, 14}
    detail = [[cell(h, "Header") for h in HEADERS]]
    for row in rows:
        detail.append([cell(v, "Percent" if i in percent_cols and v is not None else "Integer" if i else "Text") for i, v in enumerate(row)])
    method = [
        [cell("Methodology & Source Notes", "Title")],
        [cell("June source", "Header"), cell(JUNE.name)],
        [cell("July source", "Header"), cell(JULY.name)],
        [cell("Period", "Header"), cell("Full calendar months: June 1–30 and July 1–31, 2026.")],
        [cell("City normalization", "Header"), cell("Obvious aliases merged (for example Paranaque/Parañaque and Mandaluyong City/Mandaluyong).")],
        [cell("(not set)", "Header"), cell("Retained as a data-quality row and excluded only from the identified-city KPI.")],
        [cell("Grand-total reconciliation", "Header"), cell(f"June declared/detail: {june_total[0]:,}/{june_detail_total[0]:,} purchases and {june_total[1]:,}/{june_detail_total[1]:,} users. July declared/detail: {july_total[0]:,}/{july_detail_total[0]:,} purchases and {july_total[1]:,}/{july_detail_total[1]:,} users. Executive KPIs use declared totals; city shares use detail sums.")],
        [cell("Purchase per user", "Header"), cell("Purchases divided by Total Users; descriptive rate, not a unique-buyer conversion rate.")],
    ]
    styles = '''<Styles>
 <Style ss:ID="Default" ss:Name="Normal"><Alignment ss:Vertical="Bottom"/><Font ss:FontName="Arial" ss:Size="10"/></Style>
 <Style ss:ID="Text"><Alignment ss:Vertical="Center"/></Style>
 <Style ss:ID="Title"><Font ss:Bold="1" ss:Size="18" ss:Color="#FFFFFF"/><Interior ss:Color="#17365D" ss:Pattern="Solid"/></Style>
 <Style ss:ID="Subtitle"><Font ss:Italic="1" ss:Color="#404040"/><Interior ss:Color="#D9EAF7" ss:Pattern="Solid"/></Style>
 <Style ss:ID="Section"><Font ss:Bold="1" ss:Size="12" ss:Color="#FFFFFF"/><Interior ss:Color="#1F4E78" ss:Pattern="Solid"/></Style>
 <Style ss:ID="Header"><Font ss:Bold="1" ss:Color="#FFFFFF"/><Interior ss:Color="#5B9BD5" ss:Pattern="Solid"/><Alignment ss:WrapText="1"/></Style>
 <Style ss:ID="Integer"><NumberFormat ss:Format="#,##0"/></Style>
 <Style ss:ID="Percent"><NumberFormat ss:Format="0.00%;[Red]-0.00%"/></Style>
</Styles>'''
    xml = '<?xml version="1.0"?><?mso-application progid="Excel.Sheet"?><Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">' + styles
    xml += sheet("Executive Summary", exec_rows, [260, 95, 95, 95, 95], False)
    xml += sheet("City Analytics", detail, [180] + [105] * 17)
    xml += sheet("Methodology", method, [210, 650], False) + '</Workbook>'
    XML_OUT.write_text(xml, encoding="utf-8")


def main():
    june, jt, jdetail = load(JUNE, "June"); july, ut, udetail = load(JULY, "July")
    rows = build_rows(june, july, jdetail, udetail)
    write_csv(rows); write_workbook(rows, jt, ut, jdetail, udetail)
    import subprocess
    with tempfile.TemporaryDirectory(prefix="web_city_") as outdir:
        subprocess.run(["libreoffice", "--headless", "--convert-to", "xlsx", "--outdir", outdir, str(XML_OUT)], check=True, capture_output=True, text=True)
        (Path(outdir) / f"{XML_OUT.stem}.xlsx").replace(XLSX_OUT)
    XML_OUT.unlink(missing_ok=True)
    print(f"CSV: {CSV_OUT}\nWorkbook: {XLSX_OUT}\nCities: {len(rows)}\nJune declared/detail: {jt}/{jdetail}\nJuly declared/detail: {ut}/{udetail}")


if __name__ == "__main__":
    main()
