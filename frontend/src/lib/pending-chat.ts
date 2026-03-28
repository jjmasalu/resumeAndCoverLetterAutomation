"use client";

const PENDING_CHAT_PREFIX = "pending-chat:";

function keyForConversation(conversationId: string) {
  return `${PENDING_CHAT_PREFIX}${conversationId}`;
}

export interface PendingChatMessage {
  content: string;
  attachmentFileIds?: string[];
}

export function storePendingChatMessage(
  conversationId: string,
  content: string,
  attachmentFileIds: string[] = []
) {
  if (typeof window === "undefined") return;
  window.sessionStorage.setItem(
    keyForConversation(conversationId),
    JSON.stringify({
      content,
      attachmentFileIds,
    } satisfies PendingChatMessage)
  );
}

export function readPendingChatMessage(conversationId: string) {
  if (typeof window === "undefined") return null;
  const raw = window.sessionStorage.getItem(keyForConversation(conversationId));
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as PendingChatMessage;
    if (!parsed || typeof parsed.content !== "string") {
      return null;
    }
    return {
      content: parsed.content,
      attachmentFileIds: Array.isArray(parsed.attachmentFileIds)
        ? parsed.attachmentFileIds.filter((value): value is string => typeof value === "string")
        : [],
    } satisfies PendingChatMessage;
  } catch {
    return {
      content: raw,
      attachmentFileIds: [],
    } satisfies PendingChatMessage;
  }
}

export function clearPendingChatMessage(conversationId: string) {
  if (typeof window === "undefined") return;
  window.sessionStorage.removeItem(keyForConversation(conversationId));
}
