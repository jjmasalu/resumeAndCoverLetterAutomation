"use client";

export const ATTACHMENT_ACCEPTED_MIME_TYPES = [
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "image/png",
  "image/jpeg",
];

export const ATTACHMENT_ACCEPTED_EXTENSIONS = [
  ".pdf",
  ".docx",
  ".png",
  ".jpg",
  ".jpeg",
];

export const ATTACHMENT_ACCEPTED_EXTENSIONS_ATTR =
  ATTACHMENT_ACCEPTED_EXTENSIONS.join(",");

export const ATTACHMENT_MAX_SIZE = 10 * 1024 * 1024;

function hasAcceptedExtension(name: string) {
  const lower = name.toLowerCase();
  return ATTACHMENT_ACCEPTED_EXTENSIONS.some((extension) => lower.endsWith(extension));
}

function isAcceptedType(file: File) {
  return (
    ATTACHMENT_ACCEPTED_MIME_TYPES.includes(file.type) || hasAcceptedExtension(file.name)
  );
}

export function validateAttachmentFiles(files: File[]) {
  const accepted: File[] = [];
  const errors: string[] = [];

  for (const file of files) {
    if (!isAcceptedType(file)) {
      errors.push(`${file.name}: supported formats are PDF, DOCX, PNG, JPG`);
      continue;
    }
    if (file.size > ATTACHMENT_MAX_SIZE) {
      errors.push(`${file.name}: file must be under 10MB`);
      continue;
    }
    accepted.push(file);
  }

  return {
    accepted,
    errorMessage: errors.length > 0 ? errors.join(" · ") : null,
  };
}
