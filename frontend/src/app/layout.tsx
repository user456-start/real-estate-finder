import type { Metadata } from "next";
import "./globals.css";
import AppHeader from "@/components/AppHeader";

export const metadata: Metadata = {
  title: "Dubai Property Finder",
  description: "AI-powered Dubai real estate search",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="min-h-screen flex flex-col antialiased">
        <AppHeader />
        <main className="flex-1">{children}</main>
      </body>
    </html>
  );
}
