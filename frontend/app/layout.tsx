import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "AI Dental CAD",
  description: "Upload a scan. Review the plan. Download printable restorations.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header className="topbar">
          <span className="logo">AI Dental CAD</span>
          <span className="tagline">Design aid — every case requires clinical review</span>
        </header>
        <main>{children}</main>
      </body>
    </html>
  );
}
