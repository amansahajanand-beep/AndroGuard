"""Out-of-band analysis workers.

Emulator work lives here, never inside an HTTP handler: booting an AVD,
installing and launching an APK takes minutes, far beyond a request budget.

    API  ->  create analysis job  ->  WorkerPool  ->  DeviceSession
         ->  EmulatorManager  ->  ADB  ->  existing exploration engine

Phase 12I adds bounded concurrency, device isolation, cancel/timeout, and
heartbeat — without a second exploration implementation.
"""

from app.workers.device_pool import DevicePool, DeviceSlot, get_device_pool
from app.workers.device_session import AndroidDeviceSession
from app.workers.pool import ExplorationWorkerPool, get_worker_pool
from app.workers.registry import WorkerRegistry, get_worker_registry

__all__ = [
    "AndroidDeviceSession",
    "DevicePool",
    "DeviceSlot",
    "ExplorationWorkerPool",
    "WorkerRegistry",
    "get_device_pool",
    "get_worker_pool",
    "get_worker_registry",
]
