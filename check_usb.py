import usb.core
import usb.backend.libusb1 as libusb1
import usb.backend.libusb0 as libusb0

# isti patch kao u ant/ant_manager.py - bez ovoga libusb1 zna vratiti None
# na Windowsu cak i kad je Zadig driver ispravno postavljen
try:
    import libusb_package
    lib_path = libusb_package.get_library_path()
    if lib_path:
        _orig = libusb1.get_backend
        libusb1.get_backend = lambda find_library=None, **kw: _orig(find_library=lambda x: lib_path, **kw)
        print("libusb-package patch applied, path:", lib_path)
except ImportError:
    print("libusb-package not installed - run: pip install libusb-package")

b1 = libusb1.get_backend()
print("libusb1 backend:", b1)

b0 = libusb0.get_backend()
print("libusb0 backend:", b0)

if b1:
    devs = list(usb.core.find(find_all=True, backend=b1))
    print("devices via libusb1:", devs)
    for d in devs:
        print(f"  VID={hex(d.idVendor)} PID={hex(d.idProduct)}")

if b0:
    devs0 = list(usb.core.find(find_all=True, backend=b0))
    print("devices via libusb0:", devs0)
