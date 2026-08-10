import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
AUTH = (ROOT / "backend/portal/auth.py").read_text()
MODELS = (ROOT / "backend/portal/models.py").read_text()
CMS = (ROOT / "backend/portal/routes/cms.py").read_text()
ADMIN = (ROOT / "frontend/src/pages/portal/admin/AdminArticles.jsx").read_text()
CLIENT = (ROOT / "frontend/src/pages/portal/client/ClientGuide.jsx").read_text()


class KBAuthoringContractTest(unittest.TestCase):
    def test_support_is_a_kb_author_but_not_a_general_content_author(self):
        self.assertIn('KB_AUTHOR_ROLES = {"admin", "creative", "support"}', AUTH)
        self.assertIn('admin=Depends(get_current_kb_author)', CMS)
        self.assertIn('admin.get("role") == "support" and payload.type != "kb"', CMS)

    def test_article_schema_and_editor_expose_kb_fields(self):
        self.assertIn('Literal["blog", "kb"]', MODELS)
        self.assertIn('kb_section: str', MODELS)
        self.assertIn('data-testid="editor-type"', ADMIN)
        self.assertIn('data-testid="editor-kb-section"', ADMIN)
        self.assertIn('params.set("type", typeFilter)', ADMIN)

    def test_client_guide_loads_published_kb_body_from_detail_endpoint(self):
        self.assertIn('/public/articles?type=kb&limit=50', CLIENT)
        self.assertIn('`/public/articles/${guide.slug}`', CLIENT)
        self.assertIn('dangerouslySetInnerHTML', CLIENT)


if __name__ == "__main__":
    unittest.main()
