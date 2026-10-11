# NeoTV — web client

React 19 + Vite. See the [project README](../README.md) for setup, architecture and quality gates.

```bash
npm ci
npm run dev        # http://127.0.0.1:5173 (proxies /api to 127.0.0.1:5000)
npm run lint && npm test -- --run && npm run build
npm run gen:api    # regenerate src/core/api/contract.generated.js from ../openapi/openapi.json
```
