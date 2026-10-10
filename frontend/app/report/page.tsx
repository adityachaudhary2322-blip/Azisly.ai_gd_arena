import type { Metadata } from "next";

import { Report } from "@/components/report/Report";

export const metadata: Metadata = { title: "Report · GD Arena" };

export default function ReportPage() {
  return <Report />;
}
