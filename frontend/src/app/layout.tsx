import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Resume AI",
  description: "Generate tailored resumes and cover letters with AI",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="antialiased">{children}</body>
    </html>
  );
}
