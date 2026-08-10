import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
MODELS = (ROOT / "backend/portal/models.py").read_text()
ROUTES_INIT = (ROOT / "backend/portal/routes/__init__.py").read_text()
SLA = (ROOT / "backend/portal/routes/sla.py").read_text()
DOCUMENTS = (ROOT / "backend/portal/routes/documents.py").read_text()


class SLAContractTest(unittest.TestCase):
    def test_models_have_sla_incident_and_config(self):
        self.assertIn("class SLAIncidentIn", MODELS)
        self.assertIn("class SLAIncidentOut", MODELS)
        self.assertIn("class SLAIncidentUpdate", MODELS)

    def test_sla_router_is_mounted(self):
        self.assertIn("transactions, sla", ROUTES_INIT)
        self.assertIn("router.include_router(sla.router)", ROUTES_INIT)

    def test_sla_report_requires_pdf_render(self):
        self.assertIn("_render_pdf_bytes", DOCUMENTS)

    def test_sla_config_uses_settings_pattern_and_detail_is_sales_scoped(self):
        self.assertIn("_get_setting_value", SLA)
        self.assertIn("_set_setting_value", SLA)
        self.assertIn("json.loads", SLA)
        self.assertIn("_sales_scope_filter_for_incidents(admin)", SLA)

    def test_sales_scope_matches_string_customer_ids(self):
        self.assertIn('[str(x) for x in assigned]', SLA)
        self.assertNotIn('[ObjectId(x) for x in (staff.get("assigned_client_ids") or [])]', SLA)

    def test_list_date_filter_accepts_dates_or_full_timestamps(self):
        self.assertIn('start if "T" in start else start + "T00:00:00"', SLA)
        self.assertIn('end if "T" in end else end + "T23:59:59"', SLA)


if __name__ == "__main__":
    unittest.main()