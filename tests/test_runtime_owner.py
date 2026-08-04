from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from trip_decider.runtime_owner import RuntimeOwner, RuntimeOwnershipError


class RuntimeOwnerCase(unittest.TestCase):
    def test_a_second_process_owner_is_rejected_until_release(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "sessions"
            first = RuntimeOwner(root)
            second = RuntimeOwner(root)
            first.acquire()
            self.addCleanup(first.release)

            with self.assertRaisesRegex(
                RuntimeOwnershipError,
                "TRIP_DECIDER_RUNTIME_ROOT",
            ):
                second.acquire()

            first.release()
            second.acquire()
            second.release()


if __name__ == "__main__":
    unittest.main()
