"use client";

import { useEffect, useRef, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { apiJson } from "@/lib/api";
import { createClient } from "@/lib/supabase/client";
import ChatMessage from "@/components/ChatMessage";
import StatusPill from "@/components/StatusPill";
import DownloadCard from "@/components/DownloadCard";

interface Message {
  role: "user" | "assistant";
  content: string;
}

interface StatusEvent {
  tool: string;
  state: "running" | "done";
}

interface DocumentEvent {
  document_id: string;
  doc_type: string;
  download_url: string;
}

export default function ChatPage() {
  const { id } = useParams<{ id: string }>();
  const searchParams = useSearchParams();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [statuses, setStatuses] = useState<StatusEvent[]>([]);
  const [documents, setDocuments] = useState<DocumentEvent[]>([]);
  const bottomRef = useRef<HTMLDivElement>(null);
  const initialSent = useRef(false);

  // Load existing messages and documents
  useEffect(() => {
    apiJson<{ messages: Message[]; documents?: DocumentEvent[] }>(`/conversations/${id}`)
      .then((data) => {
        setMessages(data.messages || []);
        setDocuments(data.documents || []);
      })
      .catch(console.error);
  }, [id]);

  // Auto-send initial message from landing page
  useEffect(() => {
    const initial = searchParams.get("initial");
    if (initial && !initialSent.current) {
      initialSent.current = true;
      setInput(initial);
    }
  }, [searchParams]);

  // Auto-scroll
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, statuses]);

  const sendMessage = async () => {
    if (!input.trim() || streaming) return;

    const userMsg = input.trim();
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: userMsg }]);
    setStreaming(true);
    setStatuses([]);

    try {
      const supabase = createClient();
      const {
        data: { session },
      } = await supabase.auth.getSession();

      if (!session?.access_token) {
        console.error("[chat] No session for SSE request");
        setMessages((prev) => [
          ...prev,
          { role: "assistant", content: "Error: Not authenticated — please sign in again." },
        ]);
        setStreaming(false);
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
          body: JSON.stringify({ content: userMsg }),
        }
      );

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      let assistantContent = "";
      let buffer = "";

      if (reader) {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";

          let eventType = "message";
          for (const line of lines) {
            if (line.startsWith("event: ")) {
              eventType = line.slice(7).trim();
            } else if (line.startsWith("data: ")) {
              try {
                const data = JSON.parse(line.slice(6));

                if (eventType === "message") {
                  assistantContent += data.content;
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
                  setStatuses((prev) => {
                    const existing = prev.findIndex((s) => s.tool === data.tool);
                    if (existing >= 0) {
                      const updated = [...prev];
                      updated[existing] = data;
                      return updated;
                    }
                    return [...prev, data];
                  });
                } else if (eventType === "document") {
                  setDocuments((prev) => [...prev, data]);
                } else if (eventType === "error") {
                  setMessages((prev) => [
                    ...prev,
                    { role: "assistant", content: `Error: ${data.message}` },
                  ]);
                }
              } catch {
                // Skip malformed JSON
              }
            }
          }
        }
      }
    } catch (err) {
      console.error("Stream error:", err);
    } finally {
      setStreaming(false);
    }
  };

  return (
    <div className="flex flex-col h-full">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-6">
        {messages.length === 0 && (
          <div className="text-center text-content-secondary mt-20">
            <p className="text-xl font-medium">Start a conversation</p>
            <p className="text-sm mt-2">
              Describe the job you want to apply for, or paste a job URL.
            </p>
          </div>
        )}
        {messages.map((msg, i) => (
          <ChatMessage key={i} role={msg.role} content={msg.content} />
        ))}
        {statuses.map((s, i) => (
          <StatusPill key={`${s.tool}-${i}`} tool={s.tool} state={s.state} />
        ))}
        {documents.map((d) => (
          <DownloadCard
            key={d.document_id}
            docType={d.doc_type}
            downloadUrl={d.download_url}
          />
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="border-t p-4">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            sendMessage();
          }}
          className="flex gap-3 max-w-4xl mx-auto"
        >
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Type a message..."
            className="flex-1 px-4 py-3 border border-border rounded-lg text-content bg-surface focus:ring-2 focus:ring-primary focus:border-transparent"
            disabled={streaming}
          />
          <button
            type="submit"
            disabled={streaming || !input.trim()}
            className="px-6 py-3 bg-primary text-content-inverse rounded-lg hover:bg-primary-hover transition disabled:opacity-50"
          >
            Send
          </button>
        </form>
      </div>
    </div>
  );
}
