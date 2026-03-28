"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  apiJson,
  apiFetch,
  downloadGeneratedDocument,
  regenerateGeneratedDocument,
} from "@/lib/api";
import {
  documentBundleDescription,
  documentBundleTitle,
  groupDocumentsByVariant,
} from "@/lib/document-groups";
import { useApp } from "@/components/AppContext";
import ConfirmDialog from "@/components/ConfirmDialog";

interface ProfileData {
  profile: { id: string; full_name: string | null; email: string };
  user_context: Array<{
    id: string;
    category: string;
    content: Record<string, unknown>;
    updated_at: string;
  }>;
  uploaded_files: Array<{
    id: string;
    filename: string;
    mime_type: string;
    file_size: number;
    download_url: string;
    created_at: string;
    conversation_id: string;
  }>;
  generated_documents: Array<{
    document_id: string;
    doc_type: string;
    filename?: string;
    file_url: string;
    download_url: string;
    created_at: string;
    job_id: string;
    theme_id?: string | null;
    variant_key?: string | null;
    variant_label?: string | null;
    variant_group_id?: string | null;
    can_regenerate?: boolean;
  }>;
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatContextContent(
  category: string,
  content: Record<string, unknown> | unknown[]
): React.ReactNode {
  // Skills: render as tags
  if (category === "skills" || category === "skill") {
    const values = Array.isArray(content) ? content : Object.values(content).flat();
    return (
      <div className="flex flex-wrap gap-1.5 mt-1">
        {values.map((v, i) => (
          <span
            key={i}
            className="px-2 py-0.5 bg-bg-tertiary text-text-secondary text-[11px] rounded-md"
          >
            {String(v)}
          </span>
        ))}
      </div>
    );
  }

  // Array of objects (work_experience, education): render each as a block
  if (Array.isArray(content)) {
    return (
      <div className="mt-1 space-y-2">
        {content.map((item, i) => {
          if (typeof item === "object" && item !== null) {
            return (
              <div key={i} className="text-xs text-text-secondary space-y-0.5">
                {Object.entries(item as Record<string, unknown>).map(([key, value]) => (
                  <div key={key}>
                    <span className="text-text-tertiary capitalize">
                      {key.replace(/_/g, " ")}:
                    </span>{" "}
                    {String(value)}
                  </div>
                ))}
              </div>
            );
          }
          return (
            <div key={i} className="text-xs text-text-secondary">
              {String(item)}
            </div>
          );
        })}
      </div>
    );
  }

  // Flat object (personal_info): render key-value pairs
  return (
    <div className="mt-1 space-y-1">
      {Object.entries(content).map(([key, value]) => (
        <div key={key} className="text-xs text-text-secondary">
          <span className="text-text-tertiary capitalize">
            {key.replace(/_/g, " ")}:
          </span>{" "}
          {String(value)}
        </div>
      ))}
    </div>
  );
}

export default function ProfilePage() {
  const { refreshConversations } = useApp();
  const router = useRouter();

  const [data, setData] = useState<ProfileData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Account editing
  const [editName, setEditName] = useState("");
  const [savingName, setSavingName] = useState(false);
  const [regeneratingDocumentId, setRegeneratingDocumentId] = useState<string | null>(null);

  // Context editing
  const [editingContextId, setEditingContextId] = useState<string | null>(null);
  const [editContextValue, setEditContextValue] = useState("");

  // Confirm dialog
  const [confirmState, setConfirmState] = useState<{
    open: boolean;
    title: string;
    message: string;
    onConfirm: () => void;
    loading: boolean;
  }>({
    open: false,
    title: "",
    message: "",
    onConfirm: () => {},
    loading: false,
  });

  const renderGeneratedDocumentRow = (
    doc: ProfileData["generated_documents"][number],
    compact = false
  ) => (
    <div
      key={doc.document_id}
      className={`flex items-center gap-3 rounded-lg border border-border px-4 py-3 ${
        compact ? "bg-bg-primary" : "bg-bg-secondary"
      }`}
    >
      <div className="w-8 h-8 rounded-lg bg-bg-tertiary flex items-center justify-center flex-shrink-0">
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          className="text-success"
        >
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <polyline points="14 2 14 8 20 8" />
          <line x1="16" y1="13" x2="8" y2="13" />
          <line x1="16" y1="17" x2="8" y2="17" />
        </svg>
      </div>
      <div className="flex-1 min-w-0">
        <p className="truncate text-sm text-text-primary">
          {doc.filename ||
            (doc.doc_type === "cover_letter" ? "Cover Letter" : "Resume")}
        </p>
        <p className="text-[11px] text-text-tertiary">
          {doc.doc_type === "cover_letter" ? "Cover Letter" : "Resume"}
          {doc.variant_label ? ` · ${doc.variant_label}` : ""}
          {" · "}
          {new Date(doc.created_at).toLocaleDateString(undefined, {
            month: "short",
            day: "numeric",
            year: "numeric",
          })}
        </p>
      </div>
      <div className="flex items-center gap-1 flex-shrink-0">
        <button
          type="button"
          onClick={() =>
            handleDownloadDocument(
              doc.document_id,
              doc.filename ||
                `${doc.doc_type === "cover_letter" ? "cover-letter" : "resume"}.docx`
            )
          }
          className="p-1.5 rounded hover:bg-bg-tertiary transition text-text-tertiary hover:text-accent"
          title="Download"
        >
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          >
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="7 10 12 15 17 10" />
            <line x1="12" y1="15" x2="12" y2="3" />
          </svg>
        </button>
        {doc.can_regenerate && (
          <button
            type="button"
            onClick={() => void handleRegenerateDocument(doc.document_id)}
            disabled={regeneratingDocumentId === doc.document_id}
            className="p-1.5 rounded hover:bg-bg-tertiary transition text-text-tertiary hover:text-accent disabled:cursor-wait disabled:opacity-70"
            title="Regenerate"
          >
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <path d="M21 12a9 9 0 1 1-2.64-6.36" />
              <polyline points="21 3 21 9 15 9" />
            </svg>
          </button>
        )}
        <button
          onClick={() => handleDeleteDocument(doc.document_id)}
          className="p-1.5 rounded hover:bg-danger/10 transition text-text-tertiary hover:text-danger"
          title="Delete"
        >
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          >
            <polyline points="3 6 5 6 21 6" />
            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
          </svg>
        </button>
      </div>
    </div>
  );

  const fetchProfile = useCallback(async () => {
    try {
      setError(null);
      const profile = await apiJson<ProfileData>("/profile");
      setData(profile);
      setEditName(profile.profile.full_name || "");
    } catch {
      setError("Failed to load profile");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchProfile();
  }, [fetchProfile]);

  const handleSaveName = async () => {
    setSavingName(true);
    try {
      await apiJson("/profile", {
        method: "PATCH",
        body: JSON.stringify({ full_name: editName }),
      });
      await fetchProfile();
    } catch {
      setError("Failed to save name");
    } finally {
      setSavingName(false);
    }
  };

  const handleUpdateContext = async (id: string) => {
    try {
      let parsed: Record<string, unknown>;
      try {
        parsed = JSON.parse(editContextValue);
      } catch {
        parsed = { content: editContextValue };
      }
      await apiJson(`/user-context/${id}`, {
        method: "PUT",
        body: JSON.stringify({ content: parsed }),
      });
      setEditingContextId(null);
      await fetchProfile();
    } catch {
      setError("Failed to update context");
    }
  };

  const handleDeleteContext = (id: string) => {
    setConfirmState({
      open: true,
      title: "Delete context",
      message:
        "This AI-learned context entry will be permanently deleted. This cannot be undone.",
      loading: false,
      onConfirm: async () => {
        setConfirmState((s) => ({ ...s, loading: true }));
        try {
          await apiFetch(`/user-context/${id}`, { method: "DELETE" });
          setConfirmState((s) => ({ ...s, open: false, loading: false }));
          await fetchProfile();
        } catch {
          setConfirmState((s) => ({ ...s, loading: false }));
          setError("Failed to delete context");
        }
      },
    });
  };

  const handleDeleteFile = (id: string, filename: string) => {
    setConfirmState({
      open: true,
      title: "Delete file",
      message: `"${filename}" will be permanently deleted. This cannot be undone.`,
      loading: false,
      onConfirm: async () => {
        setConfirmState((s) => ({ ...s, loading: true }));
        try {
          await apiFetch(`/conversation-files/${id}`, { method: "DELETE" });
          setConfirmState((s) => ({ ...s, open: false, loading: false }));
          await fetchProfile();
        } catch {
          setConfirmState((s) => ({ ...s, loading: false }));
          setError("Failed to delete file");
        }
      },
    });
  };

  const handleDeleteDocument = (id: string) => {
    setConfirmState({
      open: true,
      title: "Delete document",
      message:
        "This generated document will be permanently deleted. This cannot be undone.",
      loading: false,
      onConfirm: async () => {
        setConfirmState((s) => ({ ...s, loading: true }));
        try {
          await apiFetch(`/generated-documents/${id}`, { method: "DELETE" });
          setConfirmState((s) => ({ ...s, open: false, loading: false }));
          await fetchProfile();
        } catch {
          setConfirmState((s) => ({ ...s, loading: false }));
          setError("Failed to delete document");
        }
      },
    });
  };

  const handleDownloadDocument = async (id: string, filename: string) => {
    try {
      await downloadGeneratedDocument(id, filename);
    } catch {
      setError("Failed to download document");
    }
  };

  const handleRegenerateDocument = async (id: string) => {
    try {
      setRegeneratingDocumentId(id);
      await regenerateGeneratedDocument(id);
      await fetchProfile();
    } catch {
      setError("Failed to regenerate document");
    } finally {
      setRegeneratingDocumentId(null);
    }
  };

  const handleDeleteAllData = () => {
    setConfirmState({
      open: true,
      title: "Delete all data",
      message:
        "This will permanently delete your profile, all conversations, files, documents, and AI-learned context. This action cannot be undone.",
      loading: false,
      onConfirm: async () => {
        setConfirmState((s) => ({ ...s, loading: true }));
        try {
          await apiFetch("/profile/all-data", { method: "DELETE" });
          setConfirmState((s) => ({ ...s, open: false, loading: false }));
          await refreshConversations();
          router.push("/chat");
        } catch {
          setConfirmState((s) => ({ ...s, loading: false }));
          setError("Failed to delete data");
        }
      },
    });
  };

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="w-5 h-5 border-2 border-accent border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="text-center">
          <p className="text-sm text-text-secondary mb-2">{error}</p>
          <button
            onClick={() => {
              setLoading(true);
              fetchProfile();
            }}
            className="text-xs text-accent hover:underline"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (!data) return null;

  const { profile, user_context, uploaded_files, generated_documents } = data;
  const displayLetter = (profile.full_name || profile.email || "U")[0].toUpperCase();
  const generatedDocumentGroups = groupDocumentsByVariant(generated_documents);

  return (
    <div className="flex-1 overflow-y-auto px-6 py-6">
      <div className="max-w-2xl mx-auto">
        {/* Error banner */}
        {error && (
          <div className="mb-4 px-3 py-2 bg-danger/10 border border-danger/20 rounded-lg text-xs text-danger">
            {error}
            <button
              onClick={() => setError(null)}
              className="ml-2 underline"
            >
              Dismiss
            </button>
          </div>
        )}

        {/* ── Account Section ── */}
        <section className="py-6 border-b border-border">
          <h2 className="text-sm font-semibold text-text-primary mb-4">
            Account
          </h2>
          <div className="flex items-start gap-4">
            <div className="w-12 h-12 rounded-full bg-accent flex items-center justify-center text-lg font-semibold text-white flex-shrink-0">
              {displayLetter}
            </div>
            <div className="flex-1 min-w-0 space-y-3">
              <div>
                <label className="text-[11px] text-text-tertiary uppercase tracking-wider font-medium block mb-1">
                  Name
                </label>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={editName}
                    onChange={(e) => setEditName(e.target.value)}
                    placeholder="Your name"
                    className="flex-1 bg-bg-tertiary border border-border rounded-lg px-3 py-1.5 text-sm text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-accent/50 transition"
                  />
                  <button
                    onClick={handleSaveName}
                    disabled={
                      savingName || editName === (profile.full_name || "")
                    }
                    className="px-3 py-1.5 text-xs font-medium bg-accent text-white rounded-lg hover:bg-accent-hover transition disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {savingName ? "Saving..." : "Save"}
                  </button>
                </div>
              </div>
              <div>
                <label className="text-[11px] text-text-tertiary uppercase tracking-wider font-medium block mb-1">
                  Email
                </label>
                <p className="text-sm text-text-secondary">{profile.email}</p>
              </div>
            </div>
          </div>
        </section>

        {/* ── AI-Learned Context Section ── */}
        <section className="py-6 border-b border-border">
          <h2 className="text-sm font-semibold text-text-primary mb-4">
            AI-Learned Context
          </h2>
          {user_context.length === 0 ? (
            <p className="text-xs text-text-tertiary">
              No AI-learned context yet. Start a conversation and the AI will
              learn about your background.
            </p>
          ) : (
            <div className="space-y-3">
              {user_context.map((ctx) => (
                <div
                  key={ctx.id}
                  className="bg-bg-secondary border border-border rounded-lg p-4"
                >
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-[11px] font-semibold uppercase tracking-wider text-accent">
                      {ctx.category}
                    </span>
                    <div className="flex items-center gap-1">
                      <button
                        onClick={() => {
                          if (editingContextId === ctx.id) {
                            setEditingContextId(null);
                          } else {
                            setEditingContextId(ctx.id);
                            setEditContextValue(
                              JSON.stringify(ctx.content, null, 2)
                            );
                          }
                        }}
                        className="p-1 rounded hover:bg-bg-tertiary transition text-text-tertiary hover:text-text-primary"
                        title="Edit"
                      >
                        <svg
                          width="13"
                          height="13"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="2"
                        >
                          <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                          <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
                        </svg>
                      </button>
                      <button
                        onClick={() => handleDeleteContext(ctx.id)}
                        className="p-1 rounded hover:bg-danger/10 transition text-text-tertiary hover:text-danger"
                        title="Delete"
                      >
                        <svg
                          width="13"
                          height="13"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="2"
                        >
                          <polyline points="3 6 5 6 21 6" />
                          <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                        </svg>
                      </button>
                    </div>
                  </div>

                  {editingContextId === ctx.id ? (
                    <div className="space-y-2">
                      <textarea
                        value={editContextValue}
                        onChange={(e) => setEditContextValue(e.target.value)}
                        rows={6}
                        className="w-full bg-bg-tertiary border border-border rounded-lg px-3 py-2 text-xs text-text-primary font-mono focus:outline-none focus:border-accent/50 transition resize-y"
                      />
                      <div className="flex justify-end gap-2">
                        <button
                          onClick={() => setEditingContextId(null)}
                          className="px-3 py-1 text-xs rounded-lg bg-bg-tertiary text-text-secondary hover:text-text-primary transition"
                        >
                          Cancel
                        </button>
                        <button
                          onClick={() => handleUpdateContext(ctx.id)}
                          className="px-3 py-1 text-xs font-medium bg-accent text-white rounded-lg hover:bg-accent-hover transition"
                        >
                          Save
                        </button>
                      </div>
                    </div>
                  ) : (
                    formatContextContent(ctx.category, ctx.content)
                  )}

                  <p className="text-[10px] text-text-tertiary mt-2">
                    Updated{" "}
                    {new Date(ctx.updated_at).toLocaleDateString(undefined, {
                      month: "short",
                      day: "numeric",
                      year: "numeric",
                    })}
                  </p>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* ── Uploaded Files Section ── */}
        <section className="py-6 border-b border-border">
          <h2 className="text-sm font-semibold text-text-primary mb-4">
            Uploaded Files
          </h2>
          {uploaded_files.length === 0 ? (
            <p className="text-xs text-text-tertiary">
              No uploaded files yet. Upload a resume or other documents in a
              conversation.
            </p>
          ) : (
            <div className="space-y-2">
              {uploaded_files.map((file) => (
                <div
                  key={file.id}
                  className="flex items-center gap-3 bg-bg-secondary border border-border rounded-lg px-4 py-3"
                >
                  {/* File icon */}
                  <div className="w-8 h-8 rounded-lg bg-bg-tertiary flex items-center justify-center flex-shrink-0">
                    <svg
                      width="16"
                      height="16"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.5"
                      className="text-text-tertiary"
                    >
                      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                      <polyline points="14 2 14 8 20 8" />
                    </svg>
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-text-primary truncate">
                      {file.filename}
                    </p>
                    <p className="text-[11px] text-text-tertiary">
                      {formatFileSize(file.file_size)} &middot;{" "}
                      {new Date(file.created_at).toLocaleDateString(undefined, {
                        month: "short",
                        day: "numeric",
                        year: "numeric",
                      })}
                    </p>
                  </div>
                  <div className="flex items-center gap-1 flex-shrink-0">
                    <a
                      href={file.download_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="p-1.5 rounded hover:bg-bg-tertiary transition text-text-tertiary hover:text-accent"
                      title="Download"
                    >
                      <svg
                        width="14"
                        height="14"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                      >
                        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                        <polyline points="7 10 12 15 17 10" />
                        <line x1="12" y1="15" x2="12" y2="3" />
                      </svg>
                    </a>
                    <button
                      onClick={() =>
                        handleDeleteFile(file.id, file.filename)
                      }
                      className="p-1.5 rounded hover:bg-danger/10 transition text-text-tertiary hover:text-danger"
                      title="Delete"
                    >
                      <svg
                        width="14"
                        height="14"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                      >
                        <polyline points="3 6 5 6 21 6" />
                        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                      </svg>
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* ── Generated Documents Section ── */}
        <section className="py-6 border-b border-border">
          <h2 className="text-sm font-semibold text-text-primary mb-4">
            Generated Documents
          </h2>
          {generated_documents.length === 0 ? (
            <p className="text-xs text-text-tertiary">
              No generated documents yet. Complete a conversation to generate
              your first resume or cover letter.
            </p>
          ) : (
            <div className="space-y-2">
              {generatedDocumentGroups.map((group) => {
                if (!group.isVariantBundle) {
                  return renderGeneratedDocumentRow(group.items[0]);
                }

                return (
                  <div
                    key={group.key}
                    className="rounded-lg border border-border bg-bg-secondary/60 p-3"
                  >
                    <p className="text-sm font-medium text-text-primary">
                      {documentBundleTitle(group.docType)}
                    </p>
                    <p className="mt-1 text-[11px] text-text-tertiary">
                      {documentBundleDescription(group.docType)}
                    </p>
                    <div className="mt-3 space-y-2">
                      {group.items.map((doc) =>
                        renderGeneratedDocumentRow(doc, true)
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>

        {/* ── Danger Zone ── */}
        <section className="py-6">
          <h2 className="text-sm font-semibold text-danger mb-2">
            Danger Zone
          </h2>
          <div className="border border-danger/30 rounded-lg p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-text-primary font-medium">
                  Delete All Data
                </p>
                <p className="text-xs text-text-tertiary mt-0.5">
                  Permanently delete your profile, conversations, files, and all
                  AI-learned context.
                </p>
              </div>
              <button
                onClick={handleDeleteAllData}
                className="px-3.5 py-1.5 text-xs font-medium text-danger border border-danger/30 rounded-lg hover:bg-danger/10 transition flex-shrink-0 ml-4"
              >
                Delete All Data
              </button>
            </div>
          </div>
        </section>
      </div>

      <ConfirmDialog
        open={confirmState.open}
        title={confirmState.title}
        message={confirmState.message}
        onConfirm={confirmState.onConfirm}
        onCancel={() => setConfirmState((s) => ({ ...s, open: false }))}
        loading={confirmState.loading}
      />
    </div>
  );
}
