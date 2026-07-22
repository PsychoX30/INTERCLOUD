import TaxonomyPage from "@/components/TaxonomyPage";
import { useI18n } from "@/context/I18nContext";

export default function Categories() {
  const { t } = useI18n();
  return (
    <TaxonomyPage
      resource="categories"
      title={t("common.categories")}
      extraField="description"
      extraLabel={t("common.description")}
    />
  );
}
