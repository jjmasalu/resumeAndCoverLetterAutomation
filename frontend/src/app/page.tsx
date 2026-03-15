"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import { apiJson } from "@/lib/api";

const steps = [
  {
    num: 1,
    title: "Find Job",
    desc: "Paste URL or search keywords. Tavily finds the posting.",
    color: "bg-blue-100 text-blue-600",
  },
  {
    num: 2,
    title: "Extract Details",
    desc: "Firecrawl extracts the full job description automatically.",
    color: "bg-purple-100 text-purple-600",
  },
  {
    num: 3,
    title: "AI Generation",
    desc: "Gemini 2.5 Flash tailors your resume & writes cover letter.",
    color: "bg-pink-100 text-pink-600",
  },
  {
    num: 4,
    title: "Download",
    desc: "Get polished .docx files ready to submit instantly.",
    color: "bg-green-100 text-green-600",
  },
];

export default function LandingPage() {
  const [tab, setTab] = useState<"url" | "search">("url");
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const router = useRouter();

  const handleSubmit = async () => {
    if (!input.trim()) return;
    setLoading(true);

    try {
      const supabase = createClient();
      const {
        data: { session },
      } = await supabase.auth.getSession();

      if (!session) {
        router.push("/login");
        return;
      }

      const mode = tab === "search" ? "find_jobs" : "job_to_resume";
      const conv = await apiJson<{ id: string }>("/conversations", {
        method: "POST",
        body: JSON.stringify({ mode }),
      });

      const message =
        tab === "url"
          ? `I want to apply for this job: ${input.trim()}`
          : `Search for: ${input.trim()}`;

      router.push(`/chat/${conv.id}?initial=${encodeURIComponent(message)}`);
    } catch {
      router.push("/login");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-b from-purple-50/50 via-white to-white">
      {/* Header */}
      <header className="flex items-center justify-between px-8 py-5 max-w-6xl mx-auto">
        <h1 className="text-xl font-bold text-gray-900">Resume AI</h1>
        <a
          href="/login"
          className="px-5 py-2 text-sm font-medium text-white bg-gray-900 rounded-lg hover:bg-gray-800 transition"
        >
          Sign in
        </a>
      </header>

      {/* Hero */}
      <section className="text-center px-6 pt-12 pb-8 max-w-3xl mx-auto">
        <span className="inline-flex items-center gap-2 px-4 py-1.5 text-sm font-medium text-purple-700 bg-purple-100 rounded-full mb-6">
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z" />
          </svg>
          AI-Powered Job Application Assistant
        </span>
        <h2 className="text-4xl md:text-5xl font-bold text-gray-900 leading-tight mb-4">
          Get hired faster with tailored applications
        </h2>
        <p className="text-lg text-gray-500 max-w-2xl mx-auto">
          Paste a job URL or search by job title/keywords. Our AI will extract
          the posting, tailor your resume, and write a personalized cover letter.
        </p>
      </section>

      {/* Job Input Card */}
      <section className="max-w-2xl mx-auto px-6 pb-16">
        <div className="border border-gray-200 rounded-2xl p-6 bg-white shadow-sm">
          <h3 className="text-lg font-semibold text-gray-900 mb-1">
            Find Your Job Posting
          </h3>
          <p className="text-sm text-gray-500 mb-4">
            Paste a job URL or search by title/keywords to get started
          </p>

          {/* Tabs */}
          <div className="flex bg-gray-100 rounded-full p-1 mb-4">
            <button
              onClick={() => { setTab("url"); setInput(""); }}
              className={`flex-1 py-2 text-sm font-medium rounded-full transition ${
                tab === "url"
                  ? "bg-white text-gray-900 shadow-sm"
                  : "text-gray-500 hover:text-gray-700"
              }`}
            >
              Paste URL
            </button>
            <button
              onClick={() => { setTab("search"); setInput(""); }}
              className={`flex-1 py-2 text-sm font-medium rounded-full transition ${
                tab === "search"
                  ? "bg-white text-gray-900 shadow-sm"
                  : "text-gray-500 hover:text-gray-700"
              }`}
            >
              Search Job
            </button>
          </div>

          {/* Input */}
          <label className="block text-sm font-medium text-gray-700 mb-1.5">
            {tab === "url" ? "Job Posting URL" : "Job Title or Keywords"}
          </label>
          <div className="flex gap-2">
            <div className="flex-1 relative">
              <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400">
                {tab === "url" ? (
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
                  </svg>
                ) : (
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                  </svg>
                )}
              </span>
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
                placeholder={
                  tab === "url"
                    ? "https://company.com/careers/job-posting"
                    : "e.g., Senior Product Manager, UX Designer"
                }
                className="w-full pl-9 pr-4 py-2.5 bg-gray-50 border border-gray-200 rounded-lg text-sm text-gray-900 placeholder:text-gray-400 focus:ring-2 focus:ring-purple-200 focus:border-purple-400 outline-none"
              />
            </div>
            <button
              onClick={handleSubmit}
              disabled={!input.trim() || loading}
              className="px-5 py-2.5 bg-gray-900 text-white text-sm font-medium rounded-lg hover:bg-gray-800 transition disabled:opacity-50"
            >
              {loading ? "..." : tab === "url" ? "Extract" : "Search"}
            </button>
          </div>
          <p className="text-xs text-gray-400 mt-2">
            {tab === "url"
              ? "Firecrawl will extract the job description from the URL"
              : "Tavily will find relevant job postings and extract details"}
          </p>
        </div>
      </section>

      {/* How It Works */}
      <section className="bg-gray-50/50 py-16 px-6">
        <h3 className="text-2xl font-bold text-gray-900 text-center mb-10">
          How It Works
        </h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-8 max-w-4xl mx-auto">
          {steps.map((step) => (
            <div key={step.num} className="text-center">
              <div
                className={`w-14 h-14 rounded-full ${step.color} flex items-center justify-center text-xl font-bold mx-auto mb-3`}
              >
                {step.num}
              </div>
              <h4 className="font-semibold text-gray-900 mb-1">{step.title}</h4>
              <p className="text-sm text-gray-500">{step.desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Footer */}
      <footer className="text-center py-8 text-sm text-gray-400">
        Resume AI — Built with Next.js, FastAPI, and Gemini
      </footer>
    </div>
  );
}
