const PERSONA_API = process.env.PERSONA_API_URL ?? "http://localhost:8000";

export async function POST(req: Request) {
  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return Response.json({ error: "Invalid JSON" }, { status: 400 });
  }
  try {
    const upstream = await fetch(`${PERSONA_API}/book-meeting`, {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify(body),
    });
    const data = await upstream.json();
    return Response.json(data, { status: upstream.status });
  } catch {
    return Response.json({ error: "Booking service unavailable" }, { status: 503 });
  }
}
