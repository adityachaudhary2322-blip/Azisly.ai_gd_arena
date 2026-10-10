export type TopicCategory = "placement" | "abstract" | "custom";

export const PLACEMENT_TOPICS = [
  "AI in Job Markets",
  "Work From Home vs. Work From Office",
  "Is a College Degree Still Necessary?",
  "Startups vs. MNCs for Freshers",
  "Should Social Media Be Regulated?",
  "Electric Vehicles: Is India Ready?",
  "Cryptocurrency: Boon or Bane",
  "Gig Economy and Job Security",
] as const;

export const ABSTRACT_TOPICS = [
  "Zero",
  "Red vs. Blue",
  "A Blank Sheet of Paper",
  "Mirrors",
  "The Road Not Taken",
  "Silence Speaks",
  "Bridges",
  "Ctrl + Z",
] as const;

/** Discussion length choices, in minutes. */
export const DURATIONS = [3, 5, 7, 10, 15, 20] as const;
export const DEFAULT_DURATION = 7;

export const LANGUAGES = [
  { value: "en-IN", label: "English" },
  { value: "hi-IN", label: "Hindi + English (Hinglish)" },
] as const;
