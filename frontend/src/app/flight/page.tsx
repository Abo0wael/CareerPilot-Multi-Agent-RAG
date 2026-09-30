import type { Metadata } from "next";
import { FlightPlan } from "@/components/flight/FlightPlan";
import { isDemoId } from "@/lib/demos";

export const metadata: Metadata = {
  title: "Flight plan",
  description: "Upload a CV, find matching jobs, see the gaps and get a verified tailored CV.",
};

export default async function FlightPage({ searchParams }: PageProps<"/flight">) {
  const { demo } = await searchParams;
  return <FlightPlan autoDemo={isDemoId(demo) ? demo : null} />;
}
