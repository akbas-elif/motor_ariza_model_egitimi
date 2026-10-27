import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { extname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL(".", import.meta.url));
const types = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
};

export const server = createServer(async (request, response) => {
  const pathname = request.url === "/" ? "/index.html" : request.url.split("?")[0];
  const safePath = pathname.replaceAll("..", "");

  try {
    const body = await readFile(join(root, safePath));
    response.writeHead(200, { "Content-Type": types[extname(safePath)] || "application/octet-stream" });
    response.end(body);
  } catch {
    response.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
    response.end("Dosya bulunamadi.");
  }
});

const port = Number(process.env.PORT || 8000);

server.listen(port, "127.0.0.1", () => {
  console.log(`Arayuz calisiyor: http://localhost:${port}`);
  console.log("Durdurmak icin Ctrl+C");
});
