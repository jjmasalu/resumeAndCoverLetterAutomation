"use client";

const pendingFiles = new Map<string, File[]>();

export function stashPendingFiles(files: File[]) {
  const token = crypto.randomUUID();
  pendingFiles.set(token, files);
  return token;
}

export function takePendingFiles(token: string) {
  const files = pendingFiles.get(token) || [];
  pendingFiles.delete(token);
  return files;
}
