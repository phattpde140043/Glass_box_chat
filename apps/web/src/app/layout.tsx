import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Glass Box Chat",
  description: "Transparent runtime view for chat agents",
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
