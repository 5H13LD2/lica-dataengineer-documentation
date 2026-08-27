#!/usr/bin/env python3
"""Build June-vs-July Taira/all-CS city analytics from BigQuery."""

import csv
import json
import os
import re
import subprocess
import tempfile
from collections import defaultdict
from pathlib import Path
from xml.sax.saxutils import escape


BASE = Path(__file__).resolve().parent
CSV_OUT = BASE / "taira_cs_june_vs_july_2026.csv"
XML_OUT = BASE / "taira_cs_city_analytics_2026.xml"
XLSX_OUT = BASE / "Taira_CS_City_Analytics_June_vs_July_2026.xlsx"

SQL = r'''
WITH official AS (
  SELECT
    FORMAT_DATE('%Y-%m', report_date) AS month,
    CASE
      WHEN agent_group = 'chatbot_jeanel' THEN 'Taira'
      WHEN agent_group = 'cs_agent' THEN 'All CS'
    END AS team,
    SUM(total_inquiries) AS inquiries,
    SUM(total_bookings) AS bookings
  FROM `gulong-chatbot-459723.gulong_reporting.p_looker_agent_daily_conversion`
  WHERE report_date BETWEEN DATE '2026-06-01' AND DATE '2026-07-31'
    AND agent_group IN ('chatbot_jeanel', 'cs_agent')
  GROUP BY month, team
), inquiry_city AS (
  SELECT
    FORMAT_DATE('%Y-%m', i.inquiry_day) AS month,
    IF(i.is_chatbot_jeanel, 'Taira', 'All CS') AS team,
    TRIM(e.evidence_location) AS raw_city,
    COUNT(DISTINCT COALESCE(
      NULLIF(i.silver_session_id, ''),
      CONCAT('event:', NULLIF(i.assignment_event_id, '')),
      CONCAT('user:', i.user_id, ':', CAST(i.assignment_at AS STRING))
    )) AS inquiries
  FROM `gulong-chatbot-459723.gulong_core.inquiry_assignments` i
  JOIN `gulong-chatbot-459723.gulong_core.inquiry_session_evidence` e
    USING (silver_session_id)
  WHERE i.inquiry_day BETWEEN DATE '2026-06-01' AND DATE '2026-07-31'
    AND (i.is_chatbot_jeanel OR i.agent_reporting_group = 'cs_agent')
    AND NULLIF(TRIM(e.evidence_location), '') IS NOT NULL
  GROUP BY month, team, raw_city
), booking_city AS (
  SELECT
    FORMAT_DATE('%Y-%m', o.booking_day) AS month,
    CASE
      WHEN COALESCE(o.inquiry_is_chatbot_jeanel, o.original_assigned_is_chatbot_jeanel, FALSE) THEN 'Taira'
      ELSE 'All CS'
    END AS team,
    TRIM(e.evidence_location) AS raw_city,
    COUNT(DISTINCT o.order_id) AS bookings,
    SUM(o.gross_sales_amount) AS gross_booking_amount
  FROM `gulong-chatbot-459723.gulong_core.orders_all` o
  JOIN `gulong-chatbot-459723.gulong_core.inquiry_session_evidence` e
    ON e.silver_session_id = o.inquiry_silver_session_id
  WHERE o.booking_day BETWEEN DATE '2026-06-01' AND DATE '2026-07-31'
    AND o.is_reportable_booked_order
    AND (
      COALESCE(o.inquiry_is_chatbot_jeanel, o.original_assigned_is_chatbot_jeanel, FALSE)
      OR COALESCE(o.original_assigned_agent_group, o.inquiry_agent_reporting_group) = 'cs_agent'
    )
    AND NULLIF(TRIM(e.evidence_location), '') IS NOT NULL
  GROUP BY month, team, raw_city
)
SELECT 'official' AS record_type, month, team, NULL AS raw_city,
       inquiries, bookings, CAST(NULL AS NUMERIC) AS gross_booking_amount
FROM official
UNION ALL
SELECT 'inquiry_city', month, team, raw_city, inquiries, NULL, NULL
FROM inquiry_city
UNION ALL
SELECT 'booking_city', month, team, raw_city, NULL, bookings, gross_booking_amount
FROM booking_city
ORDER BY record_type, month, team, raw_city
'''


ALIASES = {
    "makati": "Makati City", "makati city": "Makati City",
    "pasig": "Pasig City", "pasig city": "Pasig City",
    "taguig": "Taguig City", "taguig city": "Taguig City",
    "paranaque": "Parañaque City", "parañaque": "Parañaque City", "parañaque city": "Parañaque City",
    "las pinas": "Las Piñas City", "las piñas": "Las Piñas City", "las piñas city": "Las Piñas City",
    "caloocan": "Caloocan City", "caloocan city": "Caloocan City",
    "davao": "Davao City", "davao city": "Davao City",
    "cebu": "Cebu City", "cebu city": "Cebu City",
    "antipolo": "Antipolo City", "antipolo city": "Antipolo City",
    "muntinlupa": "Muntinlupa City", "muntinlupa city": "Muntinlupa City",
    "marikina": "Marikina City", "marikina city": "Marikina City",
    "valenzuela": "Valenzuela City", "valenzuela city": "Valenzuela City",
    "pasay": "Pasay City", "pasay city": "Pasay City",
    "baguio": "Baguio City", "baguio city": "Baguio City",
    "lipa": "Lipa City", "lipa city": "Lipa City",
    "bacolod": "Bacolod City", "bacolod city": "Bacolod City",
    "iloilo": "Iloilo City", "iloilo city": "Iloilo City",
    "quezon city": "Quezon City",
    "manila": "Manila",
}
INVALID = re.compile(
    r"^(loc|location|location po|location pls|loc po|n/?a|none|null|unknown|test|sample)$",
    re.I,
)


def bq_rows():
    result = subprocess.run(
        ["bq", "query", "--use_legacy_sql=false", "--format=json", "--max_rows=100000", SQL],
        check=True, capture_output=True, text=True,
    )
    return json.loads(result.stdout)


def normalize_city(value):
    value = re.sub(r"\s+", " ", (value or "").strip())
    low = value.casefold()
    if not value or INVALID.fullmatch(low):
        return None
    if len(value) > 60 or any(token in low for token in (" or ", ",", " and more", "plus ", "\n")):
        return None
    return ALIASES.get(low, value.title())


def pct(new, old):
    return (new / old - 1) if old else None


def rate(num, den):
    return num / den if den else 0.0


def build_data(rows):
    official = defaultdict(lambda: {"inquiries": 0, "bookings": 0})
    data = defaultdict(lambda: defaultdict(float))
    for row in rows:
        key = (row["month"], row["team"])
        if row["record_type"] == "official":
            official[key] = {"inquiries": int(row["inquiries"] or 0), "bookings": int(row["bookings"] or 0)}
            continue
        city = normalize_city(row.get("raw_city"))
        if city is None:
            continue
        item = data[city]
        if row["record_type"] == "inquiry_city":
            item[(row["month"], row["team"], "inquiries")] += int(row["inquiries"] or 0)
        else:
            item[(row["month"], row["team"], "bookings")] += int(row["bookings"] or 0)
            item[(row["month"], row["team"], "gross")] += float(row["gross_booking_amount"] or 0)

    unidentified = data["UNIDENTIFIED / NO USABLE CITY EVIDENCE"]
    for month in ("2026-06", "2026-07"):
        for team in ("Taira", "All CS"):
            known_i = sum(v[(month, team, "inquiries")] for c, v in data.items() if not c.startswith("UNIDENTIFIED"))
            known_b = sum(v[(month, team, "bookings")] for c, v in data.items() if not c.startswith("UNIDENTIFIED"))
            unidentified[(month, team, "inquiries")] = max(official[(month, team)]["inquiries"] - known_i, 0)
            unidentified[(month, team, "bookings")] = max(official[(month, team)]["bookings"] - known_b, 0)
    return official, data


HEADERS = [
    "City / Reported Area",
    "June Taira Inquiries", "June Taira Bookings", "June Taira Conversion Rate",
    "June All CS Inquiries", "June All CS Bookings", "June All CS Conversion Rate",
    "July Taira Inquiries", "July Taira Bookings", "July Taira Conversion Rate",
    "July All CS Inquiries", "July All CS Bookings", "July All CS Conversion Rate",
    "June Total Inquiries", "July Total Inquiries", "Inquiry Change", "Inquiry Growth Rate",
    "June Total Bookings", "July Total Bookings", "Booking Change", "Booking Growth Rate",
    "June Gross Booking Amount", "July Gross Booking Amount", "Gross Amount Change",
]


def city_rows(data):
    output = []
    for city, v in data.items():
        ji_t, jb_t = int(v[("2026-06", "Taira", "inquiries")]), int(v[("2026-06", "Taira", "bookings")])
        ji_c, jb_c = int(v[("2026-06", "All CS", "inquiries")]), int(v[("2026-06", "All CS", "bookings")])
        ui_t, ub_t = int(v[("2026-07", "Taira", "inquiries")]), int(v[("2026-07", "Taira", "bookings")])
        ui_c, ub_c = int(v[("2026-07", "All CS", "inquiries")]), int(v[("2026-07", "All CS", "bookings")])
        j_i, u_i, j_b, u_b = ji_t + ji_c, ui_t + ui_c, jb_t + jb_c, ub_t + ub_c
        j_g = v[("2026-06", "Taira", "gross")] + v[("2026-06", "All CS", "gross")]
        u_g = v[("2026-07", "Taira", "gross")] + v[("2026-07", "All CS", "gross")]
        output.append([
            city, ji_t, jb_t, rate(jb_t, ji_t), ji_c, jb_c, rate(jb_c, ji_c),
            ui_t, ub_t, rate(ub_t, ui_t), ui_c, ub_c, rate(ub_c, ui_c),
            j_i, u_i, u_i-j_i, pct(u_i, j_i), j_b, u_b, u_b-j_b, pct(u_b, j_b),
            round(j_g, 2), round(u_g, 2), round(u_g-j_g, 2),
        ])
    output.sort(key=lambda r: (r[0].startswith("UNIDENTIFIED"), -(r[13] + r[14]), r[0]))
    return output


def write_csv(rows):
    with CSV_OUT.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADERS)
        writer.writerows(rows)


def cell(value, style="Text"):
    if isinstance(value, (int, float)) and value is not None:
        return f'<Cell ss:StyleID="{style}"><Data ss:Type="Number">{value}</Data></Cell>'
    return f'<Cell ss:StyleID="{style}"><Data ss:Type="String">{escape(str(value or ""))}</Data></Cell>'


def sheet(name, rows, widths=None, freeze=True):
    cols = "".join(f'<Column ss:Width="{w}"/>' for w in (widths or []))
    body = "".join("<Row>" + "".join(cells) + "</Row>" for cells in rows)
    options = '<WorksheetOptions xmlns="urn:schemas-microsoft-com:office:excel"><FreezePanes/><FrozenNoSplit/><SplitHorizontal>1</SplitHorizontal><TopRowBottomPane>1</TopRowBottomPane><ActivePane>2</ActivePane><ProtectObjects>False</ProtectObjects><ProtectScenarios>False</ProtectScenarios></WorksheetOptions>' if freeze else ''
    return f'<Worksheet ss:Name="{escape(name)}"><Table>{cols}{body}</Table>{options}</Worksheet>'


def write_workbook(rows, official):
    june_t, july_t = official[("2026-06", "Taira")], official[("2026-07", "Taira")]
    june_c, july_c = official[("2026-06", "All CS")], official[("2026-07", "All CS")]
    identified = [r for r in rows if not r[0].startswith("UNIDENTIFIED")]
    top_july = sorted(identified, key=lambda r: r[14], reverse=True)[:10]
    exec_rows = [
        [cell("Taira & All CS | Purchase/Inquiry by City Analytics", "Title")],
        [cell("June vs July 2026 • official general totals from p_looker • city attribution from inquiry location evidence", "Subtitle")],
        [],
        [cell("KPI", "Header"), cell("June", "Header"), cell("July", "Header"), cell("Change", "Header"), cell("Growth", "Header")],
        [cell("Taira inquiries"), cell(june_t["inquiries"], "Integer"), cell(july_t["inquiries"], "Integer"), cell(july_t["inquiries"]-june_t["inquiries"], "Integer"), cell(pct(july_t["inquiries"], june_t["inquiries"]), "Percent")],
        [cell("All CS inquiries"), cell(june_c["inquiries"], "Integer"), cell(july_c["inquiries"], "Integer"), cell(july_c["inquiries"]-june_c["inquiries"], "Integer"), cell(pct(july_c["inquiries"], june_c["inquiries"]), "Percent")],
        [cell("Taira bookings"), cell(june_t["bookings"], "Integer"), cell(july_t["bookings"], "Integer"), cell(july_t["bookings"]-june_t["bookings"], "Integer"), cell(pct(july_t["bookings"], june_t["bookings"]), "Percent")],
        [cell("All CS bookings"), cell(june_c["bookings"], "Integer"), cell(july_c["bookings"], "Integer"), cell(july_c["bookings"]-june_c["bookings"], "Integer"), cell(pct(july_c["bookings"], june_c["bookings"]), "Percent")],
        [], [cell("Top identified cities/areas by July inquiries", "Section")],
        [cell("City / Area", "Header"), cell("June inquiries", "Header"), cell("July inquiries", "Header"), cell("Change", "Header"), cell("Growth", "Header")],
    ]
    for r in top_july:
        exec_rows.append([cell(r[0]), cell(r[13], "Integer"), cell(r[14], "Integer"), cell(r[15], "Integer"), cell(r[16], "Percent")])
    exec_rows += [[], [cell("Executive interpretation", "Section")],
        [cell(f"Taira inquiries changed by {july_t['inquiries']-june_t['inquiries']:+,} ({pct(july_t['inquiries'], june_t['inquiries']):+.1%}); All CS changed by {july_c['inquiries']-june_c['inquiries']:+,} ({pct(july_c['inquiries'], june_c['inquiries']):+.1%}).")],
        [cell("City results are identified-location minimums. The Unidentified row reconciles the city table to official p_looker totals.")],
        [cell("Do not interpret city-level conversion causally: location coverage and attribution completeness vary by team and month.")],
    ]

    detail = [[cell(h, "Header") for h in HEADERS]]
    percent_cols = {3, 6, 9, 12, 16, 20}
    money_cols = {21, 22, 23}
    for row in rows:
        detail.append([cell(v, "Percent" if i in percent_cols and v is not None else "Money" if i in money_cols else "Integer" if i and isinstance(v, int) else "Text") for i, v in enumerate(row)])
    method = [
        [cell("Methodology & Source Notes", "Title")],
        [cell("General inquiry and booking totals", "Header"), cell("gulong_reporting.p_looker_agent_daily_conversion; full June and July 2026; Taira=chatbot_jeanel; All CS=cs_agent.")],
        [cell("City inquiry attribution", "Header"), cell("gulong_core.inquiry_assignments joined to gulong_core.inquiry_session_evidence by silver_session_id.")],
        [cell("City booking attribution", "Header"), cell("gulong_core.orders_all reportable bookings joined to inquiry_session_evidence; booking-month basis.")],
        [cell("Location normalization", "Header"), cell("Common aliases merged; placeholders, multi-city strings, and unusable values treated as unidentified.")],
        [cell("Reconciliation", "Header"), cell("Unidentified = official p_looker total minus usable identified-city rows; therefore monthly team totals reconcile to p_looker.")],
        [cell("Important limitation", "Header"), cell("p_looker has no city column. Identified city counts are reconstructed and should be treated as minimum observable counts.")],
    ]
    xml = '''<?xml version="1.0"?><?mso-application progid="Excel.Sheet"?>
<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">
<Styles>
 <Style ss:ID="Default" ss:Name="Normal"><Alignment ss:Vertical="Bottom"/><Font ss:FontName="Arial" ss:Size="10"/></Style>
 <Style ss:ID="Text"><Alignment ss:Vertical="Center"/></Style>
 <Style ss:ID="Title"><Font ss:Bold="1" ss:Size="18" ss:Color="#FFFFFF"/><Interior ss:Color="#17365D" ss:Pattern="Solid"/></Style>
 <Style ss:ID="Subtitle"><Font ss:Italic="1" ss:Color="#404040"/><Interior ss:Color="#D9EAF7" ss:Pattern="Solid"/></Style>
 <Style ss:ID="Section"><Font ss:Bold="1" ss:Size="12" ss:Color="#FFFFFF"/><Interior ss:Color="#1F4E78" ss:Pattern="Solid"/></Style>
 <Style ss:ID="Header"><Font ss:Bold="1" ss:Color="#FFFFFF"/><Interior ss:Color="#5B9BD5" ss:Pattern="Solid"/><Alignment ss:WrapText="1"/></Style>
 <Style ss:ID="Integer"><NumberFormat ss:Format="#,##0"/></Style>
 <Style ss:ID="Percent"><NumberFormat ss:Format="0.0%;[Red]-0.0%"/></Style>
 <Style ss:ID="Money"><NumberFormat ss:Format="₱#,##0.00;[Red]-₱#,##0.00"/></Style>
</Styles>''' + sheet("Executive Summary", exec_rows, [260, 90, 90, 90, 90], False) + sheet("City Analytics", detail, [180]+[95]*23) + sheet("Methodology", method, [210, 650], False) + '</Workbook>'
    XML_OUT.write_text(xml, encoding="utf-8")


def convert_xlsx():
    with tempfile.TemporaryDirectory(prefix="city_analytics_") as outdir:
        subprocess.run(["libreoffice", "--headless", "--convert-to", "xlsx", "--outdir", outdir, str(XML_OUT)], check=True, capture_output=True, text=True)
        generated = Path(outdir) / (XML_OUT.stem + ".xlsx")
        generated.replace(XLSX_OUT)
    XML_OUT.unlink(missing_ok=True)


def main():
    official, data = build_data(bq_rows())
    rows = city_rows(data)
    write_csv(rows)
    write_workbook(rows, official)
    convert_xlsx()
    print(f"CSV: {CSV_OUT}")
    print(f"Workbook: {XLSX_OUT}")
    print(f"City rows: {len(rows)}")


if __name__ == "__main__":
    main()
