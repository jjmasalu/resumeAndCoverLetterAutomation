"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import {
  apiJson,
  apiUpload,
  handleTeamAccessRedirect,
  toApiError,
} from "@/lib/api";
import {
  clearPendingChatMessage,
  readPendingChatMessage,
} from "@/lib/pending-chat";
import { useApp } from "@/components/AppContext";
import { createClient } from "@/lib/supabase/client";
import ChatMessage from "@/components/ChatMessage";
import ActivityTimeline, { type ActivityStep } from "@/components/ActivityTimeline";
import DownloadCard from "@/components/DownloadCard";
import JobCard from "@/components/JobCard";

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
  theme_id?: string;
  variant_key?: string | null;
  variant_label?: string | null;
  variant_group_id?: string | null;
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
  const [pendingInitialMessage, setPendingInitialMessage] = useState<string | null>(null);
  const [initialMessageChecked, setInitialMessageChecked] = useState(false);
  const [loadingMessages, setLoadingMessages] = useState(true);
  const [attachError, setAttachError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const initialSent = useRef(false);
  const streamingRef = useRef(false);
  const activityStepsRef = useRef<ActivityStep[]>([]);
  const skipNextHistoryLoadRef = useRef(false);

  useEffect(() => {
    activityStepsRef.current = activitySteps;
  }, [activitySteps]);

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

  const conversationReadyForSend =
    activeConversation?.id === id || conversations.some((conversation) => conversation.id === id);

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

  const handleAttachment = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setAttachError(null);
    try {
      const upload = await apiUpload<UploadResponse>(`/conversations/${id}/upload`, file);
      await doSend(
        `I've uploaded an additional document: ${file.name}. Please review it.`,
        [upload.file_id]
      );
    } catch (err) {
      console.error("Upload failed:", err);
      setAttachError(err instanceof Error ? err.message : "Upload failed — please try again.");
    }
    // Reset input so same file can be re-selected
    e.target.value = "";
  };

  // Auto-send initial message from landing page / new chat
  useEffect(() => {
    if (
      pendingInitialMessage &&
      conversationReadyForSend &&
      !initialSent.current &&
      !loadingMessages
    ) {
      initialSent.current = true;
      skipNextHistoryLoadRef.current = true;
      clearPendingChatMessage(id);
      setPendingInitialMessage(null);
      doSend(pendingInitialMessage);
    }
  }, [pendingInitialMessage, conversationReadyForSend, loadingMessages, id, doSend]);

  const isAwaitingInitialMessage =
    pendingInitialMessage && !initialSent.current && messages.length === 0;
  const showCenteredLoader = loadingMessages && messages.length === 0 && !isAwaitingInitialMessage;
  const showEmptyState = !loadingMessages && messages.length === 0 && !isAwaitingInitialMessage;
  const hasStreamingAssistant = streaming && messages[messages.length - 1]?.role === "assistant";
  const showTypingIndicator = streaming;

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

  const sendMessage = () => {
    if (!input.trim() || streaming) return;
    const userMsg = input.trim();
    setInput("");
    doSend(userMsg);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

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
              Describe the job you want to apply for, or paste a job URL.
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
          {documents.map((d) => (
            <DownloadCard
              key={d.document_id}
              docType={d.doc_type}
              documentId={d.document_id}
              filename={d.filename || `${d.doc_type === "cover_letter" ? "cover-letter" : "resume"}.docx`}
              variantLabel={d.variant_label}
            />
          ))}
          <div ref={bottomRef} />
        </div>
      </div>

      {/* Input */}
      <div className="border-t border-border px-5 py-3">
        <div className="max-w-3xl mx-auto">
          <div
            className={`flex items-center gap-2 bg-bg-secondary border border-border rounded-xl px-3.5 py-2.5 transition ${
              streaming ? "opacity-50" : ""
            }`}
          >
            {activeConversation?.mode === "find_jobs" && (
              <>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".pdf,.docx,.png,.jpg,.jpeg"
                  onChange={handleAttachment}
                  className="hidden"
                />
                <button
                  onClick={() => fileInputRef.current?.click()}
                  disabled={streaming}
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
              </>
            )}
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Message Resume AI..."
              rows={1}
              disabled={streaming}
              className="flex-1 bg-transparent text-sm text-text-primary placeholder:text-text-tertiary resize-none outline-none max-h-40"
            />
            <button
              onClick={sendMessage}
              disabled={streaming || !input.trim()}
              className={`w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0 transition ${
                input.trim() && !streaming
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
            <span>Enter to send · Shift+Enter for newline</span>
            <span>Powered by Gemini</span>
          </div>
        </div>
      </div>
    </div>
  );
}
