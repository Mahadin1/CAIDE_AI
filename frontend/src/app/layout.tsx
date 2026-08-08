import type { Metadata } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import "./globals.css";

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
    <html lang="en" className={`${GeistSans.variable} ${GeistMono.variable}`}>
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var t=localStorage.getItem('datascope-theme');if(t==='light'||(!t&&window.matchMedia('(prefers-color-scheme: light)').matches&&localStorage.getItem('datascope-theme-set')!=='dark')){document.documentElement.classList.add('light');}}catch(e){}})();`,
          }}
        />
      </head>
      <body className="font-sans antialiased">
        {children}
      </body>
    </html>
  );
}
