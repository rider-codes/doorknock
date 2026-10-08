import { useEffect, useState, type AnchorHTMLAttributes, type MouseEvent } from "react";

/** Tiny history-API router: two pages, no dependency. "/" is the overview, "/app" is the workspace. */
export type Route = "home" | "app";

const toRoute = (path: string): Route => (path.replace(/\/+$/, "") === "/app" ? "app" : "home");

export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(() => toRoute(window.location.pathname));
  useEffect(() => {
    const onPop = () => setRoute(toRoute(window.location.pathname));
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  return route;
}

export function navigate(path: string) {
  if (window.location.pathname === path) return;
  window.history.pushState({}, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
  window.scrollTo({ top: 0 });
}

/** A real <a href> (so it can be opened in a new tab or shared) that navigates without a reload. */
export function Link({ to, onClick, ...rest }: AnchorHTMLAttributes<HTMLAnchorElement> & { to: string }) {
  const handle = (e: MouseEvent<HTMLAnchorElement>) => {
    onClick?.(e);
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    navigate(to);
  };
  return <a href={to} onClick={handle} {...rest} />;
}
