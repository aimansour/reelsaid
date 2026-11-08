import statements from "./statements.json" with { type: "json" };

const encoder = new TextEncoder();
const maxBodyBytes = 2 * 1024 * 1024;
const responseHeaders = { "Cache-Control": "no-store" };

function reply(value, status = 200) {
    return Response.json(value, { status, headers: responseHeaders });
}

async function authorized(request, secret) {
    const header = request.headers.get("Authorization");
    if (!secret || !header?.startsWith("Bearer ")) {
        return false;
    }
    const hashes = await Promise.all(
        [header.slice(7), secret].map((value) => crypto.subtle.digest("SHA-256", encoder.encode(value))),
    );
    return crypto.subtle.timingSafeEqual(hashes[0], hashes[1]);
}

async function readJson(request) {
    const reader = request.body?.getReader();
    if (!reader) {
        throw new SyntaxError("Missing request body");
    }
    const decoder = new TextDecoder();
    let bytes = 0;
    let content = "";
    for (;;) {
        const { done, value } = await reader.read();
        if (done) {
            return JSON.parse(content + decoder.decode());
        }
        bytes += value.length;
        if (bytes > maxBodyBytes) {
            await reader.cancel();
            throw new RangeError("Request body too large");
        }
        content += decoder.decode(value, { stream: true });
    }
}

export default {
    async fetch(request, env) {
        if (request.method !== "POST" || new URL(request.url).pathname !== "/v1/query") {
            return reply({ error: "NOT_FOUND" }, 404);
        }
        if (!await authorized(request, env.STATE_SECRET)) {
            return reply({ error: "UNAUTHORIZED" }, 401);
        }

        let body;
        try {
            body = await readJson(request);
        } catch (error) {
            return error instanceof RangeError
                ? reply({ error: "PAYLOAD_TOO_LARGE" }, 413)
                : reply({ error: "INVALID_REQUEST" }, 400);
        }
        const { operation, parameters } = body ?? {};
        if (
            typeof operation !== "string" || !Object.hasOwn(statements, operation)
            || !Array.isArray(parameters) || parameters.length > 16
            || !parameters.every((value) => value === null || typeof value === "string" || Number.isSafeInteger(value))
        ) {
            return reply({ error: "INVALID_OPERATION" }, 400);
        }
        try {
            const result = await env.DB.prepare(statements[operation]).bind(...parameters).all();
            return reply(result.results);
        } catch {
            console.error(JSON.stringify({ event: "state_query_failed", operation }));
            return reply({ error: "STATE_UNAVAILABLE" }, 503);
        }
    },
};
