"use client";

import { useEffect, useState, useRef } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import { MODE_COPY } from "@/lib/conversation-modes";
import {
  storePendingLandingIntent,
} from "@/lib/pending-landing-intent";
import { stashPendingFiles } from "@/lib/pending-files";

const BRAND_NAME = "Resume AI";

type Tab = "job_to_resume" | "find_jobs";

export default function LandingPage() {
  const [activeTab, setActiveTab] = useState<Tab>("job_to_resume");
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [stagingFile, setStagingFile] = useState(false);
  const [sessionChecked, setSessionChecked] = useState(false);
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const router = useRouter();

  useEffect(() => {
    const supabase = createClient();

    supabase.auth.getSession().then(({ data: { session } }) => {
      setIsAuthenticated(Boolean(session));
      setSessionChecked(true);
    });

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, session) => {
      setIsAuthenticated(Boolean(session));
      setSessionChecked(true);
    });

    return () => {
      subscription.unsubscribe();
    };
  }, []);

  const ensureAuth = async (returnTo?: string): Promise<boolean> => {
    const supabase = createClient();
    const { data: { session } } = await supabase.auth.getSession();
    if (!session) {
      const path = returnTo ? `/login?returnTo=${encodeURIComponent(returnTo)}` : "/login";
      router.push(path);
      return false;
    }
    return true;
  };

  const handleUrlSubmit = async () => {
    if (!input.trim()) return;
    setLoading(true);
    try {
      storePendingLandingIntent({ kind: "specific_job", input: input.trim() });
      const returnTo = "/chat?mode=job_to_resume";
      if (!(await ensureAuth(returnTo))) return;
      router.push(returnTo);
    } catch {
      router.push("/login?returnTo=%2Fchat%3Fmode%3Djob_to_resume");
    } finally {
      setLoading(false);
    }
  };

  const handleFileUpload = async (file: File) => {
    setStagingFile(true);
    try {
      if (!(await ensureAuth("/chat?mode=find_jobs"))) {
        setStagingFile(false);
        return;
      }
      const token = stashPendingFiles([file]);
      storePendingLandingIntent({
        kind: "find_jobs_attachment",
        token,
        filename: file.name,
      });
      router.push("/chat?mode=find_jobs");
    } catch {
      router.push("/login");
    } finally {
      setStagingFile(false);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleFileUpload(file);
  };

  const handleUploadClick = async () => {
    if (!(await ensureAuth("/chat?mode=find_jobs"))) return;
    fileInputRef.current?.click();
  };

  return (
    <div className="min-h-screen bg-bg-primary">
      {/* Nav */}
      <header className="flex items-center justify-between px-8 py-4 max-w-6xl mx-auto">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 bg-accent rounded-md flex items-center justify-center text-[11px] font-bold text-white">R</div>
          <span className="font-semibold text-sm text-text-primary">{BRAND_NAME}</span>
        </div>
        <div className="flex items-center gap-5">
          <a href="#how-it-works" className="text-sm text-text-secondary hover:text-text-primary transition">How it works</a>
          <div className="w-px h-4 bg-border" />
          {sessionChecked && isAuthenticated ? (
            <>
              <a href="/history" className="text-sm text-text-secondary hover:text-text-primary transition">History</a>
              <a
                href="/chat"
                className="px-4 py-1.5 text-sm font-medium text-white bg-accent rounded-md hover:bg-accent-hover transition"
              >
                Open app
              </a>
            </>
          ) : (
            <>
              <a href="/login" className="text-sm text-text-secondary hover:text-text-primary transition">Sign in</a>
              <a
                href="/login"
                className="px-4 py-1.5 text-sm font-medium text-white bg-accent rounded-md hover:bg-accent-hover transition"
              >
                Get Started
              </a>
            </>
          )}
        </div>
      </header>

      {/* Hero */}
      <section className="text-center px-6 pt-20 pb-10 max-w-3xl mx-auto relative">
        <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[600px] h-[300px] bg-[radial-gradient(ellipse,var(--accent-muted)_0%,transparent_70%)] pointer-events-none" />

        <div className="relative">
          <div className="inline-flex items-center gap-1.5 px-3.5 py-1 border border-border rounded-full text-[11px] text-text-secondary bg-bg-secondary mb-6">
            <span className="w-1.5 h-1.5 rounded-full bg-accent" />
            AI-powered job applications
          </div>

          <h1 className="text-4xl md:text-5xl font-bold text-text-primary leading-tight mb-4 tracking-tight">
            Land interviews,<br />not rejections
          </h1>

          <p className="text-base text-text-tertiary max-w-md mx-auto mb-8 leading-relaxed">
            Start from a specific job, or let Resume AI find roles that fit.
          </p>

          {/* Tab Switcher */}
          <div className="max-w-lg mx-auto">
            <div className="flex bg-bg-secondary border border-border rounded-lg p-1 mb-4">
              <button
                onClick={() => setActiveTab("job_to_resume")}
                className={`flex-1 text-center py-2 text-xs font-medium rounded-md transition ${
                  activeTab === "job_to_resume"
                    ? "bg-accent text-white"
                    : "text-text-secondary hover:text-text-primary"
                }`}
              >
                {MODE_COPY.job_to_resume.label}
              </button>
              <button
                onClick={() => setActiveTab("find_jobs")}
                className={`flex-1 text-center py-2 text-xs font-medium rounded-md transition ${
                  activeTab === "find_jobs"
                    ? "bg-accent text-white"
                    : "text-text-secondary hover:text-text-primary"
                }`}
              >
                {MODE_COPY.find_jobs.label}
              </button>
            </div>

            {/* Tab Content */}
            {activeTab === "job_to_resume" ? (
              <>
                <p className="mb-3 text-xs text-text-tertiary">
                  {MODE_COPY.job_to_resume.description}
                </p>
                <div className="bg-bg-secondary border border-border rounded-xl p-1.5 flex gap-1.5">
                  <div className="flex-1 flex items-center gap-2 px-3">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-text-tertiary flex-shrink-0">
                      <path d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
                    </svg>
                    <input
                      value={input}
                      onChange={(e) => setInput(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && handleUrlSubmit()}
                      placeholder="Paste a job URL, company + role, or job description..."
                      className="flex-1 bg-transparent text-sm text-text-primary placeholder:text-text-tertiary outline-none py-2"
                    />
                  </div>
                  <button
                    onClick={handleUrlSubmit}
                    disabled={!input.trim() || loading}
                    className="px-6 py-2.5 bg-accent text-white text-sm font-medium rounded-lg hover:bg-accent-hover transition disabled:opacity-50"
                  >
                    {loading ? "..." : "Generate"}
                  </button>
                </div>
                <div className="flex items-center justify-center gap-4 mt-3 text-[11px] text-text-tertiary">
                  <span>Company careers</span>
                  <span className="text-border">&middot;</span>
                  <span>Greenhouse</span>
                  <span className="text-border">&middot;</span>
                  <span>Lever</span>
                  <span className="text-border">&middot;</span>
                  <span>Ashby</span>
                  <span className="text-border">&middot;</span>
                  <span>Workday</span>
                </div>
              </>
            ) : (
              <>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".pdf,.docx,.png,.jpg,.jpeg"
                  onChange={handleFileChange}
                  className="hidden"
                />
                <div
                  onClick={handleUploadClick}
                  onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); }}
                  onDrop={async (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    const file = e.dataTransfer.files?.[0];
                    if (file) {
                      if (!(await ensureAuth("/chat?mode=find_jobs"))) return;
                      handleFileUpload(file);
                    }
                  }}
                  className="bg-bg-secondary border-2 border-dashed border-border rounded-xl p-8 text-center cursor-pointer hover:border-text-tertiary transition"
                >
                  {stagingFile ? (
                    <>
                      <div className="w-5 h-5 border-2 border-accent border-t-transparent rounded-full animate-spin mx-auto mb-3" />
                      <div className="text-sm text-text-secondary">Preparing...</div>
                    </>
                  ) : (
                    <>
                      <div className="w-10 h-10 rounded-lg bg-accent-muted flex items-center justify-center mx-auto mb-3">
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-accent">
                          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12" />
                        </svg>
                      </div>
                      <div className="text-sm font-medium text-text-primary mb-1">Upload your resume</div>
                      <div className="text-xs text-text-tertiary mb-3">PDF, DOCX, or image</div>
                      <div className="inline-block bg-accent text-white text-xs font-medium px-4 py-1.5 rounded-lg">
                        Choose file
                      </div>
                    </>
                  )}
                </div>
                <div className="mt-3">
                  <p className="mb-2 text-xs text-text-tertiary">
                    {MODE_COPY.find_jobs.description}
                  </p>
                  <button
                    onClick={async () => {
                      if (!(await ensureAuth("/chat?mode=find_jobs"))) return;
                      router.push("/chat?mode=find_jobs");
                    }}
                    className="text-xs text-text-tertiary hover:text-accent transition bg-transparent border-none cursor-pointer"
                  >
                    or tell us about your background &rarr;
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      </section>

      {/* Social proof */}
      <section className="flex items-center justify-center gap-8 py-6 border-t border-border-subtle max-w-3xl mx-auto">
        {[
          { value: "2.4k+", label: "Resumes generated" },
          { value: "30s", label: "Average generation time" },
          { value: "89%", label: "ATS pass rate" },
        ].map((stat, i) => (
          <div key={i} className="flex items-center gap-8">
            {i > 0 && <div className="w-px h-8 bg-border" />}
            <div className="text-center">
              <div className="text-xl font-bold text-text-primary">{stat.value}</div>
              <div className="text-[11px] text-text-tertiary">{stat.label}</div>
            </div>
          </div>
        ))}
      </section>

      {/* How it works */}
      <section id="how-it-works" className="py-16 px-6">
        <div className="text-center mb-10">
          <h2 className="text-2xl font-semibold text-text-primary tracking-tight mb-2">How it works</h2>
          <p className="text-sm text-text-tertiary">Three steps. No templates. No formatting.</p>
        </div>
        <div className="flex gap-4 max-w-2xl mx-auto">
          {[
            {
              icon: (
                <path d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
              ),
              title: "Start with a target or your resume",
              desc: "Bring a specific job, or upload your resume so we can find matching roles.",
            },
            {
              icon: (
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
              ),
              title: "Chat with AI",
              desc: "Answer a few questions about your experience. The AI learns and remembers you.",
            },
            {
              icon: (
                <path d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              ),
              title: "Download & apply",
              desc: "Get a tailored resume and cover letter as .docx files. Ready to submit.",
            },
          ].map((step, i) => (
            <div key={i} className="flex-1 bg-bg-secondary border border-border rounded-xl p-5">
              <div className="w-8 h-8 rounded-lg bg-accent-muted flex items-center justify-center mb-3">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-accent">
                  {step.icon}
                </svg>
              </div>
              <h3 className="text-sm font-semibold text-text-primary mb-1">{step.title}</h3>
              <p className="text-xs text-text-tertiary leading-relaxed">{step.desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Footer */}
      <footer className="flex items-center justify-between px-8 py-5 border-t border-border-subtle max-w-6xl mx-auto">
        <div className="flex items-center gap-2">
          <div className="w-4 h-4 bg-accent rounded-sm flex items-center justify-center text-[8px] font-bold text-white">R</div>
          <span className="text-xs text-text-tertiary">{BRAND_NAME}</span>
        </div>
        <span className="text-[11px] text-text-tertiary">Built with care. Not with templates.</span>
      </footer>
    </div>
  );
}
