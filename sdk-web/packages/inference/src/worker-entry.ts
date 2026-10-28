import { installWorker, type WorkerScope } from "./worker";

// The file that is built into certivo-inference-worker.js. It has no model yet (P0-37).
installWorker(self as unknown as WorkerScope, null);
