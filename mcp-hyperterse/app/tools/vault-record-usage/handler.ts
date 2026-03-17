const BRIDGE = "http://127.0.0.1:8100";

export default async function handler(payload: {
  inputs: Record<string, unknown>;
  tool: string;
}) {
  const res = await fetch(`${BRIDGE}/tools/vault-record-usage`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload.inputs),
  });
  return await res.json();
}
