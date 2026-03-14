"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { apiJson } from "@/lib/api";

interface Conversation {
  id: string;
  title: string;
  mode: string;
  status: string;
  created_at: string;
}

export default function HistoryPage() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const router = useRouter();

  useEffect(() => {
    apiJson<Conversation[]>("/conversations")
      .then(setConversations)
      .catch(console.error);
  }, []);

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <h1 className="text-2xl font-bold mb-6">Conversation History</h1>
      {conversations.length === 0 ? (
        <p className="text-gray-400">No conversations yet.</p>
      ) : (
        <div className="space-y-3">
          {conversations.map((c) => (
            <button
              key={c.id}
              onClick={() => router.push(`/chat/${c.id}`)}
              className="w-full text-left p-4 bg-white border border-gray-200 rounded-lg hover:border-blue-300 transition"
            >
              <div className="flex justify-between items-center">
                <div>
                  <p className="font-medium">{c.title}</p>
                  <p className="text-sm text-gray-500">
                    {c.mode === "job_to_resume" ? "Job → Resume" : "Find Jobs"}{" "}
                    · {new Date(c.created_at).toLocaleDateString()}
                  </p>
                </div>
                <span
                  className={`text-xs px-2 py-1 rounded ${
                    c.status === "active"
                      ? "bg-green-100 text-green-700"
                      : "bg-gray-100 text-gray-600"
                  }`}
                >
                  {c.status}
                </span>
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
