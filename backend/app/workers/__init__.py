"""Out-of-band analysis workers.

Emulator work lives here, never inside an HTTP handler: booting an AVD,
installing and launching an APK takes minutes, far beyond a request budget.

    API  ->  create analysis job  ->  worker  ->  EmulatorManager  ->  ADB
"""
