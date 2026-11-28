import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, call
import stat

from core import receiver_hardware, receiver_usb_reset as reset


class USBResetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.addCleanup(patch.stopall)
        patch.object(receiver_hardware, "SYSFS", self.root).start()
        patch.object(reset, "USBFS", Path("/dev/bus/usb")).start()
        self.make("1-3", "24006572", 12)
        self.make("1-5", "05419737", 4)

    def make(self, port, serial, number):
        d = self.root / port
        d.mkdir(exist_ok=True)
        for key, value in {"idVendor":"0bda", "idProduct":"2838", "product":"NESDR", "serial":serial, "busnum":"1", "devnum":str(number), "dev":f"189:{number-1}"}.items():
            (d / key).write_text(value)

    def test_exact_identity(self):
        node, device = reset._identity("24006572", "1-3")
        self.assertEqual(str(node), "/dev/bus/usb/001/012")
        with self.assertRaises(RuntimeError):
            reset._identity("24006572", "1-5")
        with self.assertRaises(RuntimeError):
            reset._identity("24006572", "../1-3")

    def test_duplicate_or_missing_serial_never_reset(self):
        for serial in ("24006572", ""):
            self.make("1-5", serial, 4)
            with patch.object(reset.os, "open") as opened:
                with self.assertRaises(RuntimeError):
                    reset.reset_once("24006572", "1-3")
                opened.assert_not_called()

    def test_reset_only_exact_fd_and_drop_privileges_first(self):
        node, device = reset._identity("24006572", "1-3")
        info = SimpleNamespace(st_mode=stat.S_IFCHR, st_rdev=device, st_dev=1, st_ino=2)
        with patch.object(reset.os, "open", return_value=99) as opened, patch.object(reset.os, "fstat", return_value=info), patch.object(reset.os, "stat", return_value=info), patch.object(reset, "_identity", return_value=(node, device)), patch.object(reset.os, "close") as close, patch.object(reset.fcntl, "ioctl") as ioctl:
            reset.reset_once("24006572", "1-3")
            self.assertEqual(opened.call_args.args[0], node)
            self.assertEqual(ioctl.call_args_list, [call(99, reset.USBDEVFS_DROP_PRIVILEGES, b"\0"*4), call(99, reset.USBDEVFS_RESET, 0)])
            close.assert_called_once_with(99)

    def test_privilege_drop_failure_blocks_reset(self):
        node, device = reset._identity("24006572", "1-3")
        info = SimpleNamespace(st_mode=stat.S_IFCHR, st_rdev=device, st_dev=1, st_ino=2)
        with patch.object(reset.os, "open", return_value=99), patch.object(reset.os, "fstat", return_value=info), patch.object(reset.os, "stat", return_value=info), patch.object(reset, "_identity", return_value=(node, device)), patch.object(reset.os, "close"), patch.object(reset.fcntl, "ioctl", side_effect=PermissionError("busy")) as ioctl:
            with self.assertRaises(PermissionError):
                reset.reset_once("24006572", "1-3")
            ioctl.assert_called_once()

    def test_child_timeout_and_failed_reset_not_reported_success(self):
        with patch.object(reset.subprocess, "run", return_value=SimpleNamespace(returncode=1, stderr="busy", stdout="")) as run:
            with self.assertRaisesRegex(RuntimeError, "busy"):
                reset.reset_receiver({"serial":"24006572"})
            self.assertEqual(run.call_args.kwargs["timeout"], 15)
            self.assertEqual(run.call_args.args[0][-2:], ["24006572", "1-3"])

if __name__ == "__main__":
    unittest.main()
