import { useEffect } from "react";
import { useLocation } from "react-router-dom";

/**
 * On every route change scroll the window (and the outermost scrollable
 * container) back to the top. React Router keeps the previous scroll
 * position when navigating between routes — for content-heavy pages like
 * TOS / AUP / SLA the user would otherwise land mid-page.
 *
 * Uses an instant jump (not smooth) so the user never perceives the old
 * page's content while the new one is mounting.
 */
const ScrollToTop = () => {
  const { pathname, hash } = useLocation();

  useEffect(() => {
    // Respect explicit anchor navigation (e.g. /page#section-b)
    if (hash) return;
    try {
      window.scrollTo({ top: 0, left: 0, behavior: "instant" });
    } catch {
      // Fallback for browsers that don't support behavior:'instant'
      window.scrollTo(0, 0);
    }
    // Also reset the document element and body scroll — needed when a
    // parent element (not window) is the scroll container.
    if (document.documentElement) document.documentElement.scrollTop = 0;
    if (document.body) document.body.scrollTop = 0;
  }, [pathname, hash]);

  return null;
};

export default ScrollToTop;
