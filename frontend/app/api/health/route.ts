/**
 * Proxies the FastAPI /health endpoint so the frontend can confirm the
 * backend is reachable from the browser without setting up CORS just for
 * a health check. The real chat traffic goes through the custom transport
 * to FastAPI directly in Layer I.
 */

import { NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const res = await fetch(`${BACKEND_URL}/health`, { cache: "no-store" });
    const body = await res.json();
    return NextResponse.json(
      { ...body, backend_url: BACKEND_URL },
      { status: res.status },
    );
  } catch (err) {
    return NextResponse.json(
      {
        status: "unreachable",
        backend_url: BACKEND_URL,
        error: String(err),
      },
      { status: 502 },
    );
  }
}
