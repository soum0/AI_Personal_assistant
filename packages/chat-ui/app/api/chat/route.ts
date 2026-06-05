import { type NextRequest } from "next/server";
import { sanitize } from "@/lib/sanitize";

const PERSONA_API = process.env.PERSONA_API_URL ?? "http://localhost:8000";

export async function POST(req: NextRequest) {
  let body: { message?: string; session_id?: string; conversation_history?: unknown[] };
  try {
    body = await req.json();
  } catch {
    return Response.json({ error: "Invalid JSON" }, { status: 400 });
  }

  const message = sanitize(body.message ?? "");
  if (!message) {
    return Response.json({ error: "Empty message" }, { status: 400 });
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${PERSONA_API}/chat`, {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({
        message,
        session_id:           body.session_id           ?? "web",
        conversation_history: body.conversation_history ?? [],
        stream:               true,
      }),
    });
  } catch {
    return Response.json({ error: "Persona API unreachable" }, { status: 503 });
  }

  if (!upstream.ok || !upstream.body) {
    return Response.json({ error: "Backend error" }, { status: upstream.status });
  }

  // Proxy the SSE stream directly to the browser
  return new Response(upstream.body, {
    headers: {
      "Content-Type":    "text/event-stream",
      "Cache-Control":   "no-cache, no-transform",
      "X-Accel-Buffering": "no",
      Connection:        "keep-alive",
    },
  });
}
