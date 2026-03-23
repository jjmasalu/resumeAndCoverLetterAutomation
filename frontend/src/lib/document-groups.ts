export interface VariantDocumentLike {
  doc_type: string;
  variant_group_id?: string | null;
}

export interface DocumentGroup<T extends VariantDocumentLike> {
  key: string;
  docType: string;
  variantGroupId: string | null;
  items: T[];
  isVariantBundle: boolean;
}

export function groupDocumentsByVariant<T extends VariantDocumentLike>(
  documents: T[]
): Array<DocumentGroup<T>> {
  const bundleCounts = new Map<string, number>();

  for (const document of documents) {
    if (!document.variant_group_id) continue;
    const key = `${document.doc_type}:${document.variant_group_id}`;
    bundleCounts.set(key, (bundleCounts.get(key) || 0) + 1);
  }

  const seenBundles = new Set<string>();
  const groups: Array<DocumentGroup<T>> = [];

  for (const document of documents) {
    const bundleKey = document.variant_group_id
      ? `${document.doc_type}:${document.variant_group_id}`
      : null;

    if (bundleKey && (bundleCounts.get(bundleKey) || 0) > 1) {
      if (seenBundles.has(bundleKey)) {
        continue;
      }
      seenBundles.add(bundleKey);
      groups.push({
        key: bundleKey,
        docType: document.doc_type,
        variantGroupId: document.variant_group_id || null,
        items: documents.filter(
          (item) =>
            item.doc_type === document.doc_type &&
            item.variant_group_id === document.variant_group_id
        ),
        isVariantBundle: true,
      });
      continue;
    }

    groups.push({
      key: bundleKey || `single:${document.doc_type}:${groups.length}`,
      docType: document.doc_type,
      variantGroupId: document.variant_group_id || null,
      items: [document],
      isVariantBundle: false,
    });
  }

  return groups;
}

export function documentBundleTitle(docType: string): string {
  return docType === "cover_letter" ? "Cover letter variants" : "Resume variants";
}

export function documentBundleDescription(docType: string): string {
  if (docType === "cover_letter") {
    return "These versions share the same content plan and differ only in presentation.";
  }
  return "These versions share the same resume content. ATS-safe is best for recruiter systems, while Creative-safe gives a stronger design-forward presentation.";
}
