"""Second gate: LibreOffice recalculation of the generated workbook.

Environment-dependent (needs soffice). The Python formula verifier in
generate_workbook is the always-on gate; run this one locally before publishing.

    python -m audit.recalc_gate data/MI_PE_Tracking_System_v4.xlsx
"""
import json, shutil, subprocess, sys
from pathlib import Path


def main(path):
    if not shutil.which("soffice"):
        print(json.dumps({"skipped": "soffice not on PATH — run locally"}))
        return 0
    subprocess.run(["soffice", "--headless", "--convert-to", "xlsx", "--outdir",
                    str(Path(path).parent), str(path)],
                   capture_output=True, text=True, timeout=300)
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True)
    errs = [f"{ws.title}!{c.coordinate}={c.value}" for ws in wb.worksheets
            for row in ws.iter_rows() for c in row
            if isinstance(c.value, str) and c.value.startswith("#")]
    print(json.dumps({"total_errors": len(errs), "errors": errs[:20]}))
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "data/MI_PE_Tracking_System_v4.xlsx"))
