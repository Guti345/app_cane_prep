/** Router por hash: no requiere redirects en Netlify. */

export type Route =
  | { name: "login" }
  | { name: "home" }
  | { name: "play"; sessionId: string }
  | { name: "ranking" }
  | { name: "notfound" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function parseHash(hash: string): Route {
  const path = hash.replace(/^#/, "").replace(/\/+$/, "") || "/";
  if (path === "/") return { name: "home" };
  if (path === "/login") return { name: "login" };
  if (path === "/ranking") return { name: "ranking" };
  const play = /^\/jugar\/([^/]+)$/.exec(path);
  if (play && UUID.test(play[1]!)) {
    return { name: "play", sessionId: play[1]! };
  }
  return { name: "notfound" };
}

export function hrefFor(route: Route): string {
  switch (route.name) {
    case "login":
      return "#/login";
    case "play":
      return `#/jugar/${route.sessionId}`;
    case "ranking":
      return "#/ranking";
    default:
      return "#/";
  }
}

export function navigate(route: Route): void {
  const target = hrefFor(route);
  if (window.location.hash === target) {
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  } else {
    window.location.hash = target;
  }
}

export function onRouteChange(callback: (route: Route) => void): () => void {
  const handler = () => callback(parseHash(window.location.hash));
  window.addEventListener("hashchange", handler);
  return () => window.removeEventListener("hashchange", handler);
}

export function currentRoute(): Route {
  return parseHash(window.location.hash);
}
