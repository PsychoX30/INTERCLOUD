// Polyfill TextEncoder / TextDecoder for jsdom (Jest 27).
// React Router v7 internals reference these globals; older jsdom omits them.
const { TextEncoder, TextDecoder } = require("util");
if (typeof globalThis.TextEncoder === "undefined") {
  globalThis.TextEncoder = TextEncoder;
}
if (typeof globalThis.TextDecoder === "undefined") {
  globalThis.TextDecoder = TextDecoder;
}
