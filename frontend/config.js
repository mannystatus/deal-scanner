// Runtime config for the frontend. Edit this file (not index.html) to change
// where the frontend points. Cloudflare Pages serves it with a 60-second
// cache, so updates land fast without a redeploy of index.html.
//
// Locally, override by setting window.API_BASE before loading index.html
// (or just edit this file and run `python -m http.server --directory frontend`).

window.API_BASE = "https://deal-scanner-api.onrender.com";
