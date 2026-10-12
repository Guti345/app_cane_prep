import { describe, expect, it } from "vitest";
import { hrefFor, parseHash } from "./router";

const ID = "3f2c8a6e-1d4b-4f6a-9c0e-7b5a1c2d3e4f";

describe("parseHash", () => {
  it.each([
    ["", { name: "home" }],
    ["#/", { name: "home" }],
    ["#/login", { name: "login" }],
    ["#/ranking", { name: "ranking" }],
    ["#/ranking/", { name: "ranking" }],
    [`#/jugar/${ID}`, { name: "play", sessionId: ID }],
  ])("%s", (hash, route) => {
    expect(parseHash(hash)).toEqual(route);
  });

  it.each(["#/jugar/no-es-un-uuid", "#/jugar/", "#/otra-cosa", "#/jugar/../login"])(
    "%s es notfound",
    (hash) => {
      expect(parseHash(hash)).toEqual({ name: "notfound" });
    },
  );

  it("hrefFor es la inversa de parseHash", () => {
    for (const route of [
      { name: "login" }, { name: "home" }, { name: "ranking" }, { name: "play", sessionId: ID },
    ] as const) {
      expect(parseHash(hrefFor(route))).toEqual(route);
    }
  });
});
