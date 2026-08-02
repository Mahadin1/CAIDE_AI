import type { Metadata } from "next";
import { Space_Grotesk } from "next/font/google";
import "./globals.css";

const spaceGrotesk = Space_Grotesk({
  subsets: ["latin"],
  weight: ["500", "700"],
  variable: "--font-heading",
  display: "swap",
});

export const metadata: Metadata = {
  title: {
    default: "DataScope — Turn messy CSVs into answers",
    template: "%s · DataScope",
  },
  description:
    "Upload any spreadsheet and get a plain-English analysis — outliers flagged, correlations explained, nothing left for you to interpret.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${spaceGrotesk.variable}`}>
      <head>
        {/* General Sans (body font) from Fontshare — never Inter/Roboto/Open Sans */}
        <link
          rel="preconnect"
          href="https://api.fontshare.com"
          crossOrigin="anonymous"
        />
        <link
          rel="stylesheet"
          href="https://api.fontshare.com/v2/css?f[]=general-sans@400,500&display=swap"
        />
      </head>
      <body
        style={{ fontFamily: "'General Sans', var(--font-heading), sans-serif" }}
      >
        {children}
      </body>
    </html>
  );
}
