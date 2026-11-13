/**
 * The browser tab's title. A page names itself; the tab reads "<page> · margin", or just
 * "margin" on the home page. The title goes back when the page goes.
 */
import { useEffect } from "react";

const APP = "margin";

export function usePageTitle(title?: string | null) {
  useEffect(() => {
    document.title = title ? `${title} · ${APP}` : APP;
    return () => {
      document.title = APP;
    };
  }, [title]);
}
