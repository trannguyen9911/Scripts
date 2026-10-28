"""
Convert a local ARR Data Hub download into ARR Storm Generator inputs (InfoWorks ICM and XPSWMM).

See README.md in this folder for usage, required files, and import steps.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import shutil
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable

DUR_ROW_RE = re.compile(r"^(\d+)\s*\(")

BUILD_LOG_NAME = "build_log.txt"
WORK_DIR_NAME = ".work"

# Standard IFD (BomIfds.csv) — hub AEP column headers (%)
STD_AEP_HUB = ["63.2", "50.0", "20.0", "10.0", "5.0", "2.0", "1.0"]
STD_AEP_ICM = ["63.2%", "50%", "20%", "10%", "5%", "2%", "1%"]

# Very frequent — hub columns map to BoM EY columns
VF_AEP_HUB = ["99.999", "99.752", "98.168", "95.021", "86.466", "63.2", "39.35", "20.0"]
VF_AEP_ICM = ["12EY", "6EY", "4EY", "3EY", "2EY", "1EY", "0.5EY", "0.2EY"]

# Rare IFD — hub lower-tail AEP (%)
RARE_AEP_HUB = ["1.0", "0.5", "0.2", "0.1", "0.05"]
RARE_AEP_ICM = ["1 in 100", "1 in 200", "1 in 500", "1 in 1000", "1 in 2000"]

DURATION_MINUTES = [
    (1, "1 min"),
    (2, "2 min"),
    (3, "3 min"),
    (4, "4 min"),
    (5, "5 min"),
    (10, "10 min"),
    (15, "15 min"),
    (20, "20 min"),
    (25, "25 min"),
    (30, "30 min"),
    (45, "45 min"),
    (60, "1 hour"),
    (90, "1.5 hour"),
    (120, "2 hour"),
    (180, "3 hour"),
    (270, "4.5 hour"),
    (360, "6 hour"),
    (540, "9 hour"),
    (720, "12 hour"),
    (1080, "18 hour"),
    (1440, "24 hour"),
    (1800, "30 hour"),
    (2160, "36 hour"),
    (2880, "48 hour"),
    (4320, "72 hour"),
    (5760, "96 hour"),
    (7200, "120 hour"),
    (8640, "144 hour"),
    (10080, "168 hour"),
]


@dataclass
class HubInputs:
    folder: Path
    hub_txt: Path
    bom_csv: Path
    point_zip: Path
    areal_zip: Path
    point_increments_csv: Path
    tp_code: str
    limb_hr_csv: Path | None = None
    limb_bom_csv: Path | None = None
    shell_arr_zip: Path | None = None
    temp_paths: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class BuildResult:
    output_dir: Path
    zip_path: Path | None
    manifest_lines: list[str]
    errors: list[str]


def parse_duration_minutes(cell: str) -> int | None:
    m = DUR_ROW_RE.match(cell.strip())
    return int(m.group(1)) if m else None


def _hub_column_index(headers: list[str], key: str) -> int:
    key = key.strip()
    if key in headers:
        return headers.index(key)
    if key == "63.2" and "63.23" in headers:
        return headers.index("63.23")
    raise KeyError(key)


def parse_hub_ifd_csv(text: str) -> tuple[list[str], dict[int, list[float]]]:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    header_parts = [p.strip() for p in lines[0].split(",")]
    aep_headers = header_parts[1:]
    table: dict[int, list[float]] = {}
    for line in lines[1:]:
        parts = [p.strip() for p in line.split(",")]
        dur = parse_duration_minutes(parts[0])
        if dur is None:
            continue
        table[dur] = [float(x) for x in parts[1 : 1 + len(aep_headers)]]
    return aep_headers, table


def _bom_table_has_aep_keys(aep_headers: list[str], keys: Iterable[str]) -> bool:
    for key in keys:
        try:
            _hub_column_index(aep_headers, key)
        except KeyError:
            return False
    return True


def _extract_allbomifd_from_hub(hub_text: str) -> tuple[list[str], dict[int, list[float]]] | None:
    """Full AEP range (incl. very frequent) embedded in hub results.txt [ALLBOMIFD]."""
    lines = hub_text.replace("\r\n", "\n").split("\n")
    if not any(ln.strip() == "[ALLBOMIFD]" for ln in lines):
        return None
    try:
        block = _extract_section(lines, "[ALLBOMIFD]", "[END_ALLBOMIFD]")
    except ValueError:
        return None
    header_line = next((ln for ln in block if ln.strip().startswith("min (h)")), None)
    if not header_line:
        return None
    aep_headers = [p.strip() for p in header_line.split(",")][1:]
    table: dict[int, list[float]] = {}
    for ln in block:
        m = DUR_ROW_RE.match(ln.strip())
        if not m:
            continue
        parts = [p.strip() for p in ln.split(",")]
        dur = int(m.group(1))
        table[dur] = [float(x) for x in parts[1 : 1 + len(aep_headers)]]
    if not table:
        return None
    return aep_headers, table


def resolve_bom_ifd_table(
    hub_text: str, bom_csv_text: str
) -> tuple[list[str], dict[int, list[float]], str | None]:
    """
    Prefer a CSV with all AEP columns; fall back to [ALLBOMIFD] in hub text when
    All IFD Datasets.zip only contains the narrower BoM IFD Depths.csv.
    """
    aep_headers, bom_table = parse_hub_ifd_csv(bom_csv_text)
    all_keys = STD_AEP_HUB + VF_AEP_HUB + RARE_AEP_HUB
    if _bom_table_has_aep_keys(aep_headers, all_keys):
        return aep_headers, bom_table, None
    hub_table = _extract_allbomifd_from_hub(hub_text)
    if hub_table and _bom_table_has_aep_keys(hub_table[0], all_keys):
        return hub_table[0], hub_table[1], (
            "Very-frequent and rare rainfall columns were taken from the hub text "
            "export (results.txt) because the BoM CSV inside All IFD Datasets.zip "
            "only includes standard design AEPs."
        )
    return aep_headers, bom_table, None


def _format_depth(v: float) -> str:
    if abs(v - round(v)) < 0.05:
        return str(int(round(v)))
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return s


def _bom_csv_header(latitude: float, longitude: float, title: str, subtitle: str) -> str:
    out = io.StringIO()
    out.write(
        "Copyright Commonwealth of Australia 2016 Bureau of Meteorology "
        "(ABN 92 637 533 532)\n\n"
    )
    out.write(f"{title}\n")
    out.write(f"Issued:,{datetime.now():%d %B %Y}\n")
    out.write("Location Label:,\n")
    out.write(
        f"Requested coordinate:,Latitude,{latitude:.3f},Longitude,{longitude:.3f}\n"
    )
    lat_s = abs(latitude)
    out.write(
        f"Nearest grid cell:,Latitude,{lat_s:.4f} (S),Longitude,{longitude:.4f} (E)\n\n"
    )
    out.write(f",,{subtitle}\n")
    return out.getvalue()


def build_bom_ifds_variant(
    bom_table: dict[int, list[float]],
    aep_headers: list[str],
    latitude: float,
    longitude: float,
    hub_keys: list[str],
    icm_labels: list[str],
    title: str,
    subtitle: str,
) -> str:
    col_idx = [_hub_column_index(aep_headers, k) for k in hub_keys]
    out = io.StringIO()
    out.write(_bom_csv_header(latitude, longitude, title, subtitle))
    out.write("Duration,Duration in min," + ",".join(icm_labels) + "\n")
    for dur_min, label in DURATION_MINUTES:
        if dur_min not in bom_table:
            raise KeyError(f"Duration {dur_min} min missing from BoM IFD CSV.")
        row = bom_table[dur_min]
        vals = [_format_depth(row[i]) for i in col_idx]
        out.write(f"{label},{dur_min}," + ",".join(vals) + "\n")
    return out.getvalue()


def discover_inputs(
    folder: Path, work_dir: Path
) -> tuple[HubInputs | None, list[str]]:
    missing: list[str] = []
    if not folder.is_dir():
        return None, [f"Not a directory: {folder}"]

    txt_files = [
        p
        for p in folder.glob("*.txt")
        if p.is_file()
        and "manifest" not in p.name.lower()
        and not p.name.lower().startswith("_extract")
        and p.name.lower() != BUILD_LOG_NAME
    ]
    if not txt_files:
        missing.append("Hub results .txt (e.g. results.txt)")
        hub_txt = None
    else:
        hub_txt = next((p for p in txt_files if p.name.lower() == "results.txt"), txt_files[0])

    bom_candidates = sorted(
        list(folder.glob("*BoM*IFD*.csv")) + list(folder.glob("*IFD*Depths*.csv")),
        key=lambda p: (
            0 if "all durations" in p.name.lower() else 1,
            p.name.lower(),
        ),
    )
    bom_csv = bom_candidates[0] if bom_candidates else None
    temp_paths: list[Path] = []
    if bom_csv is None:
        bom_csv, bom_from_zip = _bom_csv_from_ifd_zip(folder, work_dir, temp_paths)
        if bom_csv is None:
            missing.append(
                "BoM IFD Depths (All Durations and AEPs).csv, or BoM IFD Depths.csv inside All IFD Datasets.zip"
            )
        elif bom_from_zip:
            pass  # warning added after warnings list exists

    point_zips = [p for p in folder.glob("Point*.zip") if p.is_file()]
    areal_zips = [p for p in folder.glob("Areal*.zip") if p.is_file()]
    if not point_zips:
        missing.append("Point temporal patterns zip (Point_<code>.zip)")
    if not areal_zips:
        missing.append("Areal temporal patterns zip (Areal_<code>.zip)")

    if missing or hub_txt is None or bom_csv is None or not point_zips or not areal_zips:
        return None, missing

    point_zip = point_zips[0]
    areal_zip = areal_zips[0]
    if len(point_zips) > 1:
        pass  # warn later
    inc_path, tp_from_zip = _increments_csv_in_zip(point_zip, work_dir)
    if inc_path is None:
        missing.append(f"Increments CSV inside {point_zip.name}")
        return None, missing

    hub_text = hub_txt.read_text(encoding="utf-8", errors="replace")
    tp_code = _read_tp_code(hub_text)
    if tp_code and tp_from_zip and tp_code.lower() != tp_from_zip.lower():
        missing.append(
            f"Point temporal pattern zip ({tp_from_zip}) does not match the "
            f"pattern region in results.txt ({tp_code})."
        )
        return None, missing

    atp_code = _read_atp_code(hub_text)
    areal_code = _code_from_areal_zip(areal_zip.name)
    if atp_code and areal_code and atp_code.lower() != areal_code.lower():
        missing.append(
            f"Areal temporal pattern zip ({areal_code}) does not match the "
            f"areal region in results.txt ({atp_code})."
        )
        return None, missing

    warnings: list[str] = []
    if bom_csv and bom_csv.parent.resolve() == work_dir.resolve():
        warnings.append(
            "BoM IFD table was read from All IFD Datasets.zip. If available, also "
            "keep BoM IFD Depths (All Durations and AEPs).csv in the download folder."
        )
    if len(point_zips) > 1:
        warnings.append(f"Several Point*.zip files found; using {point_zip.name}.")
    if len(areal_zips) > 1:
        warnings.append(f"Several Areal*.zip files found; using {areal_zip.name}.")

    limb_hr, limb_bom, limb_temps, limb_source = _find_limb_csvs(folder, work_dir)
    temp_paths.extend(limb_temps)
    if inc_path.parent.resolve() == work_dir.resolve():
        temp_paths.append(inc_path)
    hub_preview = hub_txt.read_text(encoding="utf-8", errors="replace")
    has_limb_hr = bool(limb_hr) or _hub_has_limb_hr(hub_preview)
    has_limb_bom = bool(limb_bom) or _hub_has_limb_bom(hub_preview)
    if not has_limb_hr and not has_limb_bom:
        warnings.append(
            "This location has no LIMB 2020 IFD grids. Standard BoM 2016 depths "
            "were used where ICM expects LIMB rainfall blocks."
        )
    elif has_limb_bom and not has_limb_hr:
        warnings.append(
            "LIMB high-resolution grids are not available for this location; "
            "BoM-resolution LIMB data was included."
        )
    if limb_source:
        warnings.append(limb_source.replace("LIMB IFD CSVs extracted from", "LIMB data read from"))

    shell_zip = _find_icm_shell_zip(folder)

    return (
        HubInputs(
            folder=folder,
            hub_txt=hub_txt,
            bom_csv=bom_csv,
            point_zip=point_zip,
            areal_zip=areal_zip,
            point_increments_csv=inc_path,
            tp_code=tp_code or tp_from_zip or "",
            limb_hr_csv=limb_hr,
            limb_bom_csv=limb_bom,
            shell_arr_zip=shell_zip,
            temp_paths=temp_paths,
            warnings=warnings,
        ),
        [],
    )


def _first_glob(folder: Path, pattern: str) -> Path | None:
    hits = sorted(folder.glob(pattern))
    return hits[0] if hits else None


def _find_ifd_datasets_zip(folder: Path) -> Path | None:
    for pattern in ("All IFD Datasets.zip", "*All*IFD*Datasets*.zip", "*All*IFD*.zip"):
        hits = sorted(folder.glob(pattern))
        if hits:
            return hits[0]
    return None


def _work_dir(output_dir: Path) -> Path:
    dest = output_dir / WORK_DIR_NAME
    dest.mkdir(parents=True, exist_ok=True)
    return dest


def _extract_zip_member_csv(
    zip_path: Path, name_predicate, dest_dir: Path
) -> Path | None:
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            if not name.lower().endswith(".csv"):
                continue
            base = Path(name).name
            if name_predicate(base):
                dest = dest_dir / base
                dest.write_bytes(zf.read(name))
                return dest
    return None


def _bom_csv_from_ifd_zip(
    folder: Path, work_dir: Path, temp_paths: list[Path]
) -> tuple[Path | None, bool]:
    ifd_zip = _find_ifd_datasets_zip(folder)
    if not ifd_zip:
        return None, False
    dest = work_dir
    path = _extract_zip_member_csv(
        ifd_zip,
        lambda n: "bom" in n.lower() and "ifd" in n.lower() and "limb" not in n.lower(),
        dest,
    )
    if path:
        temp_paths.append(path)
        return path, True
    return None, False


def _find_limb_csvs(
    folder: Path, work_dir: Path
) -> tuple[Path | None, Path | None, list[Path], str | None]:
    """LIMB CSVs from loose files or from All IFD Datasets.zip."""
    temps: list[Path] = []
    candidates = [p for p in folder.glob("*.csv") if "limb" in p.name.lower()]
    hr = next(
        (
            p
            for p in candidates
            if "high" in p.name.lower() and "resolution" in p.name.lower()
        ),
        None,
    )
    bom = next(
        (
            p
            for p in candidates
            if "bom" in p.name.lower() and "resolution" in p.name.lower()
        ),
        None,
    )
    if not hr:
        hr = _first_glob(folder, "*LIMB*High*Resolution*.csv")
    if not bom:
        bom = _first_glob(folder, "*LIMB*BoM*Resolution*.csv")

    source_note: str | None = None
    ifd_zip = _find_ifd_datasets_zip(folder)
    if ifd_zip and (not hr or not bom):
        dest = work_dir
        if not hr:
            hr = _extract_zip_member_csv(
                ifd_zip,
                lambda n: "limb" in n.lower()
                and "high" in n.lower()
                and "resolution" in n.lower(),
                dest,
            )
            if hr:
                temps.append(hr)
        if not bom:
            bom = _extract_zip_member_csv(
                ifd_zip,
                lambda n: "limb" in n.lower()
                and "bom" in n.lower()
                and "resolution" in n.lower(),
                dest,
            )
            if bom:
                temps.append(bom)
        if hr and bom and temps:
            source_note = f"LIMB IFD CSVs extracted from {ifd_zip.name}"

    return hr, bom, temps, source_note


def _hub_has_limb_hr(hub_text: str) -> bool:
    return "[LIMBIFDhr(2019)]" in hub_text or "[LIMBifdhr]" in hub_text


def _hub_has_limb_bom(hub_text: str) -> bool:
    return "[LIMBIFDbom(2019)]" in hub_text or "[LIMBifdbom]" in hub_text


def _hub_txt_has_limb_sections(hub_text: str) -> bool:
    return _hub_has_limb_hr(hub_text) or _hub_has_limb_bom(hub_text)


ICM_DATA_FILES = (
    "ArrDataHub.txt",
    "BomIfds.csv",
    "BomIfdsVeryFrequent.csv",
    "BomIfsRare.csv",
)


def _find_icm_shell_zip(folder: Path) -> Path | None:
    """ICM-exported .arr.zip containing StormGenerator.xpx (required to open in Storm Generator UI)."""
    candidates: list[Path] = []
    for zpath in sorted(folder.glob("*.arr.zip")):
        try:
            with zipfile.ZipFile(zpath) as zf:
                names = set(zf.namelist())
        except zipfile.BadZipFile:
            continue
        if "StormGenerator.xpx" in names and "StormGenerator.json" in names:
            candidates.append(zpath)
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_size)


def _normalize_starttxt_header(lines: list[str]) -> list[str]:
    """ICM expects exactly one blank line after [STARTTXT] (2026 hub export often has two)."""
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        if line.strip() == "[STARTTXT]":
            i += 1
            while i < len(lines) and lines[i].strip() == "":
                i += 1
            out.append("")
            continue
        i += 1
    return out


def package_arr_zip_with_shell(
    shell_zip: Path, output_dir: Path, out_zip: Path, lat: float, lon: float
) -> None:
    with zipfile.ZipFile(shell_zip) as zin:
        payload = {info.filename: zin.read(info.filename) for info in zin.infolist()}
    for name in ICM_DATA_FILES:
        payload[name] = (output_dir / name).read_bytes()
    meta = json.loads(payload["StormGenerator.json"].decode("utf-8"))
    meta["DownloadConfig"]["Latitude"] = lat
    meta["DownloadConfig"]["Longitude"] = lon
    meta["FileName"] = out_zip.name
    payload["StormGenerator.json"] = (json.dumps(meta, indent=2) + "\n").encode("utf-8")
    with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        for name, data in payload.items():
            zout.writestr(name, data)


def write_icm_text_file(path: Path, content: str) -> None:
    """Write text the way legacy Storm Generator exports: UTF-8, CRLF, no BOM."""
    normalized = content.replace("\r\n", "\n").replace("\n", "\r\n")
    path.write_bytes(normalized.encode("utf-8"))


def _code_from_areal_zip(name: str) -> str:
    m = re.match(r"Areal_(.+)\.zip$", name, re.I)
    return m.group(1) if m else ""


def _increments_csv_in_zip(
    zip_path: Path, work_dir: Path
) -> tuple[Path | None, str | None]:
    with zipfile.ZipFile(zip_path) as zf:
        inc_names = [n for n in zf.namelist() if n.lower().endswith("_increments.csv")]
        if not inc_names:
            return None, None
        name = inc_names[0]
        tp = name.split("_")[0] if "_" in name else None
        tmp = work_dir / f"point_increments_{Path(name).name}"
        tmp.write_bytes(zf.read(name))
        return tmp, tp


def _read_tp_code(hub_text: str) -> str | None:
    return _read_code_after_tag(hub_text, "[TP]", "code,")


def _read_atp_code(hub_text: str) -> str | None:
    return _read_code_after_tag(hub_text, "[ATP]", "code,")


def _read_code_after_tag(hub_text: str, tag: str, prefix: str) -> str | None:
    inside = False
    for line in hub_text.splitlines():
        if line.strip() == tag:
            inside = True
            continue
        if inside and line.startswith(prefix):
            return line.split(",", 1)[1].strip()
        if inside and line.strip().startswith("[") and not line.startswith(prefix):
            break
    return None


def _parse_inputdata(hub_text: str) -> tuple[float, float]:
    lat = lon = None
    for line in hub_text.splitlines():
        if line.startswith("Latitude,"):
            lat = float(line.split(",", 1)[1])
        elif line.startswith("Longitude,"):
            lon = float(line.split(",", 1)[1])
    if lat is None or lon is None:
        raise ValueError("Latitude/Longitude missing from hub .txt")
    return lat, lon


def build_startpatterns_block(increments_csv: Path) -> str:
    raw = increments_csv.read_text(encoding="utf-8", errors="replace").strip("\n")
    if not raw.lower().startswith("eventid"):
        raise ValueError(f"Unexpected increments CSV format in {increments_csv.name}")
    return "Temporal Pattern Raw Data\n[STARTPATTERNS]\n" + raw + "\n[ENDPATTERNS]"


def transform_hub_text_to_arr_datahub(
    hub_text: str, patterns_block: str, inputs: HubInputs
) -> tuple[str, list[str]]:
    lines = hub_text.replace("\r\n", "\n").split("\n")
    cleaned: list[str] = []
    for line in lines:
        if line.startswith("Data Hub Version,"):
            continue
        if line.startswith("Centroid_Used,"):
            continue
        if line.strip().startswith("Download URL:"):
            continue
        cleaned.append(_sanitize_meta_line(line))

    cleaned = _normalize_starttxt_header(cleaned)

    end_txt_i = next(
        (i for i, ln in enumerate(cleaned) if ln.strip() == "[ENDTXT]"), len(cleaned) - 1
    )
    body = cleaned[: end_txt_i + 1]
    body = _remove_tagged_block(body, "[RECIFD]", "[END_RECIFD]")
    body = _remove_standalone_title(body, "Default IFD Depths")
    body = _remove_tagged_block(body, "[ALLBOMIFD]", "[END_ALLBOMIFD]")
    body = _simplify_losses(body)
    body, ifd_notes = _reorder_and_trim_ifd(body, inputs)
    body = _normalize_preburst_end_tags(body)
    body = _normalize_icm_meta_sections(body)
    body = _normalize_icm_preburst_tables(body)

    while body and body[-1].strip() in ("", "[ENDTXT]"):
        body.pop()
    body.append("[ENDTXT]")
    body.append(patterns_block.strip("\n"))
    text = "\n".join(body) + "\n"
    _validate_icm_arr_datahub(text)
    return text, ifd_notes


def _validate_icm_arr_datahub(text: str) -> None:
    required = (
        "[STARTTXT]",
        "[END_CCF]",
        "[LIMBifdbom]",
        "[LIMBifdenv]",
        "[ENDTXT]",
        "[STARTPATTERNS]",
        "[ENDPATTERNS]",
    )
    missing = [tag for tag in required if tag not in text]
    if missing:
        raise ValueError(
            "ArrDataHub.txt is incomplete for ICM (missing rainfall sections). "
            "Check that BoM and LIMB inputs are present in the download folder."
        )
    anchor = text.find("[END_CCF]")
    end_txt = text.find("[ENDTXT]")
    limb_tail = text[anchor:end_txt] if anchor != -1 and end_txt != -1 else ""
    if anchor != -1 and end_txt != -1 and "[LIMBifdbom]" not in limb_tail:
        raise ValueError(
            "ArrDataHub.txt is missing LIMB rainfall blocks required by ICM."
        )


def _sanitize_meta_line(line: str) -> str:
    if "<" in line:
        line = re.sub(r"</?br\s*/?>", ". ", line, flags=re.I)
        line = re.sub(r"</?strong>", "", line, flags=re.I)
    line = re.sub(r"(\.\s*){2,}", ". ", line)
    return line.rstrip()


def _normalize_preburst_end_tags(lines: list[str]) -> list[str]:
    """ICM legacy ArrDataHub.txt concatenates this suffix on preburst section ends."""
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if re.fullmatch(r"\[END_PREBURST(\d+)?\]", stripped):
            out.append(stripped + "From preburst class")
        else:
            out.append(line)
    return out


_ICM_PREBURST_NOTE = (
    "Preburst interpolation methods for catchment wide preburst has been slightly "
    "altered. Point values remain unchanged."
)


def _remove_standalone_title(lines: list[str], title: str) -> list[str]:
    """Drop a section title left behind when a tagged block was removed."""
    out: list[str] = []
    i = 0
    while i < len(lines):
        if lines[i].strip() == title:
            i += 1
            while i < len(lines) and lines[i].strip() == "":
                i += 1
            continue
        out.append(lines[i])
        i += 1
    return out


def _normalize_icm_meta_sections(lines: list[str]) -> list[str]:
    """2026 hub exports duplicate Time Accessed and extended Version strings ICM rejects."""
    out: list[str] = []
    in_meta = False
    seen_time_accessed = False
    for line in lines:
        stripped = line.strip()
        if stripped.endswith("_META]") and stripped.startswith("["):
            in_meta = True
            seen_time_accessed = False
            out.append(line)
            continue
        if in_meta:
            if stripped.startswith("Time Accessed,"):
                if seen_time_accessed:
                    continue
                seen_time_accessed = True
            elif stripped.startswith("Version,") and " (" in stripped:
                ver = stripped.split(",", 1)[1].split(" (", 1)[0].strip()
                line = f"Version,{ver}"
            elif stripped.startswith("Note,") and "2030) baseline default IFD" in stripped:
                line = f"Note,{_ICM_PREBURST_NOTE}"
            if stripped.startswith("[END_"):
                in_meta = False
        out.append(line)
    return out


def _normalize_icm_aep_header(line: str) -> str:
    if not line.strip().startswith("min (h)"):
        return line
    parts = line.split(",")
    normalized = [parts[0]]
    for cell in parts[1:]:
        cell = cell.strip()
        try:
            val = float(cell)
            normalized.append(str(int(val)) if val == int(val) else cell)
        except ValueError:
            normalized.append(cell)
    return ",".join(normalized)


def _normalize_icm_preburst_tables(lines: list[str]) -> list[str]:
    """ICM legacy preburst tables omit 30 min rows and use integer AEP column labels."""
    out: list[str] = []
    in_table = False
    for line in lines:
        stripped = line.strip()
        if re.fullmatch(r"\[PREBURST(\d+)?\]", stripped):
            in_table = True
            out.append(line)
            continue
        if in_table:
            if stripped.endswith("_META]") and stripped.startswith("["):
                in_table = False
            elif stripped.startswith("min (h)"):
                out.append(_normalize_icm_aep_header(line))
                continue
            elif re.match(r"^30\s*\(0\.5\)", stripped):
                continue
            elif stripped.startswith("[") and not stripped.startswith("[PREBURST"):
                in_table = False
        out.append(line)
    return out


def _remove_tagged_block(lines: list[str], start: str, end: str) -> list[str]:
    out: list[str] = []
    skip = False
    for line in lines:
        if line.strip() == start:
            skip = True
            continue
        if skip and (line.strip() == end or line.strip().startswith(end)):
            skip = False
            continue
        if not skip:
            out.append(line)
    return out


def _simplify_losses(lines: list[str]) -> list[str]:
    native_il = native_cl = loss_id = None
    inside_native = False
    for line in lines:
        s = line.strip()
        if s == "[LOSSES_NATIVE]":
            inside_native = True
            continue
        if inside_native and s.startswith("ID,"):
            loss_id = s.split(",", 1)[1]
        if inside_native and s.lower().startswith("storm initial losses"):
            native_il = s.split(",", 1)[1]
        if inside_native and s.lower().startswith("storm continuing losses"):
            native_cl = s.split(",", 1)[1]
        if inside_native and s == "[END_LOSSES_NATIVE]":
            break
    if not all([native_il, native_cl, loss_id]):
        return lines

    out: list[str] = []
    skip = False
    replaced = False
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("Storm Losses -") or line.strip() == "[LOSSES]":
            if not replaced:
                out.extend(
                    [
                        "Storm Losses",
                        "[LOSSES]",
                        f"ID,{loss_id}",
                        f"Storm Initial Losses (mm),{native_il}",
                        f"Storm Continuing Losses (mm/h),{native_cl}",
                        "[LOSSES_META]",
                        f"Time Accessed,{datetime.now():%d %B %Y %I:%M%p}",
                        "Version,2016_v1",
                        "[END_LOSSES]",
                        "",
                    ]
                )
                replaced = True
            skip = True
            i += 1
            continue
        if skip:
            if line.strip() in ("[END_LOSSES]", "[END_LOSSES_NATIVE]"):
                skip = False
            elif line.startswith("Storm Losses -"):
                i += 1
                continue
            i += 1
            continue
        if line.strip() == "[LOSSES_NATIVE]" or line.startswith("Storm Losses - Native"):
            skip = True
            i += 1
            continue
        out.append(line)
        i += 1
    return out


def _extract_section(lines: list[str], start_tag: str, end_tag: str) -> list[str]:
    out: list[str] = []
    inside = False
    for line in lines:
        if line.strip() == start_tag:
            inside = True
            out.append(line)
            continue
        if inside:
            out.append(line)
            if line.strip() == end_tag or line.strip().startswith(end_tag):
                break
    if not out:
        raise ValueError(f"Section {start_tag} not found.")
    return out


def _rename_limb_sections(block: list[str]) -> list[str]:
    repl = {
        "[LIMBIFDhr(2019)]": "[LIMBifdhr]",
        "[END_LIMBIFDhr(2019)]": "[END_LIMBifdhr]",
        "[LIMBIFDhr(2019)_META]": "[LIMBifdhr_META]",
        "[LIMBIFDbom(2019)]": "[LIMBifdbom]",
        "[END_LIMBIFDbom(2019)]": "[END_LIMBifdbom]",
        "[LIMBIFDbom(2019)_META]": "[LIMBifdbom_META]",
    }
    return [repl.get(ln.strip(), ln) for ln in block]


def _table_from_section(section_lines: list[str]) -> tuple[list[str], dict[int, list[float]]]:
    header_line = next(ln for ln in section_lines if ln.strip().startswith("min (h)"))
    aep_headers = [p.strip() for p in header_line.split(",")][1:]
    table: dict[int, list[float]] = {}
    for ln in section_lines:
        m = DUR_ROW_RE.match(ln.strip())
        if not m:
            continue
        parts = [p.strip() for p in ln.split(",")]
        dur = int(m.group(1))
        table[dur] = [float(x) for x in parts[1 : 1 + len(aep_headers)]]
    return aep_headers, table


def build_limb_envelope_lines(bom_section: list[str], limb_bom_section: list[str]) -> list[str]:
    _, bom_t = _table_from_section(bom_section)
    _, limb_t = _table_from_section(limb_bom_section)
    header = next(ln for ln in bom_section if ln.strip().startswith("min (h)"))
    labels: dict[int, str] = {}
    for ln in bom_section:
        m = DUR_ROW_RE.match(ln.strip())
        if m:
            labels[int(m.group(1))] = ln.split(",")[0].strip()
    rows = []
    for dur in sorted(set(bom_t) & set(limb_t)):
        merged = [max(a, b) for a, b in zip(bom_t[dur], limb_t[dur])]
        label = labels.get(dur, f"{dur} (0)")
        rows.append(label + "," + ",".join(str(v) for v in merged))
    return (
        ["", "LIMB 2020 IFD - Enveloped", "[LIMBifdenv]", header]
        + rows
        + [
            "[LIMBifdenv_META]",
            f"Time Accessed,{datetime.now():%d %B %Y %I:%M%p}",
            "Version,2022_v1",
            "Note,Envelope of BoM 2016 IFD and LIMB 2020 BoM-resolution depths.",
            "[END_LIMBifdenv]",
            "",
        ]
    )


def _extract_with_title(lines: list[str], title: str, core: list[str]) -> list[str]:
    try:
        ti = next(i for i, ln in enumerate(lines) if ln.strip() == title)
    except StopIteration:
        return [""] + core
    start_tag = core[0].strip()
    si = next(i for i, ln in enumerate(lines) if ln.strip() == start_tag)
    return lines[ti:si] + core


def _section_exists(lines: list[str], tag: str) -> bool:
    return any(ln.strip() == tag for ln in lines)


def _csv_to_ifd_section(csv_path: Path, section_tag: str, title: str) -> list[str]:
    lines = csv_path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not lines:
        raise ValueError(f"Empty CSV: {csv_path.name}")
    header = lines[0].strip()
    data = [ln for ln in lines[1:] if ln.strip() and DUR_ROW_RE.match(ln.strip())]
    return (
        ["", title, f"[{section_tag}]", header]
        + data
        + [
            f"[{section_tag}_META]",
            f"Time Accessed,{datetime.now():%d %B %Y %I:%M%p}",
            "Version,2022_v1",
            f"Note,Prepared from ARR Data Hub download ({csv_path.name}).",
            f"[END_{section_tag}]",
            "",
        ]
    )


def _bom_csv_as_ifd_section(bom_csv: Path) -> list[str]:
    lines = bom_csv.read_text(encoding="utf-8", errors="replace").splitlines()
    header = lines[0].strip()
    data = [ln for ln in lines[1:] if ln.strip() and DUR_ROW_RE.match(ln.strip())]
    return ["[BOMIFD(2016)]", header] + data + ["[END_BOMIFD(2016)]"]


def _resolve_bom_ifd_section(lines: list[str], inputs: HubInputs) -> list[str]:
    if _section_exists(lines, "[BOMIFD(2016)]"):
        return _extract_section(lines, "[BOMIFD(2016)]", "[END_BOMIFD(2016)]")
    return _bom_csv_as_ifd_section(inputs.bom_csv)


def _ifd_table_lines(section_lines: list[str]) -> list[str]:
    return [
        ln
        for ln in section_lines
        if ln.strip().startswith("min (h)") or DUR_ROW_RE.match(ln.strip())
    ]


def _bom_ifd_to_limb_bom_block(bom_ifd: list[str], note: str) -> list[str]:
    return (
        ["", "LIMB 2020 IFD - BoM Resolution", "[LIMBifdbom]"]
        + _ifd_table_lines(bom_ifd)
        + [
            "[LIMBifdbom_META]",
            f"Time Accessed,{datetime.now():%d %B %Y %I:%M%p}",
            "Version,2022_v1",
            f"Note,{note}",
            "[END_LIMBifdbom]",
            "",
        ]
    )


def _limb_bom_block_from_inputs(lines: list[str], inputs: HubInputs) -> list[str]:
    if _section_exists(lines, "[LIMBIFDbom(2019)]"):
        limb_bom = _extract_section(lines, "[LIMBIFDbom(2019)]", "[END_LIMBIFDbom(2019)]")
        block = _extract_with_title(
            lines, "LIMB 2020 IFD Depths - BoM Resolution", limb_bom
        )
        return _rename_limb_sections(block)
    if inputs.limb_bom_csv:
        return _csv_to_ifd_section(
            inputs.limb_bom_csv, "LIMBifdbom", "LIMB 2020 IFD - BoM Resolution"
        )
    bom_ifd = _resolve_bom_ifd_section(lines, inputs)
    return _bom_ifd_to_limb_bom_block(
        bom_ifd,
        "No LIMB 2020 IFD at this location; BoM 2016 IFD used for LIMB rainfall block.",
    )


def _reorder_and_trim_ifd(lines: list[str], inputs: HubInputs) -> tuple[list[str], list[str]]:
    notes: list[str] = []
    ccf_end = next(i for i, ln in enumerate(lines) if ln.strip() == "[END_CCF]")
    prefix = lines[: ccf_end + 1]

    limb_hr_full: list[str] | None = None
    bom_ifd = _resolve_bom_ifd_section(lines, inputs)

    if _section_exists(lines, "[LIMBIFDhr(2019)]"):
        limb_hr = _extract_section(lines, "[LIMBIFDhr(2019)]", "[END_LIMBIFDhr(2019)]")
        limb_hr_full = _rename_limb_sections(
            _extract_with_title(
                lines, "LIMB 2020 IFD Depths - High Resolution", limb_hr
            )
        )
        limb_bom_full = _limb_bom_block_from_inputs(lines, inputs)
        if not _section_exists(lines, "[LIMBIFDbom(2019)]") and not inputs.limb_bom_csv:
            notes.append(
                "LIMB BoM-resolution grids were derived from BoM 2016 IFD depths."
            )
    elif inputs.limb_hr_csv and inputs.limb_bom_csv:
        limb_hr_full = _csv_to_ifd_section(
            inputs.limb_hr_csv, "LIMBifdhr", "LIMB 2020 IFD - High Resolution"
        )
        limb_bom_full = _csv_to_ifd_section(
            inputs.limb_bom_csv, "LIMBifdbom", "LIMB 2020 IFD - BoM Resolution"
        )
    elif inputs.limb_hr_csv:
        raise ValueError(
            "LIMB high-resolution file found without matching BoM-resolution LIMB data."
        )
    elif _section_exists(lines, "[LIMBIFDbom(2019)]") or inputs.limb_bom_csv:
        limb_bom_full = _limb_bom_block_from_inputs(lines, inputs)
        notes.append("LIMB high-resolution grids were omitted (not available).")
    else:
        limb_bom_full = _limb_bom_block_from_inputs(lines, inputs)
        notes.append(
            "No LIMB IFD at this location; BoM 2016 depths used for LIMB rainfall blocks."
        )

    limb_bom_table = _ifd_table_lines(limb_bom_full)
    env_block = build_limb_envelope_lines(
        bom_ifd, ["[LIMBIFDbom(2019)]"] + limb_bom_table
    )
    tail: list[str] = ["", ""]
    if limb_hr_full:
        tail.extend(limb_hr_full)
    tail.extend(env_block)
    tail.extend(limb_bom_full)
    return prefix + tail, notes


def _storm_generator_json(lat: float, lon: float, zip_path: Path) -> str:
    """Minimal StormGenerator.json aligned with ICM layout (storm state not included)."""
    template_path = Path(__file__).resolve().parent / "_storm_generator_json_template.json"
    if template_path.is_file():
        data = json.loads(template_path.read_text(encoding="utf-8"))
    else:
        data = _default_storm_generator_json()
    data["DownloadConfig"]["Latitude"] = lat
    data["DownloadConfig"]["Longitude"] = lon
    data["FileName"] = zip_path.name
    return json.dumps(data, indent=2) + "\n"


def _default_storm_generator_json() -> dict:
    return {
        "DownloadConfig": {
            "Longitude": 0.0,
            "Latitude": 0.0,
            "AcceptedBomConditionsOfUse": True,
            "AcceptedBomCoordinatesCaveat": True,
            "IncludeVeryFrequentAndRareIfds": True,
            "ArrDataHubVersion": 1,
        },
        "FileName": "",
        "TargetFolder": None,
        "LastGeneratedOn": None,
        "LastGeneratedBy": None,
        "BaseMultiplier": 1,
        "DataFiles": {
            "ArrDataHubText": {"SourceType": 0, "Source": None, "FileName": "ArrDataHub.txt"},
            "ArrTemporalPatternsIncrementsCsv": {
                "SourceType": 0,
                "Source": None,
                "FileName": None,
            },
            "ArfTemporalPatternsCsv": {"SourceType": 0, "Source": None, "FileName": None},
            "BomIfds": {"SourceType": 0, "Source": None, "FileName": "BomIfds.csv"},
            "BomIfdsVeryFrequent": {
                "SourceType": 0,
                "Source": None,
                "FileName": "BomIfdsVeryFrequent.csv",
            },
            "BomIFdsRare": {"SourceType": 0, "Source": None, "FileName": "BomIfsRare.csv"},
            "StormGeneratorState": {"SourceType": 0, "Source": None, "FileName": None},
            "StormGeneratorXpx": {"SourceType": 0, "Source": None, "FileName": None},
            "StormGeneratorReport": {"SourceType": 0, "Source": None, "FileName": None},
        },
        "Aeps": [{"Name": n, "IsSelected": True} for n in _default_aep_names()],
        "Durations": [
            {"Name": label, "IsSelected": True}
            for dur_min, label in DURATION_MINUTES
            if dur_min >= 5
        ],
    }


def _default_aep_names() -> list[str]:
    return [
        "12EY", "6EY", "4EY", "3EY", "2EY", "63.2%", "50%", "0.5EY", "20%", "0.2EY",
        "10%", "5%", "2%", "1%", "1 in 200", "1 in 500", "1 in 1000", "1 in 2000",
    ]


def _friendly_bom_csv_error(exc: BaseException) -> str:
    if isinstance(exc, KeyError):
        key = exc.args[0] if exc.args else "unknown"
        return (
            f"The BoM rainfall table is missing column '{key}' (needed for very-frequent "
            "or rare design storms). Include BoM IFD Depths (All Durations and AEPs).csv "
            "in the download folder, or use a complete results.txt from the ARR Data Hub."
        )
    return f"BoM rainfall table could not be read: {exc}"


def _write_build_log(
    output_dir: Path,
    *,
    latitude: float,
    longitude: float,
    zip_name: str | None,
    notes: list[str],
) -> None:
    lines = [
        "ARR Data Hub to Storm Generator (ICM & XPSWMM) — build log",
        f"Generated: {datetime.now():%d %B %Y %H:%M}",
        f"Location: {latitude:.6f}, {longitude:.6f}",
    ]
    if zip_name:
        lines.append(f"Storm archive: {zip_name}")
    else:
        lines.append("Storm archive: not created (see README — template .arr.zip required)")
    if notes:
        lines.append("")
        lines.append("Notes:")
        lines.extend(f"- {note}" for note in notes)
    else:
        lines.append("")
        lines.append("Notes: none")
    (output_dir / BUILD_LOG_NAME).write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_from_folder(
    input_dir: Path, output_dir: Path, shell_arr_zip: Path | None = None
) -> BuildResult:
    log_notes: list[str] = []
    errors: list[str] = []

    output_dir.mkdir(parents=True, exist_ok=True)
    work_dir = _work_dir(output_dir)

    inputs, missing = discover_inputs(input_dir, work_dir)
    if inputs is None:
        errors.extend(f"Missing input: {m}" for m in missing)
        return BuildResult(output_dir, None, log_notes, errors)

    if shell_arr_zip is not None:
        inputs.shell_arr_zip = shell_arr_zip
    elif inputs.shell_arr_zip is None:
        log_notes.append(
            "To produce a .arr.zip that opens in ARR Storm Generator, place one existing "
            "storm .arr.zip from the same region in the download folder as a template."
        )

    log_notes.extend(inputs.warnings)

    hub_text = inputs.hub_txt.read_text(encoding="utf-8", errors="replace")
    try:
        lat, lon = _parse_inputdata(hub_text)
    except ValueError as exc:
        errors.append(str(exc))
        return BuildResult(output_dir, None, log_notes, errors)

    bom_text = inputs.bom_csv.read_text(encoding="utf-8", errors="replace")
    try:
        aep_headers, bom_table, bom_source_note = resolve_bom_ifd_table(hub_text, bom_text)
        if bom_source_note:
            log_notes.append(bom_source_note)
        for keys in (STD_AEP_HUB, VF_AEP_HUB, RARE_AEP_HUB):
            for k in keys:
                _hub_column_index(aep_headers, k)
    except (KeyError, ValueError) as exc:
        errors.append(_friendly_bom_csv_error(exc))
        return BuildResult(output_dir, None, log_notes, errors)

    try:
        patterns = build_startpatterns_block(inputs.point_increments_csv)
        arr_txt, ifd_notes = transform_hub_text_to_arr_datahub(hub_text, patterns, inputs)
        log_notes.extend(ifd_notes)
    except ValueError as exc:
        errors.append(str(exc))
        return BuildResult(output_dir, None, log_notes, errors)

    try:
        bom_std = build_bom_ifds_variant(
            bom_table,
            aep_headers,
            lat,
            lon,
            STD_AEP_HUB,
            STD_AEP_ICM,
            "IFD Design Rainfall Depth (mm)",
            "Annual Exceedance Probability (AEP)",
        )
        bom_vf = build_bom_ifds_variant(
            bom_table,
            aep_headers,
            lat,
            lon,
            VF_AEP_HUB,
            VF_AEP_ICM,
            "Very Frequent Design Rainfall Depth (mm)",
            "Exceedance per Year (EY)",
        )
        bom_rare = build_bom_ifds_variant(
            bom_table,
            aep_headers,
            lat,
            lon,
            RARE_AEP_HUB,
            RARE_AEP_ICM,
            "Rare Design Rainfall Depth (mm)",
            "Annual Exceedance Probability (1 in x)",
        )
    except KeyError as exc:
        errors.append(_friendly_bom_csv_error(exc))
        return BuildResult(output_dir, None, log_notes, errors)

    stamp = datetime.now().strftime("%Y-%m-%d_%H.%M.%S")
    zip_path = output_dir / f"StormGenerator_{stamp}.arr.zip"

    write_icm_text_file(output_dir / "ArrDataHub.txt", arr_txt)
    write_icm_text_file(output_dir / "BomIfds.csv", bom_std)
    write_icm_text_file(output_dir / "BomIfdsVeryFrequent.csv", bom_vf)
    write_icm_text_file(output_dir / "BomIfsRare.csv", bom_rare)

    shell = inputs.shell_arr_zip
    if shell:
        package_arr_zip_with_shell(shell, output_dir, zip_path, lat, lon)
        log_notes.append(f"Created {zip_path.name} using template archive {shell.name}.")
    else:
        log_notes.append(
            "Individual data files were written. Import them in ARR Storm Generator "
            "(ICM or XPSWMM) via Edit > Add from file, or add a template .arr.zip to the download folder."
        )
        zip_path = None

    _write_build_log(
        output_dir,
        latitude=lat,
        longitude=lon,
        zip_name=zip_path.name if zip_path else None,
        notes=log_notes,
    )

    for tmp in inputs.temp_paths:
        if tmp.is_file():
            tmp.unlink(missing_ok=True)
    shutil.rmtree(work_dir, ignore_errors=True)

    return BuildResult(output_dir, zip_path, log_notes, errors)


def _pick_folders_ui() -> tuple[Path | None, Path | None]:
    import tkinter as tk
    from tkinter import filedialog, messagebox

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    in_dir = filedialog.askdirectory(title="Select ARR Data Hub input folder")
    if not in_dir:
        root.destroy()
        return None, None
    out_dir = filedialog.askdirectory(
        title="Select output folder (Cancel = create 'StormGenerator_output' inside input folder)",
        initialdir=in_dir,
    )
    root.destroy()
    in_path = Path(in_dir)
    out_path = Path(out_dir) if out_dir else in_path / "StormGenerator_output"
    return in_path, out_path


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Convert an ARR Data Hub download into Storm Generator files (ICM & XPSWMM)."
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        help="Folder containing results.txt and related ARR Data Hub downloads",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Folder for output files (default: StormGenerator_output inside input folder)",
    )
    parser.add_argument(
        "--shell-arr-zip",
        type=Path,
        help="Optional Storm Generator .arr.zip template used to build a loadable output archive",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.input_dir is None:
        in_dir, out_dir = _pick_folders_ui()
        if in_dir is None:
            print("Cancelled.")
            return 1
    else:
        in_dir = args.input_dir
        out_dir = args.output_dir or (in_dir / "StormGenerator_output")

    result = build_from_folder(in_dir, out_dir, args.shell_arr_zip)
    if result.errors:
        print("Build failed.")
        for e in result.errors:
            print(f"  • {e}")
        return 1

    print("Build completed successfully.")
    print(f"  Output folder: {result.output_dir}")
    if result.zip_path:
        print(f"  Storm archive: {result.zip_path.name}")
    if result.manifest_lines:
        print(f"  Notes: {len(result.manifest_lines)} (see {BUILD_LOG_NAME})")
    else:
        print(f"  Log: {BUILD_LOG_NAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
