let leaving = false;

/**
 * A full page load, used whenever the signed-in state changes (login, registration, logout,
 * expired session, account deletion). A client-side navigation would keep the router cache,
 * which can hold redirects the proxy issued for the previous state (for example a prefetched
 * "/home -> /login" from the sign-in page), and in-memory data of the previous account.
 */
export function hardNavigate(path: string, { replace = false } = {}): void {
  leaving = true;
  if (replace) window.location.replace(path);
  else window.location.assign(path);
}

/**
 * True once a full page load has started. Requests still in flight then fail with 401 (the
 * session just ended); they must not start a competing "session expired" redirect.
 */
export function isLeaving(): boolean {
  return leaving;
}
