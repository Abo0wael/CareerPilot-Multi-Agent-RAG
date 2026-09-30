// The five LangGraph agents, in the order the full flow runs them.
export const AGENTS = [
  { id: "profile", name: "Profile", endpoint: "POST /profile", does: "Reads the CV into a structured profile" },
  { id: "matcher", name: "Matcher", endpoint: "POST /match", does: "Expands the query, searches 91k chunks, reranks" },
  { id: "gap", name: "Gap", endpoint: "POST /gap", does: "Matched requirements with CV evidence, and what is missing" },
  { id: "tailor", name: "Tailor", endpoint: "POST /tailor", does: "Rewrites bullets using only facts from the CV" },
  { id: "verifier", name: "Verifier", endpoint: "POST /tailor", does: "Checks every bullet; removes unsupported claims" },
] as const;

export type AgentId = (typeof AGENTS)[number]["id"];
