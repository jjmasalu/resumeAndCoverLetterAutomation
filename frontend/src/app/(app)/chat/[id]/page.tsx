"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import {
  apiJson,
  apiUpload,
  handleTeamAccessRedirect,
  regenerateGeneratedDocument,
  toApiError,
} from "@/lib/api";
import {
  clearPendingChatMessage,
  readPendingChatMessage,
  type PendingChatMessage,
} from "@/lib/pending-chat";
import {
  documentBundleDescription,
  documentBundleTitle,
  groupDocumentsByVariant,
} from "@/lib/document-groups";
import { useApp } from "@/components/AppContext";
import { createClient } from "@/lib/supabase/client";
import ChatMessage from "@/components/ChatMessage";
import ActivityTimeline, { type ActivityStep } from "@/components/ActivityTimeline";
import DownloadCard from "@/components/DownloadCard";
import JobCard from "@/components/JobCard";
import AttachmentComposer from "@/components/AttachmentComposer";
import { MODE_COPY } from "@/lib/conversation-modes";
import {
  ATTACHMENT_ACCEPTED_EXTENSIONS_ATTR,
  validateAttachmentFiles,
} from "@/lib/attachment-validation";
import { useFileDropzone } from "@/lib/use-file-dropzone";

interface Message {
  role: "user" | "assistant";
  content: string;
  metadata?: {
    activity_trace?: ActivityStep[];
  };
}

interface DocumentEvent {
  document_id: string;
  doc_type: string;
  filename?: string;
  download_url: string;
  theme_id?: string | null;
  variant_key?: string | null;
  variant_label?: string | null;
  variant_group_id?: string | null;
  can_regenerate?: boolean;
  page_budget?: number;
  document_plan?: {
    repair_history?: Array<{ action?: string }>;
    verification?: { status?: string };
  };
}

interface JobResultEvent {
  title: string;
  url: string;
  snippet: string;
  match_score: number;
  company?: string;
  location?: string;
}

interface UploadResponse {
  file_id: string;
}

const HIDDEN_ACTIVITY_PHASES = new Set(["understanding_request"]);

function normalizeActivityStep(raw: unknown): ActivityStep | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const step = raw as Record<string, unknown>;
  const phase = String(step.phase || step.tool || "activity");
  if (HIDDEN_ACTIVITY_PHASES.has(phase)) {
    return null;
  }
  const state =
    step.state === "done" || step.state === "failed" ? step.state : "running";

  return {
    id: String(step.id || step.phase || step.tool || crypto.randomUUID()),
    phase,
    label: String(step.label || step.tool || "Working"),
    state,
    tool: typeof step.tool === "string" ? step.tool : undefined,
    detail: typeof step.detail === "string" ? step.detail : undefined,
    meta:
      step.meta && typeof step.meta === "object" && !Array.isArray(step.meta)
        ? (step.meta as Record<string, unknown>)
        : undefined,
  };
}

function normalizeMessage(raw: unknown): Message | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const message = raw as Record<string, unknown>;
  if (message.role !== "user" && message.role !== "assistant") return null;

  const activityTrace = Array.isArray((message.metadata as Record<string, unknown> | undefined)?.activity_trace)
    ? ((message.metadata as Record<string, unknown>).activity_trace as unknown[])
        .map(normalizeActivityStep)
        .filter((step): step is ActivityStep => Boolean(step))
    : undefined;

  return {
    role: message.role,
    content: typeof message.content === "string" ? message.content : "",
    metadata: activityTrace ? { activity_trace: activityTrace } : undefined,
  };
}

export default function ChatPage() {
  const { id } = useParams<{ id: string }>();
  const { conversations, setActiveConversation, activeConversation } = useApp();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [activitySteps, setActivitySteps] = useState<ActivityStep[]>([]);
  const [documents, setDocuments] = useState<DocumentEvent[]>([]);
  const [jobResults, setJobResults] = useState<JobResultEvent[]>([]);
  const [regeneratingDocumentId, setRegeneratingDocumentId] = useState<string | null>(null);
  const [pendingInitialMessage, setPendingInitialMessage] = useState<PendingChatMessage | null>(null);
  const [initialMessageChecked, setInitialMessageChecked] = useState(false);
  const [loadingMessages, setLoadingMessages] = useState(true);
  const [attachError, setAttachError] = useState<string | null>(null);
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [uploadingAttachments, setUploadingAttachments] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const initialSent = useRef(false);
  const streamingRef = useRef(false);
  const activityStepsRef = useRef<ActivityStep[]>([]);
  const skipNextHistoryLoadRef = useRef(false);
  const pendingAutoSendTimeoutRef = useRef<number | null>(null);

  const stageFiles = useCallback((files: File[]) => {
    const { accepted, errorMessage } = validateAttachmentFiles(files);
    if (errorMessage) {
      setAttachError(errorMessage);
    }
    if (accepted.length === 0) {
      return;
    }
    setPendingFiles((prev) => [...prev, ...accepted]);
    setAttachError(null);
  }, []);

  const { isDragOver, dropzoneProps } = useFileDropzone(stageFiles);

  useEffect(() => {
    activityStepsRef.current = activitySteps;
  }, [activitySteps]);

  useEffect(() => {
    return () => {
      if (pendingAutoSendTimeoutRef.current !== null) {
        window.clearTimeout(pendingAutoSendTimeoutRef.current);
      }
    };
  }, []);

  useEffect(() => {
    const pendingMessage = readPendingChatMessage(id);
    setPendingInitialMessage(pendingMessage);
    setInitialMessageChecked(true);
  }, [id]);

  // Set active conversation in context
  useEffect(() => {
    const conv = conversations.find((c) => c.id === id);
    if (conv) setActiveConversation(conv);
    return () => setActiveConversation(null);
  }, [id, conversations, setActiveConversation]);

  // Load existing messages and documents (skip if auto-sending initial message)
  useEffect(() => {
    if (!initialMessageChecked) {
      return;
    }
    if (skipNextHistoryLoadRef.current) {
      skipNextHistoryLoadRef.current = false;
      setLoadingMessages(false);
      return;
    }
    if (pendingInitialMessage) {
      // Brand-new conversation via redirect — no messages to fetch
      setLoadingMessages(false);
      return;
    }
    setLoadingMessages(true);
    apiJson<{ messages: unknown[]; documents?: DocumentEvent[] }>(`/conversations/${id}`)
      .then((data) => {
        setMessages(
          (data.messages || [])
            .map(normalizeMessage)
            .filter((message): message is Message => Boolean(message))
        );
        setDocuments(data.documents || []);
      })
      .catch(console.error)
      .finally(() => setLoadingMessages(false));
  }, [id, initialMessageChecked, pendingInitialMessage]);

  // Core send logic — accepts message directly, no dependency on input state
  const doSend = useCallback(async (userMsg: string, attachmentFileIds: string[] = []) => {
    if (streamingRef.current) return;

    setMessages((prev) => [...prev, { role: "user", content: userMsg }]);
    setStreaming(true);
    streamingRef.current = true;
    setActivitySteps([]);
    setJobResults([]);

    try {
      const supabase = createClient();
      const {
        data: { session },
      } = await supabase.auth.getSession();

      if (!session?.access_token) {
        setMessages((prev) => [
          ...prev,
          { role: "assistant", content: "Error: Not authenticated — please sign in again." },
        ]);
        return;
      }

      const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
      const response = await fetch(
        `${API_URL}/conversations/${id}/messages`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${session.access_token}`,
          },
          body: JSON.stringify({
            content: userMsg,
            attachment_file_ids: attachmentFileIds,
          }),
        }
      );

      if (!response.ok) {
        const error = await toApiError(response);
        handleTeamAccessRedirect(error, `/chat/${id}`);
        throw error;
      }

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      let assistantContent = "";
      let buffer = "";

      const consumeSseBuffer = (flushTrailing = false) => {
        buffer = buffer.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
        const rawEvents = buffer.split("\n\n");
        buffer = flushTrailing ? "" : rawEvents.pop() || "";

        for (const rawEvent of rawEvents) {
          const lines = rawEvent.split("\n");
          let eventType = "message";
          const dataLines: string[] = [];

          for (const line of lines) {
            if (line.startsWith("event: ")) {
              eventType = line.slice(7).trim();
            } else if (line.startsWith("data: ")) {
              dataLines.push(line.slice(6));
            }
          }

          if (dataLines.length === 0) {
            continue;
          }

          try {
            const data = JSON.parse(dataLines.join("\n"));
            handleSseEvent(eventType, data);
          } catch {
            // Skip malformed JSON
          }
        }
      };

      const handleSseEvent = (eventType: string, data: unknown) => {
        if (eventType === "message") {
          const chunk =
            typeof (data as { content?: unknown } | null)?.content === "string"
              ? (data as { content: string }).content
              : "";
          if (!chunk) return;
          assistantContent += chunk;
          setMessages((prev) => {
            const updated = [...prev];
            const lastIdx = updated.length - 1;
            if (lastIdx >= 0 && updated[lastIdx].role === "assistant") {
              updated[lastIdx] = {
                ...updated[lastIdx],
                content: assistantContent,
              };
            } else {
              updated.push({ role: "assistant", content: assistantContent });
            }
            return updated;
          });
        } else if (eventType === "status") {
          const nextStep = normalizeActivityStep(data);
          if (!nextStep) return;
          setActivitySteps((prev) => {
            const existing = prev.findIndex((s) => s.id === nextStep.id);
            if (existing >= 0) {
              const updated = [...prev];
              updated[existing] = nextStep;
              return updated;
            }
            return [...prev, nextStep];
          });
        } else if (eventType === "document") {
          setDocuments((prev) => [...prev, data as DocumentEvent]);
        } else if (eventType === "job_result") {
          setJobResults((prev) => [...prev, data as JobResultEvent]);
        } else if (eventType === "error") {
          const message =
            typeof (data as { message?: unknown } | null)?.message === "string"
              ? (data as { message: string }).message
              : "Unknown error";
          setMessages((prev) => [
            ...prev,
            { role: "assistant", content: `Error: ${message}` },
          ]);
        }
      };

      if (reader) {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          consumeSseBuffer();
        }
        buffer += decoder.decode();
      } else {
        buffer += await response.text();
      }

      consumeSseBuffer(true);
    } catch (err) {
      console.error("Stream error:", err);
    } finally {
      const finalTrace = activityStepsRef.current;
      if (finalTrace.length > 0) {
        setMessages((prev) => {
          const updated = [...prev];
          const lastAssistantIndex = [...updated]
            .map((message, index) => ({ message, index }))
            .reverse()
            .find(({ message }) => message.role === "assistant")?.index;

          if (lastAssistantIndex === undefined) return updated;

          updated[lastAssistantIndex] = {
            ...updated[lastAssistantIndex],
            metadata: {
              ...updated[lastAssistantIndex].metadata,
              activity_trace: finalTrace,
            },
          };
          return updated;
        });
      }
      setStreaming(false);
      streamingRef.current = false;
      setActivitySteps([]);
    }
  }, [id]);

  const handleAttachment = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    if (files.length === 0) return;
    stageFiles(files);
    e.target.value = "";
  };

  // Auto-send initial message from landing page / new chat
  useEffect(() => {
    if (
      pendingInitialMessage &&
      !initialSent.current &&
      !loadingMessages
    ) {
      initialSent.current = true;
      skipNextHistoryLoadRef.current = true;
      const messageToSend = pendingInitialMessage;
      clearPendingChatMessage(id);
      setPendingInitialMessage(null);
      pendingAutoSendTimeoutRef.current = window.setTimeout(() => {
        pendingAutoSendTimeoutRef.current = null;
        void doSend(messageToSend.content, messageToSend.attachmentFileIds ?? []);
      }, 50);
    }
  }, [pendingInitialMessage, loadingMessages, id, doSend]);

  const isAwaitingInitialMessage =
    pendingInitialMessage && !initialSent.current && messages.length === 0;
  const showCenteredLoader = loadingMessages && messages.length === 0 && !isAwaitingInitialMessage;
  const showEmptyState = !loadingMessages && messages.length === 0 && !isAwaitingInitialMessage;
  const showTypingIndicator = streaming;
  const documentGroups = groupDocumentsByVariant(documents);

  // Auto-scroll
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, activitySteps, documents, jobResults]);

  // Auto-resize textarea
  const adjustTextarea = useCallback(() => {
    const el = textareaRef.current;
    if (el) {
      el.style.height = "auto";
      el.style.height = Math.min(el.scrollHeight, 160) + "px";
    }
  }, []);

  useEffect(() => {
    adjustTextarea();
  }, [input, adjustTextarea]);

  const removePendingFile = (index: number) => {
    setPendingFiles((prev) => prev.filter((_, currentIndex) => currentIndex !== index));
  };

  const uploadPendingFiles = useCallback(async () => {
    if (pendingFiles.length === 0) return [];
    setUploadingAttachments(true);
    try {
      const uploads = await Promise.all(
        pendingFiles.map((file) =>
          apiUpload<UploadResponse>(`/conversations/${id}/upload`, file)
        )
      );
      setPendingFiles([]);
      return uploads.map((upload) => upload.file_id);
    } finally {
      setUploadingAttachments(false);
    }
  }, [id, pendingFiles]);

  const sendMessage = async () => {
    if (streaming || uploadingAttachments) return;
    const trimmedInput = input.trim();
    if (!trimmedInput && pendingFiles.length === 0) return;

    const fallbackMessage =
      activeConversation?.mode === "find_jobs"
        ? `I've attached ${pendingFiles.map((file) => file.name).join(", ")}. Please review ${pendingFiles.length > 1 ? "them" : "it"} for my job search.`
        : `I've attached ${pendingFiles.map((file) => file.name).join(", ")}. Please use ${pendingFiles.length > 1 ? "them" : "it"} to tailor my application materials.`;

    const userMsg = trimmedInput || fallbackMessage;
    setInput("");
    setAttachError(null);

    try {
      const attachmentFileIds = await uploadPendingFiles();
      await doSend(userMsg, attachmentFileIds);
    } catch (err) {
      console.error("Upload failed:", err);
      setAttachError(err instanceof Error ? err.message : "Upload failed — please try again.");
      setInput((prev) => prev || trimmedInput);
    }
  };

  const handleRegenerateDocument = async (documentId: string) => {
    if (regeneratingDocumentId) return;
    try {
      setRegeneratingDocumentId(documentId);
      const result = await regenerateGeneratedDocument(documentId);
      setDocuments((prev) =>
        prev.map((document) =>
          document.document_id === result.replaced_document_id
            ? { ...document, ...result.document }
            : document
        )
      );
    } catch (error) {
      console.error("Failed to regenerate document:", error);
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content:
            error instanceof Error
              ? `I couldn't regenerate that document: ${error.message}`
              : "I couldn't regenerate that document right now.",
        },
      ]);
    } finally {
      setRegeneratingDocumentId(null);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void sendMessage();
    }
  };

  const isComposerBusy = streaming || uploadingAttachments;

  return (
    <div className="flex flex-col h-full">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-5 py-6">
        {showCenteredLoader && (
          <div className="flex items-center justify-center h-full">
            <div className="w-5 h-5 border-2 border-accent border-t-transparent rounded-full animate-spin" />
          </div>
        )}
        {showEmptyState && (
          <div className="flex flex-col items-center justify-center h-full">
            <div className="w-12 h-12 rounded-xl bg-bg-secondary border border-border flex items-center justify-center mb-4">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-accent">
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
              </svg>
            </div>
            <p className="text-sm font-medium text-text-primary mb-1">Start a conversation</p>
            <p className="text-xs text-text-tertiary text-center max-w-xs">
              {activeConversation?.mode === "find_jobs"
                ? MODE_COPY.find_jobs.emptyStateHint
                : MODE_COPY.job_to_resume.emptyStateHint}
            </p>
          </div>
        )}
        <div className="max-w-3xl mx-auto">
          {messages.map((msg, i) => {
            const persistedTrace = msg.metadata?.activity_trace || [];
            const isStreamingAssistantMessage =
              streaming && i === messages.length - 1 && msg.role === "assistant";
            const showTrace = !isStreamingAssistantMessage && persistedTrace.length > 0;

            return (
              <div key={i}>
                <ChatMessage role={msg.role} content={msg.content} />
                {msg.role === "assistant" && showTrace && (
                  <ActivityTimeline
                    steps={persistedTrace}
                    defaultExpanded={false}
                  />
                )}
              </div>
            );
          })}
          {showTypingIndicator && (
            <div className="mb-3 ml-9">
              <div className="inline-flex items-center gap-1.5 rounded-2xl border border-border bg-bg-secondary px-3 py-2 text-text-tertiary">
                <span className="h-2 w-2 animate-bounce rounded-full bg-current [animation-delay:-0.2s]" />
                <span className="h-2 w-2 animate-bounce rounded-full bg-current [animation-delay:-0.1s]" />
                <span className="h-2 w-2 animate-bounce rounded-full bg-current" />
              </div>
            </div>
          )}
          {streaming && activitySteps.length > 0 && (
            <ActivityTimeline steps={activitySteps} defaultExpanded />
          )}
          {jobResults.map((j, i) => (
            <JobCard
              key={`job-${i}`}
              title={j.title}
              url={j.url}
              snippet={j.snippet}
              matchScore={j.match_score}
              company={j.company}
              location={j.location}
              onAction={(msg) => {
                setInput("");
                doSend(msg);
              }}
            />
          ))}
          {documentGroups.map((group) => {
            if (!group.isVariantBundle) {
              const d = group.items[0];
              return (
                <DownloadCard
                  key={d.document_id}
                  docType={d.doc_type}
                  documentId={d.document_id}
                  filename={d.filename || `${d.doc_type === "cover_letter" ? "cover-letter" : "resume"}.docx`}
                  variantLabel={d.variant_label}
                  canRegenerate={Boolean(d.can_regenerate)}
                  regenerating={regeneratingDocumentId === d.document_id}
                  onRegenerate={() => handleRegenerateDocument(d.document_id)}
                />
              );
            }

            return (
              <div
                key={group.key}
                className="ml-9 mb-4 rounded-lg border border-border bg-bg-secondary/60 p-3"
              >
                <p className="text-sm font-medium text-text-primary">
                  {documentBundleTitle(group.docType)}
                </p>
                <p className="mt-1 text-[11px] text-text-tertiary">
                  {documentBundleDescription(group.docType)}
                </p>
                <div className="mt-3 space-y-3">
                  {group.items.map((d) => (
                    <DownloadCard
                      key={d.document_id}
                      docType={d.doc_type}
                      documentId={d.document_id}
                      filename={d.filename || `${d.doc_type === "cover_letter" ? "cover-letter" : "resume"}.docx`}
                      variantLabel={d.variant_label}
                      embedded
                      canRegenerate={Boolean(d.can_regenerate)}
                      regenerating={regeneratingDocumentId === d.document_id}
                      onRegenerate={() => handleRegenerateDocument(d.document_id)}
                    />
                  ))}
                </div>
              </div>
            );
          })}
          <div ref={bottomRef} />
        </div>
      </div>

      {/* Input */}
      <div className="border-t border-border px-5 py-3">
        <div className="max-w-3xl mx-auto">
          <AttachmentComposer
            files={pendingFiles}
            uploading={uploadingAttachments}
            onRemove={removePendingFile}
            disabled={isComposerBusy}
          />
          <div
            {...dropzoneProps}
            className={`flex items-center gap-2 bg-bg-secondary border border-border rounded-xl px-3.5 py-2.5 transition ${
              isComposerBusy ? "opacity-50" : ""
            } ${
              !isComposerBusy && isDragOver
                ? "border-accent bg-accent-muted/40 ring-1 ring-accent/30"
                : ""
            }`}
          >
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept={ATTACHMENT_ACCEPTED_EXTENSIONS_ATTR}
              onChange={handleAttachment}
              className="hidden"
            />
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={isComposerBusy}
              className="w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0 bg-accent-muted text-accent hover:bg-accent/20 transition"
              aria-label="Attach file"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
              </svg>
            </button>
            {attachError && (
              <span className="text-xs text-red-500">{attachError}</span>
            )}
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={
                activeConversation?.mode === "find_jobs"
                  ? "Describe target roles, refine your search, or upload another file..."
                  : "Paste a job URL, company + role, or ask to tailor your documents..."
              }
              rows={1}
              disabled={isComposerBusy}
              className="flex-1 bg-transparent text-sm text-text-primary placeholder:text-text-tertiary resize-none outline-none max-h-40"
            />
            <button
              onClick={() => void sendMessage()}
              disabled={isComposerBusy || (!input.trim() && pendingFiles.length === 0)}
              className={`w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0 transition ${
                (input.trim() || pendingFiles.length > 0) && !isComposerBusy
                  ? "bg-accent text-white"
                  : "bg-bg-tertiary text-text-tertiary"
              }`}
              aria-label="Send message"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z" />
              </svg>
            </button>
          </div>
          <div className="flex justify-between mt-1.5 text-[10px] text-text-tertiary px-1">
            <span>
              {isDragOver
                ? "Drop files here to stage them"
                : pendingFiles.length > 0 && !uploadingAttachments
                ? "Attachments stay local until you send"
                : uploadingAttachments
                  ? "Uploading attachments with this message..."
                  : "Enter to send · Shift+Enter for newline"}
            </span>
            <span>Powered by Gemini</span>
          </div>
        </div>
      </div>
    </div>
  );
}
