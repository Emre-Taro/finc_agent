import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "finc_agent",
  description: "金融ニュースのAI評価と銘柄スコアリング",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ja">
      <body>
        <header className="topbar">
          <span className="brand">finc_agent</span>
          <nav>
            <Link href="/">ニュース・指標</Link>
            <Link href="/companies">銘柄スコア</Link>
          </nav>
        </header>
        <main>{children}</main>
      </body>
    </html>
  );
}
