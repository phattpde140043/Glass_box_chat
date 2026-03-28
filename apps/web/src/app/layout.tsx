import type { Metadata, Viewport } from "next";
import "./globals.css";

const metadataBase = new URL("http://localhost:3000");

export const viewport: Viewport = {
  colorScheme: "light",
  themeColor: "#f4efe6",
  width: "device-width",
  initialScale: 1,
};

export const metadata: Metadata = {
  title: "Glass Box Chat",
  description: "Transparent runtime view for chat agents",
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

export const metadata: Metadata = {
  title: "The Glass Box",
  description: "Observable agent runtime UI",
  metadataBase,
  applicationName: "The Glass Box",
  keywords: ["agent runtime", "trace", "chat", "observability"],
  openGraph: {
    title: "The Glass Box",
    description: "Observable agent runtime UI",
    type: "website",
    url: metadataBase,
  },
  twitter: {
    card: "summary_large_image",
    title: "The Glass Box",
    description: "Observable agent runtime UI",
  },
  icons: {
    icon: "/favicon.ico",
  },
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
