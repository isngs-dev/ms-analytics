import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";
import { themeInitScript } from "@/components/theme";

export const metadata: Metadata = {
  title: "MS Analytics",
  description: "Mystery shopping operations: volumes, QC and escalations",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
      </head>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
