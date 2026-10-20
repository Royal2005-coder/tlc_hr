__version__ = "0.1.0"

# The 2026 PIT table must be in place in every process before a salary slip is computed.
from tlc_hr.vn.statutory import patch_pit_table  # noqa: E402

patch_pit_table()
