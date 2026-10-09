import { useEffect, useState } from "react";

/** Tiny History-API router: paths are /, /search, /trip/:id, /favorites, /alerts. */
export function navigate(to: string, replace = false) {
  if (to === location.pathname + location.search) return;
  history[replace ? "replaceState" : "pushState"](null, "", to);
  window.dispatchEvent(new PopStateEvent("popstate"));
  if (!replace) window.scrollTo(0, 0);
}

export function useLocation() {
  const [loc, setLoc] = useState(() => ({ path: location.pathname, search: location.search }));
  useEffect(() => {
    const h = () => setLoc({ path: location.pathname, search: location.search });
    window.addEventListener("popstate", h);
    return () => window.removeEventListener("popstate", h);
  }, []);
  return loc;
}

/** <a> that routes client-side but still works with middle-click / new tab. */
export function linkProps(to: string) {
  return {
    href: to,
    onClick: (e: React.MouseEvent) => {
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
      e.preventDefault(); navigate(to);
    },
  };
}
