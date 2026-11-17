"""Vertical slices. Each subpackage is one independent feature.

Slices never import each other. They communicate only through events (outbox -> Redpanda).
"""
