import csv
import io
import logging

from openpyxl import load_workbook

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = (".xlsx", ".csv")


def parse_upload(file_bytes: bytes, filename: str) -> tuple[list[dict], list[dict]]:
    """Parse an uploaded .xlsx or .csv file into raw row dicts.

    Returns (valid_rows, skipped_rows). Never raises on a malformed row —
    row-level failures are logged and collected in skipped_rows instead.
    """
    lower_name = filename.lower()

    if lower_name.endswith(".xlsx"):
        return _parse_xlsx(file_bytes)
    if lower_name.endswith(".csv"):
        return _parse_csv(file_bytes)

    raise ValueError(
        f"Unsupported file type for '{filename}'. Supported formats: {', '.join(SUPPORTED_EXTENSIONS)}"
    )


def _clean_headers(raw_headers: list) -> list[str]:
    return [str(h).strip() if h is not None else "" for h in raw_headers]


def _row_is_empty(values) -> bool:
    return all(v is None or str(v).strip() == "" for v in values)


def _build_row_dict(headers: list[str], values) -> dict:
    row_dict = {}
    for header, value in zip(headers, values):
        if not header:
            continue
        row_dict[header] = value.strip() if isinstance(value, str) else value
    return row_dict


def _parse_xlsx(file_bytes: bytes) -> tuple[list[dict], list[dict]]:
    valid_rows: list[dict] = []
    skipped_rows: list[dict] = []

    try:
        wb = load_workbook(io.BytesIO(file_bytes), data_only=True)
        ws = wb.active
    except Exception as e:
        logger.error(f"Failed to open xlsx file: {e}")
        return [], [{"row_number": None, "reason": f"Could not open file: {e}"}]

    # Propagate merged-cell values across their full range so every cell
    # in a merged block carries data instead of being blank.
    try:
        for merged_range in list(ws.merged_cells.ranges):
            top_left_value = ws.cell(row=merged_range.min_row, column=merged_range.min_col).value
            ws.unmerge_cells(str(merged_range))
            for row in range(merged_range.min_row, merged_range.max_row + 1):
                for col in range(merged_range.min_col, merged_range.max_col + 1):
                    ws.cell(row=row, column=col).value = top_left_value
    except Exception as e:
        logger.warning(f"Could not fully unmerge cells: {e}")

    rows_iter = ws.iter_rows(values_only=True)
    try:
        raw_headers = next(rows_iter)
    except StopIteration:
        return [], [{"row_number": None, "reason": "File is empty"}]

    headers = _clean_headers(raw_headers)

    for row_number, row in enumerate(rows_iter, start=2):
        if row is None or _row_is_empty(row):
            continue

        try:
            row_dict = _build_row_dict(headers, row)
            row_dict["__row_number"] = row_number
            valid_rows.append(row_dict)
        except Exception as e:
            logger.warning(f"Skipping row {row_number}: {e}")
            skipped_rows.append({"row_number": row_number, "reason": str(e)})

    return valid_rows, skipped_rows


def _decode_csv_bytes(file_bytes: bytes) -> str | None:
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return file_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    return None


def _parse_csv(file_bytes: bytes) -> tuple[list[dict], list[dict]]:
    valid_rows: list[dict] = []
    skipped_rows: list[dict] = []

    text = _decode_csv_bytes(file_bytes)
    if text is None:
        return [], [{"row_number": None, "reason": "Could not decode file with any supported encoding"}]

    try:
        reader = csv.reader(io.StringIO(text))
        raw_headers = next(reader)
    except StopIteration:
        return [], [{"row_number": None, "reason": "File is empty"}]
    except Exception as e:
        logger.error(f"Failed to parse csv file: {e}")
        return [], [{"row_number": None, "reason": f"Could not parse CSV: {e}"}]

    headers = _clean_headers(raw_headers)

    for row_number, row in enumerate(reader, start=2):
        if not row or _row_is_empty(row):
            continue

        try:
            row_dict = _build_row_dict(headers, row)
            row_dict["__row_number"] = row_number
            valid_rows.append(row_dict)
        except Exception as e:
            logger.warning(f"Skipping row {row_number}: {e}")
            skipped_rows.append({"row_number": row_number, "reason": str(e)})

    return valid_rows, skipped_rows
