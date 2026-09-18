from __future__ import annotations

import re
from typing import Any

from .cells import cell_str, is_number, trim_rows
from .ir import TableBlock

HEATMAP_SHEET = re.compile(r"heat\s*map", re.I)
PLACEHOLDER_CELL = re.compile(r"^\$\{.+\}$")
MEASURE_CLUSTER = re.compile(r"^(?P<country>.+?)\s+cluster\s+(?P<cluster>\d+)$", re.I)
MAX_CLUSTER_ID = 20


def survey_schema_text(clusters: list[int] | None = None) -> str:
    if clusters:
        cluster_note = f"{', '.join(str(c) for c in clusters)}, or NULL for the country/market total"
    else:
        cluster_note = "segment id as stored, or NULL for the country/market total"
    return f"""Table survey (
  document_id VARCHAR,
  source_file VARCHAR,
  sheet VARCHAR,
  question VARCHAR,   -- exact question or feature text from the catalog
  option VARCHAR,     -- answer / row label (e.g. 21-34, Must Have, Somewhat favorable)
  country VARCHAR,    -- market name as stored (Japan, USA, HongKong, Hong Kong, Global, Overall, …)
  cluster INTEGER,    -- {cluster_note}
  metric VARCHAR,     -- 'count' (headcount) or 'pct' (column share as a 0-1 fraction)
  value DOUBLE
)
HongKong and Hong Kong refer to the same market; match either with country IN ('HongKong','Hong Kong').
Country totals use cluster IS NULL (never cluster = NULL).
Percent questions must filter metric = 'pct'. Count / n / base questions use metric = 'count'.
Likert / importance batteries store the feature in question and the rating in option
(e.g. question = 'Warranty Period', option = 'Must Have').
For rankings skip option IN ('Total', 'Base n') and skip country IN ('Overall') unless asked.
Report metric='pct' to humans as a percentage (value * 100, one decimal).
"""


SURVEY_SCHEMA_TEXT = survey_schema_text()


def skip_duplicate_crosstab_sheet(sheet: str) -> bool:
    return bool(HEATMAP_SHEET.search(sheet or ""))


def repeating_int_cycle(ids: list[int]) -> list[int] | None:
    n = len(ids)
    if n < 4:
        return None
    for period in range(2, n // 2 + 1):
        if n < 2 * period:
            continue
        cycle = ids[:period]
        if len(set(cycle)) != period:
            continue
        if min(cycle) < 1 or max(cycle) > MAX_CLUSTER_ID:
            continue
        expected = (cycle * ((n // period) + 1))[:n]
        if expected == ids:
            return cycle
    return None


def cluster_cycle(row: list[Any]) -> list[int] | None:
    filled = [cell_str(v) for v in row if cell_str(v)]
    ids: list[int] = []
    for value in filled:
        if not is_number(value):
            return None
        number = float(value.replace(",", ""))
        if number != int(number) or number < 1:
            return None
        ids.append(int(number))
    return repeating_int_cycle(ids)


def is_cluster_id_row(row: list[Any]) -> bool:
    return cluster_cycle(row) is not None


def is_crosstab_headers(headers: list[str]) -> bool:
    cluster_headers = [h for h in headers if " cluster " in h]
    return len(cluster_headers) >= 4


def looks_like_crosstab(table: TableBlock) -> bool:
    if is_crosstab_headers(table.headers):
        return True
    if table.rows and is_cluster_id_row(table.rows[0][1]):
        return True
    if len(table.header_rows) >= 2 and is_cluster_id_row(table.header_rows[1]):
        return True
    return False


def survey_crosstab_score(table: TableBlock) -> float:
    return 1.0 if looks_like_crosstab(table) else 0.0


def crosstab_stub_names(count: int) -> list[str]:
    names = ["question", "option", "metric", "Overall"]
    if count <= len(names):
        return names[:count]
    extra = [f"col_{index}" for index in range(len(names), count)]
    return names + extra


def cluster_token(value: str) -> str:
    if not value or not is_number(value):
        return ""
    number = float(value.replace(",", ""))
    if number != int(number) or number < 1 or number > MAX_CLUSTER_ID:
        return ""
    return str(int(number))


def crosstab_headers(country_row: list[Any], cluster_row: list[Any]) -> list[str]:
    width = max(len(country_row), len(cluster_row))
    countries = [cell_str(country_row[col] if col < len(country_row) else "") for col in range(width)]
    clusters = [cell_str(cluster_row[col] if col < len(cluster_row) else "") for col in range(width)]
    first_measure = next(
        (
            col
            for col in range(width)
            if countries[col] or cluster_token(clusters[col])
        ),
        width,
    )
    stub_names = crosstab_stub_names(first_measure)
    headers: list[str] = []
    last_country = ""
    last_filled = 0
    for col in range(width):
        if col < first_measure:
            headers.append(stub_names[col])
            last_filled = len(headers)
            continue
        if countries[col]:
            last_country = countries[col]
        cluster = cluster_token(clusters[col])
        if cluster:
            label = f"{last_country} cluster {cluster}" if last_country else f"cluster {cluster}"
            headers.append(label)
            last_filled = len(headers)
        elif countries[col]:
            headers.append(countries[col])
            last_filled = len(headers)
        else:
            headers.append(f"col_{col}")
    return headers[:last_filled]


def materialize_crosstab_table(table: TableBlock) -> TableBlock:
    if is_crosstab_headers(table.headers) and not (
        table.rows and is_cluster_id_row(table.rows[0][1])
    ):
        return table
    cluster_row: list[Any] | None = None
    data_rows = list(table.rows)
    country_row: list[Any]
    if table.rows and is_cluster_id_row(table.rows[0][1]):
        cluster_row = list(table.rows[0][1])
        data_rows = list(table.rows[1:])
        country_row = table.header_rows[0] if table.header_rows else list(table.headers)
    elif len(table.header_rows) >= 2 and is_cluster_id_row(table.header_rows[1]):
        country_row = table.header_rows[0]
        cluster_row = table.header_rows[1]
    else:
        return table
    headers = crosstab_headers(country_row, cluster_row)
    return TableBlock(
        sheet=table.sheet,
        headers=headers,
        rows=trim_rows(data_rows, max(len(headers), 1)),
        start_row=table.start_row,
        end_row=table.end_row,
        kind="crosstab",
        column_map=table.column_map,
        header_rows=table.header_rows,
    )


def chunk(chunk_id: str, text: str, metadata: dict[str, Any]) -> dict[str, Any]:
    return {"id": chunk_id, "text": text, "metadata": metadata}


def crosstab_records(table: TableBlock) -> list[dict[str, Any]]:
    headers = table.headers
    question_i = headers.index("question") if "question" in headers else None
    option_i = headers.index("option") if "option" in headers else None
    metric_i = headers.index("metric") if "metric" in headers else None
    measure_indexes = [
        index
        for index, header in enumerate(headers)
        if index not in {question_i, option_i, metric_i}
    ]
    records: list[dict[str, Any]] = []
    question = ""
    option = ""
    for excel_row, values in table.rows:
        padded = list(values) + [None] * max(0, len(headers) - len(values))
        row_question = cell_str(padded[question_i]) if question_i is not None else ""
        row_option = cell_str(padded[option_i]) if option_i is not None else ""
        metric = cell_str(padded[metric_i]) if metric_i is not None else ""
        measures = crosstab_measures(headers, padded, measure_indexes)
        if option_i is None:
            if row_question and not measures:
                question = row_question
                continue
            if row_question:
                option = row_question
        else:
            if row_question:
                question = row_question
            if row_option:
                option = row_option
        if skip_crosstab_record(question, option or row_question):
            continue
        if not measures or measures_all_zero(measures):
            continue
        if not option:
            option = "Base n"
        records.append(
            {
                "excel_row": excel_row,
                "question": question,
                "option": option,
                "metric": metric,
                "measures": measures,
            }
        )
    return records


def crosstab_chunks_from_records(
    table: TableBlock,
    records: list[dict[str, Any]],
    source_file: str,
) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    index = 0
    while index < len(records):
        current = records[index]
        paired = None
        if index + 1 < len(records):
            nxt = records[index + 1]
            if (
                metric_kind(current["metric"]) == "value"
                and metric_kind(nxt["metric"]) == "percent"
                and nxt["question"] == current["question"]
                and nxt["option"] == current["option"]
            ):
                paired = nxt
        text = format_crosstab_chunk(table.sheet, current, paired)
        if text:
            meta = {
                "excel_row": current["excel_row"],
                "excel_sheet": table.sheet,
                "sheet_kind": "crosstab",
                "chunk_type": "excel_crosstab",
                "table_kind": "survey",
                "source_file": source_file,
                "question": current["question"],
                "option": current["option"],
            }
            chunks.append(
                chunk(
                    f"{table.sheet}_q_{current['excel_row']}",
                    text,
                    meta,
                )
            )
        index += 2 if paired is not None else 1
    return chunks


def unpivot_crosstab_records(
    records: list[dict[str, Any]],
    sheet: str,
    source_file: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in records:
        metric = "pct" if metric_kind(str(record.get("metric") or "")) == "percent" else "count"
        for header, raw in record.get("measures") or []:
            if not is_number(raw):
                continue
            country, cluster = split_measure_header(header)
            if not country:
                continue
            rows.append(
                {
                    "source_file": source_file,
                    "sheet": sheet,
                    "question": record["question"],
                    "option": record["option"],
                    "country": country,
                    "cluster": cluster,
                    "metric": metric,
                    "value": float(raw.replace(",", "")),
                }
            )
    return rows


def split_measure_header(header: str) -> tuple[str, int | None]:
    match = MEASURE_CLUSTER.match((header or "").strip())
    if match:
        return match.group("country").strip(), int(match.group("cluster"))
    return (header or "").strip(), None


def build_question_catalog(long_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in long_rows:
        question = str(row.get("question") or "").strip()
        sheet = str(row.get("sheet") or "").strip()
        if not question:
            continue
        entry = grouped.setdefault(
            (sheet, question),
            {
                "sheet": sheet,
                "question": question,
                "options": set(),
                "countries": set(),
                "clusters": set(),
            },
        )
        option = str(row.get("option") or "").strip()
        country = str(row.get("country") or "").strip()
        cluster = row.get("cluster")
        if option:
            entry["options"].add(option)
        if country:
            entry["countries"].add(country)
        if cluster is not None and str(cluster).strip() != "":
            entry["clusters"].add(int(cluster))
    catalog: list[dict[str, Any]] = []
    for entry in grouped.values():
        options = sorted(entry["options"])
        countries = sorted(entry["countries"])
        clusters = sorted(entry["clusters"])
        catalog.append(
            {
                "sheet": entry["sheet"],
                "question": entry["question"],
                "options": options,
                "countries": countries,
                "clusters": clusters,
                "option_count": len(options),
            }
        )
    return catalog


def catalog_clusters(catalog: list[dict[str, Any]]) -> list[int]:
    ids: set[int] = set()
    for entry in catalog:
        for cluster in entry.get("clusters") or []:
            ids.add(int(cluster))
    return sorted(ids)


def cluster_lookup_hint(clusters: list[Any]) -> str:
    ids = [str(c) for c in clusters if str(c).strip() != ""]
    if not ids:
        return "cluster (NULL for country totals)"
    return "cluster " + ", ".join(ids)


def catalog_chunks(catalog: list[dict[str, Any]], source_file: str) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for index, entry in enumerate(catalog):
        question = entry["question"]
        options = entry.get("options") or []
        countries = entry.get("countries") or []
        clusters = entry.get("clusters") or []
        preview = "; ".join(str(item) for item in options[:12])
        if len(options) > 12:
            preview += "; …"
        text = (
            f"Survey catalog | {source_file}\n"
            f"Question: {question}\n"
            f"Sheet: {entry.get('sheet')}\n"
            f"Options ({entry.get('option_count') or len(options)}): {preview}\n"
            f"Countries: {', '.join(str(item) for item in countries)}\n"
            "Look up counts (metric=count) and column percentages (metric=pct) "
            f"by country and {cluster_lookup_hint(clusters)} in the survey table."
        )
        chunks.append(
            chunk(
                f"catalog_{index}_{entry.get('sheet')}",
                text,
                {
                    "excel_sheet": entry.get("sheet"),
                    "sheet_kind": "crosstab",
                    "chunk_type": "excel_catalog",
                    "table_kind": "survey",
                    "source_file": source_file,
                    "question": question,
                },
            )
        )
    return chunks


def skip_crosstab_record(question: str, option: str) -> bool:
    blobs = (question, option)
    if any(PLACEHOLDER_CELL.match(text) for text in blobs):
        return True
    if question.strip().lower() == "hidden for country":
        return True
    return False


def crosstab_measures(
    headers: list[str],
    values: list[Any],
    measure_indexes: list[int],
) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for index in measure_indexes:
        text = cell_str(values[index] if index < len(values) else "")
        if not text:
            continue
        out.append((headers[index], text))
    return out


def measures_all_zero(measures: list[tuple[str, str]]) -> bool:
    if not measures:
        return True
    for _header, raw in measures:
        if not is_number(raw):
            return False
        if float(raw.replace(",", "")) != 0:
            return False
    return True


def metric_kind(metric: str) -> str:
    lowered = metric.strip().lower()
    if lowered == "value":
        return "value"
    if "percent" in lowered:
        return "percent"
    return lowered


def format_crosstab_chunk(
    sheet: str,
    record: dict[str, Any],
    percent_record: dict[str, Any] | None,
) -> str:
    lines = [f"Crosstab | {sheet}"]
    question = str(record.get("question") or "").strip()
    option = str(record.get("option") or "").strip()
    if question:
        lines.append(f"Question: {question}")
    if option:
        lines.append(f"Answer: {option}")
    value_lines = measure_lines(record.get("measures") or [], as_percent=False)
    if value_lines:
        heading = "Value:" if percent_record is not None or metric_kind(record.get("metric") or "") == "value" else "Counts:"
        if metric_kind(record.get("metric") or "") == "percent" and percent_record is None:
            heading = "Column percentage:"
            value_lines = measure_lines(record.get("measures") or [], as_percent=True)
        lines.append(heading)
        lines.extend(value_lines)
    if percent_record is not None:
        pct_lines = measure_lines(percent_record.get("measures") or [], as_percent=True)
        if pct_lines:
            lines.append("Column percentage:")
            lines.extend(pct_lines)
    if len(lines) <= 3:
        return ""
    return "\n".join(lines)


def measure_lines(measures: list[tuple[str, str]], *, as_percent: bool) -> list[str]:
    lines: list[str] = []
    for header, raw in measures:
        display = format_measure(raw, as_percent=as_percent)
        if not display:
            continue
        lines.append(f"- {header}: {display}")
    return lines


def format_measure(raw: str, *, as_percent: bool) -> str:
    if not raw:
        return ""
    if not as_percent or not is_number(raw):
        return raw
    number = float(raw.replace(",", ""))
    if 0 <= number <= 1:
        return f"{number * 100:.1f}%"
    return raw
