import { useCallback, useEffect, useState } from "react";

/**
 * Hash routes, so a static Vercel deploy needs no rewrites and every view has a shareable URL.
 *   #/projects
 *   #/projects/:id/:tab
 *   #/new/draw
 *   #/limitations
 */
export type ProjectTab = "overview" | "map" | "crowns" | "validation" | "runs" | "audit";

export type Route =
  | { name: "projects" }
  | { name: "project"; id: string; tab: ProjectTab; run?: string }
  | { name: "draw" }
  | { name: "limitations" };

const TABS: ProjectTab[] = ["overview", "map", "crowns", "validation", "runs", "audit"];

export function parseHash(hash: string): Route {
  const [path, query = ""] = hash.replace(/^#/, "").split("?");
  const parts = path.split("/").filter(Boolean);
  const params = new URLSearchParams(query);
  if (parts[0] === "projects" && parts[1]) {
    const tab = TABS.includes(parts[2] as ProjectTab) ? (parts[2] as ProjectTab) : "overview";
    return { name: "project", id: parts[1], tab, run: params.get("run") ?? undefined };
  }
  if (parts[0] === "new" && parts[1] === "draw") return { name: "draw" };
  if (parts[0] === "limitations") return { name: "limitations" };
  return { name: "projects" };
}

export function toHash(route: Route): string {
  switch (route.name) {
    case "project":
      return `#/projects/${route.id}/${route.tab}${route.run ? `?run=${route.run}` : ""}`;
    case "draw":
      return "#/new/draw";
    case "limitations":
      return "#/limitations";
    default:
      return "#/projects";
  }
}

export function useRoute() {
  const [route, setRoute] = useState<Route>(() => parseHash(window.location.hash));
  useEffect(() => {
    const onChange = () => setRoute(parseHash(window.location.hash));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  const navigate = useCallback((next: Route, { replace = false } = {}) => {
    const hash = toHash(next);
    if (replace) window.history.replaceState(null, "", hash);
    else window.location.hash = hash;
    setRoute(parseHash(hash));
  }, []);
  return [route, navigate] as const;
}
