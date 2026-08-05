export function pairingTokenFromSerial(text) {
  const matches = [...text.matchAll(/\[heliox-daemon\] bridge pairing token: ([0-9a-f]{32})/g)];
  return matches.length ? matches[matches.length - 1][1] : null;
}

export async function waitForPairingToken(readSerial, timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const token = pairingTokenFromSerial(readSerial());
    if (token) return token;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error("timed out waiting for Heliox bridge pairing token");
}

export function assertPaired(response) {
  if (!response?.result?.authorized) {
    throw new Error(`Heliox bridge pairing failed: ${JSON.stringify(response)}`);
  }
  return response;
}

export function rpcCall(ws, id, method, params = {}, timeoutMs = 30_000) {
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(
      () => reject(new Error(`timed out waiting for Heliox ${method}`)),
      timeoutMs,
    );
    const handler = (event) => {
      try {
        const response = JSON.parse(event.data);
        if (response.id === id) {
          clearTimeout(timeout);
          ws.removeEventListener("message", handler);
          resolve(response);
        }
      } catch { /* ignore unrelated or non-JSON frames */ }
    };
    ws.addEventListener("message", handler);
    ws.send(JSON.stringify({ jsonrpc: "2.0", id, method, params }));
  });
}
