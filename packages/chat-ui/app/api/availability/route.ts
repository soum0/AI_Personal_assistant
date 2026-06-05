const PERSONA_API = process.env.PERSONA_API_URL ?? "http://localhost:8000";

export async function GET() {
  try {
    const upstream = await fetch(`${PERSONA_API}/check-availability`, {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
    });
    const data = await upstream.json();
    return Response.json(data);
  } catch {
    return Response.json({ error: "Calendar unavailable", slots: [] }, { status: 503 });
  }
}
