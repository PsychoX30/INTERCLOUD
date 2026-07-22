import TaxonomyPage from "@/components/TaxonomyPage";
import { useI18n } from "@/context/I18nContext";

export default function Locations() {
  const { t } = useI18n();
  return (
    <TaxonomyPage
      resource="locations"
      title={t("common.locations")}
      extraField="address"
      extraLabel={t("common.address")}
    />
  );
}
