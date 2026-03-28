import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "The Glass Box",
  description: "Observable agent runtime UI",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
