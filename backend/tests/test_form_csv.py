"""Unit tests for the CSV helper (_csv_safe) and header ordering."""
import csv, io
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "backend"))

from portal.routes.catalog import _csv_safe

def test_csv_safe_prefixes_formula_chars():
    assert _csv_safe("=SUM(1,2)") == "'=SUM(1,2)"
    assert _csv_safe("+123") == "'+123"
    assert _csv_safe("-5") == "'-5"
    assert _csv_safe("@hello") == "'@hello"
    assert _csv_safe("\ttab") == "'\ttab"
    assert _csv_safe("\rcr") == "'\rcr"
    # normal values unchanged
    assert _csv_safe("plain") == "plain"
    assert _csv_safe("") == ""

def test_csv_header_order_and_bom():
    # Simulate the generator used in the export endpoint
    headers = ["submitted_at","name","email","phone","company","ip","Nama lengkap","Email"]
    out = io.StringIO()
    out.write("\ufeff")
    writer = csv.writer(out)
    writer.writerow([_csv_safe(h) for h in headers])
    data = out.getvalue()
    assert data.startswith("\ufeff")
    assert "Nama lengkap" in data and "Email" in data
