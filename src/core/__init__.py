"""Shared kernel: cross-cutting infrastructure only (config, telemetry, outbox, db).

No business or market logic lives here. Slices may import core; core never imports slices.
"""
