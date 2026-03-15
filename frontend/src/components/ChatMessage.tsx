import Markdown from "react-markdown";

interface ChatMessageProps {
  role: "user" | "assistant";
  content: string;
}

export default function ChatMessage({ role, content }: ChatMessageProps) {
  if (role === "user") {
    return (
      <div className="flex justify-end mb-4">
        <div
          className="max-w-[70%] px-4 py-3 bg-accent text-white rounded-2xl rounded-br-[4px]"
          style={{ overflowWrap: "anywhere" }}
        >
          <p className="whitespace-pre-wrap text-sm">{content}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex gap-3 mb-4">
      <div className="w-6 h-6 rounded-md bg-bg-secondary border border-border flex items-center justify-center flex-shrink-0 mt-1">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-accent">
          <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" />
        </svg>
      </div>
      <div
        className="max-w-[75%] px-4 py-3 bg-bg-secondary border border-border rounded-2xl rounded-tl-[4px] overflow-hidden"
        style={{ overflowWrap: "anywhere" }}
      >
        <div className="prose prose-sm max-w-none [&>*:first-child]:mt-0 [&>*:last-child]:mb-0 prose-a:text-accent [&_a]:break-all prose-headings:text-text-primary prose-strong:text-text-primary prose-p:text-text-primary prose-li:text-text-primary prose-code:text-text-primary">
          <Markdown>{content}</Markdown>
        </div>
      </div>
    </div>
  );
}
