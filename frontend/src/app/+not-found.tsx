import { NotFoundCard, useDocumentTitle } from "../features/common";
import { Page } from "../ui/layout";

export default function NotFound() {
  useDocumentTitle("Page not found");
  return (
    <Page testID="not-found-page">
      <NotFoundCard title="Page not found" hint="Nothing lives at this address." href="/" label="Go to the dashboard" />
    </Page>
  );
}
