import ctypes
from ctypes import wintypes


DXGI_MEMORY_SEGMENT_GROUP_LOCAL = 0
HRESULT = ctypes.c_long


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", wintypes.BYTE * 8),
    ]


IID_IDXGIFactory1 = GUID(
    0x770AAE78,
    0xF26F,
    0x4DBA,
    (0xA8, 0x29, 0x25, 0x3C, 0x83, 0xD1, 0xB3, 0x87),
)
IID_IDXGIAdapter3 = GUID(
    0x645967A4,
    0x1392,
    0x4310,
    (0xA7, 0x98, 0x80, 0x53, 0xCE, 0x3E, 0x93, 0xFD),
)


class LUID(ctypes.Structure):
    _fields_ = [
        ("LowPart", wintypes.DWORD),
        ("HighPart", wintypes.LONG),
    ]


class DXGI_ADAPTER_DESC1(ctypes.Structure):
    _fields_ = [
        ("Description", wintypes.WCHAR * 128),
        ("VendorId", wintypes.DWORD),
        ("DeviceId", wintypes.DWORD),
        ("SubSysId", wintypes.DWORD),
        ("Revision", wintypes.DWORD),
        ("DedicatedVideoMemory", ctypes.c_size_t),
        ("DedicatedSystemMemory", ctypes.c_size_t),
        ("SharedSystemMemory", ctypes.c_size_t),
        ("AdapterLuid", LUID),
        ("Flags", wintypes.DWORD),
    ]


class DXGI_QUERY_VIDEO_MEMORY_INFO(ctypes.Structure):
    _fields_ = [
        ("Budget", ctypes.c_uint64),
        ("CurrentUsage", ctypes.c_uint64),
        ("AvailableForReservation", ctypes.c_uint64),
        ("CurrentReservation", ctypes.c_uint64),
    ]


def _vtbl_fn(ptr, index, restype, argtypes):
    vtbl = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    fn = ctypes.CFUNCTYPE(restype, *argtypes)(vtbl[index])
    return fn


def _release(ptr):
    if not ptr:
        return
    _vtbl_fn(ptr, 2, wintypes.ULONG, [ctypes.c_void_p])(ptr)


def _get_dxgi_vram_status() -> dict:
    dxgi = ctypes.WinDLL("dxgi")
    create_factory = dxgi.CreateDXGIFactory1
    create_factory.argtypes = [ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
    create_factory.restype = HRESULT

    factory = ctypes.c_void_p()
    hr = create_factory(ctypes.byref(IID_IDXGIFactory1), ctypes.byref(factory))
    if hr != 0 or not factory:
        raise RuntimeError("DXGI factory creation failed")

    adapter = ctypes.c_void_p()
    try:
        enum_adapters1 = _vtbl_fn(
            factory,
            12,
            HRESULT,
            [ctypes.c_void_p, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p)],
        )
        hr = enum_adapters1(factory, 0, ctypes.byref(adapter))
        if hr != 0 or not adapter:
            raise RuntimeError("No DXGI adapter found")

        desc = DXGI_ADAPTER_DESC1()
        get_desc1 = _vtbl_fn(
            adapter,
            10,
            HRESULT,
            [ctypes.c_void_p, ctypes.POINTER(DXGI_ADAPTER_DESC1)],
        )
        hr = get_desc1(adapter, ctypes.byref(desc))
        if hr != 0:
            raise RuntimeError("DXGI GetDesc1 failed")

        adapter3 = ctypes.c_void_p()
        query_interface = _vtbl_fn(
            adapter,
            0,
            HRESULT,
            [ctypes.c_void_p, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)],
        )
        hr = query_interface(adapter, ctypes.byref(IID_IDXGIAdapter3), ctypes.byref(adapter3))
        if hr != 0 or not adapter3:
            raise RuntimeError("IDXGIAdapter3 not available")

        try:
            info = DXGI_QUERY_VIDEO_MEMORY_INFO()
            query_video_memory = _vtbl_fn(
                adapter3,
                14,
                HRESULT,
                [
                    ctypes.c_void_p,
                    wintypes.UINT,
                    wintypes.UINT,
                    ctypes.POINTER(DXGI_QUERY_VIDEO_MEMORY_INFO),
                ],
            )
            hr = query_video_memory(
                adapter3,
                0,
                DXGI_MEMORY_SEGMENT_GROUP_LOCAL,
                ctypes.byref(info),
            )
            if hr != 0:
                # NON_LOCAL fallback
                hr = query_video_memory(adapter3, 0, 1, ctypes.byref(info))
            if hr != 0:
                total_mb = int(desc.DedicatedVideoMemory / (1024 * 1024))
                return {
                    "vendor": desc.Description.strip(),
                    "vram_used_mb": 0,
                    "vram_total_mb": total_mb,
                    "vram_free_mb": total_mb,
                    "warning": "DXGI QueryVideoMemoryInfo failed; using adapter dedicated memory.",
                }

            used_mb = int(info.CurrentUsage / (1024 * 1024))
            total_mb = (
                int(info.Budget / (1024 * 1024))
                if info.Budget
                else int(desc.DedicatedVideoMemory / (1024 * 1024))
            )
            free_mb = max(total_mb - used_mb, 0)

            return {
                "vendor": desc.Description.strip(),
                "vram_used_mb": used_mb,
                "vram_total_mb": total_mb,
                "vram_free_mb": free_mb,
            }
        finally:
            _release(adapter3)
    finally:
        _release(adapter)
        _release(factory)


def get_vram_status() -> dict:
    """
    Return VRAM usage for the first detected adapter.

    The returned JSON shape matches what the /status endpoint expects.
    """
    try:
        return _get_dxgi_vram_status()
    except Exception as e:  # pragma: no cover - defensive fallback
        return {"error": str(e)}

