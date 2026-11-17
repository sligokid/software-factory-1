# Slice: {{slice}}

> Keep this file under the size limit in `factory/limits.toml`. It is read by every agent working
> in this slice and by the reviewer.

## Purpose
One or two sentences: what business capability this slice owns.

## Owns
- Tables: `{{slice}}_*`
- Events published: `{{slice}}.<event>.v1`
- HTTP routes: `/{{slice}}/...`

## Consumes
- Events: none yet
- `market_es` modules: none yet

## Invariants
- Rules that must always hold for this slice's data and behaviour.

## Not in scope
- What this slice deliberately does not do.
