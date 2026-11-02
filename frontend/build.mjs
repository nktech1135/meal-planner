// Builds the web interface with esbuild, which needs about 100 MB of memory (Vite's build took over 500 MB).
//
//   node build.mjs         production build into dist/ (hashed, minified assets under dist/assets/)
//   node build.mjs --dev   rebuild on change and serve on http://localhost:5173, reloading the page after each
//                          rebuild; /api is proxied to the API on http://localhost:8000
import * as esbuild from "esbuild";
import { cpSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import http from "node:http";
import path from "node:path";

const dev = process.argv.includes("--dev");
const root = path.dirname(new URL(import.meta.url).pathname);
const dist = path.join(root, "dist");
const DEV_PORT = 5173;
const API = { host: "localhost", port: 8000 };

/** Writes dist/index.html from the template, pointing at this build's entry script and stylesheet. */
const htmlPlugin = {
  name: "index-html",
  setup(build) {
    build.onEnd((result) => {
      if (result.errors.length || !result.metafile) return;
      const outputs = Object.entries(result.metafile.outputs);
      const entry = outputs.find(([, o]) => o.entryPoint === "src/main.tsx");
      if (!entry) throw new Error("esbuild produced no entry script");
      const url = (file) => "/" + path.relative(dist, path.resolve(root, file)).split(path.sep).join("/");
      const tags = [`<script type="module" src="${url(entry[0])}"></script>`];
      if (entry[1].cssBundle) tags.push(`<link rel="stylesheet" href="${url(entry[1].cssBundle)}" />`);
      // Dev only: reload when esbuild reports a rebuild (the API server, with its CSP, never serves this).
      if (dev) tags.push(`<script>new EventSource("/esbuild").addEventListener("change", () => location.reload());</script>`);
      const template = readFileSync(path.join(root, "index.html"), "utf8");
      const tag = /\s*<script type="module" src="\/src\/main\.tsx"><\/script>/;
      if (!tag.test(template) || !template.includes("</head>")) throw new Error("index.html no longer has the expected entry script tag");
      const html = template.replace(tag, "").replace("</head>", `  ${tags.join("\n    ")}\n  </head>`);
      writeFileSync(path.join(dist, "index.html"), html);
    });
  },
};

const options = {
  absWorkingDir: root,
  entryPoints: ["src/main.tsx"],
  bundle: true,
  splitting: true, // the barcode scanner's library loads only when it's opened
  format: "esm",
  outdir: path.join(dist, "assets"),
  entryNames: dev ? "[name]" : "[name]-[hash]",
  chunkNames: "chunk-[hash]",
  assetNames: "[name]-[hash]",
  minify: !dev,
  sourcemap: dev ? "linked" : false,
  target: ["chrome107", "edge107", "firefox104", "safari16"],
  define: { "process.env.NODE_ENV": JSON.stringify(dev ? "development" : "production") },
  metafile: true,
  logLevel: "warning",
  plugins: [htmlPlugin],
};

rmSync(dist, { recursive: true, force: true });
mkdirSync(dist, { recursive: true });
cpSync(path.join(root, "public"), dist, { recursive: true });

if (!dev) {
  await esbuild.build(options);
  console.log("built dist/");
} else {
  const ctx = await esbuild.context(options);
  await ctx.watch();
  // esbuild's own server sits behind the proxy; left to itself it would take port 8000, the API's.
  const { port } = await ctx.serve({ servedir: dist, host: "127.0.0.1", port: DEV_PORT + 1, fallback: path.join(dist, "index.html") });
  http
    .createServer((req, res) => {
      const target = req.url.startsWith("/api/") || req.url === "/api" ? API : { host: "127.0.0.1", port };
      const upstream = http.request({ ...target, path: req.url, method: req.method, headers: req.headers }, (up) => {
        res.writeHead(up.statusCode ?? 502, up.headers);
        up.pipe(res);
      });
      upstream.on("error", () => {
        res.writeHead(502, { "Content-Type": "text/plain" });
        res.end(target === API ? "The API isn't running on port 8000" : "esbuild isn't responding");
      });
      req.pipe(upstream);
    })
    .listen(DEV_PORT, () => console.log(`http://localhost:${DEV_PORT}`));
}
