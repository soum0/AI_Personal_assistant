import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Soum's AI Representative",
  description: "Ask about background, skills, GitHub projects, or book a meeting.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="h-full">
      <body className="h-full bg-gray-950 text-gray-100 antialiased">{children}</body>
    </html>
  );
}
