import { useEffect } from "react";
import { useLocation } from "react-router-dom";

/**
 * On every route change scroll the window (and the outermost scrollable
 * container) back to the top. React Router keeps the previous scroll
 * position when navigating between routes — for content-heavy pages like
 * TOS / AUP / SLA the user would otherwise land mid-page.
 *
 * If the URL has a hash (e.g. /#services), we instead try to scroll that
 * element into view once it's mounted. React Router by default IGNORES
 * hashes on navigation, so this component patches that behaviour.
 *
 * Uses an instant jump for pathname-only changes so the user never perceives
 * the old page's content while the new one is mounting. Smooth scroll for
 * in-page hash targets so the anchor feels responsive.
 */
const ScrollToTop = () => {
  const { pathname, hash } = useLocation();

  useEffect(() => {
    if (hash) {
      // Poll briefly for the target — Landing sections mount after the route
      // component itself, so the element may not exist in the very first tick.
      const id = hash.slice(1);
      let attempts = 0;
      const tick = () => {
        const el = document.getElementById(id);
        if (el) {
          el.scrollIntoView({ behavior: "smooth", block: "start" });
          return;
        }
        if (++attempts < 20) setTimeout(tick, 80);
      };
      tick();
      return;
    }
    try {
      window.scrollTo({ top: 0, left: 0, behavior: "instant" });
    } catch {
      // Fallback for browsers that don't support behavior:'instant'
      window.scrollTo(0, 0);
    }
    if (document.documentElement) document.documentElement.scrollTop = 0;
    if (document.body) document.body.scrollTop = 0;
  }, [pathname, hash]);

  return null;
};

export default ScrollToTop;
