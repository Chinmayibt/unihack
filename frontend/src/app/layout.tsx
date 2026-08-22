import type { Metadata } from "next";
import { Outfit } from "next/font/google";
import "./globals.css";

const sans = Outfit({
  subsets: ["latin"],
  variable: "--font-sans-face",
  weight: ["400", "500", "600", "700"],
});

export const metadata: Metadata = {
  title: "ALETHEIA — The Truth Layer for Industrial Product Data",
  description:
    "ALETHEIA grounds industrial catalog attributes in manufacturer evidence, taxonomy, validation, and human review.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className={`${sans.variable} antialiased`}>{children}</body>
    </html>
  );
}
