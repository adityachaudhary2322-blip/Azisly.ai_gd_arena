import type { Metadata, Viewport } from "next";
import { Geist_Mono, Plus_Jakarta_Sans } from "next/font/google";
import "./globals.css";
import { GDSessionProvider } from "@/components/GDSessionProvider";
import { InstallPrompt } from "@/components/InstallPrompt";

const jakarta = Plus_Jakarta_Sans({
  variable: "--font-jakarta",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "GD Arena",
  description: "Real-time AI group discussion practice",
  applicationName: "GD Arena",
  appleWebApp: { capable: true, title: "GD Arena", statusBarStyle: "black-translucent" },
  icons: { apple: "/apple-touch-icon.png" },
};

export const viewport: Viewport = {
  themeColor: "#081414",
  colorScheme: "dark",
  viewportFit: "cover",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${jakarta.variable} ${geistMono.variable} dark h-full antialiased`}>
      <body className="flex min-h-full flex-col font-sans text-foreground">
        <GDSessionProvider>{children}</GDSessionProvider>
        <InstallPrompt />
      </body>
    </html>
  );
}
