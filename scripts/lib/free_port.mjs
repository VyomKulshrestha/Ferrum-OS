import net from "node:net";

export async function freeTcpPort(host = "127.0.0.1") {
  return await new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.once("error", reject);
    server.listen(0, host, () => {
      const address = server.address();
      if (!address || typeof address === "string") {
        server.close();
        reject(new Error("could not allocate a free TCP port"));
        return;
      }
      const port = address.port;
      server.close((error) => error ? reject(error) : resolve(port));
    });
  });
}
