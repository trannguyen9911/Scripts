# ARR Data Hub to Storm Generator (InfoWorks ICM & XPSWMM)

Convert a **2026 ARR Data Hub** download into the file layout that **ARR Storm Generator** expects in **InfoWorks ICM** and **XPSWMM** - useful when the in-product Data Hub download is unavailable or you prefer to prepare storms offline.

For a step-by-step walkthrough, watch the two-part demo in this folder (see [Demo videos](#demo-videos) below).

## Demo videos

The workflow is split into two recordings (large file size):

| Part | Video | Covers |
|------|--------|--------|
| **1** | [1. Download data from ARR Data Hub.mp4](1.%20Download%20data%20from%20ARR%20Data%20Hub.mp4) | Choosing a location on [ARR Data Hub](https://data.arr-software.org/), downloading exports, and keeping one folder with `results.txt`, IFD zips, and temporal pattern zips |
| **2** | [2. Import data into ARR Storm Generator.mp4](2.%20Import%20data%20into%20ARR%20Storm%20Generator.mp4) | Running the converter, then creating a **New** storm in **ARR Storm Generator** and attaching the output files with **Add from file…** |

Suggested order: **Part 1 → run the converter (below) → Part 2**.

## What this tool does

The script `hub_to_storm_generator.py` reads your local Data Hub export and produces:

| Output | Purpose |
|--------|---------|
| `ArrDataHub.txt` | Hub metadata, climate factors, temporal patterns, and IFD blocks in Storm Generator layout |
| `BomIfds.csv` | Standard design IFDs |
| `BomIfdsVeryFrequent.csv` | Very-frequent design IFDs |
| `BomIfsRare.csv` | Rare design IFDs |
| `build_log.txt` | Summary of location, outputs, and any notes from the build |

Rainfall values are taken **only** from your Data Hub download folder.

## Requirements

- **Python 3.9+** (Windows: `py -3` from [python.org](https://www.python.org/downloads/))
- **tkinter** (included with standard Python on Windows; used for folder picker when run without arguments)
- **InfoWorks ICM** or **XPSWMM** with **ARR Storm Generator** (2025/2026 or as supported by your licence)

No extra pip packages are required for the converter.

## Input folder (ARR Data Hub download)

After exporting from [ARR Data Hub](https://data.arr-software.org/) (see **demo Part 1**), use one folder containing at least:

| File | Required | Notes |
|------|----------|--------|
| `results.txt` | Yes | Main hub text export |
| `BoM IFD Depths (All Durations and AEPs).csv` | Yes | Full range of AEPs for all three BoM CSVs |
| `All IFD Datasets.zip` | Yes | Often includes `BoM IFD Depths.csv` and optional LIMB CSVs |
| `Point_<region>.zip` | Yes | Point temporal patterns (`*_Increments.csv` inside) |
| `Areal_<region>.zip` | Yes | Must match the areal region in `results.txt` |

### LIMB IFD coverage

- Some locations include **LIMB high-resolution** and **BoM-resolution** grids in `All IFD Datasets.zip`.
- Others have **BoM-resolution LIMB only**, or **no LIMB** at all. The script adapts automatically and records what was used in `build_log.txt`.

## How to run

### Windows (easiest)

1. Double-click **`Run_hub_to_storm_generator.bat`** in this folder.
2. Select your **ARR Data Hub download** folder.
3. Select an **output** folder (or cancel to use `StormGenerator_output` inside the input folder).

### Command line

```bat
cd "C:\path\to\folder\containing\hub_to_storm_generator.py"
py -3 hub_to_storm_generator.py --input-dir "C:\path\to\ARR Data Hub Download" --output-dir "C:\path\to\output"
```

## Using the outputs in Storm Generator

See **demo Part 2** for the full walkthrough. The steps below match that video and work in **InfoWorks ICM** and **XPSWMM** (both use ARR Storm Generator).

1. **Run the converter** and open your **output folder**. Confirm `ArrDataHub.txt`, the three `BomIfds*.csv` files, and `build_log.txt` are present. Use `build_log.txt` to check the latitude/longitude and any LIMB or BoM notes.
2. **Open ARR Storm Generator** from ICM, XPSWMM, or the standalone Storm Generator application.
3. Click **New** to create a new storm (do not open an old `.arr.zip` from another site).
4. Tick **Include Very Frequent and Rare IFDs**
5. Choose ** Add from file…** (wording may vary slightly by product version).
6. Set **ARR Data Hub Text File** to the output **`ArrDataHub.txt`**.
7. Set **BOM Design Rainfall** to **`BomIfds.csv`**.
8. If your storm design uses them, also attach **`BomIfdsVeryFrequent.csv`** and **`BomIfsRare.csv`** to the corresponding BOM rainfall fields.
9. Finish the remaining Storm Generator settings (durations, AEPs, temporal patterns, and so on) and generate design storms as usual.

## Troubleshooting

| Symptom | What to check |
|---------|----------------|
| Build failed — missing column / `99.999` | Add `BoM IFD Depths (All Durations and AEPs).csv`, or ensure `results.txt` is the full hub export |
| Pattern zip mismatch | `Point_*.zip` / `Areal_*.zip` names must match the temporal pattern codes in `results.txt` |
| Cannot attach `ArrDataHub.txt` | Use a fresh build from this script; see `build_log.txt` for LIMB/BoM notes |

Temporary working files are stored under **`<output folder>\.work`** during the build and removed when the build finishes. Your Data Hub download folder is not modified.

## Licence and data attribution

- **BoM IFD data**: Commonwealth of Australia, Bureau of Meteorology ([CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)).
- **ARR Data Hub** exports: use in accordance with [ARR Data Hub](https://data.arr-software.org/) terms and attribution on the About page.
- **This script**: provided as open-source support material in this repository; verify results against Storm Generator, your modelling package, and project requirements before production use.

## Disclaimer

This tool is community-supported. It is not a substitute for engineering judgement, ARR Book 9 procedures, or Autodesk product documentation. Test imports on a copy of your project before relying on generated storms.
