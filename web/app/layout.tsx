import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Eval Engine Demo",
  description: "Multi-agent evaluation control plane",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="antialiased">{children}</body>
    </html>
  );
}
