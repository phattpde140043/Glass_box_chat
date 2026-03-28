import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Glass Box Chat",
  description: "Transparent runtime view for chat agents",
import { Geist, Geist_Mono } from "next/font/google";
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
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
