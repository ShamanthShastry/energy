.PHONY: venv module-install module-build publish library synth replay test lint

venv:            ## create .venv with uv and install dev extras
	uv venv --python 3.11 && uv pip install -e ".[dev]"

module-install:  ## install the SpacetimeDB module's npm deps
	cd spacetimedb && npm install

module-build:    ## type-check and build the SpacetimeDB module
	cd spacetimedb && npx tsc --noEmit -p . && spacetime build

publish:         ## publish the module to Maincloud (database name in spacetime.json)
	.venv/bin/homewatt db publish

library:         ## CMP-00: activation library + split file from data/raw/nilm-dataset
	.venv/bin/homewatt cmp00 build

synth:           ## CMP-06: 14-day demo timeline with a fridge fault at day 12
	.venv/bin/homewatt cmp06 generate --profile config/profiles/demo_household.yaml \
	  --weather data/weather/ann_arbor_2025.parquet --days 14 --seed 7 \
	  --fault config/faults/fridge_day12.yaml --out data/synthetic/demo_14d_seed7

replay:          ## CMP-05: replay the demo timeline into SpacetimeDB as fast as the store allows
	.venv/bin/homewatt ingest replay data/synthetic/demo_14d_seed7/aggregate.parquet --speed 0 --sink spacetime

test:
	.venv/bin/pytest -q

lint:
	.venv/bin/ruff check src tests
